import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { draw, color, rect, circle } from "../lib/draw.mjs";
import { encodePng } from "../lib/png.mjs";

const SPRITE = fileURLToPath(new URL("../assets/sprite.mjs", import.meta.url));

function fixtureSprite(dir, ratio) {
  const names = ["bus", "cafe", "peak", "parking"];
  const s = 17 * ratio;
  const atlas = { width: s * names.length, height: s };
  const data = Buffer.alloc(atlas.width * atlas.height * 4);
  const index = {};
  names.forEach((name, i) => {
    const icon = draw(17, 17, [
      { fill: circle(8.5, 8.5, 8), color: color("#ffffff") },
      { fill: rect(4 + i, 4, 6, 6 + i), color: color("#203040") }
    ], ratio);
    for (let y = 0; y < s; y++) {
      for (let x = 0; x < s; x++) {
        const from = (y * s + x) * 4;
        data.set(icon.data.subarray(from, from + 4), (y * atlas.width + i * s + x) * 4);
      }
    }
    index[name] = { x: i * s, y: 0, width: s, height: s, pixelRatio: ratio };
  });
  const suffix = ratio === 1 ? "" : `@${ratio}x`;
  writeFileSync(join(dir, `plain${suffix}.png`), encodePng({ ...atlas, data }));
  writeFileSync(join(dir, `plain${suffix}.json`), JSON.stringify(index));
  return names;
}

/** A four-icon plain sprite in `dir`, turned into `sdf.json`/`sdf.png` by sprite.mjs. */
export function makeSdfSprite(dir) {
  const names = fixtureSprite(dir, 1);
  fixtureSprite(dir, 2);
  execFileSync(process.execPath, [SPRITE, `--in=${join(dir, "plain")}`, `--out=${join(dir, "sdf")}`],
    { stdio: "pipe" });
  return names;
}
