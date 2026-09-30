#!/usr/bin/env node
/**
 * A road type the profile can turn off must be one the map can draw too.
 *
 * The road types are in `workers/data/routing-tags.json` (`network`) and the app
 * makes toggles from them – each with a line as the map draws it. When the two
 * lists drift, nothing fails: a toggle has no preview, or the map shows a road
 * that can't be turned off.
 *
 * Both sides are errors and both have exceptions WITH A REASON – silence is banned:
 *   1. a dictionary type whose class the style doesn't draw (`UNDRAWN`);
 *   2. a style road class no type points at (`NOT_ROUTABLE`).
 *
 *   node workers/lint/roadtypes.mjs
 */
import { readFileSync } from "node:fs";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const TAGS = "workers/data/routing-tags.json";

/**
 * OSM → class (and subclass) in the `transportation` layer.
 *
 * A COPY of someone else's list – `highway_class` in the OpenMapTiles schema
 * (`layers/transportation/transportation.yaml`). When OpenMapTiles moves, refresh
 * it from there, don't add the one name that happens to be missing.
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

/** A dictionary type absent from the `transportation` layer – and why. */
const UNDRAWN = {
  via_ferrata:
    "OpenMapTiles gives it no class. The map shows it as a WAYMARKED ROUTE " +
    "(`route=via_ferrata`, workers/trails), so it is visible – just not as a " +
    "road from `transportation`."
};

/** A class the style draws that can't be routed on – and why. */
const NOT_ROUTABLE = {
  rail: "track; a train is `transit`, which stands on GTFS (docs/navigation.md §6)",
  transit: "tram and metro – the same, OSM has no timetable",
  pier: "a pier is an area one walks on, not a network line",
  bridge: "the bridge body as an area; one travels on the road ABOVE it",
  aerialway: "cable cars and lifts – the dictionary has them under `aerialway`, not `highway`"
};

const bad = [];

function classes() {
  const hit = { class: new Set(), subclass: new Set() };
  const tagName = (x) =>
    Array.isArray(x) && x[0] === "coalesce" && Array.isArray(x[1])
      && x[1][0] === "get" ? x[1][1]
      : Array.isArray(x) && x[0] === "get" ? x[1] : null;
  const walk = (f) => {
    if (!Array.isArray(f)) return;
    const [op, a, b] = f;
    const p = tagName(a);
    if (p && (op === "==" || op === "!=")) hit[p]?.add(String(b));
    if (p && op === "in" && Array.isArray(b) && b[0] === "literal") {
      for (const v of b[1]) hit[p]?.add(String(v));
    }
    for (const x of f) walk(x);
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
        if (l["source-layer"] === "transportation") walk(l.filter);
      }
    }
  }
  hit.class.delete("");
  hit.subclass.delete("");
  return hit;
}

const dictionary = JSON.parse(readFileSync(TAGS, "utf8"));
const network = dictionary.network;
const drawn = classes();

// 1. what the profile offers must be visible on the map
const types = [
  ...network.highway,
  ...(network.route || []),
  ...(network.railway || []),
  ...(network.aerialway || []).map(() => "aerialway")
];
for (const type of new Set(types)) {
  if (UNDRAWN[type]) continue;
  const map = type === "aerialway" ? ["aerialway"] : OMT[type];
  if (!map) {
    bad.push(
      `${TAGS}: road type \`${type}\` can be turned off in the profile, but ` +
      `\`OMT\` in \`workers/lint/roadtypes.mjs\` doesn't know it – so nobody knows ` +
      `its tile class and the toggle can't get a line drawn as the map draws it. ` +
      `Add the mapping, or a reason to \`UNDRAWN\`.`);
    continue;
  }
  const [cls, subclass] = map;
  if (!drawn.class.has(cls)) {
    bad.push(
      `${TAGS}: type \`${type}\` has tile class \`${cls}\`, which the style ` +
      `doesn't draw. The profile toggle would have no preview – and the user ` +
      `would turn off a road they can't see on the map.`);
  }
  if (subclass && !drawn.subclass.has(subclass)) {
    bad.push(
      `${TAGS}: type \`${type}\` has subclass \`${subclass}\`, which the style ` +
      `doesn't draw – the toggle would have no preview.`);
  }
}

// 2. what the map draws as a road must be possible to turn off
const fromDictionary = new Set();
for (const type of new Set(types)) {
  const map = type === "aerialway" ? ["aerialway"] : OMT[type];
  if (map) fromDictionary.add(map[0]);
}
for (const cls of [...drawn.class].sort()) {
  // `*_construction` is the same road under construction – nobody travels on it
  if (cls.endsWith("_construction") || NOT_ROUTABLE[cls]) continue;
  if (fromDictionary.has(cls)) continue;
  bad.push(
    `${TAGS}: the style draws class \`${cls}\`, but no type in \`network\` ` +
    `leads to it. The map shows a road the user can't turn off in the profile – ` +
    `and routes keep using it. Add a type to the dictionary, or a reason to ` +
    `\`NOT_ROUTABLE\` in \`workers/lint/roadtypes.mjs\`.`);
}

for (const m of bad) console.log(`::error file=${TAGS}::${m}`);
if (bad.length) {
  console.log(`\n${bad.length} problem(s) between road types and the style.`);
  process.exit(1);
}
console.log(
  `Road types: ${new Set(types).size} from the dictionary have their line in the style ` +
  `(${drawn.class.size} classes, ${drawn.subclass.size} subclasses), ` +
  `and every drawn road class can be turned off in the profile.`);
