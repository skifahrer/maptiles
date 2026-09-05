#!/usr/bin/env node
/**
 * Dopečie do spritu obrázky opakujúcich sa vzorov, ktoré používa hotový štýl.
 *
 * Vzory sa v developer móde nastavujú predpisom, ktorý je zároveň názvom
 * obrázka (`pat:hatch:3a5a34:16:12`). V prehliadači si ich mapa dokreslí sama,
 * ale statický `style.json` pre iOS musí mať obrázky priamo v sprite.
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
    "Použitie: node workers/styles/patterns.mjs --sprite=<base> --styles=<dir>"
  );
  process.exit(2);
}

// ---------- ktoré vzory štýly vôbec používajú ----------
const names = new Set();
if (existsSync(stylesDir)) {
  for (const file of readdirSync(stylesDir).filter((f) => f.endsWith(".json"))) {
    try {
      for (const n of collectPatternNames(JSON.parse(readFileSync(join(stylesDir, file), "utf8")))) {
        names.add(n);
      }
    } catch (err) {
      console.warn(`⚠ ${file} sa nepodarilo prečítať: ${err.message}`);
    }
  }
}

if (!names.size) {
  console.log("Štýly nepoužívajú žiadne vzory – sprite zostáva bez zmeny.");
  process.exit(0);
}
console.log(`Vzory v štýloch (${names.size}): ${[...names].join(", ")}`);

const ok = bakeIntoSprite({
  spriteBase,
  co: "vzorov",
  // Naše sú všetky mená, ktoré sú predpisom vzoru – starý vzor sa zahodí
  // a nakreslí znova z toho, čo je v štýloch teraz.
  mine: (name) => Boolean(parsePatternName(name)),
  make: (pixelRatio) =>
    [...names].map((name) => ({
      name,
      image: renderPattern(parsePatternName(name), pixelRatio)
    }))
});

if (!ok) {
  console.error(`::error::Sprite ${spriteBase}.json/.png neexistuje`);
  process.exit(1);
}
