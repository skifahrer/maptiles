/**
 * A sprite sheet with only some of its images, repacked.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { decodePng, encodePng, packShelves } from "./png.mjs";

/**
 * @param {string} from  sheet path without extension (`_site/sprites/osm-liberty`)
 * @param {string} to    where the cut sheet goes, without extension
 * @param {Set<string>} keep  image names it keeps
 * @returns {number} images in the 1× sheet, 0 when there is no source sheet
 */
export function cutSprite(from, to, keep) {
  const count = cutOne(from, to, keep, "");
  // @2x is optional – without it the map is only softer on retina
  if (count) cutOne(from, to, keep, "@2x");
  return count;
}

function cutOne(from, to, keep, suffix) {
  if (!existsSync(`${from}${suffix}.json`) || !existsSync(`${from}${suffix}.png`)) return 0;
  const index = JSON.parse(readFileSync(`${from}${suffix}.json`, "utf8"));
  const atlas = decodePng(readFileSync(`${from}${suffix}.png`));

  const boxes = [];
  for (const [name, e] of Object.entries(index)) {
    if (!keep.has(name)) continue;
    const data = Buffer.alloc(e.width * e.height * 4);
    for (let y = 0; y < e.height; y++) {
      atlas.data.copy(data, y * e.width * 4, ((e.y + y) * atlas.width + e.x) * 4,
        ((e.y + y) * atlas.width + e.x + e.width) * 4);
    }
    boxes.push({ name, width: e.width, height: e.height, data, entry: e });
  }

  const packed = packShelves(boxes, suffix ? 1024 : 512);
  const out = Buffer.alloc(packed.width * packed.height * 4);
  const outIndex = {};
  for (const box of boxes) {
    for (let y = 0; y < box.height; y++) {
      box.data.copy(out, ((box.y + y) * packed.width + box.x) * 4,
        y * box.width * 4, (y + 1) * box.width * 4);
    }
    outIndex[box.name] = { ...box.entry, x: box.x, y: box.y };
  }
  mkdirSync(dirname(to), { recursive: true });
  writeFileSync(`${to}${suffix}.png`, encodePng({ ...packed, data: out }));
  writeFileSync(`${to}${suffix}.json`, JSON.stringify(outIndex));
  return boxes.length;
}
