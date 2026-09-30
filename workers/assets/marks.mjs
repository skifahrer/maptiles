#!/usr/bin/env node
/**
 * Bakes hiking and cycling trail marks into the sprite; `poc/web/marks.js` says which.
 *
 *   node workers/assets/marks.mjs --sprite=_site/sprites/osm-liberty
 */
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { MARK_COLOURS, MARK_PREFIX, markImages, renderMark } from "../../poc/web/marks.js";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
if (!spriteBase) {
  console.error("Usage: node workers/assets/marks.mjs --sprite=<base>");
  process.exit(2);
}

const MARKS = markImages();

const ok = bakeIntoSprite({
  spriteBase,
  what: "trail marks",
  // redrawn, so a cached sprite gains no copies
  mine: (name) => name.startsWith(MARK_PREFIX),
  make: (pixelRatio) =>
    MARKS.map(({ name, bg, fg, shape }) => ({
      name,
      // three colours at once, and never stretched
      image: renderMark(shape, MARK_COLOURS[bg], MARK_COLOURS[fg], pixelRatio)
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png doesn't exist`);
  process.exit(1);
}
