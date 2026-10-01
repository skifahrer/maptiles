#!/usr/bin/env node
/**
 * A dark variant isn't made by dimming the light colour.
 *
 * The fourth thing `workers/lint/overrides.mjs` guards; a file of its own since
 * that one is near the 800-line cap.
 *
 * `paintDark` compares only against the dark background: a white street (1.15 : 1
 * against the light background) dimmed to `#d0c8c8` is 10.5 : 1 against the dark
 * one – and the town glowed. So the pair's weight is compared, not the colours,
 * with a loose threshold for the case of a dark variant an order louder.
 */
import { THEMES } from "../../poc/web/themes.js";

/**
 * Reports pairs whose dark variant is an order louder than the light one.
 *
 * @param {object} saved contents of `poc/web/style-overrides.json`
 * @param {(file: string, text: string) => void} error error report
 * @returns {number} how many pairs were compared
 */
export function darkWeights(saved, error) {
  const CR_MAX = 6;        // below this contrast nothing is reported
  const WEIGHT_MAX = 4;    // how many times the light weight is still bearable
  const _lin = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const _lum = (h) => {
    const m = /^#([0-9a-f]{6})$/i.exec(String(h).trim());
    if (!m) return null;
    const [r, g, b] = [0, 2, 4].map((i) => _lin(parseInt(m[1].slice(i, i + 2), 16) / 255));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const _contrast = (a, b) => {
    const x = _lum(a), y = _lum(b);
    if (x === null || y === null) return null;
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  const LIGHT_BACKGROUND = THEMES.svetla.background;
  const DARK_BACKGROUND = THEMES.tmava.background;
  let pairs = 0;

  const pairWeight = (where, id, prop, light, dark) => {
    const cl = _contrast(light, LIGHT_BACKGROUND);
    const cd = _contrast(dark, DARK_BACKGROUND);
    if (cl === null || cd === null) return;
    pairs += 1;
    if (cd <= CR_MAX || cd <= WEIGHT_MAX * cl) return;
    error(
      "poc/web/style-overrides.json",
      `${where}layer "${id}", ${prop}: the dark variant ${dark} stands out of the ` +
      `dark background ${cd.toFixed(1)}:1, while the light ${light} stands out of ` +
      `the light one only ${cl.toFixed(2)}:1 – ${(cd / cl).toFixed(0)}× the weight. ` +
      `A dark variant isn't made by dimming the light colour but from the dark ` +
      `background; otherwise a dense network of such lines makes towns glow.`
    );
  };

  const layerWeights = (layers, where) => {
    for (const [id, def] of Object.entries(layers || {})) {
      for (const [prop, light] of Object.entries(def?.paint || {})) {
        const dark = def?.paintDark?.[prop];
        if (prop.endsWith("-color") && dark) pairWeight(where, id, prop, light, dark);
      }
      // an outline carries its own pair (`color` / `colorDark`), measured alike
      if (def?.outline?.color && def?.outline?.colorDark) {
        pairWeight(where, id, "outline", def.outline.color, def.outline.colorDark);
      }
    }
  };

  layerWeights(saved.layers, "");
  for (const [map, def] of Object.entries(saved.maps || {})) {
    layerWeights(def?.layers, `map “${map}”: `);
  }
  return pairs;
}
