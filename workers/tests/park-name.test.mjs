import { test } from "node:test";
import assert from "node:assert/strict";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

test("a park's name is drawn from its label point, never from its outline", () => {
  for (const theme of Object.keys(THEMES)) {
    for (const mapType of MAP_TYPE_IDS) {
      const style = buildStyle({ theme, mapType, tilesUrl: "https://x/tiles.pmtiles",
        spriteUrl: "https://x/sprite", glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf" });
      const names = style.layers.filter((l) => l.type === "symbol" && l["source-layer"] === "park");
      assert.ok(names.length > 0, `${mapType} / ${theme} names parks`);
      for (const layer of names) {
        assert.deepEqual(layer.filter, ["==", ["geometry-type"], "Point"], `${mapType} / ${theme} ${layer.id}`);
      }
    }
  }
});
