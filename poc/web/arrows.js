/**
 * Šípky jednosmeriek – vlastné, aby boli v každej sade ikoniek.
 *
 * Kým bola šípka `arrow` z cudzieho spritu, mala ju jediná z troch overených
 * sád a pri ostatných vrstva `road-oneway` v štýle vôbec nevznikla – v paneli
 * nebolo čo nastavovať a nič pri tom nespadlo.
 *
 * Zoznam tvarov navyše robí z „radšej dvojitý vtáčik" voľbu v paneli, nie
 * zmenu zdrojáku.
 *
 * SDF, a nie hotový obrázok ako pri značkách trás: šípka je jednofarebný tvar
 * a tá farba patrí do palety (`onewayIcon`), teda musí ísť s témou. Značka na
 * strome má tri farby naraz, preto je pečená natvrdo.
 *
 * Šípka mieri doprava (+x): `symbol-placement: line` natočí obrázok pozdĺž
 * čiary tak, že jeho os +x ide v smere kreslenia.
 *
 * Tento súbor je len obrázok – kedy sa kreslí, rozhoduje `themes.js`, do
 * spritu ho pečie `workers/assets/arrows.mjs`.
 */

/** Meno obrázka v sprite – predpona ako pri značkách (`mark-`) a štítkoch. */
export const ARROW_PREFIX = "arrow-";

/** Úsečka s hrúbkou – tvary sú predikáty, nie cesty (rovnako ako v `marks.js`). */
const seg = (u, v, ax, ay, bx, by, w) => {
  const dx = bx - ax;
  const dy = by - ay;
  const t = Math.max(0, Math.min(1, ((u - ax) * dx + (v - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(u - (ax + t * dx), v - (ay + t * dy)) <= w;
};

/** Plný trojuholník mieriaci doprava, od `x0` po `x1`, s polovičnou výškou `hh`. */
const hrot = (u, v, x0, x1, hh) =>
  u >= x0 && u <= x1 && Math.abs(v - 0.5) <= ((x1 - u) / (x1 - x0)) * hh;

export const ARROW_SHAPES = [
  {
    id: "triangle",
    label: "Trojuholník",
    note: "plná špička – najlepšie vidieť na malej veľkosti",
    draw: (u, v) => hrot(u, v, 0.12, 0.88, 0.42)
  },
  {
    id: "chevron",
    label: "Vtáčik",
    note: "obrys špičky, nechá pod sebou vidieť cestu",
    draw: (u, v) =>
      seg(u, v, 0.24, 0.10, 0.78, 0.50, 0.115) ||
      seg(u, v, 0.78, 0.50, 0.24, 0.90, 0.115)
  },
  {
    id: "chevron2",
    label: "Dvojitý vtáčik",
    note: "dva za sebou – smer je čitateľný aj bez priblíženia",
    draw: (u, v) => {
      const jeden = (x) =>
        seg(u, v, x, 0.14, x + 0.30, 0.50, 0.095) ||
        seg(u, v, x + 0.30, 0.50, x, 0.86, 0.095);
      return jeden(0.12) || jeden(0.54);
    }
  },
  {
    id: "stick",
    label: "Šípka s driekom",
    note: "klasická šípka – najzreteľnejšia, ale zaberie najviac miesta",
    draw: (u, v) =>
      seg(u, v, 0.06, 0.50, 0.62, 0.50, 0.085) || hrot(u, v, 0.50, 0.94, 0.34)
  }
];

export const ARROW_SHAPE_IDS = ARROW_SHAPES.map((s) => s.id);

/**
 * Tvar, ktorý štýl použije, kým ho nikto neprepne. Trojuholník zámerne:
 * šípky sa kreslia od z16 v mierke, kde má obrázok pár pixelov, a plný tvar
 * je v nej čitateľnejší než obrys.
 */
export const DEFAULT_ARROW_SHAPE = "triangle";

/** Meno obrázka v sprite pre daný tvar. */
export const arrowImage = (shape) => `${ARROW_PREFIX}${shape}`;

/** To, čo štýl žiada, kým ho úprava vrstvy neprepne na iný tvar. */
export const DEFAULT_ARROW_IMAGE = arrowImage(DEFAULT_ARROW_SHAPE);

/** Všetky mená, ktoré musia byť v sprite (stráži `workers/lint/icons.mjs`). */
export const arrowImages = () => ARROW_SHAPE_IDS.map(arrowImage);

/** Tvar podľa id; pri neznámom id vráti predvolený. */
export const arrowShape = (id) =>
  ARROW_SHAPES.find((s) => s.id === id) || ARROW_SHAPES[0];

/**
 * Rozmery obrázka v pixeloch pri `pixelRatio` 1.
 *
 * Šírka je väčšia než výška, lebo šípka leží pozdĺž cesty – v štvorci by okolo
 * nej ostal prázdny pás, ktorý MapLibre počíta do kolízie. Pomer 12 × 8 je
 * blízko maki `arrow`, nech nastavená veľkosť sedí aj po prepnutí sady.
 */
export const ARROW_W = 12;
export const ARROW_H = 8;

/** Priehľadný rámik – kvôli halu a aby hrana netiekla po susedovi v atlase. */
export const ARROW_PAD = 3;
