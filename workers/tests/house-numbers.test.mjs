import { test } from "node:test";
import assert from "node:assert/strict";
import { THEMES, buildStyle } from "../../poc/web/themes.js";

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

test("house numbers read at 3:1 on a building's roof, with a halo of 1.5", () => {
  for (const [theme, c] of Object.entries(THEMES)) {
    const palette = c.palette ?? c;
    assert.ok(contrast(palette.houseText, palette.buildingTop) >= 3,
      `${theme}: ${palette.houseText} on ${palette.buildingTop} is ${contrast(palette.houseText, palette.buildingTop).toFixed(2)}:1`);
    const style = buildStyle({ theme, tilesUrl: "https://x/tiles.pmtiles", spriteUrl: "https://x/sprite",
      glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf" });
    const layer = style.layers.find((l) => l.id === "housenumber");
    assert.equal(layer.paint["text-halo-width"], 1.5, theme);
  }
});
