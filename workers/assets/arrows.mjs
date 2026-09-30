#!/usr/bin/env node
/**
 * Bakes one-way arrows into the sprite as SDF, so every icon set has them (`poc/web/arrows.js`).
 *
 *   node workers/assets/arrows.mjs --sprite=_site/sprites/osm-liberty
 */
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { sdfFromShape, SDF_RADIUS } from "../lib/sdf.mjs";
import {
  ARROW_PREFIX, ARROW_SHAPES, ARROW_W, ARROW_H, ARROW_PAD, arrowImage
} from "../../poc/web/arrows.js";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
if (!spriteBase) {
  console.error("Usage: node workers/assets/arrows.mjs --sprite=<base>");
  process.exit(2);
}

/** SDF as RGBA: `icon-color` gives the colour, alpha holds the edge distance. */
function image(shape, r) {
  const sdf = sdfFromShape(
    shape.draw,
    Math.round(ARROW_W * r),
    Math.round(ARROW_H * r),
    Math.round(ARROW_PAD * r),
    SDF_RADIUS * r
  );
  const data = new Uint8Array(sdf.width * sdf.height * 4);
  for (let i = 0; i < sdf.data.length; i += 1) {
    data[i * 4] = 255;
    data[i * 4 + 1] = 255;
    data[i * 4 + 2] = 255;
    data[i * 4 + 3] = sdf.data[i];
  }
  return { width: sdf.width, height: sdf.height, data };
}

const ok = bakeIntoSprite({
  spriteBase,
  what: "one-way arrows",
  // redrawn, so a cached sprite gains no copies
  mine: (name) => name.startsWith(ARROW_PREFIX),
  make: (pixelRatio) =>
    ARROW_SHAPES.map((shape) => ({
      name: arrowImage(shape.id),
      image: image(shape, pixelRatio),
      entry: { sdf: true }
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png doesn't exist`);
  process.exit(1);
}
