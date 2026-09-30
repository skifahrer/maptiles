#!/usr/bin/env node
/**
 * Bakes the repeating patterns a finished style uses into the sprite (iOS has no runtime drawing).
 *
 *   node workers/styles/patterns.mjs \
 *        --sprite=_site/sprites/osm-liberty-sdf --styles=_site/styles
 */
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { collectPatternNames, parsePatternName, renderPattern } from "../../poc/web/patterns.js";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
const stylesDir = args.styles;
if (!spriteBase || !stylesDir) {
  console.error(
    "Usage: node workers/styles/patterns.mjs --sprite=<base> --styles=<dir>"
  );
  process.exit(2);
}

// which patterns the styles use
const names = new Set();
if (existsSync(stylesDir)) {
  for (const file of readdirSync(stylesDir).filter((f) => f.endsWith(".json"))) {
    try {
      for (const n of collectPatternNames(JSON.parse(readFileSync(join(stylesDir, file), "utf8")))) {
        names.add(n);
      }
    } catch (err) {
      console.warn(`⚠ ${file} couldn't be read: ${err.message}`);
    }
  }
}

if (!names.size) {
  console.log("The styles use no patterns – the sprite stays unchanged.");
  process.exit(0);
}
console.log(`Patterns in the styles (${names.size}): ${[...names].join(", ")}`);

const ok = bakeIntoSprite({
  spriteBase,
  what: "patterns",
  // every pattern recipe name is ours, redrawn from the current styles
  mine: (name) => Boolean(parsePatternName(name)),
  make: (pixelRatio) =>
    [...names].map((name) => ({
      name,
      image: renderPattern(parsePatternName(name), pixelRatio)
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png doesn't exist`);
  process.exit(1);
}
