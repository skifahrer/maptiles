#!/usr/bin/env node
/**
 * Značené trasy: čo o nich vie štýl, musí sedieť s dátami v dlaždiciach
 * aj s tým, čo ukazuje panel v developer móde.
 *
 * Pásik trasy sa skladá z troch miest naraz (`trails/routes.py`,
 * `trails/trails.yml`, `poc/web/themes.js`) a rozídené znamená mapu, ktorá sa
 * vykreslí – len sú pásiky na zlej strane alebo odlepené od cesty.
 *
 *   1. strana cesty je v `SIDE_BY_ROUTE` aj v `TRAIL_TYPES.side`;
 *   2. krivky odstupu majú rovnaké zlomy ako `TRAIL_OFFSET_ZOOMS` – skladajú
 *      sa po indexoch, takže posunutý zlom spáruje odstup zo z14 s rozostupom zo z16;
 *   3. `TRAIL_GAP_DEFAULTS` sú naozaj hodnoty pri `TRAIL_GAP_ZOOM`;
 *   4. vzor čiary je platná predvoľba z `patterns.js`;
 *   5. `side`, `off` a `way` sú v schéme dlaždíc;
 *   6. `orient_ways` sa zavolá a jeho výsledok sa podá do `Ways`;
 *   7. rozostup je šírka pásika – tá istá krivka aj druh interpolácie;
 *   8. odstup od cesty nepresiahne `TRAIL_OFFSET_LIMIT_M` metrov;
 *   9. spoj v zákrute je `miter` a má `line-miter-limit`;
 *  10. `EASE_ABOVE_DEG` v `routes.py` vychádza z toho limitu, nie z vlastného čísla.
 *
 *   node workers/lint/trails.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  TRAIL_TYPES,
  TRAIL_OFFSET_ZOOMS,
  TRAIL_OFFSET_ROAD,
  TRAIL_OFFSET_PATH,
  TRAIL_PITCH,
  TRAIL_STRIPE,
  TRAIL_OFFSET_LIMIT_M,
  TRAIL_JOIN,
  METRES_PER_PX_Z0,
  TRAIL_GAP_DEFAULTS,
  TRAIL_GAP_ZOOM,
  THEMES,
  buildStyle
} from "../../poc/web/themes.js";
import { DASH_IDS } from "../../poc/web/patterns.js";

// koreň repozitára je o dve úrovne vyššie
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ROUTES = join(ROOT, "workers", "trails", "routes.py");
const SCHEMA = join(ROOT, "workers", "trails", "trails.yml");

const bad = [];

// ---- 1. strana cesty ----
const py = readFileSync(ROUTES, "utf8");
const sideBlock = py.match(/SIDE_BY_ROUTE\s*=\s*\{([^}]*)\}/);
if (!sideBlock) {
  bad.push(
    "workers/trails/routes.py nemá SIDE_BY_ROUTE – bez nej sa nedá povedať, " +
      "na ktorú stranu cesty ktorá trasa patrí."
  );
} else {
  const sides = {};
  for (const m of sideBlock[1].matchAll(/"([a-z_]+)"\s*:\s*(-?\d+)/g)) {
    sides[m[1]] = Number(m[2]);
  }
  for (const type of TRAIL_TYPES) {
    if (sides[type.id] === undefined) {
      bad.push(
        `Druh trasy "${type.id}" je v TRAIL_TYPES, ale nie v SIDE_BY_ROUTE ` +
          "(workers/trails/routes.py) – dáta mu stranu nepridelia."
      );
    } else if (sides[type.id] !== type.side) {
      bad.push(
        `Strana trasy "${type.id}" sa rozišla: dáta ${sides[type.id]}, ` +
          `štýl ${type.side}. Developer mode podľa štýlu píše, na ktorej ` +
          "strane cesty trasu nájdeš – takto by klamal."
      );
    }
  }
  for (const id of Object.keys(sides)) {
    if (!TRAIL_TYPES.some((t) => t.id === id)) {
      bad.push(`SIDE_BY_ROUTE pozná druh "${id}", ktorý TRAIL_TYPES nemá.`);
    }
  }
}

// ---- 2. zlomy kriviek ----
const curves = [
  ["TRAIL_OFFSET_ROAD", TRAIL_OFFSET_ROAD],
  ["TRAIL_OFFSET_PATH", TRAIL_OFFSET_PATH],
  ["TRAIL_PITCH", TRAIL_PITCH]
];
for (const [name, stops] of curves) {
  const zooms = stops.map(([z]) => z);
  if (zooms.length !== TRAIL_OFFSET_ZOOMS.length ||
      zooms.some((z, i) => z !== TRAIL_OFFSET_ZOOMS[i])) {
    bad.push(
      `${name} má zlomy [${zooms}], ale TRAIL_OFFSET_ZOOMS hovorí ` +
        `[${TRAIL_OFFSET_ZOOMS}]. Krivky sa skladajú po indexoch, takže by ` +
        "sa odstup z jedného zoomu spároval s rozostupom z iného."
    );
  }
}

// ---- 3. predvolené odstupy ----
const refs = {
  road: TRAIL_OFFSET_ROAD,
  path: TRAIL_OFFSET_PATH,
  pitch: TRAIL_PITCH
};
for (const [key, stops] of Object.entries(refs)) {
  const at = (stops.find(([z]) => z === TRAIL_GAP_ZOOM) || [])[1];
  if (at !== TRAIL_GAP_DEFAULTS[key]) {
    bad.push(
      `TRAIL_GAP_DEFAULTS.${key} je ${TRAIL_GAP_DEFAULTS[key]}, ale krivka má ` +
        `pri z${TRAIL_GAP_ZOOM} hodnotu ${at}. Z toho pomeru sa škáluje celá ` +
        "krivka – pásiky by sa posunuli aj bez jedinej úpravy."
    );
  }
}

// ---- 4. vzory čiar ----
for (const type of TRAIL_TYPES) {
  if (!DASH_IDS.includes(type.dash)) {
    bad.push(
      `Druh trasy "${type.id}" má vzor čiary "${type.dash}", ktorý ` +
        "patterns.js nepozná – v mape by z neho bola plná čiara."
    );
  }
}

// ---- 6. smer čiar sa reťazí a ten výsledok sa aj použije ----
if (!/def orient_ways\(/.test(py)) {
  bad.push(
    "workers/trails/routes.py nemá `orient_ways` – smer čiar by sa potom bral " +
      "z tvaru jednej čiary a pásik by pri severojužnom chodníku preskakoval " +
      "na druhú stranu na každom druhom úseku."
  );
} else if (!/Ways\(\s*routes\.by_way\s*,\s*fh\s*,\s*flipped\s*\)/.test(py)) {
  bad.push(
    "workers/trails/routes.py nepodáva výsledok `orient_ways` do `Ways(...)` – " +
      "smery sa spočítajú a zahodia, takže pásiky budú preskakovať tak ako " +
      "predtým a nič to nepovie."
  );
}

// ---- 5. atribúty v schéme dlaždíc ----
const yml = readFileSync(SCHEMA, "utf8");
for (const key of ["side", "off", "way"]) {
  if (!new RegExp(`^\\s*-\\s*key:\\s*${key}\\s*$`, "m").test(yml)) {
    bad.push(
      `workers/trails/trails.yml nepúšťa do dlaždíc atribút \`${key}\`, ` +
        "hoci ho výraz `line-offset` v štýle číta. Bez neho si všetky pásiky " +
        "sadnú na jednu kopu vedľa cesty."
    );
  }
}

// 7. rozostup dvoch trás je šírka pásika – tá istá krivka aj ten istý druh
// interpolácie, nie len rovnaké čísla v zlomoch
const sameStops = (a, b) =>
  a.length === b.length && a.every(([z, v], i) => z === b[i][0] && v === b[i][1]);
if (!sameStops(TRAIL_PITCH, TRAIL_STRIPE)) {
  bad.push(
    "TRAIL_PITCH nie je TRAIL_STRIPE – rozostup dvoch trás musí byť šírka " +
      "pásika, inak medzi nimi presvitá ich podklad a vyzerá to, že sú trasy " +
      "od seba odsunuté."
  );
}
const trailStyle = buildStyle({
  theme: Object.keys(THEMES)[0],
  tilesUrl: "https://x/tiles.pmtiles",
  spriteUrl: "https://x/sprite",
  glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
  trailsUrl: "https://x/trails.pmtiles"
});
const stripeLayer = trailStyle.layers.find((l) => l.id === "trail-hiking");
if (!stripeLayer) {
  bad.push("V štýle nie je vrstva `trail-hiking` – pásik trasy sa nekreslí.");
} else {
  const width = stripeLayer.paint["line-width"];
  const offset = stripeLayer.paint["line-offset"];
  const widthStops = width.slice(3).filter((_, i) => i % 2 === 0);
  const wanted = TRAIL_STRIPE.map(([z]) => z);
  if (widthStops.length !== wanted.length ||
      widthStops.some((z, i) => z !== wanted[i])) {
    bad.push(
      `Šírka pásika má zlomy [${widthStops}], ale rozostup [${wanted}]. ` +
        "Musí to byť tá istá krivka (TRAIL_STRIPE), inak sa medzi zlomami " +
        "rozídu a medzi trasami vznikne medzera."
    );
  }
  if (JSON.stringify(width[1]) !== JSON.stringify(offset[1])) {
    bad.push(
      `Šírka pásika sa interpoluje ${JSON.stringify(width[1])}, ale odstup ` +
        `${JSON.stringify(offset[1])}. Rozostup JE šírka pásika, takže musí ` +
        "rásť rovnako – inak sedia na seba len v zlomoch."
    );
  }
}

// 8. odstup od cesty v metroch: pixel je pri z13 dvanásť metrov, takže
// nenápadný odstup je v teréne širší než serpentína
for (const [key, stops] of [["road", TRAIL_OFFSET_ROAD], ["path", TRAIL_OFFSET_PATH]]) {
  const limit = TRAIL_OFFSET_LIMIT_M[key];
  for (const [z, px] of stops) {
    const metres = px * (METRES_PER_PX_Z0 / 2 ** z);
    if (metres > limit * 1.05) {
      bad.push(
        `Odstup pásika od ${key === "road" ? "cesty" : "chodníka"} je pri z${z} ` +
          `${px} px, čo je v teréne ${metres.toFixed(0)} m – limit je ` +
          `${limit} m (TRAIL_OFFSET_LIMIT_M). Toľko miesta pri chodníku ` +
          "v horách nie je: pásik obehne vlásenku oblúkom širším než zákruta " +
          "a v mape z neho bude farebná plocha."
      );
    }
  }
}

// 9. spoj pásika v zákrute je `miter` – so `round` ostane na vonkajšej strane
// zlomu biely klin a na vnútornej sa rovnobežky prekryjú
for (const layer of trailStyle.layers) {
  if (layer.type !== "line" || !layer.id.startsWith("trail-")) continue;
  const join = (layer.layout || {})["line-join"];
  const limit = (layer.layout || {})["line-miter-limit"];
  if (join !== TRAIL_JOIN["line-join"]) {
    bad.push(
      `Vrstva \`${layer.id}\` má spoj "${join}", ale pásik trasy potrebuje ` +
        `"${TRAIL_JOIN["line-join"]}" (TRAIL_JOIN). Inak sa v ostrej zákrute ` +
        "rovnobežky nestretnú a v pásiku ostane biely klin."
    );
  }
  if (limit !== TRAIL_JOIN["line-miter-limit"]) {
    bad.push(
      `Vrstva \`${layer.id}\` nemá \`line-miter-limit\` ` +
        `${TRAIL_JOIN["line-miter-limit"]} – bez tej poistky sa z vlásenky ` +
        "stane výbežok dlhý ako pol obrazovky (odstup delený kosínusom " +
        "polovičného uhla rastie nad všetky medze)."
    );
  }
}

// 10. dáta nenechajú zlom, ktorý spoj nezošije: `miter` posunie vrchol
// o `odstup / cos(zlom/2)` a MapLibre nad `line-miter-limit` zreže. Hranica
// teda vychádza z limitu v štýle, nie z vlastného čísla.
const miterMaxTurn = (2 * Math.acos(1 / TRAIL_JOIN["line-miter-limit"]) * 180) / Math.PI;
const num = (name) => {
  const m2 = py.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, "m"));
  return m2 ? Number(m2[1]) : null;
};
const easeAbove = num("EASE_ABOVE_DEG");
const easeStep = num("MAX_TURN_DEG");
if (!/def ease_corners\(/.test(py) || !/coords, eased = ease_corners\(coords\)/.test(py)) {
  bad.push(
    "workers/trails/routes.py nedelí zlomy cez `ease_corners` – zlom nad " +
      `${miterMaxTurn.toFixed(0)}° spoj "${TRAIL_JOIN["line-join"]}" nezošije, ` +
      "takže sa pásik v zákrute zúži alebo sa na chvíľu stratí."
  );
} else {
  for (const [name, value] of [["EASE_ABOVE_DEG", easeAbove], ["MAX_TURN_DEG", easeStep]]) {
    if (value === null) {
      bad.push(`workers/trails/routes.py nemá ${name} – nedá sa overiť, či ` +
        "zlomy, ktoré po delení ostanú, vie spoj v štýle zošiť.");
    } else if (value > miterMaxTurn) {
      bad.push(
        `${name} je ${value}°, ale \`line-miter-limit\` ` +
          `${TRAIL_JOIN["line-miter-limit"]} zošije zlom najviac ${miterMaxTurn.toFixed(0)}°. ` +
          "Ostrejší MapLibre zreže a pásik sa v zákrute zúži."
      );
    }
  }
}

for (const m of bad) console.log(`::error::${m}`);
console.log(
  bad.length
    ? `Značené trasy: ${bad.length} chýb`
    : `Značené trasy: v poriadku ✓ (${TRAIL_TYPES.length} druhov, zlomy ` +
      `[${TRAIL_OFFSET_ZOOMS}], odstupy pri z${TRAIL_GAP_ZOOM} ` +
      `${JSON.stringify(TRAIL_GAP_DEFAULTS)})`
);
process.exit(bad.length ? 1 : 0);
