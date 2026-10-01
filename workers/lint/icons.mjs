#!/usr/bin/env node
/**
 * Checks icons: own images, own sets and `layout` properties.
 * Run by `Check · workflow lint`.
 *
 * Seven quiet things – none fails, they show only in the map:
 *
 *   1. an own icon bakes into the sprite (MapLibre quietly skips an unknown
 *      image); tried on a real sprite;
 *   2. the style lets it through even before the sprite has it;
 *   3. `icons.sh` lists an own set for download and `deploy/site.sh` for the manifest;
 *   4. `layout` only on a symbol layer – an unknown `layout` property is a hard
 *      error and MapLibre refuses the whole style;
 *   5. a POI category icon is set as a bare image name; a freshly uploaded own icon
 *      and the “none” choice hold too;
 *   6. an own image as an area pattern (baked by the same script);
 *   7. a one-way arrow exists for every set.
 *
 *   node workers/lint/icons.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { encodePng } from "../lib/png.mjs";
import {
  THEMES,
  buildStyle,
  normalizeOverrides,
  LAYOUT_PROP_IDS,
  CUSTOM_ICON_PREFIX
} from "../../poc/web/themes.js";
import { CUSTOM_SET_PREFIX, allIconSources, ICON_SOURCE_IDS } from "../../poc/web/icon-sources.js";
import { arrowImages, DEFAULT_ARROW_IMAGE } from "../../poc/web/arrows.js";
import { collectPatternNames } from "../../poc/web/patterns.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
let bad = 0;
const error = (file, text) => {
  console.log(`::error file=${file}::${text}`);
  bad += 1;
};

/** A small PNG as an own icon. */
const iconPng = () => {
  const n = 8;
  const d = Buffer.alloc(n * n * 4, 255);
  return `data:image/png;base64,${encodePng({ width: n, height: n, data: d }).toString("base64")}`;
};

const SAMPLE = {
  version: 2,
  icons: `${CUSTOM_SET_PREFIX}test`,
  iconSets: [
    {
      id: `${CUSTOM_SET_PREFIX}test`,
      label: "Test set",
      sprite: "https://example.org/sprites/test",
      suffix: "_11"
    }
  ],
  customIcons: [{ name: `${CUSTOM_ICON_PREFIX}test`, png: iconPng(), pixelRatio: 2 }]
};
const { overrides, problems } = normalizeOverrides(SAMPLE);
for (const p of problems) {
  error("poc/web/themes.js", `the sample overrides didn't pass normalisation: ${p}`);
}

// 1. an own icon bakes into the sprite
const dir = mkdtempSync(join(tmpdir(), "icons-lint-"));
try {
  const base = join(dir, "sprite");
  writeFileSync(`${base}.png`, encodePng({ width: 4, height: 4, data: Buffer.alloc(64, 255) }));
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );
  const overridesFile = join(dir, "overrides.json");
  writeFileSync(overridesFile, JSON.stringify(SAMPLE));
  execFileSync(
    "node",
    ["workers/assets/custom-icons.mjs", `--sprite=${base}`, `--overrides=${overridesFile}`],
    { stdio: "pipe", cwd: ROOT }
  );
  const index = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  const name = overrides.customIcons[0].name;
  const e = index[name];
  if (!e) {
    error(
      "workers/assets/custom-icons.mjs",
      `own icon "${name}" didn't bake into the sprite – a layer asking for it ` +
        `stays without an image and MapLibre says nothing.`
    );
  } else {
    if (e.sdf) {
      error("workers/assets/custom-icons.mjs",
        `own icon "${name}" is marked \`sdf\` – it's a finished colour image.`);
    }
    if (e.pixelRatio !== 2) {
      error("workers/assets/custom-icons.mjs",
        `own icon "${name}" has pixelRatio ${e.pixelRatio} in the index, but was uploaded @2x ` +
        `– it would be twice as big in the map.`);
    }
  }
  // the original icons mustn't get lost
  if (!index.test_11) {
    error("workers/lib/sprite-bake.mjs",
      "baking own icons dropped an icon the sprite already had.");
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

// 2. the style lets an own icon through before the sprite has it
{
  const name = overrides.customIcons[0].name;
  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    // the sprite lacks the icon on purpose – the state after adding it in the panel
    icons: ["mountain_11"],
    iconSet: "osm-liberty",
    overrides: { ...overrides, layers: { "poi-major": { icon: name } } }
  });
  const l = style.layers.find((x) => x.id === "poi-major");
  if (!l || (l.layout || {})["icon-image"] !== name) {
    error(
      "poc/web/themes.js",
      `after picking own icon "${name}" the layer kept ` +
        `"${(l?.layout || {})["icon-image"]}" – the freshly added icon is quietly dropped.`
    );
  }
}

// 3. someone really downloads an own set and writes it into the manifest
{
  const id = overrides.iconSets[0].id;
  if (!allIconSources(overrides).some((s) => s.id === id)) {
    error("poc/web/icon-sources.js", `own set "${id}" isn't in \`allIconSources\`.`);
  }
  for (const [file, what] of [
    ["workers/assets/icons.sh", "downloading sets"],
    ["workers/deploy/site.sh", "the manifest's set list"]
  ]) {
    const text = readFileSync(join(ROOT, file), "utf8");
    if (!text.includes("allIconSources")) {
      error(
        file,
        `${what} takes only the repository's sets (\`ICON_SOURCES\`). An own set ` +
          `from the overrides can then be added and picked, but its sprite is never ` +
          `made – and the map stays without icons.`
      );
    }
  }
}

// 4. `layout` lands only on a symbol layer
{
  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    icons: ["mountain_11"],
    overrides: normalizeOverrides({
      // `road-path` is a line – `icon-size` on it breaks the whole style
      layers: { "road-path": { layout: { "icon-size": 2 } } }
    }).overrides
  });
  const l = style.layers.find((x) => x.id === "road-path");
  if (l && (l.layout || {})["icon-size"] !== undefined) {
    error(
      "poc/web/themes.js",
      "a `layout` override landed on a line layer – MapLibre would refuse the " +
        "whole style and the map wouldn't load."
    );
  }
}

// 5. an icon picked for a POI category reaches the map; an empty name is a choice
{
  const name = overrides.customIcons[0].name;
  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    featuresUrl: "pmtiles://x/f.pmtiles",
    // points have their own source – without it there's no `feature-point` layer
    pointsUrl: "pmtiles://x/p.pmtiles",
    roadsUrl: "pmtiles://x/r.pmtiles",
    // the sprite lacks the own icon on purpose – the state after uploading it
    icons: ["mountain_11", "restaurant_11"],
    iconSet: "osm-liberty",
    overrides: normalizeOverrides({
      ...overrides,
      poi: { hidden: [], icons: { restaurant: name, spring: "", cave: "missing_11" } }
    }).overrides
  });
  const expr = (id) =>
    JSON.stringify((style.layers.find((l) => l.id === id)?.layout || {})["icon-image"] || null);

  for (const id of ["poi-major", "poi-all", "feature-point"]) {
    const text = expr(id);
    if (!text.includes(JSON.stringify(name))) {
      error(
        "poc/web/themes.js",
        `layer \`${id}\` didn't let through own icon "${name}" picked for a category – ` +
          `the panel can pick it, but the map won't draw it.`
      );
    }
    if (text.includes("missing_11")) {
      error(
        "poc/web/themes.js",
        `layer \`${id}\` asks for icon "missing_11", which the sprite lacks – MapLibre ` +
          `quietly skips it and the category stays without an image.`
      );
    }
    if (!text.includes('"spring"')) {
      error(
        "poc/web/themes.js",
        `layer \`${id}\` dropped the “no icon” choice for category spring. An empty ` +
          `name is an answer, not a missing value.`
      );
    }
  }
  // hidden categories apply to own points too – the panel has one list
  const hidden = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    featuresUrl: "pmtiles://x/f.pmtiles",
    pointsUrl: "pmtiles://x/p.pmtiles",
    roadsUrl: "pmtiles://x/r.pmtiles",
    icons: ["mountain_11"],
    overrides: normalizeOverrides({ poi: { hidden: ["spring"] } }).overrides
  });
  const pointFilter = JSON.stringify(
    hidden.layers.find((l) => l.id === "feature-point")?.filter || null
  );
  if (!pointFilter.includes('"spring"')) {
    error(
      "poc/web/themes.js",
      "`feature-point` ignores hidden categories – unticking springs in the panel " +
        "would do nothing and nobody would say why."
    );
  }
}

// 6. an own image as a pattern – baked by custom-icons.mjs, not the pattern rasteriser
{
  const name = overrides.customIcons[0].name;
  const valid = normalizeOverrides({
    ...overrides,
    layers: { "landcover-wood": { pattern: { image: name, opacity: 0.8 } } }
  });
  if (valid.problems.length) {
    error(
      "poc/web/themes.js",
      `normalizeOverrides refused an own image as a pattern: ${valid.problems[0]}`
    );
  }
  const invalid = normalizeOverrides({
    ...overrides,
    layers: { "landcover-wood": { pattern: { image: "own:does-not-exist" } } }
  });
  if (invalid.overrides.layers["landcover-wood"]?.pattern || !invalid.problems.length) {
    error(
      "poc/web/themes.js",
      "a pattern from an image that isn't among the overrides' own icons passed " +
        "normalisation. Nobody would bake it into the sprite and the area would " +
        "stay without a pattern – on a valid style."
    );
  }

  const style = buildStyle({
    theme: Object.keys(THEMES)[0],
    tilesUrl: "pmtiles://x/t.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/{fontstack}/{range}.pbf",
    // the sprite lacks it on purpose – the state right after uploading
    icons: ["mountain_11"],
    iconSet: "osm-liberty",
    overrides: valid.overrides
  });
  const layer = style.layers.find((l) => l.id === "landcover-wood__pattern");
  if (!layer || (layer.paint || {})["fill-pattern"] !== name) {
    error(
      "poc/web/themes.js",
      `the layer with an own-image pattern has \`fill-pattern: ` +
        `${JSON.stringify((layer?.paint || {})["fill-pattern"])}\`, expected ` +
        `"${name}" – the freshly uploaded image is quietly dropped.`
    );
  }
  const drawn = collectPatternNames(style);
  if (drawn.includes(name)) {
    error(
      "poc/web/patterns.js",
      `\`collectPatternNames\` returned own image "${name}" among drawn patterns ` +
        `– \`workers/styles/patterns.mjs\` would draw hatching over it in the atlas ` +
        `and overwrite the image \`custom-icons.mjs\` put there.`
    );
  }
}

// 7. one-way arrows exist in every set
{
  const all = arrowImages();
  if (!all.includes(DEFAULT_ARROW_IMAGE)) {
    error("poc/web/arrows.js",
      `the style asks for arrow "${DEFAULT_ARROW_IMAGE}", but it isn't among the ` +
      `baked ones (${all.join(", ")}) – the one-way layer would be quietly skipped.`);
  }
  for (const set of ICON_SOURCE_IDS) {
    // a set without its own `arrow` is why we draw them ourselves
    const style = buildStyle({
      theme: Object.keys(THEMES)[0],
      tilesUrl: "pmtiles://x/t.pmtiles",
      spriteUrl: "https://x/sprite",
      // an array, not a Set: `hasIcon` asks for `.length` and `.includes`
      icons: all,
      sdfIcons: true,
      overrides: { ...overrides, icons: set }
    });
    if (!style.layers.some((l) => l.id === "road-oneway")) {
      error("poc/web/icon-sources.js",
        `with set "${set}" the style has no "road-oneway" layer – one-way roads ` +
        `would have no arrows and the panel nothing to set.`);
    }
  }
}

console.log(
  `icons: ${bad} errors (${LAYOUT_PROP_IDS.length} layout properties, ` +
    `${overrides.customIcons.length} own icons, ${overrides.iconSets.length} own sets, ` +
    `${arrowImages().length} arrows × ${ICON_SOURCE_IDS.length} sets)`
);
process.exit(bad ? 1 : 0);
