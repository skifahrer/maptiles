#!/usr/bin/env node
/**
 * Kontrola ikon: vlastných obrázkov, vlastných sád a `layout` vlastností.
 * Volá ju `Kontrola · lint workflowov`.
 *
 * Sedem tichých vecí – nič z toho nespadne, prejaví sa to až v mape:
 *
 *   1. vlastná ikona sa musí dopiecť do spritu (neznámy obrázok MapLibre
 *      ticho preskočí); skúša sa na naozajstnom sprite;
 *   2. štýl ju musí pustiť aj vtedy, keď v sprite ešte nie je;
 *   3. vlastnú sadu musí `icons.sh` vypísať na stiahnutie a `deploy/site.sh`
 *      do manifestu;
 *   4. `layout` len na symbolovej vrstve – neznáma vlastnosť v `layout` je
 *      tvrdá chyba a MapLibre odmietne celý štýl;
 *   5. ikona pri POI kategórii sa nasadzuje ako holé meno obrázka; drží sa aj
 *      práve nahratá vlastná ikona a voľba „žiadna";
 *   6. vlastný obrázok ako vzor plochy (pečie ho ten istý skript);
 *   7. šípka jednosmerky musí vzniknúť pri každej sade – kým bola z cudzieho
 *      spritu, vrstva `road-oneway` pri dvoch z troch sád vôbec nevznikla.
 *
 *   node workers/lint/icons.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { encodePng } from "../lib/png.mjs";
import {
  THEMES,
  buildStyle,
  normalizeOverrides,
  LAYOUT_PROP_IDS,
  CUSTOM_ICON_PREFIX
} from "../../poc/web/themes.js";
import { CUSTOM_SET_PREFIX, allIconSources, ICON_SOURCE_IDS } from "../../poc/web/icon-sources.js";
import { arrowImages, DEFAULT_ARROW_IMAGE } from "../../poc/web/arrows.js";
import { collectPatternNames } from "../../poc/web/patterns.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
let bad = 0;
const chyba = (subor, text) => {
  console.log(`::error file=${subor}::${text}`);
  bad += 1;
};

/** Malé PNG ako vlastná ikona. */
const ikonaPng = () => {
  const n = 8;
  const d = Buffer.alloc(n * n * 4, 255);
  return `data:image/png;base64,${encodePng({ width: n, height: n, data: d }).toString("base64")}`;
};

const UKAZKA = {
  version: 2,
  icons: `${CUSTOM_SET_PREFIX}test`,
  iconSets: [
    {
      id: `${CUSTOM_SET_PREFIX}test`,
      label: "Testovacia sada",
      sprite: "https://example.org/sprites/test",
      suffix: "_11"
    }
  ],
  customIcons: [{ name: `${CUSTOM_ICON_PREFIX}test`, png: ikonaPng(), pixelRatio: 2 }]
};
const { overrides, problems } = normalizeOverrides(UKAZKA);
for (const p of problems) {
  chyba("poc/web/themes.js", `ukážkové úpravy neprešli normalizáciou: ${p}`);
}

// 1. vlastná ikona sa dopečie do spritu
const dir = mkdtempSync(join(tmpdir(), "icons-lint-"));
try {
  const base = join(dir, "sprite");
  writeFileSync(`${base}.png`, encodePng({ width: 4, height: 4, data: Buffer.alloc(64, 255) }));
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );
  const upravy = join(dir, "overrides.json");
  writeFileSync(upravy, JSON.stringify(UKAZKA));
  execFileSync(
    "node",
    ["workers/assets/custom-icons.mjs", `--sprite=${base}`, `--overrides=${upravy}`],
    { stdio: "pipe", cwd: ROOT }
  );
  const index = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  const meno = overrides.customIcons[0].name;
  const e = index[meno];
  if (!e) {
    chyba(
      "workers/assets/custom-icons.mjs",
      `vlastná ikona "${meno}" sa do spritu nedopiekla – vrstva, ktorá si ju pýta, ` +
        `ostane bez obrázka a MapLibre o tom nepovie nič.`
    );
  } else {
    if (e.sdf) {
      chyba("workers/assets/custom-icons.mjs",
        `vlastná ikona "${meno}" je označená ako \`sdf\` – je to hotový farebný obrázok.`);
    }
    if (e.pixelRatio !== 2) {
      chyba("workers/assets/custom-icons.mjs",
        `vlastná ikona "${meno}" má v indexe pixelRatio ${e.pixelRatio}, ale nahrala sa ako @2x ` +
        `– v mape by bola dvojnásobne veľká.`);
    }
  }
  // pôvodné ikony sa pri tom nesmú stratiť
  if (!index.test_11) {
    chyba("workers/lib/sprite-bake.mjs",
      "dopečenie vlastných ikon zahodilo ikonu, ktorá v sprite už bola.");
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

// 2. štýl vlastnú ikonu pustí, aj keď v sprite ešte nie je
{
  const meno = overrides.customIcons[0].name;
  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    // sprite zámerne bez tej ikony – stav po jej pridaní v paneli
    icons: ["mountain_11"],
    iconSet: "osm-liberty",
    overrides: { ...overrides, layers: { "poi-major": { icon: meno } } }
  });
  const l = style.layers.find((x) => x.id === "poi-major");
  if (!l || (l.layout || {})["icon-image"] !== meno) {
    chyba(
      "poc/web/themes.js",
      `vrstva si po výbere vlastnej ikony "${meno}" nechala ` +
        `"${(l?.layout || {})["icon-image"]}" – práve pridaná ikona sa tým ticho zahodí.`
    );
  }
}

// 3. vlastnú sadu naozaj niekto stiahne a zapíše do manifestu
{
  const id = overrides.iconSets[0].id;
  if (!allIconSources(overrides).some((s) => s.id === id)) {
    chyba("poc/web/icon-sources.js", `vlastná sada "${id}" nie je v \`allIconSources\`.`);
  }
  for (const [subor, co] of [
    ["workers/assets/icons.sh", "sťahovanie sád"],
    ["workers/deploy/site.sh", "zoznam sád v manifeste"]
  ]) {
    const text = readFileSync(join(ROOT, subor), "utf8");
    if (!text.includes("allIconSources")) {
      chyba(
        subor,
        `${co} berie len sady z repozitára (\`ICON_SOURCES\`). Vlastná sada z úprav ` +
          `sa tým dá pridať aj vybrať, ale sprite k nej nikdy nevznikne – a mapa ` +
          `ostane bez ikon.`
      );
    }
  }
}

// 4. `layout` sa nasadí len na symbolovú vrstvu
{
  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    icons: ["mountain_11"],
    overrides: normalizeOverrides({
      // `road-path` je čiara – `icon-size` na nej zhodí celý štýl
      layers: { "road-path": { layout: { "icon-size": 2 } } }
    }).overrides
  });
  const l = style.layers.find((x) => x.id === "road-path");
  if (l && (l.layout || {})["icon-size"] !== undefined) {
    chyba(
      "poc/web/themes.js",
      "`layout` úprava sa nasadila na čiarovú vrstvu – MapLibre by taký štýl " +
        "odmietol celý a mapa by sa nenačítala."
    );
  }
}

// 5. ikona vybraná pri POI kategórii sa do mapy dostane
// Je to jediná hodnota v štýle nasadzovaná ako holé meno obrázka. Meno, ktoré
// sprite nemá, MapLibre preskočí; práve nahratá vlastná ikona musí prejsť;
// a „žiadna ikona" (prázdne meno) je voľba, nie nezadaná hodnota.
{
  const meno = overrides.customIcons[0].name;
  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    featuresUrl: "pmtiles://x/f.pmtiles",
    // body sú vo vlastnom zdroji – bez toho vrstva `feature-point` v štýle nie je
    pointsUrl: "pmtiles://x/p.pmtiles",
    roadsUrl: "pmtiles://x/r.pmtiles",
    // sprite zámerne bez vlastnej ikony – stav po jej nahratí v paneli
    icons: ["mountain_11", "restaurant_11"],
    iconSet: "osm-liberty",
    overrides: normalizeOverrides({
      ...overrides,
      poi: { hidden: [], icons: { restaurant: meno, spring: "", cave: "nieje_11" } }
    }).overrides
  });
  const vyraz = (id) =>
    JSON.stringify((style.layers.find((l) => l.id === id)?.layout || {})["icon-image"] || null);

  for (const id of ["poi-major", "poi-all", "feature-point"]) {
    const text = vyraz(id);
    if (!text.includes(JSON.stringify(meno))) {
      chyba(
        "poc/web/themes.js",
        `vrstva \`${id}\` nepustila vlastnú ikonu "${meno}" vybranú pri kategórii – ` +
          `v paneli sa vybrať dá, ale mapa ju nenakreslí.`
      );
    }
    if (text.includes("nieje_11")) {
      chyba(
        "poc/web/themes.js",
        `vrstva \`${id}\` si pýta ikonu "nieje_11", ktorú sprite nemá – MapLibre ju ` +
          `ticho preskočí a kategória ostane bez obrázka.`
      );
    }
    if (!text.includes('"spring"')) {
      chyba(
        "poc/web/themes.js",
        `vrstva \`${id}\` zahodila voľbu „žiadna ikona" pri kategórii spring. Prázdne ` +
          `meno je odpoveď, nie chýbajúca hodnota.`
      );
    }
  }
  // skryté kategórie platia aj na vlastných bodoch – zoznam v paneli je jeden
  const skryte = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    featuresUrl: "pmtiles://x/f.pmtiles",
    pointsUrl: "pmtiles://x/p.pmtiles",
    roadsUrl: "pmtiles://x/r.pmtiles",
    icons: ["mountain_11"],
    overrides: normalizeOverrides({ poi: { hidden: ["spring"] } }).overrides
  });
  const bodyFilter = JSON.stringify(
    skryte.layers.find((l) => l.id === "feature-point")?.filter || null
  );
  if (!bodyFilter.includes('"spring"')) {
    chyba(
      "poc/web/themes.js",
      "`feature-point` nerešpektuje skryté kategórie – odškrtnutie prameňa v paneli " +
        "by neurobilo nič a nikto by nepovedal prečo."
    );
  }
}

// 6. vlastný obrázok ako vzor
// Nahratý obrázok je uložený ako vlastná ikona (`own:…`), pečie ho
// custom-icons.mjs. Meno, ktoré v úpravách nie je, MapLibre ticho preskočí;
// a keby ho `collectPatternNames` vrátilo medzi kreslené vzory, prepísal by
// ho rasterizér šrafovaním.
{
  const meno = overrides.customIcons[0].name;
  const spravne = normalizeOverrides({
    ...overrides,
    layers: { "landcover-wood": { pattern: { image: meno, opacity: 0.8 } } }
  });
  if (spravne.problems.length) {
    chyba(
      "poc/web/themes.js",
      `vlastný obrázok ako vzor normalizeOverrides odmietol: ${spravne.problems[0]}`
    );
  }
  const zle = normalizeOverrides({
    ...overrides,
    layers: { "landcover-wood": { pattern: { image: "own:tento-neexistuje" } } }
  });
  if (zle.overrides.layers["landcover-wood"]?.pattern || !zle.problems.length) {
    chyba(
      "poc/web/themes.js",
      "vzor z obrázka, ktorý nie je medzi vlastnými ikonami úprav, prešiel " +
        "normalizáciou. Do spritu by ho nemal kto dopiecť a plocha by ostala " +
        "bez vzoru – štýl je pritom platný."
    );
  }

  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    // sprite zámerne bez neho – stav hneď po nahratí v paneli
    icons: ["mountain_11"],
    iconSet: "osm-liberty",
    overrides: spravne.overrides
  });
  const vrstva = style.layers.find((l) => l.id === "landcover-wood__pattern");
  if (!vrstva || (vrstva.paint || {})["fill-pattern"] !== meno) {
    chyba(
      "poc/web/themes.js",
      `vrstva so vzorom z vlastného obrázka má \`fill-pattern: ` +
        `${JSON.stringify((vrstva?.paint || {})["fill-pattern"])}\`, čakalo sa ` +
        `"${meno}" – práve nahratý obrázok sa tým ticho zahodí.`
    );
  }
  const kreslene = collectPatternNames(style);
  if (kreslene.includes(meno)) {
    chyba(
      "poc/web/patterns.js",
      `\`collectPatternNames\` vrátilo vlastný obrázok "${meno}" medzi kreslenými ` +
        `vzormi – \`workers/styles/patterns.mjs\` by cezeň do atlasu nakreslil ` +
        `šrafovanie a prepísal obrázok, ktorý tam dal \`custom-icons.mjs\`.`
    );
  }
}

// 7. šípky jednosmeriek sú v každej sade
// Kým bola `arrow` z cudzieho spritu, vrstva `road-oneway` pri dvoch z troch
// sád vôbec nevznikla a v paneli nebolo čo nastavovať.
{
  const vsetky = arrowImages();
  if (!vsetky.includes(DEFAULT_ARROW_IMAGE)) {
    chyba("poc/web/arrows.js",
      `štýl žiada šípku "${DEFAULT_ARROW_IMAGE}", ale medzi pečenými nie je ` +
      `(${vsetky.join(", ")}) – vrstva jednosmeriek by sa ticho vynechala.`);
  }
  for (const set of ICON_SOURCE_IDS) {
    // sada bez vlastnej `arrow` je ten prípad, kvôli ktorému si ich kreslíme sami
    const style = buildStyle({
      theme: Object.keys(THEMES)[0],
      tilesUrl: "pmtiles://x/t.pmtiles",
      spriteUrl: "https://x/sprite",
      // pole, nie Set: `hasIcon` sa pýta na `.length` a `.includes`
      icons: vsetky,
      sdfIcons: true,
      overrides: { ...overrides, icons: set }
    });
    if (!style.layers.some((l) => l.id === "road-oneway")) {
      chyba("poc/web/icon-sources.js",
        `pri sade "${set}" nie je v štýle vrstva "road-oneway" – jednosmerky ` +
        `by nemali šípky a v paneli by nebolo čo nastaviť.`);
    }
  }
}

console.log(
  `ikony: ${bad} chýb (${LAYOUT_PROP_IDS.length} vlastností z layout, ` +
    `${overrides.customIcons.length} vlastných ikon, ${overrides.iconSets.length} vlastných sád, ` +
    `${arrowImages().length} šípok × ${ICON_SOURCE_IDS.length} sád)`
);
process.exit(bad ? 1 : 0);
