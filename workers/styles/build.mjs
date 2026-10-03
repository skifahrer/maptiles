#!/usr/bin/env node
/**
 * Static MapLibre style.json for every **map type × colour theme**, shared by web and iOS.
 * Files are `<region>-<map type>-<theme>.json`; the default type also as `<region>-<theme>.json`.
 *
 *   --sprite     … sprite index (JSON) – icons are taken from it, SDF enables icon colours
 *   --fonts-dir  … glyph folder on Pages – fontstacks are picked from it
 *   --overrides  … developer-mode overrides (poc/web/style-overrides.json)
 *   --trails     … marked trails from OSM relations (own .pmtiles)
 *   --transport  … transport network: road restrictions OpenMapTiles lacks
 *   --boundaries … area borders: area NAMES (OpenMapTiles `boundary` has none)
 *   --water      … water: names on the geometry instead of `water_name`
 *   --buildings  … settlements: buildings with area and name instead of `building`
 *   --features   … landscape lines and areas OpenMapTiles lacks (own .pmtiles)
 *   --points     … landscape points – springs, caves, towers (second output of the same job)
 *   --dem-source … model of contours and rocks – goes into the attribution
 *   --dem-tiles-source … model of the elevation tiles; empty = --dem-source
 *   --sprites-dir… folder of deployed sprites; the set follows the overrides
 *
 * Usage:
 *   node workers/styles/build.mjs --base-url=https://user.github.io/fricomaps \
 *        --region=slovensko --maxzoom=16 --out=_site/styles \
 *        --sprite=_site/sprites/osm-liberty.json --fonts-dir=_site/fonts \
 *        --overrides=poc/web/style-overrides.json
 */
import { mkdirSync, writeFileSync, readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  THEMES,
  buildStyle,
  normalizeOverrides,
  hasOverrides,
  paletteCoverage,
  selectedIconSource,
  MAX_TILE_Z,
  DEFAULT_DEM_TILES,
  DEFAULT_DEM_MAXZOOM,
  DEFAULT_TERRAIN_EXAGGERATION,
  DEFAULT_DEM_SOURCE,
  DEM_SOURCES,
  MAP_TYPES,
  DEFAULT_MAP_TYPE
} from "../../poc/web/themes.js";
import { allIconSources } from "../../poc/web/icon-sources.js";

// lookups are in the sibling `workers/data/`
const SELF = dirname(fileURLToPath(import.meta.url));

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=")];
  })
);

const baseUrl = (args["base-url"] || "").replace(/\/$/, "");
const region = args.region || "slovensko";
const outDir = args.out || "_site/styles";
const maxzoom = Number(args.maxzoom || MAX_TILE_Z);
// optional layers are on only when the pipeline made their .pmtiles
const contoursMaxzoom = Number(args["contours-maxzoom"] || 14);
const hasContours = args.contours === "true" || args.contours === "1";
const rocksMaxzoom = Number(args["rocks-maxzoom"] || 16);
const hasRocks = args.rocks === "true" || args.rocks === "1";
const trailsMaxzoom = Number(args["trails-maxzoom"] || 14);
const hasTrails = args.trails === "true" || args.trails === "1";
const featuresMaxzoom = Number(args["features-maxzoom"] || 15);
const hasFeatures = args.features === "true" || args.features === "1";
// points: the features job's second output, same maxzoom
const pointsMaxzoom = Number(args["points-maxzoom"] || featuresMaxzoom);
const hasPoints = args.points === "true" || args.points === "1";
const transportMaxzoom = Number(args["transport-maxzoom"] || 14);
const hasTransport = args.transport === "true" || args.transport === "1";
const boundariesMaxzoom = Number(args["boundaries-maxzoom"] || 12);
const hasBoundaries = args.boundaries === "true" || args.boundaries === "1";
const waterMaxzoom = Number(args["water-maxzoom"] || 14);
const hasWater = args.water === "true" || args.water === "1";
const buildingsMaxzoom = Number(args["buildings-maxzoom"] || 14);
const hasBuildings = args.buildings === "true" || args.buildings === "1";
// the elevation source goes into the contour and rock attribution
const demSource = DEM_SOURCES[args["dem-source"]]
  ? args["dem-source"]
  : DEFAULT_DEM_SOURCE;
// shading picks its own model, so its attribution is separate
const demTilesSource = DEM_SOURCES[args["dem-tiles-source"]]
  ? args["dem-tiles-source"]
  : demSource;
// `--dem-tiles=none` turns shading off
const demTiles =
  args["dem-tiles"] === "none" ? null : args["dem-tiles"] || DEFAULT_DEM_TILES;
const demMaxzoom = Number(args["dem-maxzoom"] || DEFAULT_DEM_MAXZOOM);
// 3D only on our own elevation tiles; the coarse AWS Terrain Tiles make soap hills
const ownDemTiles = Boolean(demTiles) && demTiles !== DEFAULT_DEM_TILES;
const terrain3dArg = String(args["terrain-3d"] ?? "auto").toLowerCase();
const terrain3d = ["0", "false", "no", "none", "off", "nie", "ziadne", "vypnute"].includes(terrain3dArg)
  ? false
  // `auto` and `1` mean "on if we have the tiles"
  : ownDemTiles;
const terrainExaggeration = Number(
  args["terrain-exaggeration"] || DEFAULT_TERRAIN_EXAGGERATION
);
// where our elevation tiles are – a quick test makes only a square, the rest would 404
const demBounds = args["dem-bounds"]
  ? args["dem-bounds"].split(",").map(Number)
  : null;
if (demBounds && (demBounds.length !== 4 || demBounds.some((n) => !Number.isFinite(n)))) {
  console.error("--dem-bounds must be W,S,E,N (four numbers)");
  process.exit(1);
}

if (!baseUrl) {
  console.error("--base-url is missing (the GitHub Pages URL)");
  process.exit(1);
}

const regions = JSON.parse(
  readFileSync(join(SELF, "..", "data", "regions.json"), "utf8")
);
// a custom osm.fr region isn't in regions.json – then the name from `--name`
const regionName = regions[region]?.name || args.name || region;

// the overrides pick the icon set; without its sprite the first available one
const spritesDir = args["sprites-dir"] || "";
let iconSetId = null;
let spriteJsonPath = args.sprite || "";

// an SDF sprite can be tinted, so the style adds `icon-color`
let icons = [];
let sdfIcons = false;
function readSprite(path) {
  if (!path || !existsSync(path)) return;
  try {
    const index = JSON.parse(readFileSync(path, "utf8"));
    icons = Object.keys(index);
    sdfIcons = Object.values(index).some((e) => e && e.sdf);
    console.log(
      `Sprite: ${path} – ${icons.length} icons${sdfIcons ? " (SDF, tintable)" : ""}`
    );
  } catch (err) {
    console.warn(`⚠ Sprite ${path} couldn't be read: ${err.message}`);
  }
}

// developer-mode overrides; the file is optional
const overridesPath =
  args.overrides || join(SELF, "..", "..", "poc", "web", "style-overrides.json");
let overrides = null;
if (existsSync(overridesPath)) {
  try {
    const { overrides: clean, problems } = normalizeOverrides(
      JSON.parse(readFileSync(overridesPath, "utf8"))
    );
    for (const p of problems) console.warn(`⚠ ${overridesPath}: ${p}`);
    overrides = hasOverrides(clean) ? clean : null;
  } catch (err) {
    console.warn(`⚠ ${overridesPath} couldn't be read: ${err.message}`);
  }
}
console.log(
  overrides
    ? `Developer-mode style overrides: ${Object.keys(overrides.layers).length} layers, ` +
        `${Object.values(overrides.palette).reduce((n, c) => n + Object.keys(c).length, 0)} colours` +
        `${overrides.order.length ? `, drawing order changed ${overrides.order.length}×` : ""}`
    : "Developer-mode style overrides: none"
);

iconSetId = selectedIconSource(overrides);
if (spritesDir) {
  // stand-ins when the chosen set isn't deployed, custom sets included
  const candidates = [
    iconSetId,
    ...allIconSources(overrides).map((s) => s.id).filter((id) => id !== iconSetId)
  ];
  const found = candidates.find((id) => existsSync(join(spritesDir, `${id}.json`)));
  if (!found) {
    console.warn(`⚠ ${spritesDir} has no sprite – the style will have no icons.`);
  } else {
    if (found !== iconSetId) {
      console.warn(`⚠ Icon set "${iconSetId}" isn't deployed – using "${found}".`);
    }
    iconSetId = found;
    spriteJsonPath = join(spritesDir, `${iconSetId}.json`);
  }
}
console.log(`Icon set: ${iconSetId}`);
readSprite(spriteJsonPath);
if (!icons.length) {
  console.warn("⚠ No sprite index – the fallback icon list is used.");
}

// glyphs on Pages are `_site/fonts/<Fontstack>/<range>.pbf`, else the public service
const PREFERRED = {
  regular: ["Noto Sans Regular", "Open Sans Regular", "Roboto Regular"],
  bold: ["Noto Sans Bold", "Open Sans Bold", "Roboto Medium"],
  italic: ["Noto Sans Italic", "Open Sans Italic", "Noto Sans Regular"]
};

let availableStacks = [];
if (args["fonts-dir"] && existsSync(args["fonts-dir"])) {
  availableStacks = readdirSync(args["fonts-dir"]).filter(
    (d) =>
      statSync(join(args["fonts-dir"], d)).isDirectory() &&
      existsSync(join(args["fonts-dir"], d, "0-255.pbf"))
  );
}

const fonts = {};
for (const [role, candidates] of Object.entries(PREFERRED)) {
  fonts[role] =
    candidates.find((n) => availableStacks.includes(n)) ||
    availableStacks[0] ||
    candidates[0];
}

// the style's sprite URL (without extension)
const spriteUrl = (
  args["sprite-url"] || `${baseUrl}/sprites/${iconSetId}`
).replace(/\.json$/, "");

const glyphsUrl =
  args["glyphs-url"] ||
  (availableStacks.length
    ? `${baseUrl}/fonts/{fontstack}/{range}.pbf`
    : "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf");

if (availableStacks.length) {
  console.log(`Glyphs: local (${availableStacks.length} fontstacks) → ${glyphsUrl}`);
} else {
  console.warn(`⚠ No local glyphs – using ${glyphsUrl}`);
}
console.log(`Fonts: regular="${fonts.regular}" bold="${fonts.bold}" italic="${fonts.italic}"`);

// a theme colour outside every palette group can't be found in developer mode
const coverage = paletteCoverage();
if (coverage.missing.length || coverage.extra.length) {
  console.error(
    `::error::PALETTE_GROUPS don't match the themes – missing: [${coverage.missing}], extra: [${coverage.extra}]`
  );
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });

for (const type of MAP_TYPES) {
  for (const themeKey of Object.keys(THEMES)) {
    const style = buildStyle({
      theme: themeKey,
      mapType: type.id,
      tilesUrl: `pmtiles://${baseUrl}/tiles/${region}.pmtiles`,
      spriteUrl: spriteUrl,
      glyphsUrl,
      icons,
      fonts,
      maxzoom,
      sdfIcons,
      iconSet: iconSetId,
      overrides,
      rocksUrl: hasRocks
        ? `pmtiles://${baseUrl}/tiles/${region}-rocks.pmtiles`
        : null,
      rocksMaxzoom,
      contoursUrl: hasContours
        ? `pmtiles://${baseUrl}/tiles/${region}-contours.pmtiles`
        : null,
      contoursMaxzoom,
      trailsUrl: hasTrails
        ? `pmtiles://${baseUrl}/tiles/${region}-trails.pmtiles`
        : null,
      trailsMaxzoom,
      featuresUrl: hasFeatures
        ? `pmtiles://${baseUrl}/tiles/${region}-features.pmtiles`
        : null,
      featuresMaxzoom,
      pointsUrl: hasPoints
        ? `pmtiles://${baseUrl}/tiles/${region}-points.pmtiles`
        : null,
      pointsMaxzoom,
      transportUrl: hasTransport
        ? `pmtiles://${baseUrl}/tiles/${region}-transport.pmtiles`
        : null,
      transportMaxzoom,
      boundariesUrl: hasBoundaries
        ? `pmtiles://${baseUrl}/tiles/${region}-boundaries.pmtiles`
        : null,
      boundariesMaxzoom,
      waterUrl: hasWater
        ? `pmtiles://${baseUrl}/tiles/${region}-water.pmtiles`
        : null,
      waterMaxzoom,
      buildingsUrl: hasBuildings
        ? `pmtiles://${baseUrl}/tiles/${region}-buildings.pmtiles`
        : null,
      buildingsMaxzoom,
      demSource,
      demTiles,
      demTilesSource,
      demMaxzoom,
      demBounds,
      terrain3d,
      terrainExaggeration,
      name: `FricoMaps ${regionName} – ${type.label} (${THEMES[themeKey].label})`
    });
    const json = JSON.stringify(style, null, 2);
    const drawn = style.layers.filter(
      (l) => (l.layout || {}).visibility !== "none"
    ).length;

    writeFileSync(join(outDir, `${region}-${type.id}-${themeKey}.json`), json);
    // the old name without a map type stays – iOS and the smoke test use it
    if (type.id === DEFAULT_MAP_TYPE) {
      writeFileSync(join(outDir, `${region}-${themeKey}.json`), json);
    }
    console.log(
      `✓ ${region}-${type.id}-${themeKey}.json (${drawn} of ${style.layers.length} layers draw)`
    );
  }
}

console.log(
  `Map types: ${MAP_TYPES.map((t) => t.label).join(", ")} ` +
    `(default ${DEFAULT_MAP_TYPE} also under the name without a type)`
);
console.log(
  `Marked trails: ${hasTrails ? `yes (to z${trailsMaxzoom})` : "no"}, ` +
  `Landscape features: ${hasFeatures ? `yes (to z${featuresMaxzoom})` : "no"}, ` +
  `Landscape points: ${hasPoints ? `yes (to z${pointsMaxzoom})` : "no"}, ` +
  `Transport network (road restrictions): ${hasTransport ? `yes (to z${transportMaxzoom})` : "no"}, ` +
  `Area names: ${hasBoundaries ? `yes (to z${boundariesMaxzoom})` : "no"}, ` +
  `Water names: ${hasWater ? `yes (to z${waterMaxzoom})` : "no"}, ` +
  `Settlements: ${hasBuildings ? `yes (to z${buildingsMaxzoom})` : "no"}, ` +
  `Contours: ${
    hasContours ? `yes (to z${contoursMaxzoom}, heights: ${DEM_SOURCES[demSource].label})` : "no"
  }, ` +
  `Rocks: ${hasRocks ? `yes (to z${rocksMaxzoom})` : "no"}, ` +
    `elevation data (3D terrain): ${
      demTiles
        ? demTiles === DEFAULT_DEM_TILES
          ? "AWS Terrain Tiles"
          : `own to z${demMaxzoom} from ${DEM_SOURCES[demTilesSource].label}`
        : "no"
    }, ` +
    `hillshading: ${overrides?.hillshade ? "on" : "off"}`,
    `3D terrain: ${terrain3d ? `on (exaggeration ${terrainExaggeration}×)` : "off"}`
);
