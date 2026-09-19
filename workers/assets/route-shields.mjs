#!/usr/bin/env node
/**
 * Dopečie do spritu štítky čísel ciest podľa SIETE („D1" na červenej,
 * „E 75" na zelenej, chorvátske „A1" v šesťuholníku).
 *
 * Beží po `assets/shields.mjs`: klasické štítky podľa triedy cesty ostávajú
 * v sprite ako záloha pre siete, ktoré tu nie sú.
 *
 *   node workers/assets/route-shields.mjs --sprite=_site/sprites/osm-liberty
 */
import { bakeIntoSprite } from "../lib/sprite-bake.mjs";
import { routeShieldRecipes, renderRouteShield } from "../../poc/web/route-shields.js";

const RECEPTY = routeShieldRecipes();
const MENA = new Set(RECEPTY.map((r) => r.name));

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

const spriteBase = args.sprite;
if (!spriteBase) {
  console.error("Použitie: node workers/assets/route-shields.mjs --sprite=<base>");
  process.exit(2);
}

const ok = bakeIntoSprite({
  spriteBase,
  co: "štítkov podľa siete",
  mine: (name) => MENA.has(name),
  make: (pixelRatio) =>
    RECEPTY.map(({ name, def }) => {
      const img = renderRouteShield(def, pixelRatio);
      const entry = {};
      // hrot šesťuholníka rovnú časť nemá, tak sa škáluje celý obrázok
      if (img.stretchX) Object.assign(entry, {
        stretchX: img.stretchX, stretchY: img.stretchY, content: img.content
      });
      return { name, image: img, entry };
    })
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png neexistuje`);
  process.exit(1);
}
