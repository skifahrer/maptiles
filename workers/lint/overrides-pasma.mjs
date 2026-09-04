#!/usr/bin/env node
/**
 * Kontrola: PERCENTO V ZOOMOVOM PÁSME – „na z15–z20 nech je to 110 %".
 *
 * Piata z vecí, ktoré stráži `workers/lint/overrides.mjs`; vo vlastnom
 * súbore preto, že ten je tesne pod stropom 800 riadkov, nad ktorým ho
 * „Kontrola · lint workflowov" neprepustí (pravidlo 5 v CLAUDE.md). Rez vedie
 * tam, kde sa mení otázka: tam „prejde úprava normalizáciou celá", tu „urobí
 * percento v pásme v mape naozaj to, čo sľubuje".
 *
 * ČO SA MÔŽE POKAZIŤ TICHO. Percento v pásme sa nedá zapísať ako výraz nad
 * krivkou zo štýlu – `["zoom"]` smie byť len priamym vstupom najvrchnejšieho
 * `interpolate`/`step` (rozpis pri `zw` v themes.js) –, takže sa hodnota
 * VYČÍSLI na každom celom zoome a výsledok je nová krivka
 * (`bandsOverBase`). Keby sa v tom pomýlila hoci len hranica pásma, štýl
 * ostane platný, mapa sa načíta a nikto nič nepovie: čiara bude len o kúsok
 * inde, než človek naklikal. Preto sa tu meria, čo z toho v mape naozaj
 * vyšlo, a nie to, či sa úprava uložila.
 *
 * TRI VECI:
 *   1. `normalizeOverrides` percento v pásme prijme (a `{scale: 1}` v ňom
 *      NEZAHODÍ – „na týchto zoomoch ako v štýle" je platná veta, ktorou sa
 *      pásma dopĺňajú na celý rozsah),
 *   2. mimo pásma s percentom ostane hodnota zo štýlu nezmenená,
 *   3. vnútri pásma je presne v tom pomere – a to na KAŽDOM zoome, nie len
 *      na jeho začiatku (o to pri percente ide: krivka zo štýlu ostáva).
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
