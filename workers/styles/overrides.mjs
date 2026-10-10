#!/usr/bin/env node
/**
 * Saves developer-mode style overrides to `poc/web/style-overrides.json`, cleaned by the
 * same `normalizeOverrides` the browser uses.
 *
 *   node workers/styles/overrides.mjs --file=overrides.json [--check]
 *   node workers/styles/overrides.mjs --stdin < overrides.json
 *   node workers/styles/overrides.mjs --reset
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  normalizeOverrides,
  emptyOverrides,
  hasOverrides,
  THEMES,
  PALETTE_LABELS,
  DEFAULT_ICON_SOURCE,
  TRAIL_GAP_DEFAULTS,
  TRAIL_GAP_ZOOM,
  TRAIL_MARK_DEFAULTS,
  TRAIL_MARK_ZOOM,
  isRelative,
  mapTypeDef
} from "../../poc/web/themes.js";

// `workers/styles` → the repo root is TWO levels up
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const TARGET = join(root, "poc", "web", "style-overrides.json");

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

function readInput() {
  if (args.reset) return emptyOverrides();
  if (args.file) return JSON.parse(readFileSync(args.file, "utf8"));
  if (args.stdin) return JSON.parse(readFileSync(0, "utf8"));
  console.error(
    "No input: --file=<json>, --stdin or --reset (see the file header)"
  );
  process.exit(2);
}

let raw;
try {
  raw = readInput();
} catch (err) {
  console.error(`::error::The input couldn't be read as JSON: ${err.message}`);
  process.exit(1);
}

const { overrides, problems } = normalizeOverrides(raw);

for (const p of problems) console.log(`::warning::${p}`);

// what actually changes
const summary = [];
if (overrides.hillshade) summary.push("  hillshading: on");
if (overrides.icons && overrides.icons !== DEFAULT_ICON_SOURCE) {
  summary.push(`  icon set: ${overrides.icons}`);
}
for (const [theme, colors] of Object.entries(overrides.palette)) {
  const names = Object.keys(colors)
    .map((k) => PALETTE_LABELS[k] || k)
    .join(", ");
  summary.push(`  theme ${THEMES[theme].label}: ${Object.keys(colors).length} colours (${names})`);
}
// drawing order is a list of moves, not a layer override
if (overrides.order.length) {
  summary.push(
    `  drawing order: ` +
      overrides.order
        .map((m) => `${m.id} → ${m.before ? `below ${m.before}` : "on top"}`)
        .join(", ")
  );
}
const hidden = Object.entries(overrides.layers).filter(([, o]) => o.visible === false);
const recolored = Object.entries(overrides.layers).filter(([, o]) => o.paint);
// dark variants get their own line, or they hide among the recoloured count
const darkened = Object.entries(overrides.layers).filter(
  ([, o]) => (o.paintDark && Object.keys(o.paintDark).length) || o.outline?.colorDark
);
const rezoomed = Object.entries(overrides.layers).filter(
  ([, o]) => o.minzoom != null || o.maxzoom != null
);
const patterned = Object.entries(overrides.layers).filter(([, o]) => o.pattern);
const outlined = Object.entries(overrides.layers).filter(([, o]) => o.outline);
// relative overrides scale what the style has, so the summary says by how much
const relText = (v) =>
  [v.scale != null ? `${v.scale}×` : null, v.add != null ? `${v.add > 0 ? "+" : ""}${v.add}` : null]
    .filter(Boolean).join(" and ");
const scaled = Object.entries(overrides.layers).flatMap(([id, o]) => [
  ...Object.entries(o.paint || {}).filter(([, v]) => isRelative(v))
    .map(([prop, v]) => `${id} ${prop} ${relText(v)}`),
  ...Object.entries(o.layout || {}).filter(([, v]) => isRelative(v))
    .map(([prop, v]) => `${id} ${prop} ${relText(v)}`),
  ...(isRelative(o.outline?.width) ? [`${id} outline ${relText(o.outline.width)}`] : [])
]);
// split by an OSM attribute adds a layer and narrows the template's filter
const splits = Object.entries(overrides.layers).flatMap(([id, o]) =>
  (o.variants || []).map((v) => `${id}: ${v.attr} = ${v.values.join(", ")}`));
const dashed = Object.entries(overrides.layers).filter(([, o]) => o.dash);
const reiconed = Object.entries(overrides.layers).filter(([, o]) => o.icon);
if (hidden.length) summary.push(`  hidden layers: ${hidden.map(([id]) => id).join(", ")}`);
if (recolored.length) summary.push(`  recoloured layers: ${recolored.length}`);
if (darkened.length) {
  summary.push(`  of them with their own dark-theme colour: ${darkened.map(([id]) => id).join(", ")}`);
}
if (rezoomed.length) summary.push(`  changed zoom range: ${rezoomed.length}`);
if (patterned.length) {
  summary.push(
    // a pattern is drawn (`id`) or a custom image (`image`)
    `  patterns: ${patterned
      .map(([id, o]) => `${id} → ${o.pattern.image || o.pattern.id}`)
      .join(", ")}`
  );
}
if (outlined.length) summary.push(`  outlines: ${outlined.map(([id]) => id).join(", ")}`);
if (scaled.length) summary.push(`  scaled from the style: ${scaled.join(", ")}`);
if (splits.length) summary.push(`  split by OSM: ${splits.join(" · ")}`);
if (dashed.length) {
  summary.push(`  line dashes: ${dashed.map(([id, o]) => `${id} → ${o.dash}`).join(", ")}`);
}
if (reiconed.length) {
  summary.push(`  icons: ${reiconed.map(([id, o]) => `${id} → ${o.icon}`).join(", ")}`);
}
if (overrides.poi.hidden.length) {
  summary.push(`  hidden POI classes: ${overrides.poi.hidden.join(", ")}`);
}
// category icons sit beside hidden classes but answer another question
const poiIcons = Object.entries(overrides.poi.icons || {});
if (poiIcons.length) {
  summary.push(
    `  POI category icons: ` +
      poiIcons.map(([cls, name]) => `${cls} → ${name || "none"}`).join(", ")
  );
}

// one trail kind is three style layers, so trails get their own lines
const gaps = Object.entries(overrides.trails?.gap || {});
if (gaps.length) {
  summary.push(
    `  trail offset from the road (px at z${TRAIL_GAP_ZOOM}): ` +
      gaps.map(([k, v]) => `${k} ${v} (was ${TRAIL_GAP_DEFAULTS[k]})`).join(", ")
  );
}
for (const [id, def] of Object.entries(overrides.trails?.types || {})) {
  const parts = [];
  if (def.dash) parts.push(`line ${def.dash}`);
  if (def.icon != null) parts.push(`icon ${def.icon || "none"}`);
  if (def.mark != null) parts.push(`mark ${def.mark || "none"}`);
  summary.push(`  trail ${id}: ${parts.join(" · ")}`);
}
const marks = Object.entries(overrides.trails?.marks || {});
if (marks.length) {
  summary.push(
    `  trail marks (at z${TRAIL_MARK_ZOOM}): ` +
      marks.map(([k, v]) => `${k} ${v} (was ${TRAIL_MARK_DEFAULTS[k]})`).join(", ")
  );
}
for (const [id, def] of Object.entries(overrides.shields || {})) {
  summary.push(`  shield ${id}: shape ${def.shape}`);
}

// custom sets and icons change the BUILD, not only the browser
if (overrides.iconSets?.length) {
  summary.push(
    `  custom icon sets: ` +
      overrides.iconSets.map((s2) => `${s2.id} (${s2.sprite})`).join(", ")
  );
}
if (overrides.customIcons?.length) {
  const kB = Math.round(
    overrides.customIcons.reduce((n, i) => n + i.png.length, 0) / 1024
  );
  summary.push(
    `  custom icons (${kB} kB): ` +
      overrides.customIcons.map((i) => i.name).join(", ")
  );
}

// layout sizes and spacing tune the trail marks, so they get their own line
const laidOut = Object.entries(overrides.layers).filter(([, o]) => o.layout);
if (laidOut.length) {
  summary.push(
    `  sizes and spacing: ` +
      laidOut
        .map(([id, o]) => `${id} (${Object.keys(o.layout).join(", ")})`)
        .join(", ")
  );
}

// overrides of a single map type
for (const [typeId, m] of Object.entries(overrides.maps)) {
  const parts = [];
  const own = Object.entries(m.layers || {});
  const off = own.filter(([, o]) => o.visible === false).map(([id]) => id);
  const on = own.filter(([, o]) => o.visible === true).map(([id]) => id);
  const zoomed = own.filter(([, o]) => o.minzoom != null || o.maxzoom != null);
  const styled = own.filter(([, o]) => o.paint || o.dash || o.pattern || o.outline || o.icon);
  const darkenedOwn = own.filter(
    ([, o]) => (o.paintDark && Object.keys(o.paintDark).length) || o.outline?.colorDark
  );
  if (off.length) parts.push(`hidden: ${off.join(", ")}`);
  if (on.length) parts.push(`also on: ${on.join(", ")}`);
  if (zoomed.length) parts.push(`zoom: ${zoomed.length}`);
  if (styled.length) parts.push(`style: ${styled.length}`);
  if (darkenedOwn.length) {
    parts.push(`of them for the dark theme: ${darkenedOwn.map(([id]) => id).join(", ")}`);
  }
  if (m.poi?.hidden?.length) parts.push(`hidden POI: ${m.poi.hidden.join(", ")}`);
  if (parts.length) {
    summary.push(`  map ${mapTypeDef(typeId).label}: ${parts.join(" · ")}`);
  }
}

console.log(
  hasOverrides(overrides)
    ? `Style overrides:\n${summary.join("\n")}`
    : "No overrides – the style stays as it is."
);

if (args.check) {
  console.log("Checked, the file isn't written (--check).");
  process.exit(0);
}

const payload = {
  version: 2,
  updated_at: new Date().toISOString(),
  icons: overrides.icons,
  hillshade: overrides.hillshade,
  palette: overrides.palette,
  layers: overrides.layers,
  order: overrides.order,
  poi: overrides.poi,
  // every section must be written, or it silently never reaches the repo
  trails: overrides.trails,
  shields: overrides.shields,
  routeShields: overrides.routeShields,
  iconSets: overrides.iconSets,
  customIcons: overrides.customIcons,
  maps: overrides.maps
};
writeFileSync(TARGET, `${JSON.stringify(payload, null, 2)}\n`);
console.log(`✓ written to ${TARGET}`);
