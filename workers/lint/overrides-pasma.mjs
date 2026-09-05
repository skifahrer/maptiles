#!/usr/bin/env node
/**
 * Kontrola: percento v zoomovom pásme – „na z15–z20 nech je to 110 %".
 *
 * Piata z vecí, ktoré stráži `workers/lint/overrides.mjs`; vo vlastnom
 * súbore, lebo ten je pri strope 800 riadkov.
 *
 * `["zoom"]` smie byť len priamym vstupom najvrchnejšieho `interpolate`, tak
 * sa hodnota vyčísli na každom celom zoome (`bandsOverBase`). Pomýlená
 * hranica pásma štýl nezhodí – čiara bude len o kúsok inde, než človek
 * naklikal. Meria sa preto, čo z toho v mape vyšlo.
 *
 *   1. `normalizeOverrides` percento v pásme prijme a `{scale: 1}` v ňom nezahodí,
 *   2. mimo pásma ostane hodnota zo štýlu nezmenená,
 *   3. vnútri pásma je presne v tom pomere, a to na každom zoome.
 */
import { buildStyle, normalizeOverrides, valueAtZoom, THEMES } from "../../poc/web/themes.js";

/**
 * @param {(subor: string, text: string) => void} chyba hlásenie chyby
 * @returns {number} koľko zoomov sa premeralo (do súhrnu kontroly)
 */
export function percentaVPasmach(chyba) {
  const SUBOR = "poc/web/themes.js";
  const LAYER = "road-minor";
  const ZLOM = 15;
  const POMER = 1.1;

  const { overrides, problems } = normalizeOverrides({
    layers: {
      [LAYER]: {
        paint: {
          "line-width": [
            [0, ZLOM - 1, { scale: 1 }],
            [ZLOM, 20, { scale: POMER }]
          ]
        }
      }
    }
  });
  const ulozene = overrides.layers[LAYER]?.paint?.["line-width"];
  if (!Array.isArray(ulozene) || ulozene.length !== 2) {
    chyba(SUBOR,
      `percento v pásme neprešlo cez normalizeOverrides: ${problems[0] || "zahodené bez dôvodu"}. ` +
      `Bez neho sa „na z${ZLOM}–z20 o desatinu hrubšie" nedá povedať inak než ` +
      `prepísaním celej krivky pevnými číslami.`);
    return 0;
  }

  const bez = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                           spriteUrl: "https://x/sprite" });
  const s = buildStyle({ theme: Object.keys(THEMES)[0], tilesUrl: "pmtiles://x/t.pmtiles",
                         spriteUrl: "https://x/sprite", overrides });
  const povodna = bez.layers.find((l) => l.id === LAYER);
  const upravena = s.layers.find((l) => l.id === LAYER);
  if (!povodna || !upravena) {
    chyba(SUBOR, `vrstva "${LAYER}" v štýle nie je – kontrolu percenta v pásme nemá na čom merať.`);
    return 0;
  }

  let meraní = 0;
  for (let z = povodna.minzoom ?? 0; z <= 20; z += 1) {
    const a = valueAtZoom(povodna.paint["line-width"], z);
    const b = valueAtZoom(upravena.paint["line-width"], z);
    if (typeof a !== "number" || typeof b !== "number") continue;
    meraní += 1;
    const cakane = z >= ZLOM ? a * POMER : a;
    // Desatina pixela je tolerancia vyčíslenia (krivka sa vzorkuje po celých
    // zoomoch), nie zľava z pomeru – väčší rozdiel už znamená inú čiaru.
    if (Math.abs(b - cakane) > 0.1) {
      chyba(SUBOR,
        `percento v pásme: pri z${z} má čiara ${b}, čakalo sa ${Math.round(cakane * 100) / 100} ` +
        `(zo štýlu ${a}${z >= ZLOM ? ` × ${POMER}` : ", teda bez zmeny"}).`);
      break;
    }
  }
  return meraní;
}
