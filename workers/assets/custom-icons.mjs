#!/usr/bin/env node
/**
 * Dopečie do spritu vlastné ikony z úprav developer módu.
 *
 * Vlastná ikona leží priamo v `poc/web/style-overrides.json` ako PNG v `data:`
 * adrese, nie ako odkaz na cudzí server – takže ju mapa má aj bez internetu
 * a tento skript ju len dekóduje a vloží do atlasu (SVG rasterizoval
 * prehliadač už pri nahratí).
 *
 * Beží po `sprite.mjs`, `shields.mjs` a `marks.mjs`; preskladanie robí
 * `lib/sprite-bake.mjs`.
 *
 * Bez `sdf`: je to hotový farebný obrázok, takže `icon-color` na ňom neplatí –
 * kto chce inú farbu, nahrá iný obrázok.
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
  console.error("Použitie: node workers/assets/custom-icons.mjs --sprite=<base>");
  process.exit(2);
}
const overridesPath = args.overrides || "poc/web/style-overrides.json";

let raw = {};
if (existsSync(overridesPath)) {
  try {
    raw = JSON.parse(readFileSync(overridesPath, "utf8"));
  } catch (err) {
    console.error(`::error::${overridesPath} sa nedá prečítať: ${err.message}`);
    process.exit(1);
  }
}
const { overrides, problems } = normalizeOverrides(raw);
for (const p of problems) console.log(`::warning::${p}`);

const IKONY = [];
for (const ikona of overrides.customIcons) {
  const base64 = ikona.png.slice(ikona.png.indexOf(",") + 1);
  let img;
  try {
    img = decodePng(Buffer.from(base64, "base64"));
  } catch (err) {
    // Nedekódovateľná ikona nesmie zhodiť sprite – ale ani ticho zmiznúť:
    // vrstva, ktorá ju používa, ostane bez obrázka a to je vidieť len v mape.
    console.log(`::warning::Vlastná ikona "${ikona.name}" nie je čitateľné PNG (${err.message}) – vynechávam.`);
    continue;
  }
  IKONY.push({ name: ikona.name, image: img, pixelRatio: ikona.pixelRatio || 1 });
}

if (!IKONY.length) {
  console.log("Žiadne vlastné ikony – sprite zostáva bez zmeny.");
  process.exit(0);
}

const ok = bakeIntoSprite({
  spriteBase,
  co: "vlastných ikon",
  mine: (name) => name.startsWith(CUSTOM_ICON_PREFIX),
  make: () =>
    IKONY.map(({ name, image, pixelRatio }) => ({
      name,
      image,
      // `pixelRatio` obrázka je jeho vlastný – prehliadač ho ukladá v @2x,
      // takže by sa pri ratio 1 kreslil dvojnásobne veľký.
      entry: { pixelRatio }
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png neexistuje`);
  process.exit(1);
}
console.log(`Vlastné ikony: ${IKONY.map((i) => i.name).join(", ")}`);
