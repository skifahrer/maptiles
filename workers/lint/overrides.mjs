#!/usr/bin/env node
/**
 * Checks developer-mode overrides. Run by `Check · workflow lint`.
 *
 * Guards things that broke quietly (the style stayed valid, the map loaded,
 * nobody said anything):
 *
 *   1. `line-width: 0` is a hard error – a down-arrow in an empty field once
 *      blanked a whole layer. `text-halo-width: 0` isn't an error.
 *   2. Copying a style between layers must pass `normalizeOverrides` whole,
 *      or the pipeline would drop the override on write.
 *   3. A style's dash can be restored and turned off (`frico:dash`, “solid”
 *      through normalisation, `applyLayerOverrides` deletes the property).
 *   4. A dark variant mustn't be made by dimming the light colour – the pair's
 *      weight is compared, not the colours. In its own `overrides-contrast.mjs`.
 *
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
import { darkWeights } from "./overrides-contrast.mjs";
import { bandPercentages } from "./overrides-bands.mjs";

/** The smallest valid PNG (1 × 1 px) – for trying own icons. */
const PNG_1PX = "data:image/png;base64,"
  + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

let bad = 0;
const error = (file, text) => {
  console.log(`::error file=${file}::${text}`);
  bad += 1;
};

// 1. zero width
const width = (prop, value) =>
  normalizeOverrides({ layers: { x: { paint: { [prop]: value } } } });

for (const [prop, mustFail] of [
  ["line-width", true],
  ["text-halo-width", false],
  ["icon-halo-width", false],
  ["circle-stroke-width", false]
]) {
  const { overrides, problems } = width(prop, 0);
  const accepted = overrides.layers.x?.paint?.[prop] === 0;
  if (mustFail && (accepted || !problems.length)) {
    error(
      "poc/web/themes.js",
      `\`${prop}: 0\` passed normalizeOverrides. A zero-width line isn't drawn ` +
      `and looks like missing data in the map – a layer is turned off through ` +
      `\`visible\`, not its width.`
    );
  }
  if (!mustFail && !accepted) {
    error(
      "poc/web/themes.js",
      `normalizeOverrides refused \`${prop}: 0\`, though zero there means ` +
      `“no halo” – a common style value, not an error.`
    );
  }
}

// a positive width must pass
if (width("line-width", 1.5).overrides.layers.x?.paint?.["line-width"] !== 1.5) {
  error("poc/web/themes.js", "`line-width: 1.5` didn't get through normalizeOverrides.");
}

// 2. copying a style
const styles = [];
for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    styles.push({
      where: `${theme} × ${mapType}`,
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
        // on purpose: `hillshade` is the one layer with `hillshade-exaggeration`
        hillshade: true
      })
    });
  }
}

let pastes = 0;
let snapshots = 0;

/** Pastes a snapshot style into a layer and checks `normalizeOverrides` accepts it. */
function tryPaste(snap, target, where) {
  const { patch } = pasteStyle(snap, target);
  if (!Object.keys(patch).length) return;
  pastes += 1;
  const raw = emptyOverrides();
  raw.layers[target.id] = patch;
  const { overrides, problems } = normalizeOverrides(raw);
  if (problems.length) {
    error(
      "poc/web/layer-style.js",
      `copying style \`${snap.from}\` → \`${target.id}\` (${where}) made an ` +
      `override normalizeOverrides refuses: ${problems[0]}`
    );
    return;
  }
  const clean = overrides.layers[target.id] || {};
  for (const key of Object.keys(patch)) {
    if (key === "paint") continue;
    if (clean[key] === undefined) {
      error(
        "poc/web/layer-style.js",
        `copying style \`${snap.from}\` → \`${target.id}\` (${where}): ` +
        `\`${key}\` didn't get through normalizeOverrides – it would hold in ` +
        `the browser, not in the finished map.`
      );
    }
  }
  for (const prop of Object.keys(patch.paint || {})) {
    if ((clean.paint || {})[prop] === undefined) {
      error(
        "poc/web/layer-style.js",
        `copying style \`${snap.from}\` → \`${target.id}\` (${where}): ` +
        `normalizeOverrides dropped property \`${prop}\`.`
      );
    }
  }
}

for (const { where, style } of styles) {
  // one representative per layer type – pasted across types
  const representative = new Map();
  for (const layer of style.layers) if (!representative.has(layer.type)) representative.set(layer.type, layer);

  for (const layer of style.layers) {
    const snap = snapshotStyle(layer, {});
    snapshots += 1;
    tryPaste(snap, layer, where);
    for (const target of representative.values()) if (target.id !== layer.id) tryPaste(snap, target, where);
  }
}

// 3. “what it does at this zoom”: the filled value matches the style at the breaks
const curve = ["interpolate", ["exponential", 1.5], ["zoom"], 11, 0.4, 16, 2.2];
for (const [z, expected] of [[8, 0.4], [11, 0.4], [16, 2.2], [20, 2.2]]) {
  const got = valueAtZoom(curve, z);
  if (got !== expected) {
    error(
      "poc/web/layer-style.js",
      `valueAtZoom at z${z} returned ${got}, expected ${expected}.`
    );
  }
}
if (valueAtZoom(["match", ["get", "x"], "a", 1, 2], 14) !== null) {
  error(
    "poc/web/layer-style.js",
    "valueAtZoom returned a number for a feature-attribute expression – one zoom " +
    "can't say that, and an invented value is worse than none."
  );
}

// 4. zoom bands must be contiguous – a gap or overlap is a hard error
const bands = (value) =>
  normalizeOverrides({ layers: { x: { paint: { "line-width": value } } } });

for (const [label, value, mustPass] of [
  ["contiguous bands", [[9, 11, 2], [12, 12, 4], [13, 17, 6]], true],
  ["one band", [[9, 17, 2]], true],
  ["a gap between bands", [[9, 11, 2], [14, 17, 6]], false],
  ["overlapping bands", [[9, 11, 2], [11, 17, 6]], false],
  ["a curve mixed with a band", [[9, 2], [12, 13, 4]], false],
  ["a fractional zoom in a band", [[9, 11.5, 2], [12, 17, 6]], false],
  ["a reversed band", [[13, 11, 2]], false]
]) {
  const { overrides, problems } = bands(value);
  const accepted = overrides.layers.x?.paint?.["line-width"] !== undefined;
  if (mustPass && (!accepted || problems.length)) {
    error("poc/web/themes.js",
      `zoom bands (${label}) didn't pass normalizeOverrides: ${problems[0] || "dropped without a reason"}`);
  }
  if (!mustPass && (accepted || !problems.length)) {
    error("poc/web/themes.js",
      `zoom bands (${label}) passed normalizeOverrides. Bands must be contiguous ` +
      `and of one shape – otherwise something else holds than what is written.`);
  }
}

// a band edge covers fractional zooms below it (“up to 11” = z11.9 too)
const staircase = paintValue([[9, 11, 2], [12, 12, 4], [13, 17, 6]]);
for (const [z, expected] of [[5, 2], [9, 2], [11.9, 2], [12, 4], [12.9, 4], [13, 6], [20, 6]]) {
  const got = valueAtZoom(staircase, z);
  if (got !== expected) {
    error("poc/web/layer-style.js",
      `bands at z${z} returned ${got}, expected ${expected} – the band edge ` +
      `isn't where the override promises.`);
  }
}

// what a `step` layer snapshots, normalisation must accept whole
{
  const layerDef = {
    id: "stairs",
    type: "line",
    paint: { "line-width": staircase, "line-color": paintValue([[0, 9, "#112233"], [10, MAX_DISPLAY_Z, "#445566"]]) }
  };
  const snap = snapshotStyle(layerDef, {});
  if (snap.dropped.length) {
    error("poc/web/layer-style.js",
      `snapshotting a \`step\` layer dropped ${snap.dropped.join(", ")} – a zoom ` +
      `staircase must snapshot as zoom bands.`);
  }
  const raw = emptyOverrides();
  raw.layers.stairs = { paint: snap.paint };
  const { overrides, problems } = normalizeOverrides(raw);
  if (problems.length) {
    error("poc/web/layer-style.js",
      `normalizeOverrides refuses a \`step\` layer snapshot: ${problems[0]}`);
  }
  for (const prop of Object.keys(snap.paint)) {
    if ((overrides.layers.stairs?.paint || {})[prop] === undefined) {
      error("poc/web/layer-style.js",
        `snapshot property \`${prop}\` of a \`step\` layer didn't get through normalizeOverrides.`);
    }
  }
}

// 5. what developer mode sets is also saved – tried through the real script
{
  const sample = {
    trails: {
      gap: { road: 8 },
      types: { hiking: { dash: "dotted", icon: "", mark: "triangle" } },
      marks: { spacing: 300, size: 1.2 }
    },
    shields: { motorway: { shape: "shield-round" } },
    // an own set and icon affect the build, so they pass whole with the image
    iconSets: [
      { id: "own-test", label: "Test", sprite: "https://example.org/sprites/test", suffix: "_11" }
    ],
    customIcons: [{ name: "own:test", png: PNG_1PX, pixelRatio: 2 }],
    palette: {},
    // the order is its own key (`order`), not a layer property
    order: [{ id: "feature-embankment", before: "road-minor" }],
    // `poi` is written whole – half of it can be forgotten
    poi: { hidden: ["fuel"], icons: { restaurant: "bar_11", spring: "" } },
    // `layout` is the second shelf beside `paint`
    layers: {
      "trail-hiking-mark": {
        layout: { "icon-size": 1.2, "symbol-spacing": [[12, 13, 120], [14, 20, 260]] }
      },
      // a pattern from an own image has two halves: the name and the PNG
      "landcover-wood": { pattern: { image: "own:test", opacity: 0.8 } }
    }
  };
  const { overrides } = normalizeOverrides(sample);
  const dir = mkdtempSync(join(tmpdir(), "overrides-lint-"));
  try {
    // the script writes into the repository root; the original is restored after
    const input = join(dir, "in.json");
    writeFileSync(input, JSON.stringify(sample));
    const backup = readFileSync(TARGET, "utf8");
    try {
      execFileSync("node", ["workers/styles/overrides.mjs", `--file=${input}`], {
        stdio: "pipe",
        cwd: ROOT
      });
      const written = normalizeOverrides(JSON.parse(readFileSync(TARGET, "utf8"))).overrides;
      const errorIf = (path, a, b) => {
        if (JSON.stringify(a) !== JSON.stringify(b)) {
          error(
            "workers/styles/overrides.mjs",
            `writing style-overrides.json lost \`${path}\`: ` +
              `${JSON.stringify(a)} → ${JSON.stringify(b)}. It holds in the browser, ` +
              `not in the repository – the map on Pages will differ from developer mode.`
          );
        }
      };
      errorIf("trails.gap", overrides.trails.gap, written.trails.gap);
      errorIf("order", overrides.order, written.order);
      errorIf("poi.icons", overrides.poi.icons, written.poi.icons);
      errorIf(
        "layers[landcover-wood].pattern",
        overrides.layers["landcover-wood"]?.pattern,
        written.layers["landcover-wood"]?.pattern
      );
      errorIf("iconSets", overrides.iconSets, written.iconSets);
      errorIf("customIcons", overrides.customIcons, written.customIcons);
      errorIf(
        "layers[trail-hiking-mark].layout",
        overrides.layers["trail-hiking-mark"]?.layout,
        written.layers["trail-hiking-mark"]?.layout
      );
      errorIf("trails.types", overrides.trails.types, written.trails.types);
      errorIf("trails.marks", overrides.trails.marks, written.trails.marks);
      errorIf("shields", overrides.shields, written.shields);
    } finally {
      writeFileSync(TARGET, backup);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// 6. a line dash can be restored – `frico:dash`, `normalizeOverrides` and `applyLayerOverrides`
{
  let dashed = 0;
  for (const { where, style } of styles) {
    for (const layer of style.layers) {
      if (layer.type !== "line") continue;
      if ((layer.metadata || {})["frico:derived"]) continue;
      const arr = (layer.paint || {})["line-dasharray"];
      const meta = (layer.metadata || {})["frico:dash"];
      if (!Array.isArray(arr)) {
        if (meta !== undefined) {
          error("poc/web/themes.js",
            `layer \`${layer.id}\` (${where}) carries \`frico:dash\` on a solid line ` +
            `– the panel would offer to restore a dash the style doesn't have.`);
        }
        continue;
      }
      dashed += 1;
      const same = typeof meta === "string"
        ? JSON.stringify(dashArray(meta)) === JSON.stringify(arr)
        : JSON.stringify(meta) === JSON.stringify(arr);
      if (!same) {
        error("poc/web/themes.js",
          `layer \`${layer.id}\` (${where}) has \`line-dasharray: ` +
          `${JSON.stringify(arr)}\` in the style but \`${JSON.stringify(meta)}\` in ` +
          `its metadata. Developer mode reads the dash from there – it would show ` +
          `another line than the map, and “back to the original” wouldn't restore it.`);
      }
    }
  }
  if (!dashed) {
    error("workers/lint/overrides.mjs",
      "the style has not a single dashed line – the check has nothing to guard.");
  }

  // “solid” must survive normalisation…
  const { overrides: withChoice } = normalizeOverrides({
    layers: { "rail-hatch": { dash: "solid" } }
  });
  if (withChoice.layers["rail-hatch"]?.dash !== "solid") {
    error("poc/web/themes.js",
      "normalizeOverrides dropped `dash: \"solid\"`. A layer with a style dash " +
      "(railway, ford) then can't go back to a solid line – the choice is " +
      "accepted and nothing happens in the map.");
  }

  // …and really delete the dash in the finished style
  const build = (o) => buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    overrides: o
  });
  const base = build(null).layers.find((l) => l.id === "rail-hatch");
  if (!base || builtinDash(base) !== "rail") {
    error("poc/web/themes.js",
      "`rail-hatch` has no built-in `rail` dash – the railway hatching is the " +
      "very layer this showed on.");
  }
  const solid = build(withChoice).layers.find((l) => l.id === "rail-hatch");
  if (solid && (solid.paint || {})["line-dasharray"] !== undefined) {
    error("poc/web/themes.js",
      `\`dash: "solid"\` left \`line-dasharray: ` +
      `${JSON.stringify(solid.paint["line-dasharray"])}\` on \`rail-hatch\`. A solid ` +
      `line means DELETING the property – MapLibre wouldn't accept \`null\`.`);
  }
  const other = build(normalizeOverrides({ layers: { "rail-hatch": { dash: "ties" } } }).overrides)
    .layers.find((l) => l.id === "rail-hatch");
  if (JSON.stringify((other.paint || {})["line-dasharray"]) !== JSON.stringify(dashArray("ties"))) {
    error("poc/web/themes.js",
      "changing the dash to `ties` didn't show on `rail-hatch`.");
  }
  // `dashIdOf` mustn't claim an own dash is a preset
  if (dashIdOf([0.35, 2.2]) !== null) {
    error("poc/web/patterns.js",
      "`dashIdOf` named an own dash after a preset – the panel would rewrite " +
      "it to another line on the first save.");
  }
}

// 7. drawing order – the one override changing the style's structure
{
  const buildWith = (order) => buildStyle({
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

  const plain = buildWith([]).layers.map((l) => l.id);
  const tryMove = (label, order, over) => {
    const layers = buildWith(order).layers;
    const ids = layers.map((l) => l.id);
    if (ids.length !== plain.length || new Set(ids).size !== ids.length) {
      error("poc/web/themes.js",
        `moving layers (${label}) changed the layer count: ${plain.length} → ${ids.length} ` +
        `(${new Set(ids).size} distinct). A layer lost in a move isn't in the map ` +
        `while the style stays valid.`);
    }
    const last = ids.slice(-2);
    if (JSON.stringify(last) !== JSON.stringify(["region-outside", "region-border"])) {
      error("poc/web/themes.js",
        `moving layers (${label}) left ${last.join(", ")} on top instead of the region ` +
        `mask. A layer above the mask draws outside the downloaded region too.`);
    }
    over(ids);
  };

  tryMove("embankment under roads", [{ id: "feature-embankment", before: "road-minor" }], (ids) => {
    if (!(ids.indexOf("feature-embankment") < ids.indexOf("road-minor"))) {
      error("poc/web/themes.js", "moving `feature-embankment` under `road-minor` didn't take effect.");
    }
    // the teeth are the other half of the same edge (`frico:with`)
    if (ids.indexOf("feature-embankment-teeth") - ids.indexOf("feature-embankment") !== 1) {
      error("poc/web/themes.js",
        "`feature-embankment-teeth` stayed put in the move – the edge would be under " +
        "the road and its teeth above it.");
    }
  });

  tryMove("railway on top", [{ id: "rail-bg", before: null }], (ids) => {
    if (ids.indexOf("rail-hatch") - ids.indexOf("rail-bg") !== 1) {
      error("poc/web/themes.js",
        "`rail-hatch` didn't move with `rail-bg` – the hatched railway would be a " +
        "dark line in one place and white dashes in another.");
    }
  });

  tryMove("a layer this style lacks", [
    { id: "missing", before: "water" },
    { id: "water", before: "also-missing" }
  ], () => {});

  // moving above the mask mustn't work
  tryMove("trying to cover the mask", [{ id: "background", before: null }], () => {});
}

// 8. every panel tab is drawn – `TABS` and the `renderBody` switch are two places
{
  const source = readFileSync(join(ROOT, "poc", "web", "devmode.js"), "utf8");
  const block = source.match(/const TABS = \[([\s\S]*?)\];/);
  if (!block) {
    error("poc/web/devmode.js", "the `TABS` list wasn't found – the check has nothing to guard.");
  } else {
    const ids = [...block[1].matchAll(/\["([a-z]+)",/g)].map((m) => m[1]);
    if (ids.length < 2) {
      error("poc/web/devmode.js", "tab ids couldn't be read from the `TABS` list.");
    }
    // the last tab has no condition on purpose – it's the final branch
    for (const id of ids.slice(0, -1)) {
      if (!source.includes(`tab === "${id}"`)) {
        error(
          "poc/web/devmode.js",
          `tab "${id}" is listed, but \`renderBody\` doesn't draw it – tapping ` +
          `it opens the switch's last branch (the file tab).`
        );
      }
    }
  }
}

// 9. a relative value `{scale, add}` – `scaleExpr` handles bands; `{scale: 1, add: 0}` is refused
const relative = (value, prop = "line-width") =>
  normalizeOverrides({ layers: { x: { paint: { [prop]: value } } } });

for (const [label, value, prop, mustPass] of [
  ["a percentage", { scale: 1.4 }, "line-width", true],
  ["a constant", { add: 0.5 }, "line-width", true],
  ["both", { scale: 1.4, add: 0.5 }, "line-width", true],
  ["changes nothing", { scale: 1, add: 0 }, "line-width", false],
  ["zero as a factor", { scale: 0 }, "line-width", false],
  ["out of bounds", { scale: 99 }, "line-width", false],
  ["not a number", { scale: "lots" }, "line-width", false],
  ["on a colour", { scale: 1.4 }, "line-color", false]
]) {
  const { overrides, problems } = relative(value, prop);
  const accepted = overrides.layers.x?.paint?.[prop] !== undefined;
  if (mustPass && (!accepted || problems.length)) {
    error("poc/web/themes.js",
      `a relative value (${label}) didn't pass normalizeOverrides: ` +
      `${problems[0] || "dropped without a reason"}`);
  }
  if (!mustPass && (accepted || !problems.length)) {
    error("poc/web/themes.js",
      `a relative value (${label}) passed normalizeOverrides – and shouldn't have.`);
  }
}

// a curve keeps its interpolation kind – a linear stand-in shifts the widths
const scaled = scaleExpr(
  ["interpolate", ["exponential", 1.5], ["zoom"], 11, 0.4, 16, 2.2], { scale: 2 }
);
if (JSON.stringify(scaled.slice(0, 3)) !== JSON.stringify(["interpolate", ["exponential", 1.5], ["zoom"]])) {
  error("poc/web/themes.js", "scaleExpr changed the interpolation kind – widths between breaks would land elsewhere.");
}
for (const [z, expected] of [[11, 0.8], [16, 4.4]]) {
  if (valueAtZoom(scaled, z) !== expected) {
    error("poc/web/themes.js",
      `scaleExpr over a curve gave ${valueAtZoom(scaled, z)} at z${z}, expected ${expected}.`);
  }
}
// and the same over bands
const scaledBands = scaleExpr(paintValue([[9, 11, 2], [12, 17, 5]]), { add: 3 });
for (const [z, expected] of [[9, 5], [12, 8]]) {
  if (valueAtZoom(scaledBands, z) !== expected) {
    error("poc/web/themes.js",
      `scaleExpr over bands gave ${valueAtZoom(scaledBands, z)} at z${z}, ` +
      `expected ${expected} – an outline over such a line would be exactly as wide.`);
  }
}
// a feature-attribute expression mustn't be rewritten
const byData = ["match", ["get", "x"], "a", 1, 2];
if (JSON.stringify(scaleExpr(byData, { scale: 2 })) !== JSON.stringify(byData)) {
  error("poc/web/themes.js", "scaleExpr rewrote a feature-attribute expression.");
}

// an outline over a banded line must really be wider
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
  const line = s.layers.find((l) => l.id === "road-path");
  const outline = s.layers.find((l) => l.id === "road-path__outline");
  if (!line || !outline) {
    error("poc/web/themes.js", "no outline was made over the banded line at all.");
  } else {
    for (const z of [12, 16]) {
      const a = valueAtZoom(line.paint["line-width"], z);
      const b = valueAtZoom(outline.paint["line-width"], z);
      if (!(b > a)) {
        error("poc/web/themes.js",
          `the outline at z${z} is ${b}, the line ${a} – an outline that isn't wider can't be seen.`);
      }
    }
  }
}

// 10. variants by OSM attribute: a feature is drawn once – the base negates variant values
let variantLayers = 0;
{
  const test = (v) => normalizeOverrides({ layers: { "road-track": { variants: v } } });
  for (const [label, v, mustPass] of [
    ["one variant", [{ attr: "surface", values: ["paved"] }], true],
    ["no values", [{ attr: "surface", values: [] }], false],
    ["no attribute", [{ values: ["paved"] }], false],
    ["an invalid attribute name", [{ attr: "s urface!", values: ["paved"] }], false],
    ["two variants over one value",
     [{ attr: "surface", values: ["paved"] }, { attr: "surface", values: ["paved"] }], false],
    ["over the cap", Array.from({ length: MAX_VARIANTS + 1 },
      (_, i) => ({ attr: "surface", values: [`v${i}`] })), false]
  ]) {
    const { overrides, problems } = test(v);
    const accepted = (overrides.layers["road-track"]?.variants || []).length === v.length;
    if (mustPass && (!accepted || problems.length)) {
      error("poc/web/themes.js",
        `variant (${label}) didn't pass normalizeOverrides: ${problems[0] || "dropped without a reason"}`);
    }
    if (!mustPass && (accepted || !problems.length)) {
      error("poc/web/themes.js", `variant (${label}) passed normalizeOverrides – and shouldn't have.`);
    }
  }

  const { overrides } = normalizeOverrides({
    layers: {
      "road-track": {
        variants: [{ attr: "surface", values: ["paved", "asphalt"], label: "paved",
                     dash: "solid", outline: { color: "#8a7a6a", width: { scale: 1.6 } } }]
      }
    }
  });
  const s = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                         spriteUrl: "https://x/sprite", overrides });
  const base = s.layers.find((l) => l.id === "road-track");
  const variant = s.layers.find((l) => l.id === "road-track__var1");
  const outline = s.layers.find((l) => l.id === "road-track__var1__outline");
  variantLayers = [base, variant, outline].filter(Boolean).length;
  const testExpr = JSON.stringify(["in", ["coalesce", ["get", "surface"], ""],
                                   ["literal", ["paved", "asphalt"]]]);
  if (!variant) {
    error("poc/web/themes.js", "the layer variant wasn't made in the style.");
  } else if (!JSON.stringify(variant.filter).includes(testExpr)) {
    error("poc/web/themes.js", "the variant filter lacks the attribute test.");
  }
  if (!base || !JSON.stringify(base.filter).includes(`["!",${testExpr}]`)) {
    error("poc/web/themes.js",
      "the base filter isn't narrowed by the variant's negation – a feature would " +
      "draw twice over itself and just look “somehow thicker” in the map.");
  }
  // a variant outline must belong to its root, or an order move leaves it behind
  if (!outline || (outline.metadata || {})["frico:derived"] !== "road-track") {
    error("poc/web/themes.js",
      "the variant outline doesn't belong to the base – an order move would leave it behind.");
  }
  // the outline is 1.6× the line, so wider at every zoom
  if (variant && outline) {
    for (const z of [11, 16, 20]) {
      const a = valueAtZoom(variant.paint["line-width"], z);
      const b = valueAtZoom(outline.paint["line-width"], z);
      if (!(b > a)) {
        error("poc/web/themes.js",
          `the variant outline at z${z} is ${b}, the line ${a} – a percentage keeps the ratio at every zoom.`);
      }
    }
  }
  const ids2 = s.layers.map((l) => l.id);
  if (new Set(ids2).size !== ids2.length) {
    error("poc/web/themes.js", "variants made two layers with one id – MapLibre refuses such a style.");
  }
}

// 4. a dark variant isn't made from white – in its own file
const pairs = darkWeights(JSON.parse(readFileSync(TARGET, "utf8")), error);

// 5. a percentage in a zoom band – in its own file too
const zooms = bandPercentages(error);

console.log(
  `overrides: ${bad} errors (${snapshots} layer snapshots, ${pastes} pastes, ` +
  `7 zoom band shapes, 8 relative value shapes, ` +
  `6 variant shapes, ${variantLayers} variant layers, ` +
  `${zooms} zooms with a band percentage, ` +
  `${pairs} light/dark colour pairs, ` +
  `${Object.keys(THEMES).length} themes × ${MAP_TYPE_IDS.length} map types)`
);
process.exit(bad ? 1 : 0);
