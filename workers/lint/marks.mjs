#!/usr/bin/env node
/**
 * Kontrola turistických a cyklistických značiek pozdĺž trás.
 * Volá ju `Kontrola · lint workflowov`.
 *
 * Meno obrázka značky sa skladá až z dát: `trails/tags.py` napíše tvar,
 * podklad a farbu, štýl z nich `concat`-om zloží meno a `assets/marks.mjs`
 * ho musí mať v sprite. Tri miesta – rozídené znamená, že MapLibre neznámy
 * obrázok ticho preskočí a po trase nie je nič.
 *
 *   1. každý tvar z `OSMC_SHAPES` kreslí `poc/web/marks.js`;
 *   2. dvojice podklad × farba (`MARK_FACES`) sú na oboch stranách tie isté;
 *   3. farba pásu sa nerovná podkladu (taká značka je prázdny štvorec);
 *   4. meno, ktoré skladá štýl, je to isté ako `markImage()`;
 *   5. atribúty sú v schéme dlaždíc;
 *   6. vrstva značiek je v štýle pre každý druh trasy a ikonka druhu sa
 *      kreslí len tam, kde značka nie je;
 *   7. značky dvoch trás sa stavajú nad seba – bez posunu podľa `side` a
 *      `off` padnú na to isté miesto a kolízia nechá vždy tú istú;
 *   8. značky sa naozaj upečú a žiadna nie je `sdf` (SDF by z troch farieb
 *      spravil jednu).
 *
 *   node workers/lint/marks.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { encodePng } from "../lib/png.mjs";
import {
  MARK_SHAPE_IDS,
  MARK_FACES,
  MARK_COLOURS,
  MARK_IMAGE,
  markImage,
  markImages
} from "../../poc/web/marks.js";
import {
  THEMES,
  TRAIL_TYPES,
  TRAIL_MARK_STACK,
  TRAIL_MARK_STACK_MAX,
  TRAIL_MARK_PADDING,
  buildStyle
} from "../../poc/web/themes.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const TAGS = join(ROOT, "workers", "trails", "tags.py");
const SCHEMA = join(ROOT, "workers", "trails", "trails.yml");

let bad = 0;
const chyba = (subor, text) => {
  console.log(`::error file=${subor}::${text}`);
  bad += 1;
};

const py = readFileSync(TAGS, "utf8");

// ---------- 1. tvary, ktoré vedia dáta poslať ----------
const shapesBlock = py.match(/OSMC_SHAPES\s*=\s*\{([\s\S]*?)\n\}/);
if (!shapesBlock) {
  chyba("workers/trails/tags.py", "`OSMC_SHAPES` sa nenašlo – bez neho sa nedá overiť, aké tvary idú do dlaždíc.");
} else {
  const tvary = new Set(
    [...shapesBlock[1].matchAll(/"[a-z_]+"\s*:\s*"([a-z_]+)"/g)].map((m) => m[1])
  );
  if (!tvary.size) {
    chyba("workers/trails/tags.py", "`OSMC_SHAPES` je prázdne – žiadna trasa by nedostala značku.");
  }
  for (const tvar of tvary) {
    if (!MARK_SHAPE_IDS.includes(tvar)) {
      chyba(
        "workers/trails/tags.py",
        `\`OSMC_SHAPES\` posiela do dlaždíc tvar "${tvar}", ktorý poc/web/marks.js ` +
          `nekreslí (kreslí: ${MARK_SHAPE_IDS.join(", ")}). Obrázok v sprite nebude ` +
          `a po trase nebude ani značka – MapLibre to ticho preskočí.`
      );
    }
  }
}

// ---------- 2. + 3. dvojice podklad × farba ----------
const facesBlock = py.match(/MARK_FACES\s*=\s*\{([\s\S]*?)\n\}/);
const jsFaces = new Set(MARK_FACES.map(([bg, fg]) => `${bg}-${fg}`));
if (!facesBlock) {
  chyba("workers/trails/tags.py", "`MARK_FACES` sa nenašlo – nedá sa overiť, aké dvojice idú do dlaždíc.");
} else {
  const pyFaces = new Set(
    [...facesBlock[1].matchAll(/\("([a-z]+)",\s*"([a-z]+)"\)/g)].map((m) => `${m[1]}-${m[2]}`)
  );
  for (const face of pyFaces) {
    if (!jsFaces.has(face)) {
      chyba(
        "workers/trails/tags.py",
        `dvojica podklad-farba "${face}" je v dátach, ale marks.js ju nepečie – ` +
          `taká trasa ostane v mape bez značky.`
      );
    }
  }
  for (const face of jsFaces) {
    if (!pyFaces.has(face)) {
      chyba(
        "poc/web/marks.js",
        `dvojica "${face}" sa pečie do spritu, ale tags.py ju nikdy nenapíše – ` +
          `je to obrázok navyše. Buď ju do MARK_FACES v tags.py doplň, alebo ju odtiaľto zmaž.`
      );
    }
  }
}
for (const [bg, fg] of MARK_FACES) {
  if (bg === fg) {
    chyba("poc/web/marks.js", `dvojica "${bg}-${fg}" má pás vo farbe podkladu – z takej značky je prázdny štvorec.`);
  }
  for (const [meno, farba] of [["podklad", bg], ["farba", fg]]) {
    if (!MARK_COLOURS[farba]) {
      chyba("poc/web/marks.js", `dvojica "${bg}-${fg}": ${meno} "${farba}" nie je v MARK_COLOURS.`);
    }
  }
}

// ---------- 5. atribúty v schéme dlaždíc ----------
const yml = readFileSync(SCHEMA, "utf8");
for (const key of ["mark", "mark_bg", "mark_fg"]) {
  if (!new RegExp(`- key: ${key}\\s`).test(yml)) {
    chyba(
      "workers/trails/trails.yml",
      `atribút \`${key}\` nie je v schéme dlaždíc – štýl by z neho čítal prázdno ` +
        `a meno obrázka by bolo nezmyselné. Trasy by ostali bez značiek.`
    );
  }
}

// ---------- 4., 6., 7. čo z toho spraví štýl ----------
/** Vyhodnotí `["concat", …]` nad jedným prvkom – toľko z výrazov stačí. */
function evalConcat(expr, props) {
  if (typeof expr === "string") return expr;
  if (!Array.isArray(expr)) return String(expr);
  if (expr[0] === "get") return String(props[expr[1]] ?? "");
  if (expr[0] === "concat") return expr.slice(1).map((e) => evalConcat(e, props)).join("");
  return `?${expr[0]}?`;
}

const style = buildStyle({
  theme: Object.keys(THEMES)[0],
  tilesUrl: "pmtiles://x/t.pmtiles",
  spriteUrl: "https://x/sprite",
  glyphsUrl: "https://x/{fontstack}/{range}.pbf",
  trailsUrl: "pmtiles://x/trails.pmtiles",
  icons: markImages().map((m) => m.name)
});
const poradie = new Map(style.layers.map((l, i) => [l.id, i]));
const rozostupy = new Map();
for (const t of TRAIL_TYPES) {
  const mark = style.layers.find((l) => l.id === `trail-${t.id}-mark`);
  if (!mark) {
    chyba(
      "poc/web/themes.js",
      `vrstva \`trail-${t.id}-mark\` v štýle nie je, hoci značky v sprite sú – ` +
        `trasy tohto druhu by ostali bez značenia.`
    );
    continue;
  }
  const meno = evalConcat(mark.layout["icon-image"], {
    mark_bg: "white",
    mark_fg: "red",
    mark: "bar"
  });
  if (meno !== markImage("white", "red", "bar")) {
    chyba(
      "poc/web/themes.js",
      `\`trail-${t.id}-mark\` skladá meno obrázka ako "${meno}", ale marks.js ho ` +
        `pečie ako "${markImage("white", "red", "bar")}". Sú to dve cesty k jednému ` +
        `menu a rozídené znamenajú prázdno v mape.`
    );
  }
  // Posun podľa pruhu – bez neho si značky sadnú na seba a kolízia nechá
  // jednu. Kontroluje sa, že sa `off` aj `side` naozaj čítajú a že sa dvojice
  // `(side, off)` posúvajú KAŽDÁ INAM (dva rovnaké posuny = pôvodná chyba).
  const offset = JSON.stringify(mark.layout["icon-offset"] || null);
  for (const kluc of ["side", "off"]) {
    if (!offset.includes(`"${kluc}"`)) {
      chyba(
        "poc/web/themes.js",
        `\`trail-${t.id}-mark\` nečíta pri posune značky \`${kluc}\`. Trasy na tej ` +
          `istej ceste majú tú istú geometriu, takže by značky padli na jedno miesto ` +
          `a kolízia by nechala jednu – ostatné by v mape neboli vôbec.`
      );
      break;
    }
  }
  const posuny = new Set();
  for (const side of [1, -1]) {
    for (let off = 0; off <= TRAIL_MARK_STACK_MAX; off += 1) {
      const y = -side * (TRAIL_MARK_STACK.base + TRAIL_MARK_STACK.step * off);
      const kluc = `${side}:${off}`;
      if (posuny.has(String(y))) {
        chyba(
          "poc/web/themes.js",
          `posun značky pre pruh ${kluc} je ten istý ako pre iný pruh (y = ${y}) – ` +
            `dve trasy by mali značku na jednom mieste.`
        );
      }
      posuny.add(String(y));
    }
  }
  rozostupy.set(offset, t.id);

  // STĹPIK STOJÍ TESNE, TAKŽE SA MUSÍ KRESLIŤ BEZ OHĽADU NA KOLÍZIE.
  // Kolízny obdĺžnik je CELÝ obrázok (`MARK_IMAGE`, teda aj priehľadný okraj)
  // plus `icon-padding` na každej strane. Keď je krok stĺpika menší, susedné
  // značky si obdĺžniky prekryjú a MapLibre všetky okrem prvej ZAHODÍ – v mape
  // by z troch trás na chodníku bola jedna a nikto by nepovedal nič.
  const tesne = TRAIL_MARK_STACK.step < MARK_IMAGE + 2 * TRAIL_MARK_PADDING;
  if (tesne && mark.layout["icon-allow-overlap"] !== true) {
    chyba(
      "poc/web/themes.js",
      `\`trail-${t.id}-mark\` má krok stĺpika ${TRAIL_MARK_STACK.step} px, ale ` +
        `kolízny obdĺžnik značky je ${MARK_IMAGE + 2 * TRAIL_MARK_PADDING} px ` +
        `(obrázok ${MARK_IMAGE} + 2 × padding ${TRAIL_MARK_PADDING}) – bez ` +
        `\`icon-allow-overlap\` by v stĺpiku ostala len prvá značka.`
    );
  }

  // Ikonka druhu trasy je NÁHRADA za značku, nie druhý symbol.
  const icon = style.layers.find((l) => l.id === `trail-${t.id}-icon`);
  // A to isté pri ikonke druhu trasy: stojí v tom istom stĺpiku (`off`/`side`
  // sa číslujú raz na cestu), takže bez `icon-allow-overlap` by z nej ostala
  // tiež len prvá priečka.
  if (icon && JSON.stringify(icon.layout["icon-offset"] || null).includes('"off"')
      && icon.layout["icon-allow-overlap"] !== true) {
    chyba(
      "poc/web/themes.js",
      `\`trail-${t.id}-icon\` sa posúva podľa pruhu, ale kreslí sa s ohľadom na ` +
        `kolízie – z ikoniek viacerých trás na jednej ceste by ostala jedna.`
    );
  }
  if (icon && !JSON.stringify(icon.filter).includes('["!",["has","mark"]]')) {
    chyba(
      "poc/web/themes.js",
      `\`trail-${t.id}-icon\` sa kreslí aj tam, kde má trasa značku – na jednej ` +
        `čiare by boli dva symboly naraz a brali by si miesto navzájom.`
    );
  }
  const label = poradie.get(`trail-${t.id}-label`);
  if (label != null && poradie.get(`trail-${t.id}-mark`) > label) {
    chyba(
      "poc/web/themes.js",
      `\`trail-${t.id}-mark\` je až za popiskami trasy. MapLibre umiestňuje symboly ` +
        `v poradí vrstiev, takže by názov trasy bral miesto značke – a značka je to, ` +
        `podľa čoho sa ide v teréne.`
    );
  }
}

// ---------- 8. značky sa naozaj upečú ----------
const dir = mkdtempSync(join(tmpdir(), "marks-lint-"));
try {
  const base = join(dir, "sprite");
  // Najmenší možný sprite: jeden štvorček, aby bolo čo preskladávať.
  writeFileSync(`${base}.png`, encodePng({ width: 4, height: 4, data: Buffer.alloc(64, 255) }));
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );
  execFileSync("node", ["workers/assets/marks.mjs", `--sprite=${base}`], {
    stdio: "pipe",
    cwd: ROOT
  });
  const index = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  let chybajucich = 0;
  for (const { name } of markImages()) {
    const e = index[name];
    if (!e) {
      chybajucich += 1;
      if (chybajucich <= 3) {
        chyba("workers/assets/marks.mjs", `značka "${name}" sa do spritu nedopiekla.`);
      }
      continue;
    }
    if (e.sdf) {
      chyba(
        "workers/assets/marks.mjs",
        `značka "${name}" je označená ako \`sdf\` – vzdialenostné pole nesie jednu ` +
          `farbu, kým značka má tri (podklad, pás, lem).`
      );
    }
  }
  if (chybajucich > 3) {
    chyba("workers/assets/marks.mjs", `… a ďalších ${chybajucich - 3} značiek chýba.`);
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

console.log(
  `značky trás: ${bad} chýb (${MARK_SHAPE_IDS.length} tvarov × ${MARK_FACES.length} dvojíc ` +
    `= ${markImages().length} obrázkov, ${TRAIL_TYPES.length} druhov trás)`
);
process.exit(bad ? 1 : 0);
