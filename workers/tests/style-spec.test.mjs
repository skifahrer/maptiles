import { test } from "node:test";
import assert from "node:assert/strict";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";
import { styleSpec, NEEDS_SPEC } from "./spec.mjs";

const spec = styleSpec();
const OWN = {
  contoursUrl: "https://x/contours.pmtiles",
  rocksUrl: "https://x/rocks.pmtiles",
  trailsUrl: "https://x/trails.pmtiles",
  featuresUrl: "https://x/features.pmtiles",
  pointsUrl: "https://x/points.pmtiles",
  transportUrl: "https://x/transport.pmtiles"
};

for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    for (const [what, own] of [["base", {}], ["every archive", OWN]]) {
      test(`${mapType} / ${theme} / ${what} passes the style spec`, { skip: !spec && NEEDS_SPEC }, () => {
        const style = buildStyle({
          theme,
          mapType,
          tilesUrl: "https://x/tiles.pmtiles",
          spriteUrl: "https://x/sprite",
          glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
          ...own
        });
        const errors = spec.validateStyleMin(style).map((e) => e.message);
        assert.deepEqual(errors, []);
      });
    }
  }
}
