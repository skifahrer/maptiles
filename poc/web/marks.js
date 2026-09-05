/**
 * Turistická a cyklistická značka – to, čo je na strome (SK aj CZ).
 *
 * Značenie u nás aj v Česku má jeden tvar: štvorec 10 × 10 cm s vodorovným
 * pásom vo farbe trasy a pásmi podkladu nad ním aj pod ním. Podklad je pri
 * pešej značke biely, pri cyklistickej žltý; k tomu tvarové značky
 * (trojuholník na vrchol, „L", kruh) a český bicykel na žltom.
 *
 * Nie ikona zo sady: tá povie druh trasy, ale nie to, čo človek v teréne
 * hľadá. „Choď po červenej" sa z ikonky horského štítu prečítať nedá.
 *
 * Hotový farebný obrázok, nie SDF: značka má tri farby naraz (podklad, pás,
 * lem) a SDF vie zafarbiť jednu plus halo.
 *
 * A preto sa farby značiek nemenia s témou – značka je obrázok naozajstnej
 * tabuľky, nie prvok mapy. Pásik trasy pod ňou naopak témou ide.
 *
 * Kombinácie sú vymenované, nie všetky: podklad × farba × tvar by bolo
 * niekoľko stoviek obrázkov a väčšina neexistuje ani v teréne. `MARK_FACES`
 * je zoznam dvojíc, ktoré na značkách naozaj sú, a `lint/marks.mjs` stráži,
 * že routes.py inú do dlaždíc nenapíše – meno obrázka skladá štýl z dát
 * a obrázok, ktorý v sprite nie je, MapLibre ticho nenakreslí.
 *
 * Tento súbor je len obrázok. Ktorá trasa akú značku dostane, rozhoduje
 * `workers/trails/routes.py`, kedy sa kreslí `themes.js`, a do spritu ich
 * pečie `workers/assets/marks.mjs`.
 */

/**
 * Farby značiek – farby náteru na strome, nie farby mapy, preto nie sú
 * v palete tém. Blízko k `trail*` farbám svetlej témy, aby pásik a značka nad
 * ním nevyzerali ako dve rôzne trasy.
 */
export const MARK_COLOURS = {
  red: "#d42a2a",
  blue: "#2a54c8",
  green: "#1f8a3c",
  yellow: "#f2c200",
  black: "#2a2a2a",
  white: "#ffffff"
};

export const MARK_COLOUR_IDS = Object.keys(MARK_COLOURS);

/**
 * Dvojice podklad → farba značky, ktoré sa pečú.
 *
 * Prvé dva riadky sú to, čo je v teréne: biely podklad je pešia značka, žltý
 * cyklistická. Tretí sú obrátené značky – náučný chodník má biely pás na
 * farebnom podklade, inak by sa kreslil biely pás na bielom štvorci.
 *
 * Rovnaká farba pásu ako podkladu tu byť nesmie: taká značka je prázdny
 * štvorec. Stráži to lint.
 */
export const MARK_FACES = [
  ["white", "red"], ["white", "blue"], ["white", "green"],
  ["white", "yellow"], ["white", "black"],
  ["yellow", "red"], ["yellow", "blue"], ["yellow", "green"],
  ["yellow", "black"], ["yellow", "white"],
  ["red", "white"], ["blue", "white"], ["green", "white"], ["black", "white"]
];

/**
 * Tvary značiek – len to, ako tvar vyzerá.
 *
 * Ktorá hodnota `osmc:symbol` znamená ktorý tvar, je v `OSMC_SHAPES` vo
 * `workers/trails/routes.py`, teda tam, kde sa tag číta. `lint/marks.mjs`
 * stráži, že routes.py nepošle tvar, ktorý tu nie je.
 *
 * `label` je pre developer mode.
 */
export const MARK_SHAPES = [
  {
    id: "bar",
    label: "Pásová (vodorovný pás)",
    draw: (u, v) => v >= 0.34 && v <= 0.66
  },
  {
    id: "slash",
    label: "Šikmý pás",
    // `backslash` sa kreslí tým istým tvarom: v mierke, kde má značka 14 px,
    // je smer šikmého pásu nerozoznateľný a druhý obrázok by nič nepridal.
    draw: (u, v) => Math.abs(u + v - 1) <= 0.22
  },
  {
    id: "triangle",
    label: "Vrcholová (trojuholník)",
    draw: (u, v) => v >= 0.16 && v <= 0.84 &&
      Math.abs(u - 0.5) <= ((v - 0.16) / 0.68) * 0.42
  },
  {
    id: "circle",
    label: "Kruh (prstenec)",
    draw: (u, v) => {
      const r = Math.hypot(u - 0.5, v - 0.5);
      return r >= 0.24 && r <= 0.40;
    }
  },
  {
    id: "dot",
    label: "Plný kruh",
    draw: (u, v) => Math.hypot(u - 0.5, v - 0.5) <= 0.32
  },
  {
    id: "corner",
    label: "„L“ (odbočka k pamiatke)",
    draw: (u, v) => (u >= 0.14 && u <= 0.42 && v >= 0.14 && v <= 0.86) ||
      (v >= 0.58 && v <= 0.86 && u >= 0.14 && u <= 0.86)
  },
  {
    id: "bowl",
    label: "„U“ (odbočka k prameňu)",
    draw: (u, v) => {
      const inRing = (() => {
        const r = Math.hypot(u - 0.5, v - 0.58);
        return r >= 0.20 && r <= 0.36 && v >= 0.58;
      })();
      const legs = Math.abs(Math.abs(u - 0.5) - 0.28) <= 0.08 && v <= 0.58 && v >= 0.16;
      return inRing || legs;
    }
  },
  {
    id: "cross",
    label: "Kríž",
    draw: (u, v) => (Math.abs(u - 0.5) <= 0.12 && Math.abs(v - 0.5) <= 0.36) ||
      (Math.abs(v - 0.5) <= 0.12 && Math.abs(u - 0.5) <= 0.36)
  },
  {
    id: "x",
    label: "Kríž šikmý (X)",
    draw: (u, v) => {
      const inSquare = u >= 0.14 && u <= 0.86 && v >= 0.14 && v <= 0.86;
      return inSquare && (Math.abs(u - v) <= 0.17 || Math.abs(u + v - 1) <= 0.17);
    }
  },
  {
    id: "diamond",
    label: "Kosoštvorec",
    draw: (u, v) => Math.abs(u - 0.5) + Math.abs(v - 0.5) <= 0.40
  },
  {
    id: "bicycle",
    // Česká (a slovenská mestská) cyklistická značka: žltý štvorec s čiernym
    // bicyklom. Kreslí sa z dvoch kolies a rámu – v 14 pixeloch je detailnejší
    // bicykel aj tak nerozoznateľný od škvrny.
    label: "Bicykel (cyklistická značka)",
    draw: (u, v) => {
      const wheel = (cx) => {
        const r = Math.hypot(u - cx, v - 0.64);
        return r >= 0.13 && r <= 0.22;
      };
      const seg = (ax, ay, bx, by, w) => {
        const dx = bx - ax;
        const dy = by - ay;
        const t = Math.max(0, Math.min(1, ((u - ax) * dx + (v - ay) * dy) / (dx * dx + dy * dy)));
        return Math.hypot(u - (ax + t * dx), v - (ay + t * dy)) <= w;
      };
      return wheel(0.23) || wheel(0.77) ||
        seg(0.23, 0.64, 0.5, 0.64, 0.05) || seg(0.5, 0.64, 0.77, 0.64, 0.05) ||
        seg(0.5, 0.64, 0.42, 0.34, 0.05) || seg(0.42, 0.34, 0.68, 0.34, 0.05);
    }
  }
];

export const MARK_SHAPE_IDS = MARK_SHAPES.map((s) => s.id);
export const DEFAULT_MARK_SHAPE = "bar";

/** Tvar podľa id; pri neznámom id vráti pásovú značku. */
export function markShape(id) {
  return MARK_SHAPES.find((s) => s.id === id) || MARK_SHAPES[0];
}

/**
 * Meno obrázka v sprite. Skladá ho aj štýl – ale výrazom nad dátami
 * (`concat`), takže tu je to isté meno ako funkcia a lint porovnáva, že sa
 * tie dve cesty k nemu zhodujú.
 */
export const MARK_PREFIX = "mark-";
export function markImage(bg, fg, shape) {
  return `${MARK_PREFIX}${bg}-${fg}-${shape}`;
}

/** Všetky obrázky, ktoré sa pečú: dvojice × tvary. */
export function markImages() {
  const out = [];
  for (const [bg, fg] of MARK_FACES) {
    for (const shape of MARK_SHAPES) {
      out.push({ name: markImage(bg, fg, shape.id), bg, fg, shape });
    }
  }
  return out;
}

/**
 * Strana štvorca značky v pixeloch pri `pixelRatio` 1 (bez lemu a okraja).
 *
 * Pri z16 je pásik trasy 2,6 px, takže značka má byť výrazne väčšia, ale nie
 * taká, aby zakryla cestu pod sebou.
 */
export const MARK_BOX = 14;

/**
 * Od akého zoomu má značka zmysel.
 *
 * Tu, a nie v štýle, lebo sa pýtajú dve miesta: `themes.js` a `map-types.js`
 * (turistická mapa púšťa pásiky už od z8 a značky pri tom nesmie stiahnuť so
 * sebou). Pod z12 je zo značky škvrna a je ich toľko, koľko trás.
 */
export const MARK_MINZOOM = 12;
/**
 * Priehľadný okraj okolo štvorca v pixeloch pri `pixelRatio` 1.
 *
 * Aby sa pri škálovaní neoprela hrana obrázka o susedný v atlase. Pýta sa naň
 * aj štýl: kolízny obdĺžnik značky je celý obrázok vrátane tohto okraja.
 */
export const MARK_PAD = 1;

/** Celá strana obrázka značky – to, čo MapLibre kreslí aj počíta do kolízie. */
export const MARK_IMAGE = MARK_BOX + 2 * MARK_PAD;

/** Tenký lem okolo štvorca – bez neho biela značka na svetlej mape zmizne. */
export const MARK_EDGE = "#00000055";
/** Hrúbka lemu v pixeloch pri `pixelRatio` 1. */
export const MARK_EDGE_W = 1;

/** `#rrggbb` (aj s alfou) → `[r, g, b, a]`, a je 0–1. */
function rozlozFarbu(hex) {
  const h = String(hex || "#000000").replace("#", "");
  const n = h.length === 3 || h.length === 4
    ? h.split("").map((ch) => ch + ch).join("")
    : h;
  const v = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) || 0);
  const a = n.length >= 8 ? (parseInt(n.slice(6, 8), 16) || 0) / 255 : 1;
  return [v[0], v[1], v[2], a];
}

/**
 * Vykreslí značku ako hotový farebný obrázok (RGBA, nie SDF).
 *
 * Tvary sú predikáty nad jednotkovým štvorcom (`draw(u, v)`), nie cesty:
 * vyhladenie hrán je preto obyčajné 4 × 4 prevzorkovanie a nový tvar je jeden
 * riadok podmienky.
 *
 * @param {object} shape       položka z `MARK_SHAPES`
 * @param {string} bgHex       farba podkladu
 * @param {string} fgHex       farba pásu / tvaru
 * @param {number} pixelRatio  1 alebo 2 (varianta @2x)
 * @returns {{width:number, height:number, data:Uint8Array}}
 */
export function renderMark(shape, bgHex, fgHex, pixelRatio = 1) {
  const r = pixelRatio;
  const box = Math.round(MARK_BOX * r);
  const edge = MARK_EDGE_W * r;
  // Priehľadný okraj (rozpis pri `MARK_PAD`).
  const pad = Math.max(1, Math.round(MARK_PAD * r));
  const size = box + 2 * pad;

  const bg = rozlozFarbu(bgHex);
  const fg = rozlozFarbu(fgHex);
  const ed = rozlozFarbu(MARK_EDGE);
  const data = new Uint8Array(size * size * 4);

  const SS = 4;                       // prevzorkovanie na pixel (4 × 4)
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      let vnutri = 0;                 // koľko vzoriek padlo do štvorca
      let pas = 0;                    // z toho do tvaru značky
      let lem = 0;                    // z toho do lemu
      for (let sy = 0; sy < SS; sy += 1) {
        for (let sx = 0; sx < SS; sx += 1) {
          const px = x + (sx + 0.5) / SS - pad;
          const py = y + (sy + 0.5) / SS - pad;
          if (px < 0 || py < 0 || px >= box || py >= box) continue;
          vnutri += 1;
          if (px < edge || py < edge || px >= box - edge || py >= box - edge) {
            lem += 1;
            continue;
          }
          if (shape.draw(px / box, py / box)) pas += 1;
        }
      }
      const n = SS * SS;
      const aVnutri = vnutri / n;
      if (!aVnutri) continue;
      const wLem = lem / n;
      const wPas = pas / n;
      const wPod = aVnutri - wLem - wPas;

      // Lem je poloprehľadný, takže leží NAD podkladom – zmieša sa s ním,
      // nie s mapou pod značkou (tam by z bielej značky vznikol sivý rám).
      const lemR = ed[0] * ed[3] + bg[0] * (1 - ed[3]);
      const lemG = ed[1] * ed[3] + bg[1] * (1 - ed[3]);
      const lemB = ed[2] * ed[3] + bg[2] * (1 - ed[3]);

      const i = (y * size + x) * 4;
      data[i] = Math.round((bg[0] * wPod + fg[0] * wPas + lemR * wLem) / aVnutri);
      data[i + 1] = Math.round((bg[1] * wPod + fg[1] * wPas + lemG * wLem) / aVnutri);
      data[i + 2] = Math.round((bg[2] * wPod + fg[2] * wPas + lemB * wLem) / aVnutri);
      data[i + 3] = Math.round(255 * aVnutri);
    }
  }

  return { width: size, height: size, data };
}
