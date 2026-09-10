#!/usr/bin/env node
/**
 * Typ cesty, ktorý sa dá vypnúť v profile, musí mapa vedieť aj nakresliť.
 *
 * Zoznam typov ciest je v `workers/data/routing-tags.json` (`siet`) a appka
 * z neho robí prepínače – pri každom čiaru tak, ako ju kreslí mapa. Keď sa tie
 * dva zoznamy rozídu, nespadne nič: prepínač ostane bez ukážky, alebo je na
 * mape cesta, ktorú sa nedá vypnúť.
 *
 * Obe strany sú chyba a obe majú výnimku S DÔVODOM – mlčanie je zakázané:
 *   1. typ zo slovníka, ktorého triedu štýl nekreslí (`NEKRESLENE`);
 *   2. trieda cesty v štýle, na ktorú neukazuje ani jeden typ (`NEJAZDNE`).
 *
 *   node workers/lint/roadtypes.mjs
 */
import { readFileSync } from "node:fs";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const TAGS = "workers/data/routing-tags.json";

/**
 * OSM → trieda (a podtrieda) vo vrstve `transportation`.
 *
 * Je to KÓPIA cudzieho zoznamu – `highway_class` v schéme OpenMapTiles
 * (`layers/transportation/transportation.yaml`). Pri posune OpenMapTiles sa
 * obnovuje odtiaľ, nie dopisuje o to jedno meno, ktoré práve chýba.
 */
const OMT = {
  motorway: ["motorway"], motorway_link: ["motorway"],
  trunk: ["trunk"], trunk_link: ["trunk"],
  primary: ["primary"], primary_link: ["primary"],
  secondary: ["secondary"], secondary_link: ["secondary"],
  tertiary: ["tertiary"], tertiary_link: ["tertiary"],
  unclassified: ["minor"], residential: ["minor"], living_street: ["minor"],
  road: ["minor"],
  service: ["service"], pedestrian: ["pedestrian"], track: ["track"],
  busway: ["busway"], bus_guideway: ["bus_guideway"], raceway: ["raceway"],
  path: ["path", "path"], footway: ["path", "footway"],
  cycleway: ["path", "cycleway"], bridleway: ["path", "bridleway"],
  steps: ["path", "steps"], corridor: ["path", "corridor"],
  ferry: ["ferry"], platform: ["path", "platform"]
};

/** Typ zo slovníka, ktorý vo vrstve `transportation` nie je – a prečo. */
const NEKRESLENE = {
  via_ferrata:
    "OpenMapTiles preň triedu nevydáva. Na mape je ako ZNAČENÁ TRASA " +
    "(`route=via_ferrata`, workers/trails), takže vidieť ju je – len nie ako " +
    "cestu z `transportation`."
};

/** Trieda, ktorú štýl kreslí a routovať sa po nej nedá – a prečo. */
const NEJAZDNE = {
  rail: "koľaj; vlak je `transit` a ten stojí na GTFS (docs/navigation.md §6)",
  transit: "električka a metro – to isté, cestovný poriadok v OSM nie je",
  pier: "mólo je plocha, po ktorej sa chodí, nie čiara siete",
  bridge: "teleso mosta ako plocha; jazdí sa po ceste NAD ním",
  aerialway: "lanovka a vlek – v slovníku sú pod `aerialway`, nie `highway`"
};

const bad = [];

function triedy() {
  const hit = { class: new Set(), subclass: new Set() };
  const menoTagu = (x) =>
    Array.isArray(x) && x[0] === "coalesce" && Array.isArray(x[1])
      && x[1][0] === "get" ? x[1][1]
      : Array.isArray(x) && x[0] === "get" ? x[1] : null;
  const chod = (f) => {
    if (!Array.isArray(f)) return;
    const [op, a, b] = f;
    const p = menoTagu(a);
    if (p && (op === "==" || op === "!=")) hit[p]?.add(String(b));
    if (p && op === "in" && Array.isArray(b) && b[0] === "literal") {
      for (const v of b[1]) hit[p]?.add(String(v));
    }
    for (const x of f) chod(x);
  };
  for (const theme of Object.keys(THEMES)) {
    for (const mapType of MAP_TYPE_IDS) {
      const st = buildStyle({
        theme, mapType,
        tilesUrl: "https://x/tiles.pmtiles",
        spriteUrl: "https://x/sprite",
        glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
        transportUrl: "https://x/transport.pmtiles"
      });
      for (const l of st.layers) {
        if (l["source-layer"] === "transportation") chod(l.filter);
      }
    }
  }
  hit.class.delete("");
  hit.subclass.delete("");
  return hit;
}

const slovnik = JSON.parse(readFileSync(TAGS, "utf8"));
const siet = slovnik.siet;
const kreslene = triedy();

// 1. čo profil ponúka, musí byť na mape vidieť
const typy = [
  ...siet.highway,
  ...(siet.route || []),
  ...(siet.railway || []),
  ...(siet.aerialway || []).map(() => "aerialway")
];
for (const typ of new Set(typy)) {
  if (NEKRESLENE[typ]) continue;
  const map = typ === "aerialway" ? ["aerialway"] : OMT[typ];
  if (!map) {
    bad.push(
      `${TAGS}: typ cesty \`${typ}\` sa dá vypnúť v profile, ale \`OMT\` vo ` +
      `\`workers/lint/roadtypes.mjs\` ho nepozná – nikto teda nevie, akú ` +
      `triedu má v dlaždici, takže sa k prepínaču nedá nakresliť čiara tak, ` +
      `ako ju kreslí mapa. Doplň mapovanie, alebo dôvod do \`NEKRESLENE\`.`);
    continue;
  }
  const [trieda, podtrieda] = map;
  if (!kreslene.class.has(trieda)) {
    bad.push(
      `${TAGS}: typ \`${typ}\` má v dlaždici triedu \`${trieda}\`, ktorú štýl ` +
      `nekreslí. Prepínač v profile by ostal bez ukážky – a používateľ by ` +
      `vypínal cestu, ktorú na mape nevidí.`);
  }
  if (podtrieda && !kreslene.subclass.has(podtrieda)) {
    bad.push(
      `${TAGS}: typ \`${typ}\` má podtriedu \`${podtrieda}\`, ktorú štýl ` +
      `nekreslí – prepínač by bol bez ukážky.`);
  }
}

// 2. čo mapa kreslí ako cestu, musí sa dať vypnúť
const zo_slovnika = new Set();
for (const typ of new Set(typy)) {
  const map = typ === "aerialway" ? ["aerialway"] : OMT[typ];
  if (map) zo_slovnika.add(map[0]);
}
for (const trieda of [...kreslene.class].sort()) {
  // `*_construction` je tá istá cesta vo výstavbe – ísť po nej sa nedá
  if (trieda.endsWith("_construction") || NEJAZDNE[trieda]) continue;
  if (zo_slovnika.has(trieda)) continue;
  bad.push(
    `${TAGS}: štýl kreslí triedu \`${trieda}\`, ale nevedie k nej ani jeden ` +
    `typ zo \`siet\`. Na mape je teda cesta, ktorú si používateľ v profile ` +
    `nemá ako vypnúť – a trasa po nej pôjde ďalej. Doplň typ do slovníka, ` +
    `alebo dôvod do \`NEJAZDNE\` vo \`workers/lint/roadtypes.mjs\`.`);
}

for (const m of bad) console.log(`::error file=${TAGS}::${m}`);
if (bad.length) {
  console.log(`\n${bad.length} problém(ov) medzi typmi ciest a štýlom.`);
  process.exit(1);
}
console.log(
  `Typy ciest: ${new Set(typy).size} zo slovníka má v štýle svoju čiaru ` +
  `(${kreslene.class.size} tried, ${kreslene.subclass.size} podtried), ` +
  `a každá kreslená trieda cesty sa dá v profile vypnúť.`);
