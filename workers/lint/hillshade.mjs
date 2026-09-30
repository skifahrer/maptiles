#!/usr/bin/env node
/**
 * Hillshading: how much of the map beneath it covers. Run by `Check · workflow lint`.
 *
 * `hillshade` isn't a filter but an overlay – coverage is the `sin` of the slope
 * stretched by exaggeration, so above ~20° it's 0.97–1.0 and under the shading one
 * sees the shading colour, not the map. The style stays valid, so only recomputing
 * the same shader catches it.
 *
 *   1. a lit slope isn't covered more than {@link LIT_MAX},
 *   2. a shaded one more than {@link SHADOW_MAX},
 *   3. the coverage difference between sides is at least {@link RELIEF_MIN},
 *   4. the light doesn't shine almost from the north ({@link NORTH_GAP}) and is
 *      written in the style – MapLibre's default is exactly the bad one.
 *
 * Every theme × map type and every exaggeration curve break is computed.
 *
 *   node workers/lint/hillshade.mjs
 */
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const PI = Math.PI;

/** Coverage cap on the lit side (a forest must stay green). */
const LIT_MAX = 0.55;
/** Coverage cap on the shaded side (a dark slope, still with content). */
const SHADOW_MAX = 0.85;
/** The coverage difference between sides below which relief vanishes. */
const RELIEF_MIN = 0.25;
/** How many degrees the light must be from north. */
const NORTH_GAP = 40;
/** The slope measured – an ordinary mountain slope, not an extreme. */
const SLOPE_DEG = 30;
/** Where: Slovakia's latitude and the highest elevation tile zoom. */
const LAT = 49;
const ZOOM = 15;

/** `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa` → `[r, g, b, a]` in 0–1. */
function parseColor(raw) {
  let s = String(raw).trim().toLowerCase();
  const short = /^#([0-9a-f]{3,4})$/.exec(s);
  if (short) s = `#${[...short[1]].map((c) => c + c).join("")}`;
  const m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/.exec(s);
  if (!m) throw new Error(`unknown colour notation: ${raw}`);
  const ch = (i) => parseInt(m[1].slice(i * 2, i * 2 + 2), 16) / 255;
  return [ch(0), ch(1), ch(2), m[2] ? parseInt(m[2], 16) / 255 : 1];
}

/**
 * Hillshade coverage on a slope – ported from `hillshade.fragment.glsl`
 * (maplibre-gl-js v4.7.1) and its prepare pass. `shade` is 1 on the lit side
 * and 0 on the shaded one.
 *
 * The prepare pass makes a gradient: a 3×3 sobel divided by
 * `pow(2, exaggeration + (19.2562 - zoom))`, so slope θ at `lat` gives
 * `deriv = 8 · (m/px) · tan θ / 2^…`. The main pass turns it into an angle,
 * stretches it by exaggeration and takes coverage from its `sin`.
 */
function coverage({ slopeDeg, shade, exaggeration, shadowA, highlightA, accentA }) {
  const exag = ZOOM < 2 ? 0.4 : ZOOM < 4.5 ? 0.35 : 0.3;
  const zoomTerm = ZOOM < 15 ? (ZOOM - 15) * exag : 0;
  const metresPerPx = (156543.03392 * Math.cos((LAT * PI) / 180)) / 2 ** ZOOM;
  const deriv =
    (8 * metresPerPx * Math.tan((slopeDeg * PI) / 180)) /
    2 ** (zoomTerm + (19.2562 - ZOOM));
  const slope = Math.atan((1.25 * deriv) / Math.cos((LAT * PI) / 180));
  const base = 1.875 - exaggeration * 1.75;
  const maxValue = 0.5 * PI;
  const scaled =
    exaggeration !== 0.5
      ? ((base ** slope - 1) / (base ** maxValue - 1)) * maxValue
      : slope;
  const k = Math.min(Math.max(exaggeration * 2, 0), 1);
  const shadeA = (shadowA + (highlightA - shadowA) * shade) * Math.sin(scaled) * k;
  const accA = (1 - Math.cos(scaled)) * accentA * k;
  // `fragColor = accent * (1 - shade.a) + shade` – the same composition
  return accA * (1 - shadeA) + shadeA;
}

/** Exaggeration curve breaks: `["interpolate", …, z, v, z, v]` or a plain number. */
function exaggerationStops(value) {
  if (typeof value === "number") return [value];
  if (!Array.isArray(value) || value[0] !== "interpolate")
    throw new Error(`unknown exaggeration notation: ${JSON.stringify(value)}`);
  const out = [];
  for (let i = 4; i < value.length; i += 2) out.push(value[i]);
  return out;
}

const problems = [];
let checks = 0;

for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    const style = buildStyle({
      theme,
      mapType,
      tilesUrl: "https://x/tiles.pmtiles",
      spriteUrl: "https://x/sprite",
      glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
      demTiles: "https://x/dem/{z}/{x}/{y}.png",
      hillshade: true
    });
    const layer = style.layers.find((l) => l.type === "hillshade");
    if (!layer) {
      problems.push(`${theme}/${mapType}: a style with hillshading on has no \`hillshade\` layer`);
      continue;
    }
    const where = `${theme}/${mapType}`;
    const paint = layer.paint || {};

    // 4. where the light comes from
    const dir = paint["hillshade-illumination-direction"];
    if (typeof dir !== "number") {
      problems.push(
        `${where}: \`hillshade-illumination-direction\` is missing from the style – ` +
          "MapLibre uses 335°, 25° from north, and north slopes get full light. " +
          "Write the direction into the style (the convention is 315°, from NW)."
      );
    } else {
      const deg = (((dir % 360) + 360) % 360);
      const fromNorth = Math.min(deg, 360 - deg);
      if (fromNorth < NORTH_GAP)
        problems.push(
          `${where}: the light shines ${fromNorth.toFixed(0)}° from north ` +
            `(direction ${dir}°) – north slopes get full light. ` +
            `Keep at least ${NORTH_GAP}° (the convention is 315°, from NW).`
        );
    }
    if (paint["hillshade-illumination-anchor"] !== "map")
      problems.push(
        `${where}: \`hillshade-illumination-anchor\` should be "map". With ` +
          '"viewport" (the default) the light is tied to the screen, so rotating ' +
          "the map spills it over the ridge and a valley sometimes looks like a " +
          "valley and sometimes like a ridge."
      );

    const [, , , shadowA] = parseColor(paint["hillshade-shadow-color"]);
    const [, , , highlightA] = parseColor(paint["hillshade-highlight-color"]);
    const [, , , accentA] = parseColor(paint["hillshade-accent-color"]);

    for (const exaggeration of exaggerationStops(paint["hillshade-exaggeration"])) {
      const at = (shade) =>
        coverage({ slopeDeg: SLOPE_DEG, shade, exaggeration, shadowA, highlightA, accentA });
      const lit = at(1);
      const dark = at(0);
      const tag = `${where}, exaggeration ${exaggeration}`;
      checks += 1;

      // 1. the lit side
      if (lit > LIT_MAX)
        problems.push(
          `${tag}: a ${SLOPE_DEG}° slope facing the light is covered ` +
            `${(lit * 100).toFixed(0)} % (cap ${(LIT_MAX * 100).toFixed(0)} %) – ` +
            `the forest under it becomes an area of \`hillHighlight\` ` +
            `(${paint["hillshade-highlight-color"]}). Give that colour alpha.`
        );
      // 2. the shaded side
      if (dark > SHADOW_MAX)
        problems.push(
          `${tag}: a ${SLOPE_DEG}° slope facing away is covered ` +
            `${(dark * 100).toFixed(0)} % (cap ${(SHADOW_MAX * 100).toFixed(0)} %) – ` +
            `no forest, road or contour shows under the shadow. ` +
            `Give \`hillShadow\` alpha (${paint["hillshade-shadow-color"]}).`
        );
      // 3. and the relief must stay visible
      if (Math.abs(dark - lit) < RELIEF_MIN)
        problems.push(
          `${tag}: the lit (${(lit * 100).toFixed(0)} %) and shaded ` +
            `(${(dark * 100).toFixed(0)} %) sides differ only by ` +
            `${(Math.abs(dark - lit) * 100).toFixed(0)} % – the relief fades. ` +
            `Transparency can only go down to ${(RELIEF_MIN * 100).toFixed(0)} %.`
        );
    }
  }
}

if (problems.length) {
  console.error(`hillshading: ${problems.length} errors\n`);
  for (const p of problems) console.error(`  ✗ ${p}`);
  process.exit(1);
}
console.log(
  `hillshading: 0 errors (${checks} coverage measurements on a ${SLOPE_DEG}° slope, ` +
    `${Object.keys(THEMES).length} themes × ${MAP_TYPE_IDS.length} map types)`
);
