#!/usr/bin/env node
/**
 * MapLibre style for the world map – one file per colour theme, relative links by default.
 * Zooms must match the schema (`workers/lint/world.py`).
 *
 *   node workers/world/style.mjs --out=_site/styles --maxzoom=6
 */
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { THEMES } from "../../poc/web/themes.js";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=")];
  })
);

const outDir = args.out || "_site/styles";
const region = args.region || "svet";
const maxzoom = Number(args.maxzoom || 6);

// the variant decides which schema layers exist (`workers/data/world-variants.json`)
const _HERE = dirname(fileURLToPath(import.meta.url));
const VARIANTS = JSON.parse(
  readFileSync(join(_HERE, "..", "data", "world-variants.json"), "utf8")
);
const VARIANT_ALIAS = { plna: "full" };
const variant = VARIANT_ALIAS[args.variant] || args.variant || "full";
if (!VARIANTS[variant] || variant.startsWith("_")) {
  console.error(
    `::error::World map variant “${variant}” is unknown. There are: ` +
      Object.keys(VARIANTS).filter((k) => !k.startsWith("_")).join(", ")
  );
  process.exit(1);
}
const LAYERS = new Set(VARIANTS[variant].layers);
// empty `--base-url` = relative links (package on disk)
const base = (args["base-url"] || "").replace(/\/$/, "");
const url = (path) => (base ? `${base}/${path}` : path);
// the app carries its own glyphs; this address is for an unpacked package on the web
const glyphs = args.glyphs || "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf";

// the fontstacks `workers/assets/glyphs.sh` copies
const REG = ["Noto Sans Regular"];
const BOLD = ["Noto Sans Bold"];

const ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap ' +
  'contributors</a> · <a href="https://download.geofabrik.de/">Geofabrik</a>' +
  ' · <a href="https://www.naturalearthdata.com/">Natural Earth</a>';

/** From which zoom what is drawn – the same numbers as `min_zoom` in `world.yml`. */
const FROM = {
  water: 0,
  lakeMinor: 5,
  boundary: 0,
  boundaryDisputed: 2,
  place: 1,
  download: { continent: 0, country: 2, subregion: 5 },
  downloadLabel: { continent: 2, country: 3, subregion: 5 }
};

/** A region level ends where the finer one starts, or three outlines stack up. */
const UNTIL = { continent: FROM.download.country, country: FROM.download.subregion };

const LEVELS = ["continent", "country", "subregion"];

function style(themeId) {
  const c = THEMES[themeId];
  const layers = [
    // land is the background, not a polygon
    {
      id: "background",
      type: "background",
      paint: { "background-color": c.background }
    },
    // seas, oceans and lakes
    {
      id: "water",
      type: "fill",
      source: "world",
      "source-layer": "water",
      minzoom: FROM.water,
      paint: { "fill-color": c.water }
    },
    {
      id: "water-outline",
      type: "line",
      source: "world",
      "source-layer": "water",
      minzoom: 3,
      paint: { "line-color": c.waterOutline, "line-width": 0.6 }
    }
  ];

  // download regions, the point of this map; one layer per level
  for (const level of LEVELS) {
    const from = FROM.download[level];
    const until = UNTIL[level];
    const range = { minzoom: from, ...(until ? { maxzoom: until } : {}) };
    layers.push({
      id: `download-${level}`,
      type: "fill",
      source: "world",
      "source-layer": "download",
      ...range,
      filter: ["==", ["get", "level"], level],
      paint: { "fill-color": c.boundaryLocal, "fill-opacity": 0.08 }
    });
    layers.push({
      id: `download-${level}-line`,
      type: "line",
      source: "world",
      "source-layer": "download",
      ...range,
      filter: ["==", ["get", "level"], level],
      paint: {
        "line-color": c.boundaryLocal,
        "line-width": level === "subregion" ? 0.8 : 1.4
      }
    });
  }

  layers.push({
    id: "boundary",
    type: "line",
    source: "world",
    "source-layer": "boundary",
    minzoom: FROM.boundary,
    filter: ["==", ["get", "kind"], "country"],
    paint: {
      "line-color": c.boundary,
      "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 6, 1.6]
    }
  });
  layers.push({
    // a disputed border is dashed
    id: "boundary-disputed",
    type: "line",
    source: "world",
    "source-layer": "boundary",
    minzoom: FROM.boundaryDisputed,
    filter: ["==", ["get", "kind"], "disputed"],
    paint: {
      "line-color": c.boundary,
      "line-width": 0.8,
      "line-dasharray": [2, 2],
      "line-opacity": 0.7
    }
  });

  layers.push({
    id: "place-country",
    type: "symbol",
    source: "world",
    "source-layer": "place",
    minzoom: FROM.place,
    layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"], ["get", "name_en"]],
      "text-font": BOLD,
      "text-size": ["match", ["get", "rank"], "major", 14, "mid", 12, 11],
      "text-max-width": 7,
      "text-padding": 4
    },
    paint: {
      "text-color": c.placeText,
      "text-halo-color": c.textHalo,
      "text-halo-width": 1.4
    }
  });
  for (const level of LEVELS) {
    const until = UNTIL[level];
    layers.push({
      id: `download-label-${level}`,
      type: "symbol",
      source: "world",
      "source-layer": "download_label",
      minzoom: FROM.downloadLabel[level],
      ...(until ? { maxzoom: until } : {}),
      filter: ["==", ["get", "level"], level],
      layout: {
        "text-field": ["get", "name"],
        "text-font": REG,
        "text-size": level === "subregion" ? 10 : 11,
        "text-max-width": 8,
        "text-padding": 6
      },
      paint: {
        "text-color": c.placeText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1.2,
        "text-opacity": 0.9
      }
    });
  }

  // what the variant lacks isn't drawn – filtered once, here
  const kept = layers.filter(
    (l) => !l["source-layer"] || LAYERS.has(l["source-layer"])
  );

  return {
    version: 8,
    name: `FricoMaps world – ${c.label}`,
    metadata: {
      "fricomaps:kind": "world",
      "fricomaps:variant": variant,
      "fricomaps:description":
        `Basic world map (${VARIANTS[variant].label}). No roads, settlements or `
        + "terrain – a base for choosing which piece to download.",
      "fricomaps:theme": themeId
    },
    glyphs,
    sources: {
      world: {
        type: "vector",
        url: `pmtiles://${url(`tiles/${region}.pmtiles`)}`,
        attribution: ATTRIBUTION,
        minzoom: 0,
        maxzoom
      }
    },
    layers: kept
  };
}

mkdirSync(outDir, { recursive: true });
const written = [];
for (const themeId of Object.keys(THEMES)) {
  const path = join(outDir, `${region}-${themeId}.json`);
  writeFileSync(path, JSON.stringify(style(themeId), null, 2) + "\n");
  written.push(path);
}
console.log(`World map styles – variant ${variant} (${written.length}): `
  + written.join(", "));
console.log(`  tiles:  pmtiles://${url(`tiles/${region}.pmtiles`)}`);
console.log(`  glyphs: ${glyphs}`);
