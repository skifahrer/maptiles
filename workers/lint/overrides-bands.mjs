#!/usr/bin/env node
/**
 * A percentage in a zoom band – “110 % at z15–z20”.
 *
 * The fifth thing `workers/lint/overrides.mjs` guards; a file of its own since
 * that one is near the 800-line cap.
 *
 * `["zoom"]` may only feed the topmost `interpolate`, so the value is expanded at
 * every whole zoom (`bandsOverBase`). A wrong band edge doesn't break the style –
 * the line is just slightly elsewhere than clicked – so the result is measured.
 *
 *   1. `normalizeOverrides` accepts a percentage in a band and keeps `{scale: 1}`,
 *   2. outside the band the style's value stays unchanged,
 *   3. inside it's exactly in that ratio, at every zoom.
 */
import { buildStyle, normalizeOverrides, valueAtZoom, THEMES } from "../../poc/web/themes.js";

/**
 * @param {(file: string, text: string) => void} error error report
 * @returns {number} how many zooms were measured
 */
export function bandPercentages(error) {
  const FILE = "poc/web/themes.js";
  const LAYER = "road-minor";
  const BREAK = 15;
  const RATIO = 1.1;

  const { overrides, problems } = normalizeOverrides({
    layers: {
      [LAYER]: {
        paint: {
          "line-width": [
            [0, BREAK - 1, { scale: 1 }],
            [BREAK, 20, { scale: RATIO }]
          ]
        }
      }
    }
  });
  const saved = overrides.layers[LAYER]?.paint?.["line-width"];
  if (!Array.isArray(saved) || saved.length !== 2) {
    error(FILE,
      `a percentage in a band didn't pass normalizeOverrides: ${problems[0] || "dropped without a reason"}. ` +
      `Without it “a tenth thicker at z${BREAK}–z20” can only be said by ` +
      `rewriting the whole curve with fixed numbers.`);
    return 0;
  }

  const plain = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                             spriteUrl: "https://x/sprite" });
  const s = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                         spriteUrl: "https://x/sprite", overrides });
  const original = plain.layers.find((l) => l.id === LAYER);
  const changed = s.layers.find((l) => l.id === LAYER);
  if (!original || !changed) {
    error(FILE, `layer "${LAYER}" isn't in the style – nothing to measure the band percentage on.`);
    return 0;
  }

  let measured = 0;
  for (let z = original.minzoom ?? 0; z <= 20; z += 1) {
    const a = valueAtZoom(original.paint["line-width"], z);
    const b = valueAtZoom(changed.paint["line-width"], z);
    if (typeof a !== "number" || typeof b !== "number") continue;
    measured += 1;
    const expected = z >= BREAK ? a * RATIO : a;
    // a tenth of a pixel is sampling tolerance, not a discount on the ratio
    if (Math.abs(b - expected) > 0.1) {
      error(FILE,
        `band percentage: at z${z} the line is ${b}, expected ${Math.round(expected * 100) / 100} ` +
        `(the style's ${a}${z >= BREAK ? ` × ${RATIO}` : ", so unchanged"}).`);
      break;
    }
  }
  return measured;
}
