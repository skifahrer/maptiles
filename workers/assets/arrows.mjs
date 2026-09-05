#!/usr/bin/env node
/**
 * Dopečie do spritu šípky jednosmeriek – vlastné, aby boli v každej sade
 * ikoniek (rozpis v `poc/web/arrows.js`).
 *
 * Beží po `assets/sprite.mjs`, nad hotovým atlasom; preskladanie robí
 * `lib/sprite-bake.mjs`.
 *
 * Sú to SDF obrázky: šípka je jednofarebný tvar a tá farba patrí do palety
 * témy (`onewayIcon`).
 *
 * Keď sa nedopečú, mapa nespadne – vrstva `road-oneway` sa vynechá tak ako
 * pri sade bez `arrow`. Je to teda varovanie, na ktoré má oči
 * `workers/lint/icons.mjs`.
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
  console.error("Použitie: node workers/assets/arrows.mjs --sprite=<base>");
  process.exit(2);
}

/** SDF ako RGBA: farbu dá `icon-color`, v alfe je vzdialenosť od hrany. */
function obrazok(shape, r) {
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
  co: "šípok jednosmeriek",
  // Naše sú všetky mená s predponou `arrow-`. Zahodia sa a nakreslia znova,
  // aby pri behu nad spritom z cache nepribúdali kópie.
  mine: (name) => name.startsWith(ARROW_PREFIX),
  make: (pixelRatio) =>
    ARROW_SHAPES.map((shape) => ({
      name: arrowImage(shape.id),
      image: obrazok(shape, pixelRatio),
      entry: { sdf: true }
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png neexistuje`);
  process.exit(1);
}
