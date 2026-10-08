#!/usr/bin/env node
/**
 * Checks of the finished style. Run by `Check · workflow lint`.
 *
 * Quiet things:
 *   1. a `fill` over mixed geometry needs a guard. MapLibre doesn't skip lines –
 *      it hands an open polyline to earcut and gets a self-overlapping polygon.
 *   2. a derived layer (pattern, edge) is visible exactly when its base is.
 *   3. a scatter pattern mustn't have an empty tile seam – repeated, it becomes a
 *      grid of empty alleys.
 *   4. a more important road lies above a less important one; a pass's casings
 *      lie wholly under its fills and passes go tunnel → surface → bridge.
 *   5. no style draws a region mask; every vector worker cuts its tiles instead.
 *
 * Every map type × theme is checked – a map type profile adds and hides layers.
 *
 *   node workers/lint/style.mjs
 */
import { THEMES, buildStyle, ROAD_DEFS, ROAD_PASSES } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS, MAP_TYPES, applyMapType } from "../../poc/web/map-types.js";
import { PATTERNS, renderPattern } from "../../poc/web/patterns.js";
import { readFileSync } from "node:fs";

/**
 * Tile layers with more than one geometry type – and why.
 * Every `fill` over them needs `geometry-type` in its filter.
 */
const MIXED = {
  transportation:
    "roads and paths are lines, but pedestrian areas, piers and bridge bodies polygons",
  aeroway: "runways and taxiways are lines, aprons polygons",
  park: "the outline is a polygon, with a point for the label (pointOnSurface)",
  piste: "workers/features/features.yml passes a piste as an area AND an axis (line)",
  mountain_peak: "peaks are points, but `cliff`, `ridge` and `arete` lines"
};

/** Fill layer types – the ones earcut really triangulates. */
const FILL = new Set(["fill", "fill-extrusion"]);

function styles() {
  const out = [];
  for (const theme of Object.keys(THEMES)) {
    for (const mapType of MAP_TYPE_IDS) {
      out.push({
        where: `${mapType} / ${theme}`,
        style: buildStyle({
          theme,
          mapType,
          tilesUrl: "https://x/tiles.pmtiles",
          spriteUrl: "https://x/sprite",
          glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
          // layers from own .pmtiles appear only when the archives exist
          contoursUrl: "https://x/contours.pmtiles",
          rocksUrl: "https://x/rocks.pmtiles",
          trailsUrl: "https://x/trails.pmtiles",
          featuresUrl: "https://x/features.pmtiles",
          pointsUrl: "https://x/points.pmtiles",
          transportUrl: "https://x/transport.pmtiles"
        })
      });
    }
  }
  return out;
}

let bad = 0;
let checked = 0;
let derived = 0;
const seen = new Set();

// 2. a derived layer follows its base – tried on a made-up pair, since today's
// `/^rock-/` rule is a prefix and would match even without the fix
for (const type of MAP_TYPES) {
  const rule = (type.rules || []).find(
    (r) => r.visible === false && Array.isArray(r.match?.id) && r.match.id.length
  );
  if (!rule) continue;
  const parentId = rule.match.id[0];
  const probe = {
    layers: [
      { id: parentId, type: "line", layout: {}, metadata: {} },
      {
        id: `${parentId}__pattern`,
        type: "fill",
        layout: {},
        metadata: { "frico:derived": parentId }
      }
    ]
  };
  applyMapType(probe, type.id);
  const hidden = (l) => (l.layout || {}).visibility === "none";
  derived += 1;
  if (hidden(probe.layers[0]) && !hidden(probe.layers[1])) {
    console.log(
      `::error file=poc/web/map-types.js::map type \`${type.id}\` hides ` +
      `\`${parentId}\` but leaves the derived \`${parentId}__pattern\` on. A ` +
      `pattern without its area hangs over an empty background and nobody says so ` +
      `– \`matchesLayer\` must ask a derived layer for its base's id ` +
      `(\`frico:derived\`).`
    );
    bad += 1;
  }
}

// and the same over finished styles
for (const { where, style } of styles()) {
  const byId = new Map(style.layers.map((l) => [l.id, l]));
  for (const layer of style.layers) {
    const parentId = (layer.metadata || {})["frico:derived"];
    if (!parentId) continue;
    derived += 1;
    const parent = byId.get(parentId);
    const vis = (l) => ((l.layout || {}).visibility === "none" ? "hidden" : "visible");
    if (!parent) {
      console.log(
        `::error file=poc/web/themes.js::derived layer \`${layer.id}\` ` +
        `(${where}) refers to base \`${parentId}\`, which isn't in the style.`
      );
      bad += 1;
    } else if (vis(parent) !== vis(layer)) {
      console.log(
        `::error file=poc/web/map-types.js::derived layer \`${layer.id}\` ` +
        `is ${vis(layer)}, but its base \`${parentId}\` is ${vis(parent)} ` +
        `(${where}).`
      );
      bad += 1;
    }
  }
}

// 1. a fill over mixed geometry
for (const { where, style } of styles()) {
  for (const layer of style.layers) {
    const src = layer["source-layer"];
    if (!FILL.has(layer.type) || !MIXED[src]) continue;
    checked += 1;
    if (JSON.stringify(layer.filter ?? null).includes("geometry-type")) continue;
    // the same layer comes out alike in every theme
    if (seen.has(layer.id)) continue;
    seen.add(layer.id);
    console.log(
      `::error file=poc/web/themes.js::layer \`${layer.id}\` (${layer.type} ` +
      `over \`${src}\`, ${where}) has no \`geometry-type\` in its filter. In ` +
      `\`${src}\` ${MIXED[src]}, and MapLibre lets a line into the fill – earcut ` +
      `makes a nonsense polygon of it that looks like an area cut across the ` +
      `land. Wrap the filter in \`polygonOnly(…)\`.`
    );
    bad += 1;
  }
}

// 3. a pattern mustn't give itself away at the seam – seam coverage against the tile mean
const SEAM_MIN = 0.25;   // at least a quarter of the mean coverage
let patterns = 0;
for (const pat of PATTERNS) {
  // scatter patterns only – a regular motif has an empty edge on purpose
  if (pat.line || !pat.scatter) continue;
  patterns += 1;
  const size = 24;
  const { data } = renderPattern(
    { id: pat.id, color: "#000000", size, weight: 1 }, 1
  );
  const a = (x, y) => data[(y * size + x) * 4 + 3] / 255;
  let all = 0;
  const rows = [], cols = [];
  for (let i = 0; i < size; i++) {
    let r = 0, cc = 0;
    for (let j = 0; j < size; j++) { r += a(j, i); cc += a(i, j); }
    rows.push(r / size); cols.push(cc / size); all += r;
  }
  const ink = all / (size * size);
  const seam = (rows[0] + rows[size - 1] + cols[0] + cols[size - 1]) / 4;
  if (ink > 0 && seam < ink * SEAM_MIN) {
    console.log(
      `::error file=poc/web/patterns.js::pattern \`${pat.id}\` has ` +
      `${(seam * 100).toFixed(1)} % ink at the tile seam against ${(ink * 100).toFixed(1)} % ` +
      `in the whole tile. Repeated, it becomes a grid of empty alleys every ` +
      `\`size\` pixels. Move some shapes so they STICK OUT past the edge ` +
      `(coordinates outside 0–1); the rasteriser draws the other half opposite.`
    );
    bad += 1;
  }
}

// 4. a more important road lies above a less important one – `ROAD_DEFS` reversed,
// per pass, for fills and casings
let roadPairs = 0;
for (const { where, style } of styles()) {
  const order = new Map(style.layers.map((l, i) => [l.id, i]));
  for (const suffix of ROAD_PASSES) {
    for (const casing of ["", "-casing"]) {
      // least to most important – the style index must grow
      const chain = [...ROAD_DEFS]
        .reverse()
        .map(([id]) => [`road-${id}${casing}${suffix}`, id])
        .filter(([layerId]) => order.has(layerId));
      for (let i = 0; i + 1 < chain.length; i += 1) {
        const [lowerId, lower] = chain[i];
        const [higherId, higher] = chain[i + 1];
        roadPairs += 1;
        if (order.get(lowerId) < order.get(higherId)) continue;
        console.log(
          `::error file=poc/web/themes.js::in the style (${where}) \`${lowerId}\` ` +
          `is ABOVE \`${higherId}\`. \`${lower}\` is a less important road than ` +
          `\`${higher}\` (by ROAD_DEFS), so it draws over it and breaks it at ` +
          `junctions. Road layers are added FROM THE END of ROAD_DEFS – see \`roadPass\`.`
        );
        bad += 1;
      }
    }
  }
  // a pass's casings lie wholly under its fills: the lowest fill against the highest casing
  for (const suffix of ROAD_PASSES) {
    const idx = (pre) => ROAD_DEFS
      .map(([id]) => order.get(`road-${id}${pre}${suffix}`))
      .filter((i) => i !== undefined);
    const casings = idx("-casing");
    const fills = idx("");
    if (!casings.length || !fills.length) continue;
    roadPairs += 1;
    const topCasing = Math.max(...casings);
    const lowestFill = Math.min(...fills);
    if (topCasing < lowestFill) continue;
    const culprit = ROAD_DEFS
      .map(([id]) => id)
      .find((id) => order.get(`road-${id}-casing${suffix}`) === topCasing);
    console.log(
      `::error file=poc/web/themes.js::in the style (${where}) road casings and ` +
      `fills of pass \`${suffix || "(surface)"}\` interleave – casing ` +
      `\`road-${culprit}-casing${suffix}\` is above some fill of the same pass. ` +
      `Casings lie WHOLLY under fills (hence two loops in \`roadPass\`), or ` +
      `junctions cover them.`
    );
    bad += 1;
  }

  // passes go tunnel → surface → bridge – a level, not a class
  const levels = ROAD_PASSES
    .map((suffix) => {
      const idx = ROAD_DEFS
        .flatMap(([id]) => [`road-${id}-casing${suffix}`, `road-${id}${suffix}`])
        .map((l) => order.get(l))
        .filter((i) => i !== undefined);
      return idx.length ? { suffix, from: Math.min(...idx), to: Math.max(...idx) } : null;
    })
    .filter(Boolean);
  for (let i = 0; i + 1 < levels.length; i += 1) {
    const lower = levels[i];
    const higher = levels[i + 1];
    roadPairs += 1;
    if (lower.to < higher.from) continue;
    const name = (s) => s === "-tunnel" ? "tunnels" : s === "-bridge" ? "bridges" : "surface";
    console.log(
      `::error file=poc/web/themes.js::in the style (${where}) road passes aren't ` +
      `ordered tunnel → surface → bridge: \`${name(lower.suffix)}\` ` +
      `(${lower.from}–${lower.to}) reaches above \`${name(higher.suffix)}\` ` +
      `(from ${higher.from}). ROAD_PASSES sets the order and it's a level, not a ` +
      `class – a road on a bridge lies above every surface road.`
    );
    bad += 1;
  }
}

// 5. no mask: the tiles end at the region
let cutters = 0;
for (const { where, style } of styles()) {
  const mask = style.layers.filter((l) => ["region-outside", "region-border"].includes(l.id));
  if (mask.length || style.sources.region) {
    console.log(
      `::error file=poc/web/themes.js::the style (${where}) draws a region mask again. ` +
      `The region ends in the tiles (workers/lib/clip-tiles.sh), not in the style.`
    );
    bad += 1;
  }
}
for (const worker of ["tiles", "trails", "features", "boundaries", "buildings", "water",
                      "transport", "rail", "history"]) {
  const build = readFileSync(`workers/${worker}/build.sh`, "utf8");
  cutters += 1;
  if (!build.includes("workers/lib/clip-tiles.sh")) {
    console.log(
      `::error file=workers/${worker}/build.sh::its tiles aren't cut to the region ` +
      `(workers/lib/clip-tiles.sh), so the map draws what lies beyond it.`
    );
    bad += 1;
  }
}

console.log(
  `style: ${bad} errors (${checked} fills over mixed geometry, ` +
  `${derived} derived layer checks, ${patterns} area patterns at the seam, ` +
  `${roadPairs} road pairs in order, ` +
  `${cutters} workers cutting to the region, ` +
  `${Object.keys(THEMES).length} themes × ${MAP_TYPE_IDS.length} map types)`
);
process.exit(bad ? 1 : 0);
