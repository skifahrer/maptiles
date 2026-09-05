#!/usr/bin/env node
/**
 * Dopečie do spritu turistické a cyklistické značky – to, čo je namaľované na
 * strome: biely alebo žltý štvorec s farebným pásom, tvarové značky a bicykel.
 *
 * Beží po `assets/sprite.mjs` a `shields.mjs`, nad hotovým atlasom;
 * preskladanie robí `lib/sprite-bake.mjs`.
 *
 * Čo sa pečie, hovorí `poc/web/marks.js`: dvojice podklad × farba krát tvary.
 * Meno obrázka skladá aj štýl, ale výrazom nad dátami, takže chýbajúci obrázok
 * sa v mape ticho nenakreslí – stráži to `workers/lint/marks.mjs`.
 *
 * Keď sa nedopečú, mapa nespadne ani nestratí trasy: štýl vtedy kreslí pozdĺž
 * trasy ikonku zo sady.
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
  console.error("Použitie: node workers/assets/marks.mjs --sprite=<base>");
  process.exit(2);
}

const ZNACKY = markImages();

const ok = bakeIntoSprite({
  spriteBase,
  co: "značiek trás",
  // Naše sú všetky mená s predponou `mark-`. Zahodia sa a nakreslia znova,
  // aby pri behu nad spritom z cache nepribúdali kópie.
  mine: (name) => name.startsWith(MARK_PREFIX),
  make: (pixelRatio) =>
    ZNACKY.map(({ name, bg, fg, shape }) => ({
      name,
      // BEZ `sdf` a bez rozťahovacích pásem: značka je hotový farebný obrázok
      // (podklad, pás a lem sú tri farby naraz) a nikdy sa nenaťahuje – je to
      // štvorec, nie podklad pod text.
      image: renderMark(shape, MARK_COLOURS[bg], MARK_COLOURS[fg], pixelRatio)
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png neexistuje`);
  process.exit(1);
}
