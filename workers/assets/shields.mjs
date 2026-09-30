#!/usr/bin/env node
/**
 * Bakes stretchable road-number shield bases ("D1") into the sprite; shapes in `poc/web/shields.js`.
 *
 *   node workers/assets/shields.mjs --sprite=_site/sprites/osm-liberty
 */
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { SHIELD_SHAPES, renderShield } from "../../poc/web/shields.js";
import { THEMES, SHIELD_DEFS } from "../../poc/web/themes.js";

/**
 * Shield names baked here: shape × road class × theme – coloured images, not SDF.
 * Every shape is baked, since developer mode switches it without a sprite rebuild.
 */
function shields() {
  const out = [];
  for (const shape of SHIELD_SHAPES) {
    for (const [id, , , colorKey, , , , borderKey] of SHIELD_DEFS) {
      for (const [themeKey, theme] of Object.entries(THEMES)) {
        out.push({
          name: `${shape.id}-${id}-${themeKey}`,
          shape,
          colors: { field: theme[colorKey], ring: theme[borderKey] }
        });
      }
    }
  }
  return out;
}

const SHIELDS = shields();
const NAMES = new Set(SHIELDS.map((s) => s.name));

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
if (!spriteBase) {
  console.error("Usage: node workers/assets/shields.mjs --sprite=<base>");
  process.exit(2);
}

const ok = bakeIntoSprite({
  spriteBase,
  what: "road shields",
  mine: (name) => NAMES.has(name),
  make: (pixelRatio) =>
    SHIELDS.map((st) => {
      const img = renderShield(st.shape, st.colors, pixelRatio);
      return {
        name: st.name,
        image: img,
        // no `sdf`, the image is coloured; stretch bands keep long numbers rectangular
        entry: { stretchX: img.stretchX, stretchY: img.stretchY, content: img.content }
      };
    })
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png doesn't exist`);
  process.exit(1);
}
