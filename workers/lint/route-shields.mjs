#!/usr/bin/env node
/**
 * Checks SHIELDS BY NETWORK (“D1”, “E 75”, Croatian “A1”).
 * Run by `Check · workflow lint`.
 *
 * Four quiet things – none fails anything and all show only in the map: a network
 * without an image falls back to the classic shield, a lost `stretchX` makes a long
 * number a capsule, `sdf: true` makes it a blurry cross and a missing `match`
 * fallback leaves an unknown network without a background.
 *
 *   node workers/lint/route-shields.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { buildStyle, SHIELD_DEFS, EURO_NETWORK, THEMES } from "../../poc/web/themes.js";
import {
  ROUTE_SHIELD_NETWORKS,
  routeShieldDef,
  routeShieldName,
  routeShieldRecipes
} from "../../poc/web/route-shields.js";
import { EXTRA_SHIELDS } from "../../poc/web/route-shield-defs.js";
import { outline, blankWidth, stretchable } from "../../poc/web/route-shield-shapes.js";
import { AMERICANA_NETWORKS } from "../../poc/web/route-shield-americana.js";
import { encodePng } from "../lib/png.mjs";

let bad = 0;
const error = (file, text) => {
  console.log(`::error file=${file}::${text}`);
  bad += 1;
};

// 1. every recipe can be drawn: shape, colours and a closing outline
const HEX = /^#[0-9a-f]{6}$/i;
for (const { name, def } of routeShieldRecipes()) {
  for (const key of ["fill", "text"]) {
    if (!HEX.test(def[key] || "")) {
      error("poc/web/route-shield-americana.js",
        `shield "${name}" has \`${key}\` = "${def[key]}", which isn't #rrggbb ` +
        `– the importer only knows the names "white" and "black".`);
    }
  }
  if (def.stroke && !HEX.test(def.stroke)) {
    error("poc/web/route-shield-americana.js",
      `shield "${name}" has \`stroke\` = "${def.stroke}", which isn't #rrggbb.`);
  }
  const pts = outline(def, 1);
  if (!pts || pts.length < 3) {
    error("poc/web/route-shield-shapes.js",
      `shape "${def.shape}" doesn't draw – shield "${name}" would stay empty.`);
    continue;
  }
  const width = blankWidth(def);
  const outside = pts.some(([x, y]) => x < -0.01 || y < -0.01 || x > width + 0.01);
  if (outside) {
    error("poc/web/route-shield-shapes.js",
      `the outline of shield "${name}" (shape ${def.shape}) leaves the image ` +
      `– it would be clipped in the map.`);
  }
}

// 1b. every network points at an existing recipe
for (const network of ROUTE_SHIELD_NETWORKS) {
  if (!routeShieldDef(network)) {
    error("poc/web/route-shield-defs.js",
      `network "${network}" has no recipe – the style would ask for a missing image.`);
  }
}

// 1c. own networks don't quietly override the Americana table
for (const network of Object.keys(EXTRA_SHIELDS)) {
  if (AMERICANA_NETWORKS[network] !== undefined) {
    error("poc/web/route-shield-defs.js",
      `network "${network}" is in the generated table too – ours quietly overrides it. ` +
      `Either drop it from \`EXTRA_SHIELDS\` or justify it with a note.`);
  }
}

// 2. images really bake and survive sprite repacking
const dir = mkdtempSync(join(tmpdir(), "route-shields-lint-"));
try {
  const base = join(dir, "sprite");
  writeFileSync(
    `${base}.png`,
    encodePng({ width: 4, height: 4, data: Buffer.alloc(4 * 4 * 4, 255) })
  );
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );
  execFileSync("node", ["workers/assets/route-shields.mjs", `--sprite=${base}`], { stdio: "pipe" });
  const index = JSON.parse(readFileSync(`${base}.json`, "utf8"));

  for (const network of ROUTE_SHIELD_NETWORKS) {
    const name = routeShieldName(network);
    if (!index[name]) {
      error("workers/assets/route-shields.mjs",
        `network "${network}" asks for image "${name}", which didn't bake into ` +
        `the sprite – the style quietly draws the classic class shield.`);
    }
  }

  for (const { name, def } of routeShieldRecipes()) {
    const e = index[name];
    if (!e) continue;
    if (e.sdf) {
      error("workers/assets/route-shields.mjs",
        `shield "${name}" is marked \`sdf\` – the image is coloured, a distance ` +
        `field doesn't belong there and it becomes a blurry cross in the map.`);
    }
    // a pointed shape has no straight edge part, so it scales whole
    if (!stretchable(def)) continue;
    for (const key of ["stretchX", "stretchY", "content"]) {
      if (!e[key]) {
        error("workers/assets/route-shields.mjs",
          `shield "${name}" has no \`${key}\` in the index – without stretch ` +
          `bands the image scales with its corners and a long number becomes a capsule.`);
      }
    }
  }

  // 3. fallback: `match` must end with the classic class shield
  const icons = [...Object.keys(index), "shield-motorway-svetla", "shield-primary-svetla",
                 "shield-secondary-svetla", "shield-euro-svetla"];
  const style = buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://t",
    spriteUrl: "http://s",
    glyphsUrl: "g/{fontstack}/{range}",
    icons
  });
  // the last `match` branch is the fallback – the app looks for it too
  const fallback = (value) => {
    if (!Array.isArray(value) || value[0] !== "let") return value;
    const body = value[value.length - 1];
    if (!Array.isArray(body) || body[0] !== "match") return null;
    return body[body.length - 1];
  };

  for (const [id, , , , , , textKey] of SHIELD_DEFS) {
    const layer = style.layers.find((l) => l.id === `road-shield-${id}`);
    if (!layer) {
      error("poc/web/themes.js", `layer "road-shield-${id}" isn't in the style.`);
      continue;
    }
    if (fallback(layer.layout["icon-image"]) !== `shield-${id}-svetla`) {
      error("poc/web/themes.js",
        `"road-shield-${id}" doesn't end its \`match\` with the classic shield as a ` +
        `fallback – a road in a network the table doesn't know would have no ` +
        `background and the app couldn't switch back.`);
    }
    if (fallback(layer.paint["text-color"]) !== THEMES.svetla[textKey]) {
      error("poc/web/themes.js",
        `"road-shield-${id}" doesn't end its \`match\` with the style's number colour as a fallback.`);
    }
  }

  // 4. shields by network off = exactly what was there before
  const off = buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://t",
    spriteUrl: "http://s",
    glyphsUrl: "g/{fontstack}/{range}",
    icons,
    overrides: { routeShields: false }
  });
  for (const [id] of SHIELD_DEFS) {
    const image = off.layers.find((l) => l.id === `road-shield-${id}`)?.layout["icon-image"];
    if (image !== `shield-${id}-svetla`) {
      error("poc/web/themes.js",
        `with shields by network off "road-shield-${id}" draws ` +
        `"${JSON.stringify(image)}" instead of the classic "shield-${id}-svetla".`);
    }
  }

  if (!routeShieldDef(EURO_NETWORK)) {
    error("poc/web/route-shield-defs.js",
      `the European road ("${EURO_NETWORK}") has no shield of its own, though its layer exists.`);
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

if (bad) {
  console.log(`::error::Shields by network: ${bad} ${bad === 1 ? "error" : "errors"}.`);
  process.exit(1);
}
console.log(`✓ Shields by network: ${ROUTE_SHIELD_NETWORKS.length} networks, ` +
  `${routeShieldRecipes().length} images, fallback in place.`);
