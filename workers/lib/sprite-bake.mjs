/**
 * Dopečenie vlastných obrázkov do hotového spritu.
 *
 * Sprite vyrobí `assets/sprite.mjs` z cudzej sady. Štítky ciest, značky trás
 * a vzory výplní si kreslíme sami a v žiadnej sade byť nemôžu; všetky tri
 * rozoberú atlas, pridajú svoje a preskladajú ho späť. Kým to bol trikrát ten
 * istý kus kódu, líšil sa – a rozdiel bol tichý: v jednej kópii sa
 * neprenášali `stretchX`/`stretchY`/`content`, takže z dlhého čísla na štítku
 * vyšla kapsula.
 *
 * Volajúci povie dve veci: ktoré mená v atlase sú jeho (tie sa zahodia
 * a nakreslia znova, nech pri behu nad spritom z cache nepribúdajú kópie)
 * a čo pridať.
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { decodePng, encodePng, packShelves } from "./png.mjs";

/**
 * @param {object} opts
 * @param {string} opts.spriteBase  cesta bez prípony (`_site/sprites/osm-liberty`)
 * @param {(name: string) => boolean} opts.mine  patrí toto meno v atlase nám?
 * @param {(pixelRatio: number) => Array<{name:string,
 *          image:{width:number,height:number,data:Uint8Array},
 *          entry?:object}>} opts.make  čo pridať do varianty s týmto ratiom
 * @param {string} [opts.co]  čo sa pečie – ide do hlášky („štítkov ciest")
 * @returns {boolean} podarilo sa aspoň variant 1× (bez neho je to chyba)
 */
export function bakeIntoSprite({ spriteBase, mine, make, co = "obrázkov" }) {
  const ok = addTo(spriteBase, mine, make, co, "", 1);
  if (!ok) return false;
  // @2x je voliteľné – bez neho je mapa na retine len mäkšia.
  addTo(spriteBase, mine, make, co, "@2x", 2);
  return true;
}

function addTo(spriteBase, mine, make, co, suffix, pixelRatio) {
  const jsonPath = `${spriteBase}${suffix}.json`;
  const pngPath = `${spriteBase}${suffix}.png`;
  if (!existsSync(jsonPath) || !existsSync(pngPath)) return false;

  const index = JSON.parse(readFileSync(jsonPath, "utf8"));
  const atlas = decodePng(readFileSync(pngPath));

  // Existujúce obrázky sa z atlasu vyberú, aby sa dal preskladať aj s novými.
  const boxes = [];
  for (const [name, e] of Object.entries(index)) {
    if (mine(name)) continue;
    const data = Buffer.alloc(e.width * e.height * 4);
    for (let y = 0; y < e.height; y++) {
      for (let x = 0; x < e.width; x++) {
        const s = ((e.y + y) * atlas.width + e.x + x) * 4;
        atlas.data.copy(data, (y * e.width + x) * 4, s, s + 4);
      }
    }
    boxes.push({ name, width: e.width, height: e.height, data, entry: e });
  }

  const nove = make(pixelRatio);
  for (const { name, image, entry } of nove) {
    boxes.push({
      name,
      width: image.width,
      height: image.height,
      data: Buffer.from(image.data.buffer, image.data.byteOffset, image.data.length),
      entry: { pixelRatio, ...(entry || {}) }
    });
  }

  const packed = packShelves(boxes, suffix ? 1024 : 512);
  const out = Buffer.alloc(packed.width * packed.height * 4);
  const outIndex = {};
  for (const box of boxes) {
    for (let y = 0; y < box.height; y++) {
      box.data.copy(
        out,
        ((box.y + y) * packed.width + box.x) * 4,
        y * box.width * 4,
        (y + 1) * box.width * 4
      );
    }
    outIndex[box.name] = {
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      pixelRatio: box.entry.pixelRatio || 1,
      ...(box.entry.sdf ? { sdf: true } : {}),
      // ROZŤAHOVACIE PÁSMA SA MUSIA PRENIESŤ. Preskladanie atlasu mení len to,
      // KDE obrázok leží – čo o sebe hovorí, ostáva jeho. Štítok cesty
      // (`workers/assets/shields.mjs`) sa bez `stretchX`/`stretchY`/`content`
      // natiahne celý aj s rohmi a z obdĺžnika je pri dlhom čísle rozmazaná
      // kapsula; nič pri tom nespadne, lebo štýl aj sprite sú ďalej platné.
      ...(box.entry.stretchX ? { stretchX: box.entry.stretchX } : {}),
      ...(box.entry.stretchY ? { stretchY: box.entry.stretchY } : {}),
      ...(box.entry.content ? { content: box.entry.content } : {})
    };
  }

  writeFileSync(pngPath, encodePng({ ...packed, data: out }));
  writeFileSync(jsonPath, JSON.stringify(outIndex));
  console.log(
    `✓ ${jsonPath}: ${boxes.length} obrázkov (z toho ${nove.length} ${co}), ` +
      `atlas ${packed.width}×${packed.height}`
  );
  return true;
}
