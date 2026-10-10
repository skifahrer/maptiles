import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

// not checked in; the job installs it under STYLE_SPEC_DIR
function styleSpec() {
  const require = createRequire(import.meta.url);
  const paths = [process.env.STYLE_SPEC_DIR, process.cwd()].filter(Boolean);
  try {
    return require(require.resolve("@maplibre/maplibre-gl-style-spec", { paths }));
  } catch (err) {
    if (process.env.TESTS_REQUIRE_ALL === "1") throw err;
    return null;
  }
}

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
      test(`${mapType} / ${theme} / ${what} passes the style spec`, { skip: !spec && "needs @maplibre/maplibre-gl-style-spec" }, () => {
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
