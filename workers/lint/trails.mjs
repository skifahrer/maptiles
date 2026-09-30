#!/usr/bin/env node
/**
 * Waymarked trails: what the style knows matches the tile data and what the
 * developer-mode panel shows.
 *
 * A trail stripe comes from three places (`trails/routes.py`, `trails/trails.yml`,
 * `poc/web/themes.js`); drifted, the map renders – with stripes on the wrong side
 * or detached from the road.
 *
 *   1. the road side is in `SIDE_BY_ROUTE` and `TRAIL_TYPES.side`;
 *   2. offset curves share the breaks of `TRAIL_OFFSET_ZOOMS` – they combine by index;
 *   3. `TRAIL_GAP_DEFAULTS` really are the values at `TRAIL_GAP_ZOOM`;
 *   4. the line dash is a valid `patterns.js` preset;
 *   5. `side`, `off` and `way` are in the tile schema;
 *   6. `orient_ways` is called and its result passed to `Ways`;
 *   7. the pitch is the stripe width – the same curve and interpolation;
 *   8. the offset from the road stays within `TRAIL_OFFSET_LIMIT_M` metres;
 *   9. the corner join is `miter` with a `line-miter-limit`;
 *  10. `EASE_ABOVE_DEG` in `routes.py` follows that limit, not a number of its own.
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

// the repository root is two levels up
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ROUTES = join(ROOT, "workers", "trails", "routes.py");
const SCHEMA = join(ROOT, "workers", "trails", "trails.yml");

const bad = [];

// 1. the road side
const py = readFileSync(ROUTES, "utf8");
const sideBlock = py.match(/SIDE_BY_ROUTE\s*=\s*\{([^}]*)\}/);
if (!sideBlock) {
  bad.push(
    "workers/trails/routes.py has no SIDE_BY_ROUTE – without it there's no " +
      "saying which side of the road a trail belongs on."
  );
} else {
  const sides = {};
  for (const m of sideBlock[1].matchAll(/"([a-z_]+)"\s*:\s*(-?\d+)/g)) {
    sides[m[1]] = Number(m[2]);
  }
  for (const type of TRAIL_TYPES) {
    if (sides[type.id] === undefined) {
      bad.push(
        `Trail type "${type.id}" is in TRAIL_TYPES but not in SIDE_BY_ROUTE ` +
          "(workers/trails/routes.py) – the data gives it no side."
      );
    } else if (sides[type.id] !== type.side) {
      bad.push(
        `The side of trail "${type.id}" drifted: data ${sides[type.id]}, ` +
          `style ${type.side}. Developer mode tells from the style which side ` +
          "of the road to find the trail on – it would lie."
      );
    }
  }
  for (const id of Object.keys(sides)) {
    if (!TRAIL_TYPES.some((t) => t.id === id)) {
      bad.push(`SIDE_BY_ROUTE knows type "${id}", which TRAIL_TYPES lacks.`);
    }
  }
}

// 2. curve breaks
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
      `${name} has breaks [${zooms}], but TRAIL_OFFSET_ZOOMS says ` +
        `[${TRAIL_OFFSET_ZOOMS}]. Curves combine by index, so one zoom's offset ` +
        "would pair with another zoom's pitch."
    );
  }
}

// 3. default gaps
const refs = {
  road: TRAIL_OFFSET_ROAD,
  path: TRAIL_OFFSET_PATH,
  pitch: TRAIL_PITCH
};
for (const [key, stops] of Object.entries(refs)) {
  const at = (stops.find(([z]) => z === TRAIL_GAP_ZOOM) || [])[1];
  if (at !== TRAIL_GAP_DEFAULTS[key]) {
    bad.push(
      `TRAIL_GAP_DEFAULTS.${key} is ${TRAIL_GAP_DEFAULTS[key]}, but the curve has ` +
        `${at} at z${TRAIL_GAP_ZOOM}. The whole curve scales by that ratio – ` +
        "stripes would shift without a single override."
    );
  }
}

// 4. line dashes
for (const type of TRAIL_TYPES) {
  if (!DASH_IDS.includes(type.dash)) {
    bad.push(
      `Trail type "${type.id}" has line dash "${type.dash}", which ` +
        "patterns.js doesn't know – it would be a solid line in the map."
    );
  }
}

// 6. way directions are chained and the result used
if (!/def orient_ways\(/.test(py)) {
  bad.push(
    "workers/trails/routes.py has no `orient_ways` – directions would come from " +
      "each way's own shape and on a north-south path the stripe would jump sides " +
      "on every other section."
  );
} else if (!/Ways\(\s*routes\.by_way\s*,\s*fh\s*,\s*flipped\s*\)/.test(py)) {
  bad.push(
    "workers/trails/routes.py doesn't pass the `orient_ways` result to `Ways(...)` – " +
      "directions are computed and dropped, so stripes jump as before and nothing " +
      "says so."
  );
}

// 5. attributes in the tile schema
const yml = readFileSync(SCHEMA, "utf8");
for (const key of ["side", "off", "way"]) {
  if (!new RegExp(`^\\s*-\\s*key:\\s*${key}\\s*$`, "m").test(yml)) {
    bad.push(
      `workers/trails/trails.yml doesn't pass attribute \`${key}\` into tiles, ` +
        "though the style's `line-offset` expression reads it. Without it every " +
        "stripe piles up beside the road."
    );
  }
}

// 7. the pitch of two trails is the stripe width – the same curve and interpolation
const sameStops = (a, b) =>
  a.length === b.length && a.every(([z, v], i) => z === b[i][0] && v === b[i][1]);
if (!sameStops(TRAIL_PITCH, TRAIL_STRIPE)) {
  bad.push(
    "TRAIL_PITCH isn't TRAIL_STRIPE – the pitch of two trails must be the stripe " +
      "width, or the background shows between them and the trails look pushed apart."
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
  bad.push("The style has no `trail-hiking` layer – the trail stripe isn't drawn.");
} else {
  const width = stripeLayer.paint["line-width"];
  const offset = stripeLayer.paint["line-offset"];
  const widthStops = width.slice(3).filter((_, i) => i % 2 === 0);
  const wanted = TRAIL_STRIPE.map(([z]) => z);
  if (widthStops.length !== wanted.length ||
      widthStops.some((z, i) => z !== wanted[i])) {
    bad.push(
      `The stripe width has breaks [${widthStops}], but the pitch [${wanted}]. ` +
        "It must be the same curve (TRAIL_STRIPE), or they drift between breaks " +
        "and a gap opens between trails."
    );
  }
  if (JSON.stringify(width[1]) !== JSON.stringify(offset[1])) {
    bad.push(
      `The stripe width interpolates ${JSON.stringify(width[1])}, but the offset ` +
        `${JSON.stringify(offset[1])}. The pitch IS the stripe width, so it must ` +
        "grow alike – otherwise they meet only at the breaks."
    );
  }
}

// 8. the offset in metres: at z13 a pixel is twelve metres
for (const [key, stops] of [["road", TRAIL_OFFSET_ROAD], ["path", TRAIL_OFFSET_PATH]]) {
  const limit = TRAIL_OFFSET_LIMIT_M[key];
  for (const [z, px] of stops) {
    const metres = px * (METRES_PER_PX_Z0 / 2 ** z);
    if (metres > limit * 1.05) {
      bad.push(
        `The stripe offset from the ${key === "road" ? "road" : "path"} at z${z} is ` +
          `${px} px, ${metres.toFixed(0)} m on the ground – the limit is ` +
          `${limit} m (TRAIL_OFFSET_LIMIT_M). Mountain paths have no such room: ` +
          "the stripe rounds a hairpin wider than the bend and becomes a coloured area."
      );
    }
  }
}

// 9. the stripe's corner join is `miter` – `round` leaves a white wedge outside
for (const layer of trailStyle.layers) {
  if (layer.type !== "line" || !layer.id.startsWith("trail-")) continue;
  const join = (layer.layout || {})["line-join"];
  const limit = (layer.layout || {})["line-miter-limit"];
  if (join !== TRAIL_JOIN["line-join"]) {
    bad.push(
      `Layer \`${layer.id}\` has join "${join}", but a trail stripe needs ` +
        `"${TRAIL_JOIN["line-join"]}" (TRAIL_JOIN). Otherwise parallels don't meet ` +
        "in a sharp bend and the stripe keeps a white wedge."
    );
  }
  if (limit !== TRAIL_JOIN["line-miter-limit"]) {
    bad.push(
      `Layer \`${layer.id}\` lacks \`line-miter-limit\` ` +
        `${TRAIL_JOIN["line-miter-limit"]} – without that guard a hairpin becomes ` +
        "a spike half a screen long (the offset over the cosine of half the angle " +
        "grows without bound)."
    );
  }
}

// 10. the data leaves no bend the join can't stitch – the limit comes from the style
const miterMaxTurn = (2 * Math.acos(1 / TRAIL_JOIN["line-miter-limit"]) * 180) / Math.PI;
const num = (name) => {
  const m2 = py.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, "m"));
  return m2 ? Number(m2[1]) : null;
};
const easeAbove = num("EASE_ABOVE_DEG");
const easeStep = num("MAX_TURN_DEG");
if (!/def ease_corners\(/.test(py) || !/coords, eased = ease_corners\(coords\)/.test(py)) {
  bad.push(
    "workers/trails/routes.py doesn't split bends through `ease_corners` – a join " +
      `"${TRAIL_JOIN["line-join"]}" can't stitch a bend over ${miterMaxTurn.toFixed(0)}°, ` +
      "so the stripe narrows or vanishes for a moment in the bend."
  );
} else {
  for (const [name, value] of [["EASE_ABOVE_DEG", easeAbove], ["MAX_TURN_DEG", easeStep]]) {
    if (value === null) {
      bad.push(`workers/trails/routes.py has no ${name} – there's no checking ` +
        "that the bends left after splitting can be stitched by the style's join.");
    } else if (value > miterMaxTurn) {
      bad.push(
        `${name} is ${value}°, but \`line-miter-limit\` ` +
          `${TRAIL_JOIN["line-miter-limit"]} stitches a bend of ${miterMaxTurn.toFixed(0)}° at most. ` +
          "MapLibre cuts a sharper one and the stripe narrows in the bend."
      );
    }
  }
}

for (const m of bad) console.log(`::error::${m}`);
console.log(
  bad.length
    ? `Waymarked trails: ${bad.length} errors`
    : `Waymarked trails: fine ✓ (${TRAIL_TYPES.length} types, breaks ` +
      `[${TRAIL_OFFSET_ZOOMS}], gaps at z${TRAIL_GAP_ZOOM} ` +
      `${JSON.stringify(TRAIL_GAP_DEFAULTS)})`
);
process.exit(bad.length ? 1 : 0);
