import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { toSdf, sdfFromShape, SDF_RADIUS } from "../lib/sdf.mjs";
import { draw, color, rect, circle } from "../lib/draw.mjs";
import { encodePng, decodePng, packShelves } from "../lib/png.mjs";
import { makeSdfSprite } from "./fixtures.mjs";

test("SDF of a filled square: inside above the edge, outside below", () => {
  const n = 16;
  const cov = new Float64Array(n * n);
  for (let y = 4; y < 12; y++) for (let x = 4; x < 12; x++) cov[y * n + x] = 1;
  const pad = 4;
  const { data, width, height } = toSdf(cov, n, n, pad, SDF_RADIUS);
  assert.equal(width, n + 2 * pad);
  assert.equal(height, n + 2 * pad);
  const at = (x, y) => data[(y + pad) * width + (x + pad)];
  const edge = 191;
  assert.ok(at(8, 8) > edge, "centre is inside");
  assert.ok(at(0, 0) < edge, "corner is outside");
  assert.ok(at(4, 8) > edge && at(3, 8) < edge, "the edge lies on the square's border");
  assert.ok(at(3, 8) > at(2, 8) && at(2, 8) > at(0, 8), "falls off towards the outside");
});

test("sdfFromShape matches its predicate", () => {
  const disc = sdfFromShape((u, v) => (u - 0.5) ** 2 + (v - 0.5) ** 2 < 0.16, 20, 20, 2);
  const mid = disc.data[12 * disc.width + 12];
  const corner = disc.data[2 * disc.width + 2];
  assert.ok(mid > 191 && corner < 191);
});

test("draw: a fill covers its polygon, a stroke its line, colours stay", () => {
  const img = draw(10, 10, [
    { fill: rect(0, 0, 5, 10), color: color("#ff0000") },
    { stroke: [[7, 0], [7, 10]], width: 2, color: color("#0000ff") }
  ], 2);
  assert.equal(img.width, 20);
  const px = (x, y) => Array.from(img.data.slice((y * img.width + x) * 4, (y * img.width + x) * 4 + 4));
  assert.deepEqual(px(4, 10), [255, 0, 0, 255]);
  assert.deepEqual(px(14, 10), [0, 0, 255, 255]);
  assert.equal(px(18, 10)[3], 0);
  assert.equal(circle(0, 0, 1, 8).length, 8);
});

test("PNG round trip", () => {
  const data = Buffer.from([255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 9, 9, 9, 9]);
  const back = decodePng(encodePng({ width: 2, height: 2, data }));
  assert.equal(back.width, 2);
  assert.deepEqual(Buffer.from(back.data), data);
});

function overlaps(a, b) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function assertPacked(boxes, atlas) {
  for (const [i, a] of boxes.entries()) {
    assert.ok(a.x >= 0 && a.y >= 0 && a.x + a.width <= atlas.width && a.y + a.height <= atlas.height,
      `${a.name ?? i} within the atlas`);
    for (const b of boxes.slice(i + 1)) assert.ok(!overlaps(a, b), `${a.name ?? i} overlaps ${b.name}`);
  }
}

test("packShelves: no overlap, everything inside", () => {
  const boxes = Array.from({ length: 40 }, (_, i) => ({ width: 5 + (i * 7) % 23, height: 4 + (i * 5) % 19 }));
  assertPacked(boxes, packShelves(boxes, 64));
});

test("sprite.mjs: the SDF index matches its packed image", () => {
  const dir = mkdtempSync(join(tmpdir(), "sprite-"));
  try {
    const names = makeSdfSprite(dir);
    for (const suffix of ["", "@2x"]) {
      const index = JSON.parse(readFileSync(join(dir, `sdf${suffix}.json`), "utf8"));
      const png = decodePng(readFileSync(join(dir, `sdf${suffix}.png`)));
      assert.deepEqual(Object.keys(index).sort(), [...names].sort());
      const boxes = Object.entries(index).map(([name, e]) => ({ name, ...e }));
      assertPacked(boxes, png);
      for (const b of boxes) {
        assert.equal(b.sdf, true);
        assert.equal(b.pixelRatio, suffix ? 2 : 1);
      }
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
