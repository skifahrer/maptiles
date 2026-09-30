#!/usr/bin/env node
/**
 * Bakes road-number shields by NETWORK ("D1" on red, "E 75" on green) into the sprite.
 *
 *   node workers/assets/route-shields.mjs --sprite=_site/sprites/osm-liberty
 */
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { routeShieldRecipes, renderRouteShield } from "../../poc/web/route-shields.js";

const RECIPES = routeShieldRecipes();
const NAMES = new Set(RECIPES.map((r) => r.name));

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
if (!spriteBase) {
  console.error("Usage: node workers/assets/route-shields.mjs --sprite=<base>");
  process.exit(2);
}

const ok = bakeIntoSprite({
  spriteBase,
  what: "network shields",
  mine: (name) => NAMES.has(name),
  make: (pixelRatio) =>
    RECIPES.map(({ name, def }) => {
      const img = renderRouteShield(def, pixelRatio);
      const entry = {};
      // a hexagon's point has no straight part, so the whole image scales
      if (img.stretchX) Object.assign(entry, {
        stretchX: img.stretchX, stretchY: img.stretchY, content: img.content
      });
      return { name, image: img, entry };
    })
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png doesn't exist`);
  process.exit(1);
}
