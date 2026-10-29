import { test } from "node:test";
import assert from "node:assert/strict";
import { buildStyle, realWidthPx, PATH_GROUND_M, MAX_DISPLAY_Z } from "../../poc/web/themes.js";
import { layerOwners } from "../../poc/web/packages.js";

const style = (mapType) => buildStyle({
  theme: "svetla",
  mapType,
  tilesUrl: "https://x/tiles.pmtiles",
  spriteUrl: "https://x/sprite",
  glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf"
});

const widthAt = (layer, z) => {
  const [, , , ...stops] = layer.paint["line-width"];
  const pairs = [];
  for (let i = 0; i < stops.length; i += 2) pairs.push([stops[i], stops[i + 1]]);
  const [[z0, w0], [z1, w1]] = pairs;
  return w0 * 2 ** ((z - z0) * Math.log2(w1 / w0) / (z1 - z0));
};

test("zoomed in, a path is as wide as it is on the ground, under its dashes", () => {
  const layers = style("turisticka").layers;
  const ids = layers.map((l) => l.id);
  for (const [id, metres] of Object.entries(PATH_GROUND_M)) {
    const ground = layers.find((l) => l.id === `road-${id}__ground`);
    assert.ok(ground, `road-${id} has no ground`);
    assert.ok(ids.indexOf(ground.id) < ids.indexOf(`road-${id}`), "the ground is under the line");
    assert.ok(Math.abs(widthAt(ground, MAX_DISPLAY_Z) - realWidthPx(metres, MAX_DISPLAY_Z)) < 0.01);
    assert.deepEqual(layerOwners(ground), layerOwners(layers.find((l) => l.id === `road-${id}`)));
  }
  // a 3 m track at z20 in the middle of Slovakia is about 60 px wide
  assert.ok(Math.abs(realWidthPx(3, 20) - 60.8) < 1);
});

test("a map type that hides a path hides its ground too", () => {
  const layers = style("cestna").layers;
  const visibility = (id) => (layers.find((l) => l.id === id)?.layout || {}).visibility;
  assert.equal(visibility("road-footway"), "none");
  assert.equal(visibility("road-footway__ground"), "none");
});
