#!/usr/bin/env node
/**
 * Kontrola úprav z developer módu. Volá ju `Kontrola · lint workflowov`.
 *
 * TRI TICHÉ VECI, VŠETKY ZAPLATENÉ:
 *
 * 1. **Nulová hrúbka čiary.** Políčko „hrúbka" v developer móde ukazuje pri
 *    krivke podľa zoomu prázdne „auto" a prázdne `input[type=number]` skočí
 *    šípkou dole na spodnú medzu. Kým tou medzou bola nula, jedno ťuknutie
 *    zhaslo celú vrstvu – mapa sa načítala, štýl bol platný, MapLibre nepovedal
 *    nič a v mape jednoducho neboli chodníky. Odvtedy je `line-width: 0` TVRDÁ
 *    chyba v `normalizeOverrides` a políčko má medzu 0,1; táto kontrola drží
 *    oboje (a zároveň to, že `text-halo-width: 0` chybou NIE JE – tam nula
 *    znamená „bez lemu", čo je bežná hodnota zo štýlu).
 *
 * 2. **Kopírovanie štýlu medzi vrstvami.** „Sprav túto vrstvu takú, ako je
 *    tamtá" odfotí `paint` hotového štýlu a zapíše ho ako úpravu. Keby z toho
 *    vypadlo čokoľvek, čo `normalizeOverrides` neprijme (krivka s viac než
 *    `MAX_PAINT_STOPS` zlomami, „bez výplne" na čiare, vlastnosť, ktorú cieľ
 *    nepozná), úprava by sa v prehliadači tvárila, že platí, a pipeline by ju
 *    pri zápise do repozitára potichu zahodila – v mape na Pages by potom bolo
 *    niečo iné než v prehliadači. Kontrola preto skúsi odfotiť KAŽDÚ vrstvu
 *    každej témy a typu mapy, vložiť ju do vrstvy toho istého aj iného druhu
 *    a trvá na tom, že `normalizeOverrides` nemá ani jednu výhradu a nič
 *    nezahodí.
 *
 * 3. **Prerušovanie čiary, ktoré vrstva má zo štýlu.** Výber „Čiara" si
 *    predvoľbu čítal z ÚPRAVY, a tá je prázdna, kým sa niečo nezmení – takže
 *    pri železnici ukazoval „Plná", hoci je čiarkovaná. A voľba „Plná" sa
 *    zahadzovala ako „veď to je predvolené", čiže sa zabudované prerušovanie
 *    nedalo ani zmeniť späť, ani vypnúť. Kontrola drží všetky tri kusy, ktoré
 *    to opravili: metadáta `frico:dash`, „solid" cez `normalizeOverrides`
 *    a to, že `applyLayerOverrides` vlastnosť naozaj ZMAŽE.
 *
 * Použitie:
 *   node workers/lint/overrides.mjs
 */
import {
  THEMES,
  buildStyle,
  builtinDash,
  emptyOverrides,
  normalizeOverrides,
  paintValue,
  scaleExpr,
  MAX_VARIANTS,
  MAX_DISPLAY_Z
} from "../../poc/web/themes.js";
import { dashArray, dashIdOf } from "../../poc/web/patterns.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const TARGET = join(ROOT, "poc", "web", "style-overrides.json");
import { snapshotStyle, pasteStyle, valueAtZoom } from "../../poc/web/layer-style.js";

/** Najmenšie platné PNG (1 × 1 px) – na skúšanie vlastných ikon. */
const PNG_1PX = "data:image/png;base64,"
  + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

let bad = 0;
const chyba = (subor, text) => {
  console.log(`::error file=${subor}::${text}`);
  bad += 1;
};

// ---------- 1. nulová hrúbka ----------
const width = (prop, value) =>
  normalizeOverrides({ layers: { x: { paint: { [prop]: value } } } });

for (const [prop, musiSpadnut] of [
  ["line-width", true],
  ["text-halo-width", false],
  ["icon-halo-width", false],
  ["circle-stroke-width", false]
]) {
  const { overrides, problems } = width(prop, 0);
  const prijate = overrides.layers.x?.paint?.[prop] === 0;
  if (musiSpadnut && (prijate || !problems.length)) {
    chyba(
      "poc/web/themes.js",
      `\`${prop}: 0\` prešlo cez normalizeOverrides. Čiara s nulovou hrúbkou ` +
      `sa nekreslí a v mape to vyzerá ako chýbajúce dáta – vrstva sa má vypínať ` +
      `cez \`visible\`, nie hrúbkou.`
    );
  }
  if (!musiSpadnut && !prijate) {
    chyba(
      "poc/web/themes.js",
      `\`${prop}: 0\` normalizeOverrides odmietol, hoci nula tam znamená ` +
      `„bez lemu" – to je bežná hodnota zo štýlu, nie chyba.`
    );
  }
}

// Kladná hrúbka musí prejsť ďalej – kontrola vyššie sa nesmie zvrhnúť na
// „zakážme hrúbku".
if (width("line-width", 1.5).overrides.layers.x?.paint?.["line-width"] !== 1.5) {
  chyba("poc/web/themes.js", "`line-width: 1.5` sa cez normalizeOverrides nedostalo.");
}

// ---------- 2. kopírovanie štýlu ----------
const styles = [];
for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    styles.push({
      kde: `${theme} × ${mapType}`,
      style: buildStyle({
        theme,
        mapType,
        tilesUrl: "pmtiles://x/t.pmtiles",
        spriteUrl: "https://x/sprite",
        glyphsUrl: "https://x/{fontstack}/{range}.pbf",
        contoursUrl: "pmtiles://x/c.pmtiles",
        rocksUrl: "pmtiles://x/r.pmtiles",
        trailsUrl: "pmtiles://x/tr.pmtiles",
        featuresUrl: "pmtiles://x/f.pmtiles",
        pointsUrl: "pmtiles://x/p.pmtiles",
        roadsUrl: "pmtiles://x/r.pmtiles",
        // Tieňovanie zapnuté NASCHVÁL: vrstva `hillshade` je jediná s
        // vlastnosťou `hillshade-exaggeration` a bez nej by sa kopírovanie
        // štýlu na túto vlastnosť vôbec neskúsilo.
        hillshade: true
      })
    });
  }
}

let skusok = 0;
let odfotenych = 0;

/** Vloží odfotený štýl do vrstvy a overí, že to `normalizeOverrides` prijme. */
function skus(snap, target, kde) {
  const { patch } = pasteStyle(snap, target);
  if (!Object.keys(patch).length) return;
  skusok += 1;
  const raw = emptyOverrides();
  raw.layers[target.id] = patch;
  const { overrides, problems } = normalizeOverrides(raw);
  if (problems.length) {
    chyba(
      "poc/web/layer-style.js",
      `kopírovanie štýlu \`${snap.from}\` → \`${target.id}\` (${kde}) vyrobilo ` +
      `úpravu, ktorú normalizeOverrides odmieta: ${problems[0]}`
    );
    return;
  }
  const clean = overrides.layers[target.id] || {};
  for (const key of Object.keys(patch)) {
    if (key === "paint") continue;
    if (clean[key] === undefined) {
      chyba(
        "poc/web/layer-style.js",
        `kopírovanie štýlu \`${snap.from}\` → \`${target.id}\` (${kde}): ` +
        `\`${key}\` sa cez normalizeOverrides nedostalo – v prehliadači by ` +
        `platilo, v hotovej mape nie.`
      );
    }
  }
  for (const prop of Object.keys(patch.paint || {})) {
    if ((clean.paint || {})[prop] === undefined) {
      chyba(
        "poc/web/layer-style.js",
        `kopírovanie štýlu \`${snap.from}\` → \`${target.id}\` (${kde}): ` +
        `vlastnosť \`${prop}\` normalizeOverrides zahodil.`
      );
    }
  }
}

for (const { kde, style } of styles) {
  // Zástupca každého druhu vrstvy – do neho sa skúša vkladať naprieč druhmi.
  const zastupca = new Map();
  for (const layer of style.layers) if (!zastupca.has(layer.type)) zastupca.set(layer.type, layer);

  for (const layer of style.layers) {
    const snap = snapshotStyle(layer, {});
    odfotenych += 1;
    skus(snap, layer, kde);
    for (const target of zastupca.values()) if (target.id !== layer.id) skus(snap, target, kde);
  }
}

// ---------- 3. „čo to robí na tomto zoome" ----------
// Hodnota, ktorou sa napĺňa prázdne políčko, musí sedieť so štýlom aspoň
// v zlomoch – inak by šípka začínala inde, než mapa práve kreslí.
const krivka = ["interpolate", ["exponential", 1.5], ["zoom"], 11, 0.4, 16, 2.2];
for (const [z, cakane] of [[8, 0.4], [11, 0.4], [16, 2.2], [20, 2.2]]) {
  const dostal = valueAtZoom(krivka, z);
  if (dostal !== cakane) {
    chyba(
      "poc/web/layer-style.js",
      `valueAtZoom pri z${z} vrátilo ${dostal}, čakalo sa ${cakane}.`
    );
  }
}
if (valueAtZoom(["match", ["get", "x"], "a", 1, 2], 14) !== null) {
  chyba(
    "poc/web/layer-style.js",
    "valueAtZoom vrátilo číslo pre výraz podľa atribútu prvku – to sa jedným " +
    "zoomom povedať nedá a vymyslená hodnota je horšia než žiadna."
  );
}

// ---------- 4. zoomové pásma ----------
// „Od z9 do z11 takáto čiara, na z12 takáto" je vlastný tvar úpravy
// (`[[od, do, hodnota], …]`) a stojí a padá s tým, že rad pásiem je SÚVISLÝ.
// Medzera aj prekryv musia byť tvrdá chyba: keby sa medzera doplnila držaním
// predošlej hodnoty, „do 11" by neplatilo a nikto by to nemal ako spozorovať.
const pasma = (value) =>
  normalizeOverrides({ layers: { x: { paint: { "line-width": value } } } });

for (const [popis, value, musiPrejst] of [
  ["súvislé pásma", [[9, 11, 2], [12, 12, 4], [13, 17, 6]], true],
  ["jedno pásmo", [[9, 17, 2]], true],
  ["medzera medzi pásmami", [[9, 11, 2], [14, 17, 6]], false],
  ["prekryv pásiem", [[9, 11, 2], [11, 17, 6]], false],
  ["zmiešaná krivka a pásmo", [[9, 2], [12, 13, 4]], false],
  ["desatinný zoom v pásme", [[9, 11.5, 2], [12, 17, 6]], false],
  ["pásmo naopak", [[13, 11, 2]], false]
]) {
  const { overrides, problems } = pasma(value);
  const prijate = overrides.layers.x?.paint?.["line-width"] !== undefined;
  if (musiPrejst && (!prijate || problems.length)) {
    chyba("poc/web/themes.js",
      `zoomové pásma (${popis}) neprešli cez normalizeOverrides: ${problems[0] || "zahodené bez dôvodu"}`);
  }
  if (!musiPrejst && (prijate || !problems.length)) {
    chyba("poc/web/themes.js",
      `zoomové pásma (${popis}) prešli cez normalizeOverrides. Rad pásiem musí ` +
      `byť súvislý a v jednom tvare – inak platí niečo iné, než čo je napísané.`);
  }
}

// Hranica pásma je tam, kde hovorí – vrátane desatinných zoomov pod ňou.
// (`do 11` znamená „ešte na z11,9", nie „po z11,0".)
const schodisko = paintValue([[9, 11, 2], [12, 12, 4], [13, 17, 6]]);
for (const [z, cakane] of [[5, 2], [9, 2], [11.9, 2], [12, 4], [12.9, 4], [13, 6], [20, 6]]) {
  const dostal = valueAtZoom(schodisko, z);
  if (dostal !== cakane) {
    chyba("poc/web/layer-style.js",
      `pásma pri z${z} vrátili ${dostal}, čakalo sa ${cakane} – hranica pásma ` +
      `nie je tam, kde ju úprava sľubuje.`);
  }
}

// A to isté, čo pri kopírovaní štýlu: čo sa zo `step` vrstvy odfotí, musí
// `normalizeOverrides` prijať CELÉ. Inak by úprava v prehliadači platila
// a pipeline by ju pri zápise do repozitára potichu zahodila.
{
  const vrstva = {
    id: "schody",
    type: "line",
    paint: { "line-width": schodisko, "line-color": paintValue([[0, 9, "#112233"], [10, MAX_DISPLAY_Z, "#445566"]]) }
  };
  const snap = snapshotStyle(vrstva, {});
  if (snap.dropped.length) {
    chyba("poc/web/layer-style.js",
      `odfotenie \`step\` vrstvy zahodilo ${snap.dropped.join(", ")} – schodisko ` +
      `podľa zoomu sa má odfotiť ako zoomové pásma.`);
  }
  const raw = emptyOverrides();
  raw.layers.schody = { paint: snap.paint };
  const { overrides, problems } = normalizeOverrides(raw);
  if (problems.length) {
    chyba("poc/web/layer-style.js",
      `odfotené \`step\` vrstvy normalizeOverrides odmieta: ${problems[0]}`);
  }
  for (const prop of Object.keys(snap.paint)) {
    if ((overrides.layers.schody?.paint || {})[prop] === undefined) {
      chyba("poc/web/layer-style.js",
        `odfotená vlastnosť \`${prop}\` zo \`step\` vrstvy sa cez normalizeOverrides nedostala.`);
    }
  }
}

// ---------- 5. čo developer mode nastaví, to sa aj ULOŽÍ ----------
// TICHÁ VEC, KTORÁ SA STALA: `workers/styles/overrides.mjs` skladá súbor pre
// repozitár po kľúčoch (`palette`, `layers`, `poi`, `maps`…) a na `trails`
// zabudol. Developer mode vedel odstup pásikov, vzor čiary aj značku
// nastaviť, uložiť aj zobraziť – ale do `poc/web/style-overrides.json` z toho
// neprišlo NIČ a ďalší build kreslil trasy po starom. Nespadlo pri tom nič:
// zapísaný súbor bol platný, len o polovicu chudobnejší.
//
// Kontroluje sa to tak, ako to naozaj chodí: úpravy prejdú tým skriptom
// (`--file`, bez `--check`, do dočasného repozitára) a musia sa vrátiť.
{
  const ukazka = {
    trails: {
      gap: { road: 8 },
      types: { hiking: { dash: "dotted", icon: "", mark: "triangle" } },
      marks: { spacing: 300, size: 1.2 }
    },
    shields: { motorway: { shape: "shield-round" } },
    // Vlastná sada aj vlastná ikona: oboje ovplyvňuje BUILD (sťahovanie
    // spritu a jeho dopečenie), takže sa musí dostať do repozitára celé –
    // vrátane samotného obrázka, ktorý je tou najväčšou časťou súboru.
    iconSets: [
      { id: "own-test", label: "Test", sprite: "https://example.org/sprites/test", suffix: "_11" }
    ],
    customIcons: [{ name: "own:test", png: PNG_1PX, pixelRatio: 2 }],
    palette: {},
    // Poradie kreslenia je v súbore vlastný kľúč (`order`), nie vlastnosť
    // vrstvy – teda presne ten druh položky, na ktorý `overrides.mjs` už raz
    // pri skladaní súboru zabudol.
    order: [{ id: "feature-embankment", before: "road-minor" }],
    // Ikony kategórií sedia v `poi` vedľa skrytých tried – ten kľúč sa
    // zapisuje ako celok, takže sa pri ňom dá zabudnúť práve na polovicu.
    poi: { hidden: ["fuel"], icons: { restaurant: "bar_11", spring: "" } },
    // `layout` je druhá polica vedľa `paint` – veľkosť ikony a rozostup po
    // čiare sa ňou ladia (značky trás), takže tá istá otázka: prežije zápis?
    layers: {
      "trail-hiking-mark": {
        layout: { "icon-size": 1.2, "symbol-spacing": [[12, 13, 120], [14, 20, 260]] }
      },
      // Vzor z vlastného obrázka: obrázok je vlastná ikona vyššie, takže sa
      // do repozitára musia dostať OBE polovice – meno vo vrstve aj samotný
      // PNG. Keby prežila len jedna, mapa by ostala bez vzoru.
      "landcover-wood": { pattern: { image: "own:test", opacity: 0.8 } }
    }
  };
  const { overrides } = normalizeOverrides(ukazka);
  const dir = mkdtempSync(join(tmpdir(), "overrides-lint-"));
  try {
    // Skript zapisuje do `poc/web/style-overrides.json` v koreni repozitára,
    // tak dostane kópiu tých súborov, ktoré na to potrebuje.
    const vstup = join(dir, "in.json");
    writeFileSync(vstup, JSON.stringify(ukazka));
    const zaloha = readFileSync(TARGET, "utf8");
    try {
      execFileSync("node", ["workers/styles/overrides.mjs", `--file=${vstup}`], {
        stdio: "pipe",
        cwd: ROOT
      });
      const zapisane = normalizeOverrides(JSON.parse(readFileSync(TARGET, "utf8"))).overrides;
      const chyba_ak = (cesta, a, b) => {
        if (JSON.stringify(a) !== JSON.stringify(b)) {
          chyba(
            "workers/styles/overrides.mjs",
            `zápis do style-overrides.json stratil \`${cesta}\`: ` +
              `${JSON.stringify(a)} → ${JSON.stringify(b)}. V prehliadači to platí, ` +
              `v repozitári nie – mapa na Pages bude iná než developer mode.`
          );
        }
      };
      chyba_ak("trails.gap", overrides.trails.gap, zapisane.trails.gap);
      chyba_ak("order", overrides.order, zapisane.order);
      chyba_ak("poi.icons", overrides.poi.icons, zapisane.poi.icons);
      chyba_ak(
        "layers[landcover-wood].pattern",
        overrides.layers["landcover-wood"]?.pattern,
        zapisane.layers["landcover-wood"]?.pattern
      );
      chyba_ak("iconSets", overrides.iconSets, zapisane.iconSets);
      chyba_ak("customIcons", overrides.customIcons, zapisane.customIcons);
      chyba_ak(
        "layers[trail-hiking-mark].layout",
        overrides.layers["trail-hiking-mark"]?.layout,
        zapisane.layers["trail-hiking-mark"]?.layout
      );
      chyba_ak("trails.types", overrides.trails.types, zapisane.trails.types);
      chyba_ak("trails.marks", overrides.trails.marks, zapisane.trails.marks);
      chyba_ak("shields", overrides.shields, zapisane.shields);
    } finally {
      writeFileSync(TARGET, zaloha);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// ---------- 6. prerušovanie čiary sa dá aj VRÁTIŤ ----------
// TRETIA TICHÁ VEC: developer mode ukazoval pri každej čiare „Plná" – aj pri
// železnici, ktorá má `rail` – lebo si predvoľbu čítal z úpravy, a tá je
// prázdna, kým sa niečo nezmení. Voľba „Plná" sa navyše zahadzovala ako
// „veď to je predvolené", takže sa čiarkovanie železnice nedalo ani zmeniť,
// ani vypnúť: panel voľbu prijal, uložil z nej prázdno a v mape ostalo
// pôvodné prerušovanie. Nespadlo nič.
//
// Držia to tri veci naraz a kontrola je na všetky tri: metadáta
// (`frico:dash` – čo má vrstva zo štýlu), `normalizeOverrides` (nezahodí
// „solid") a `applyLayerOverrides` („solid" vlastnosť ZMAŽE, nie nastaví
// na `null`, ktoré by MapLibre neprijal).
{
  let sChiarkou = 0;
  for (const { kde, style } of styles) {
    for (const layer of style.layers) {
      if (layer.type !== "line") continue;
      if ((layer.metadata || {})["frico:derived"]) continue;
      const arr = (layer.paint || {})["line-dasharray"];
      const meta = (layer.metadata || {})["frico:dash"];
      if (!Array.isArray(arr)) {
        if (meta !== undefined) {
          chyba("poc/web/themes.js",
            `vrstva \`${layer.id}\` (${kde}) nesie \`frico:dash\`, hoci plnú čiaru ` +
            `– panel by ponúkal návrat na prerušovanie, ktoré v štýle nie je.`);
        }
        continue;
      }
      sChiarkou += 1;
      const rovnake = typeof meta === "string"
        ? JSON.stringify(dashArray(meta)) === JSON.stringify(arr)
        : JSON.stringify(meta) === JSON.stringify(arr);
      if (!rovnake) {
        chyba("poc/web/themes.js",
          `vrstva \`${layer.id}\` (${kde}) má v štýle \`line-dasharray: ` +
          `${JSON.stringify(arr)}\`, ale v metadátach \`${JSON.stringify(meta)}\`. ` +
          `Developer mode číta prerušovanie odtiaľ – ukazoval by inú čiaru, ` +
          `než je v mape, a „späť na pôvodnú" by ju nevrátilo.`);
      }
    }
  }
  if (!sChiarkou) {
    chyba("workers/lint/overrides.mjs",
      "v štýle nie je ani jedna čiara s prerušovaním – kontrola nemá čo strážiť.");
  }

  // „solid" musí prežiť normalizáciu…
  const { overrides: soVolbou } = normalizeOverrides({
    layers: { "rail-hatch": { dash: "solid" } }
  });
  if (soVolbou.layers["rail-hatch"]?.dash !== "solid") {
    chyba("poc/web/themes.js",
      "`dash: \"solid\"` normalizeOverrides zahodil. Vrstva, ktorá má " +
      "prerušovanie zo štýlu (železnica, brod), sa potom nedá vrátiť na plnú " +
      "čiaru – voľba sa prijme a v mape sa nestane nič.");
  }

  // …a v hotovom štýle to prerušovanie naozaj zmazať.
  const spolu = (o) => buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    overrides: o
  });
  const zaklad = spolu(null).layers.find((l) => l.id === "rail-hatch");
  if (!zaklad || builtinDash(zaklad) !== "rail") {
    chyba("poc/web/themes.js",
      "`rail-hatch` nemá zabudované prerušovanie `rail` – čiarkovanie železnice " +
      "je práve tá vrstva, na ktorej sa to celé ukázalo.");
  }
  const plna = spolu(soVolbou).layers.find((l) => l.id === "rail-hatch");
  if (plna && (plna.paint || {})["line-dasharray"] !== undefined) {
    chyba("poc/web/themes.js",
      `\`dash: "solid"\` nechalo na \`rail-hatch\` \`line-dasharray: ` +
      `${JSON.stringify(plna.paint["line-dasharray"])}\`. Plná čiara znamená ` +
      `vlastnosť ZMAZAŤ – \`null\` by MapLibre neprijal.`);
  }
  const ine = spolu(normalizeOverrides({ layers: { "rail-hatch": { dash: "ties" } } }).overrides)
    .layers.find((l) => l.id === "rail-hatch");
  if (JSON.stringify((ine.paint || {})["line-dasharray"]) !== JSON.stringify(dashArray("ties"))) {
    chyba("poc/web/themes.js",
      "zmena prerušovania na `ties` sa na `rail-hatch` neprejavila.");
  }
  // A poistka proti opačnému omylu: `dashIdOf` nesmie tvrdiť, že vlastné
  // prerušovanie je niektorá z predvolieb.
  if (dashIdOf([0.35, 2.2]) !== null) {
    chyba("poc/web/patterns.js",
      "`dashIdOf` pomenovalo vlastné prerušovanie predvoľbou – panel by ho " +
      "pri prvom uložení prepísal na inú čiaru.");
  }
}

// ---------- 7. poradie kreslenia ----------
// Presun vrstvy je jediná úprava, ktorá mení ŠTRUKTÚRU štýlu, nie hodnoty
// v ňom – a tri veci sa pri tom dajú pokaziť ticho:
//
//   * vrstva sa pri presune STRATÍ (alebo sa zdvojí) a v mape jednoducho nie
//     je – štýl je pritom platný,
//   * odvodená vrstva (vzor, okraj) alebo druhá polovica dvojice (zúbky
//     hrany, čiarkovanie železnice) ostane, kde bola, takže sa prvok rozpadne
//     na dve polovice na dvoch miestach,
//   * niekto presunie vrstvu ZA masku regiónu a tá potom kreslí aj mimo
//     stiahnutého regiónu – presne to, kvôli čomu maska existuje.
{
  const postav = (order) => buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    featuresUrl: "pmtiles://x/f.pmtiles",
    pointsUrl: "pmtiles://x/p.pmtiles",
    roadsUrl: "pmtiles://x/r.pmtiles",
    regionOutline: { type: "FeatureCollection", features: [] },
    overrides: normalizeOverrides({ order }).overrides
  });

  const bez = postav([]).layers.map((l) => l.id);
  const skus = (popis, order, over) => {
    const layers = postav(order).layers;
    const ids = layers.map((l) => l.id);
    if (ids.length !== bez.length || new Set(ids).size !== ids.length) {
      chyba("poc/web/themes.js",
        `presun vrstiev (${popis}) zmenil počet vrstiev: ${bez.length} → ${ids.length} ` +
        `(z toho ${new Set(ids).size} rôznych). Vrstva, ktorá sa pri presune stratí, ` +
        `nie je v mape a štýl je pritom platný.`);
    }
    const posledne = ids.slice(-2);
    if (JSON.stringify(posledne) !== JSON.stringify(["region-outside", "region-border"])) {
      chyba("poc/web/themes.js",
        `presun vrstiev (${popis}) nechal navrchu ${posledne.join(", ")} namiesto masky ` +
        `regiónu. Vrstva za maskou kreslí aj mimo stiahnutého regiónu.`);
    }
    over(ids);
  };

  skus("násyp pod cesty", [{ id: "feature-embankment", before: "road-minor" }], (ids) => {
    if (!(ids.indexOf("feature-embankment") < ids.indexOf("road-minor"))) {
      chyba("poc/web/themes.js", "presun `feature-embankment` pod `road-minor` sa neprejavil.");
    }
    // Zúbky sú druhá polovica tej istej hrany (`frico:with`) – musia ísť s ňou.
    if (ids.indexOf("feature-embankment-teeth") - ids.indexOf("feature-embankment") !== 1) {
      chyba("poc/web/themes.js",
        "`feature-embankment-teeth` ostali pri presune na mieste – hrana by bola pod " +
        "cestou a jej zúbky nad ňou.");
    }
  });

  skus("železnica navrch", [{ id: "rail-bg", before: null }], (ids) => {
    if (ids.indexOf("rail-hatch") - ids.indexOf("rail-bg") !== 1) {
      chyba("poc/web/themes.js",
        "`rail-hatch` sa nepresunul s `rail-bg` – z čiarkovanej železnice by bola " +
        "tmavá čiara na jednom mieste a biele čiarky na druhom.");
    }
  });

  skus("vrstva, ktorú tento štýl nemá", [
    { id: "neexistuje", before: "water" },
    { id: "water", before: "tiez-neexistuje" }
  ], () => {});

  // Presun ZA masku sa nesmie dať – kontroluje to `skus` vyššie pri každom
  // volaní, tu je to napísané výslovne.
  skus("pokus prekryť masku", [{ id: "background", before: null }], () => {});
}

// ---------- 8. každá záložka panela sa aj kreslí ----------
// TICHÁ VEC, KTORÁ SA PONÚKA SAMA: zoznam záložiek (`TABS`) a prepínač
// v `renderBody` sú dve miesta. Keď v prepínači nejaká chýba, nespadne nič –
// ťuknutie na ňu prepadne do POSLEDNEJ vetvy (`renderFile`), takže sa
// otvorí záložka „Súbor" s JSON-om a vyzerá to, že panel „nefunguje".
{
  const zdroj = readFileSync(join(ROOT, "poc", "web", "devmode.js"), "utf8");
  const blok = zdroj.match(/const TABS = \[([\s\S]*?)\];/);
  if (!blok) {
    chyba("poc/web/devmode.js", "zoznam záložiek `TABS` sa nenašiel – kontrola nemá čo strážiť.");
  } else {
    const ids = [...blok[1].matchAll(/\["([a-z]+)",/g)].map((m) => m[1]);
    if (ids.length < 2) {
      chyba("poc/web/devmode.js", "zo zoznamu `TABS` sa nedali prečítať id záložiek.");
    }
    // Posledná záložka je zámerne bez podmienky – je to koncová vetva
    // prepínača (`: renderFile()`), teda tá, do ktorej všetko prepadne.
    for (const id of ids.slice(0, -1)) {
      if (!zdroj.includes(`tab === "${id}"`)) {
        chyba(
          "poc/web/devmode.js",
          `záložka "${id}" je v zozname, ale \`renderBody\` ju nekreslí – ` +
          `ťuknutie na ňu otvorí poslednú vetvu prepínača (záložku „Súbor").`
        );
      }
    }
  }
}

// ---------- 8. relatívna hodnota `{scale, add}` ----------
// „Nechaj krivku zo štýlu, len ju preškáluj". Dve veci sa tu strážia a obe
// boli tiché:
//
//   * `scaleExpr` nad PÁSMAMI. Kým to vedela len krivka, obrys nad čiarou so
//     šírkou v pásmach dostal výraz NEZMENENÝ – čiže bol presne taký široký
//     ako čiara, teda neviditeľný. Štýl platný, mapa načítaná, nikto nič.
//   * `{scale: 1, add: 0}` nesmie prejsť: uložené by bolo len šumom v súbore
//     a v paneli by nad nezmenenou vrstvou svietilo „zmenené".
const rel = (value, prop = "line-width") =>
  normalizeOverrides({ layers: { x: { paint: { [prop]: value } } } });

for (const [popis, value, prop, musiPrejst] of [
  ["percento", { scale: 1.4 }, "line-width", true],
  ["konštanta", { add: 0.5 }, "line-width", true],
  ["oboje", { scale: 1.4, add: 0.5 }, "line-width", true],
  ["nič nemení", { scale: 1, add: 0 }, "line-width", false],
  ["nula ako násobok", { scale: 0 }, "line-width", false],
  ["mimo medze", { scale: 99 }, "line-width", false],
  ["nečíslo", { scale: "hodne" }, "line-width", false],
  ["nad farbou", { scale: 1.4 }, "line-color", false]
]) {
  const { overrides, problems } = rel(value, prop);
  const prijate = overrides.layers.x?.paint?.[prop] !== undefined;
  if (musiPrejst && (!prijate || problems.length)) {
    chyba("poc/web/themes.js",
      `relatívna hodnota (${popis}) neprešla cez normalizeOverrides: ` +
      `${problems[0] || "zahodená bez dôvodu"}`);
  }
  if (!musiPrejst && (prijate || !problems.length)) {
    chyba("poc/web/themes.js",
      `relatívna hodnota (${popis}) prešla cez normalizeOverrides – a nemala.`);
  }
}

// Krivka si musí nechať DRUH interpolácie: `zw` je `exponential 1.5` a lineárna
// náhrada by šírky medzi zlomami ticho posunula.
const skalovana = scaleExpr(
  ["interpolate", ["exponential", 1.5], ["zoom"], 11, 0.4, 16, 2.2], { scale: 2 }
);
if (JSON.stringify(skalovana.slice(0, 3)) !== JSON.stringify(["interpolate", ["exponential", 1.5], ["zoom"]])) {
  chyba("poc/web/themes.js", "scaleExpr zmenil druh interpolácie – šírky medzi zlomami by sedeli inde.");
}
for (const [z, cakane] of [[11, 0.8], [16, 4.4]]) {
  if (valueAtZoom(skalovana, z) !== cakane) {
    chyba("poc/web/themes.js",
      `scaleExpr nad krivkou dal pri z${z} ${valueAtZoom(skalovana, z)}, čakalo sa ${cakane}.`);
  }
}
// A to isté nad PÁSMAMI – práve tie `widenExpr` kedysi prepustil nezmenené.
const pasmaSkalovane = scaleExpr(paintValue([[9, 11, 2], [12, 17, 5]]), { add: 3 });
for (const [z, cakane] of [[9, 5], [12, 8]]) {
  if (valueAtZoom(pasmaSkalovane, z) !== cakane) {
    chyba("poc/web/themes.js",
      `scaleExpr nad pásmami dal pri z${z} ${valueAtZoom(pasmaSkalovane, z)}, ` +
      `čakalo sa ${cakane} – obrys nad takou čiarou by bol presne taký široký ako ona.`);
  }
}
// Výraz podľa atribútu prvku sa prepisovať NESMIE – naslepo zmenená farba či
// šírka podľa dát je tichá zmena mapy.
const podlaDat = ["match", ["get", "x"], "a", 1, 2];
if (JSON.stringify(scaleExpr(podlaDat, { scale: 2 })) !== JSON.stringify(podlaDat)) {
  chyba("poc/web/themes.js", "scaleExpr prepísal výraz podľa atribútu prvku.");
}

// Obrys nad čiarou so šírkou v PÁSMACH musí byť naozaj širší než čiara.
{
  const { overrides } = normalizeOverrides({
    layers: {
      "road-path": {
        paint: { "line-width": [[11, 13, 2], [14, 20, 5]] },
        outline: { color: "#112233", width: 1.5 }
      }
    }
  });
  const s = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                         spriteUrl: "https://x/sprite", overrides });
  const ciara = s.layers.find((l) => l.id === "road-path");
  const obrys = s.layers.find((l) => l.id === "road-path__outline");
  if (!ciara || !obrys) {
    chyba("poc/web/themes.js", "obrys nad čiarou s pásmami vôbec nevznikol.");
  } else {
    for (const z of [12, 16]) {
      const a = valueAtZoom(ciara.paint["line-width"], z);
      const b = valueAtZoom(obrys.paint["line-width"], z);
      if (!(b > a)) {
        chyba("poc/web/themes.js",
          `obrys pri z${z} je ${b}, čiara ${a} – obrys, ktorý nie je širší, nie je vidieť.`);
      }
    }
  }
}

// ---------- 9. rozlíšenie podľa atribútu OSM ----------
// PRVOK SA SMIE NAKRESLIŤ RAZ. Variant si berie svoje hodnoty, predloha si
// k filtru pridá ich negáciu – bez toho druhého by sa čiara kreslila dvakrát
// cez seba a vyzeralo by to len „nejako hrubšie".
let variantov = 0;
{
  const test = (v) => normalizeOverrides({ layers: { "road-track": { variants: v } } });
  for (const [popis, v, musiPrejst] of [
    ["jeden variant", [{ attr: "surface", values: ["paved"] }], true],
    ["bez hodnôt", [{ attr: "surface", values: [] }], false],
    ["bez atribútu", [{ values: ["paved"] }], false],
    ["neplatné meno atribútu", [{ attr: "s urface!", values: ["paved"] }], false],
    ["dva varianty nad tou istou hodnotou",
     [{ attr: "surface", values: ["paved"] }, { attr: "surface", values: ["paved"] }], false],
    ["viac než strop", Array.from({ length: MAX_VARIANTS + 1 },
      (_, i) => ({ attr: "surface", values: [`v${i}`] })), false]
  ]) {
    const { overrides, problems } = test(v);
    const prijate = (overrides.layers["road-track"]?.variants || []).length === v.length;
    if (musiPrejst && (!prijate || problems.length)) {
      chyba("poc/web/themes.js",
        `variant (${popis}) neprešiel cez normalizeOverrides: ${problems[0] || "zahodený bez dôvodu"}`);
    }
    if (!musiPrejst && (prijate || !problems.length)) {
      chyba("poc/web/themes.js", `variant (${popis}) prešiel cez normalizeOverrides – a nemal.`);
    }
  }

  const { overrides } = normalizeOverrides({
    layers: {
      "road-track": {
        variants: [{ attr: "surface", values: ["paved", "asphalt"], label: "spevnené",
                     dash: "solid", outline: { color: "#8a7a6a", width: { scale: 1.6 } } }]
      }
    }
  });
  const s = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                         spriteUrl: "https://x/sprite", overrides });
  const predloha = s.layers.find((l) => l.id === "road-track");
  const variant = s.layers.find((l) => l.id === "road-track__var1");
  const obrys = s.layers.find((l) => l.id === "road-track__var1__outline");
  variantov = [predloha, variant, obrys].filter(Boolean).length;
  const testExpr = JSON.stringify(["in", ["coalesce", ["get", "surface"], ""],
                                   ["literal", ["paved", "asphalt"]]]);
  if (!variant) {
    chyba("poc/web/themes.js", "variant vrstvy sa v štýle nevyrobil.");
  } else if (!JSON.stringify(variant.filter).includes(testExpr)) {
    chyba("poc/web/themes.js", "filter variantu neobsahuje test atribútu.");
  }
  if (!predloha || !JSON.stringify(predloha.filter).includes(`["!",${testExpr}]`)) {
    chyba("poc/web/themes.js",
      "filter predlohy nie je zúžený o negáciu variantu – prvok by sa nakreslil " +
      "dvakrát cez seba a v mape by to vyzeralo len „nejako hrubšie“.");
  }
  // Obrys variantu sa musí hlásiť ku KOREŇU, inak ho presun poradia nechá
  // stáť tam, kde predloha už nie je.
  if (!obrys || (obrys.metadata || {})["frico:derived"] !== "road-track") {
    chyba("poc/web/themes.js",
      "obrys variantu sa nehlási k predlohe – presun poradia by ho nechal za ňou.");
  }
  // Obrys je 1,6× čiara, teda naozaj širší na KAŽDOM zoome (o to pri percente ide).
  if (variant && obrys) {
    for (const z of [11, 16, 20]) {
      const a = valueAtZoom(variant.paint["line-width"], z);
      const b = valueAtZoom(obrys.paint["line-width"], z);
      if (!(b > a)) {
        chyba("poc/web/themes.js",
          `obrys variantu pri z${z} je ${b}, čiara ${a} – percento má držať pomer na všetkých zoomoch.`);
      }
    }
  }
  const idcka = s.layers.map((l) => l.id);
  if (new Set(idcka).size !== idcka.length) {
    chyba("poc/web/themes.js", "varianty vyrobili dve vrstvy s tým istým id – MapLibre taký štýl odmietne.");
  }
}

console.log(
  `úpravy: ${bad} chýb (${odfotenych} odfotených vrstiev, ${skusok} vložení, ` +
  `7 tvarov zoomových pásiem, 8 tvarov relatívnej hodnoty, ` +
  `6 tvarov variantu, ${variantov} vrstiev z variantu, ` +
  `${Object.keys(THEMES).length} tém × ${MAP_TYPE_IDS.length} typov mapy)`
);
process.exit(bad ? 1 : 0);
