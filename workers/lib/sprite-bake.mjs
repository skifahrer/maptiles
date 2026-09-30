/**
 * Bakes our own images into a finished sprite; `mine` names are redrawn, not duplicated.
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { decodePng, encodePng, packShelves } from "./png.mjs";

/**
 * @param {object} opts
 * @param {string} opts.spriteBase  path without extension (`_site/sprites/osm-liberty`)
 * @param {(name: string) => boolean} opts.mine  is this atlas name ours?
 * @param {(pixelRatio: number) => Array<{name:string,
 *          image:{width:number,height:number,data:Uint8Array},
 *          entry?:object}>} opts.make  what to add to the variant with this ratio
 * @param {string} [opts.what]  what is baked – goes into the message ("road shields")
 * @returns {boolean} at least the 1× variant worked (without it, an error)
 */
export function bakeIntoSprite({ spriteBase, mine, make, what = "images" }) {
  const ok = addTo(spriteBase, mine, make, what, "", 1);
  if (!ok) return false;
  // @2x is optional – without it the map is only softer on retina
  addTo(spriteBase, mine, make, what, "@2x", 2);
  return true;
}

function addTo(spriteBase, mine, make, what, suffix, pixelRatio) {
  const jsonPath = `${spriteBase}${suffix}.json`;
  const pngPath = `${spriteBase}${suffix}.png`;
  if (!existsSync(jsonPath) || !existsSync(pngPath)) return false;

  const index = JSON.parse(readFileSync(jsonPath, "utf8"));
  const atlas = decodePng(readFileSync(pngPath));

  // existing images are taken out, so the atlas can be repacked with the new ones
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

  const added = make(pixelRatio);
  for (const { name, image, entry } of added) {
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
      // stretch bands must carry over, or a long shield number turns into a capsule
      ...(box.entry.stretchX ? { stretchX: box.entry.stretchX } : {}),
      ...(box.entry.stretchY ? { stretchY: box.entry.stretchY } : {}),
      ...(box.entry.content ? { content: box.entry.content } : {})
    };
  }

  writeFileSync(pngPath, encodePng({ ...packed, data: out }));
  writeFileSync(jsonPath, JSON.stringify(outIndex));
  console.log(
    `✓ ${jsonPath}: ${boxes.length} images (${added.length} of them ${what}), ` +
      `atlas ${packed.width}×${packed.height}`
  );
  return true;
}
