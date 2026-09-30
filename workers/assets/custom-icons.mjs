#!/usr/bin/env node
/**
 * Bakes custom icons from developer-mode overrides (PNG `data:` URLs) into the sprite, not SDF.
 *
 *   node workers/assets/custom-icons.mjs --sprite=_site/sprites/osm-liberty
 */
import { readFileSync, existsSync } from "node:fs";
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { decodePng } from "../lib/png.mjs";
import { normalizeOverrides, CUSTOM_ICON_PREFIX } from "../../poc/web/themes.js";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
if (!spriteBase) {
  console.error("Usage: node workers/assets/custom-icons.mjs --sprite=<base>");
  process.exit(2);
}
const overridesPath = args.overrides || "poc/web/style-overrides.json";

let raw = {};
if (existsSync(overridesPath)) {
  try {
    raw = JSON.parse(readFileSync(overridesPath, "utf8"));
  } catch (err) {
    console.error(`::error::${overridesPath} can't be read: ${err.message}`);
    process.exit(1);
  }
}
const { overrides, problems } = normalizeOverrides(raw);
for (const p of problems) console.log(`::warning::${p}`);

const ICONS = [];
for (const icon of overrides.customIcons) {
  const base64 = icon.png.slice(icon.png.indexOf(",") + 1);
  let img;
  try {
    img = decodePng(Buffer.from(base64, "base64"));
  } catch (err) {
    // mustn't fail the sprite, nor vanish silently
    console.log(`::warning::Custom icon "${icon.name}" isn't a readable PNG (${err.message}) – skipping.`);
    continue;
  }
  ICONS.push({ name: icon.name, image: img, pixelRatio: icon.pixelRatio || 1 });
}

if (!ICONS.length) {
  console.log("No custom icons – the sprite stays unchanged.");
  process.exit(0);
}

const ok = bakeIntoSprite({
  spriteBase,
  what: "custom icons",
  mine: (name) => name.startsWith(CUSTOM_ICON_PREFIX),
  make: () =>
    ICONS.map(({ name, image, pixelRatio }) => ({
      name,
      image,
      // the browser stores it at @2x, so it keeps its own ratio
      entry: { pixelRatio }
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png doesn't exist`);
  process.exit(1);
}
console.log(`Custom icons: ${ICONS.map((i) => i.name).join(", ")}`);
