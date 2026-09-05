/**
 * Opakujúce sa vzory pre plochy a línie + prerušovanie čiar.
 *
 * Obrázok v sprite sa nedá prefarbiť, tak sa vzory vyrábajú procedurálne:
 * názov obrázka je zároveň jeho predpis (`pat:hatch:3a5a34:16:12`), takže si
 * ho prehliadač dokreslí sám a pipeline tie isté názvy nájde v hotovom štýle
 * a dopečie do spritu – rovnaký štýl teda funguje aj na iOS.
 *
 * Vzory sú v jednotkových súradniciach a dlaždicujú sa; rasterizácia počíta
 * aj 3×3 susedné kópie, takže tvar smie prečnievať za hranu a druhá polovica
 * sa objaví na opačnej strane sama. Pri vzore, ktorý má vyzerať ako rozsyp, je
 * to povinné – inak je z opakovania mriežka prázdnych uličiek (stráži
 * `workers/lint/style.mjs`). Otáčanie sa neponúka: v štvorcovej dlaždici by
 * rozbilo napojenie, tak má každý smer vlastný vzor.
 */

const seg = (ax, ay, bx, by) => ({ t: "s", ax, ay, bx, by });
const dot = (cx, cy, r) => ({ t: "d", cx, cy, r });
const ring = (cx, cy, r) => ({ t: "r", cx, cy, r });

/** Lomená čiara ako séria úsečiek. */
const poly = (pts) => {
  const out = [];
  for (let i = 1; i < pts.length; i++) {
    out.push(seg(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]));
  }
  return out;
};

/**
 * Vzory pre plochy aj línie. `shapes` sú v jednotkovej dlaždici,
 * `line: true` znamená, že vzor dáva zmysel aj pozdĺž čiary.
 */
export const PATTERNS = [
  { id: "hatch", label: "Šrafovanie /", shapes: [seg(-0.5, 1.5, 1.5, -0.5)] },
  { id: "hatch-back", label: "Šrafovanie \\", shapes: [seg(-0.5, -0.5, 1.5, 1.5)] },
  {
    id: "crosshatch",
    label: "Krížové šrafovanie",
    shapes: [seg(-0.5, 1.5, 1.5, -0.5), seg(-0.5, -0.5, 1.5, 1.5)]
  },
  { id: "hlines", label: "Vodorovné čiary", shapes: [seg(-0.5, 0.5, 1.5, 0.5)] },
  { id: "vlines", label: "Zvislé čiary", shapes: [seg(0.5, -0.5, 0.5, 1.5)] },
  {
    id: "grid",
    label: "Mriežka",
    shapes: [seg(-0.5, 0.5, 1.5, 0.5), seg(0.5, -0.5, 0.5, 1.5)]
  },
  { id: "dots", label: "Bodky", shapes: [dot(0.5, 0.5, 0.13)] },
  {
    id: "dots-dense",
    label: "Bodky husté",
    shapes: [dot(0.25, 0.25, 0.1), dot(0.75, 0.75, 0.1)]
  },
  { id: "rings", label: "Krúžky", shapes: [ring(0.5, 0.5, 0.28)] },
  {
    id: "wave",
    label: "Vlnky (mokraď)",
    line: true,
    shapes: poly([
      [-0.5, 0.5], [-0.25, 0.3], [0, 0.5], [0.25, 0.7],
      [0.5, 0.5], [0.75, 0.3], [1, 0.5], [1.25, 0.7], [1.5, 0.5]
    ])
  },
  {
    id: "zigzag",
    label: "Cikcak",
    line: true,
    shapes: poly([[-0.5, 0.75], [0, 0.25], [0.5, 0.75], [1, 0.25], [1.5, 0.75]])
  },
  {
    id: "trees",
    label: "Stromčeky (les)",
    shapes: [
      ...poly([[0.5, 0.16], [0.25, 0.7], [0.75, 0.7], [0.5, 0.16]]),
      seg(0.5, 0.7, 0.5, 0.9)
    ]
  },
  {
    // skalné pole – rozsypané kamene, nie pravidelné šrafovanie. Kamene sú
    // šesť rôznych: rovnaký tvar v pravidelnom rastri prestane byť suťou
    // a začne byť bodkovaná mriežka.
    //
    // Zámerne prečnievajú za hranu (súradnice mimo 0–1): kým ležali všetky
    // vnútri, mala dlaždica po obvode prázdny okraj a z dlaždicovania bola
    // mriežka uličiek (krytie na šve 3,4 % proti 27,1 % teraz). Stredy vyšli
    // zo zlatého rezu a doladili sa hľadaním, ktoré drží hustotu, ale bez
    // uličiek a dier; rasterizér počíta aj 3×3 susedné kópie, takže sa
    // presahujúca polovica objaví na opačnej strane sama.
    id: "rocks",
    label: "Kamienky (skalné pole)",
    // ROZSYP: tento vzor má vyzerať nepravidelne. Kontrola
    // `workers/lint/style.mjs` na ňom preto trvá, aby mal ink aj na šve
    // dlaždice – pravidelné motívy v bunke (bodky, krúžky, krížiky,
    // stromčeky) ho tam zámerne nemajú a tie sa nekontrolujú.
    scatter: true,
    shapes: [
      // cez pravý dolný kút (objaví sa aj vľavo hore)
      ...poly([[1.05, 0.89], [1.10, 0.97], [1.07, 1.08], [0.93, 1.04],
               [0.83, 0.95], [0.94, 0.87], [1.05, 0.89]]),
      // pri ľavej hrane
      ...poly([[0.19, 0.63], [0.14, 0.70], [0.03, 0.71], [0.03, 0.60],
               [0.08, 0.50], [0.18, 0.55], [0.19, 0.63]]),
      // najväčší, vnútri
      ...poly([[0.32, 0.14], [0.42, 0.12], [0.54, 0.20], [0.45, 0.31],
               [0.33, 0.38], [0.25, 0.25], [0.32, 0.14]]),
      ...poly([[0.60, 0.83], [0.54, 0.88], [0.43, 0.85], [0.48, 0.77],
               [0.58, 0.74], [0.60, 0.83]]),
      ...poly([[0.63, 0.54], [0.58, 0.46], [0.62, 0.34], [0.75, 0.39],
               [0.84, 0.48], [0.73, 0.56], [0.63, 0.54]]),
      // cez horný šev (objaví sa aj dolu)
      ...poly([[0.90, -0.01], [0.90, 0.08], [0.80, 0.14], [0.75, 0.03],
               [0.79, -0.07], [0.90, -0.01]])
    ]
  },
  {
    id: "scales",
    label: "Šupiny (skaly)",
    shapes: [
      ...poly([[0, 0.75], [0.25, 0.25], [0.5, 0.75]]),
      ...poly([[0.5, 0.75], [0.75, 0.25], [1, 0.75]]),
      ...poly([[-0.5, 0.25], [-0.25, -0.25], [0, 0.25]])
    ]
  },
  {
    id: "bricks",
    label: "Tehly",
    shapes: [
      seg(-0.5, 0.5, 1.5, 0.5),
      seg(-0.5, 0, 1.5, 0),
      seg(0.25, 0, 0.25, 0.5),
      seg(0.75, 0.5, 0.75, 1)
    ]
  },
  {
    id: "cross",
    label: "Krížiky (cintorín)",
    shapes: [seg(0.5, 0.2, 0.5, 0.8), seg(0.32, 0.42, 0.68, 0.42)]
  },
  {
    id: "ties",
    label: "Priečky (železnica)",
    line: true,
    shapes: [seg(0.5, 0.05, 0.5, 0.95)]
  },
  {
    id: "chevron",
    label: "Šípky",
    line: true,
    shapes: poly([[0.15, 0.15], [0.75, 0.5], [0.15, 0.85]])
  },
  {
    id: "sleepers",
    label: "Rebrík (lanovka)",
    line: true,
    shapes: [seg(0.5, 0.05, 0.5, 0.95), seg(-0.5, 0.5, 1.5, 0.5)]
  }
];

export const PATTERN_IDS = PATTERNS.map((p) => p.id);
const PATTERN_BY_ID = Object.fromEntries(PATTERNS.map((p) => [p.id, p]));

/**
 * Prerušovanie čiar – `line-dasharray` v násobkoch šírky čiary.
 *
 * Zoznam je jediný zdroj pravdy: tie isté predvoľby ponúka developer mode
 * a tie isté mená sa ukladajú do `style-overrides.json`.
 */
export const DASH_PRESETS = [
  { id: "solid", label: "Plná", dash: null },
  { id: "dashed", label: "Čiarkovaná", dash: [4, 2] },
  { id: "dashed-long", label: "Dlhé čiarky", dash: [8, 3] },
  { id: "dashed-fine", label: "Krátke čiarky", dash: [2, 1.5] },
  { id: "dotted", label: "Bodkovaná", dash: [1, 2] },
  { id: "dotted-dense", label: "Bodkovaná hustá", dash: [0.8, 1] },
  { id: "dotted-sparse", label: "Bodkovaná riedka", dash: [1, 4] },
  { id: "dash-dot", label: "Čiarka-bodka", dash: [5, 1.5, 1, 1.5] },
  { id: "dash-dot-dot", label: "Čiarka-bodka-bodka (náučný chodník)", dash: [6, 1.5, 1, 1.5, 1, 1.5] },
  // Železnica: svetlé a tmavé diely ROVNAKO DLHÉ – to je ten klasický
  // „vlakový" pás. `line-dasharray` je v NÁSOBKOCH ŠÍRKY ČIARY, takže `[1, 1]`
  // drží pomer 1 : 1 na každom zoome samo; keby to boli pixely, museli by sa
  // dopisovať pri každej zmene šírky. Predtým tu bolo `[0.3, 2.5]` – krátke
  // svetlé zúbky na dlhom tmavom, čiže priečky, nie čiarkovaná čiara.
  { id: "rail", label: "Čiarkovaná 1 : 1 (železnica)", dash: [1, 1] },
  { id: "ties", label: "Priečky", dash: [1, 3] },
  { id: "ladder", label: "Rebrík (lanovka)", dash: [6, 2] }
];

export const DASH_IDS = DASH_PRESETS.map((d) => d.id);
const DASH_BY_ID = Object.fromEntries(DASH_PRESETS.map((d) => [d.id, d]));

/** `line-dasharray` pre daný preset (`null` = plná čiara). */
export const dashArray = (id) => DASH_BY_ID[id]?.dash ?? null;

/**
 * Opak `dashArray`: predvoľba podľa `line-dasharray` zo štýlu.
 *
 * Tu, a nie pri čítaní štýlu, lebo sa pýtajú tri miesta – štýl, developer mode
 * a kopírovanie štýlu medzi vrstvami. Vlastné prerušovanie vráti `null`, a to
 * je poctivá odpoveď, nie „plná".
 */
export function dashIdOf(dasharray) {
  if (!Array.isArray(dasharray)) return null;
  const found = DASH_PRESETS.find(
    (d) => d.dash && d.dash.length === dasharray.length &&
      d.dash.every((n, i) => Math.abs(n - dasharray[i]) < 0.001)
  );
  return found ? found.id : null;
}

/** Popis prerušovania do panela: meno predvoľby, inak samotné čísla. */
export function dashLabel(dash) {
  if (Array.isArray(dash)) {
    const id = dashIdOf(dash);
    return id ? DASH_BY_ID[id].label : `vlastné [${dash.join(", ")}]`;
  }
  return DASH_BY_ID[dash]?.label || "Plná";
}

/**
 * Náhľad prerušovania ako `stroke-dasharray` do SVG – z textu v rozbaľovačke
 * nie je vidieť, ako čiara vyzerá.
 *
 * @param {string|number[]} dash  predvoľba alebo rovno `line-dasharray`
 * @param {number} scale  hrúbka čiary v ukážke
 */
export function dashPreview(dash, scale = 2) {
  const d = Array.isArray(dash) ? dash : dashArray(dash);
  return d ? d.map((n) => Math.max(0.1, n * scale)).join(" ") : "";
}

/**
 * Predvolený predpis vzoru – doplní, čo používateľ nezadal.
 *
 * Vlastný obrázok je iný druh odpovede: vtedy sa dlaždicuje nahratý obrázok
 * a farba, veľkosť ani hrúbka naň neplatia. Preto sa vracia len `image` – inak
 * by ich panel ponúkal a nič by nerobili.
 */
export function patternSpec(spec = {}) {
  const image = typeof spec?.image === "string" ? spec.image.trim() : "";
  if (image) return { image };
  return {
    id: PATTERN_BY_ID[spec.id] ? spec.id : "hatch",
    color: /^#[0-9a-f]{6}$/i.test(spec.color || "") ? spec.color.toLowerCase() : "#000000",
    size: Math.min(64, Math.max(4, Math.round(Number(spec.size) || 16))),
    weight: Math.min(8, Math.max(0.5, Math.round((Number(spec.weight) || 1) * 10) / 10))
  };
}

/**
 * Celý predpis vzoru vrátane krytia – to, čo drží štýl (`frico:pattern`) aj
 * úprava vrstvy z developer módu. `patternSpec` sám krytie nerieši, lebo to
 * nie je vlastnosť obrázka, ale vrstvy, ktorá ho kreslí; jedna funkcia to má
 * ale dopĺňať pre oba prípady, inak sa raz rozídu v tom, čo je predvolené.
 */
export function patternDef(spec = {}) {
  const opacity = Number(spec?.opacity);
  return {
    ...patternSpec(spec),
    opacity: Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : 1
  };
}

/**
 * Názov obrázka = jeho predpis. Vďaka tomu si ho vie dokresliť prehliadač aj
 * pipeline a nikde sa nemusí viesť zoznam vygenerovaných obrázkov.
 */
export function patternImageName(spec) {
  const s = patternSpec(spec);
  // Vlastný obrázok už meno má – je to vlastná ikona z úprav (`own:…`) a do
  // spritu ju pečie `workers/assets/custom-icons.mjs`. Tým pádom preň netreba
  // druhú pečiacu cestu ani druhý formát mena.
  if (s.image) return s.image;
  return `pat:${s.id}:${s.color.slice(1)}:${s.size}:${Math.round(s.weight * 10)}`;
}

/** Opak `patternImageName` – vracia `null`, ak to nie je názov vzoru. */
export function parsePatternName(name) {
  if (typeof name !== "string" || !name.startsWith("pat:")) return null;
  const [, id, color, size, weight10] = name.split(":");
  if (!PATTERN_BY_ID[id]) return null;
  return patternSpec({
    id,
    color: `#${color}`,
    size: Number(size),
    weight: Number(weight10) / 10
  });
}

/** Nájde všetky názvy vzorov použité v štýle. */
export function collectPatternNames(style) {
  const names = new Set();
  for (const layer of style.layers || []) {
    for (const prop of ["fill-pattern", "line-pattern"]) {
      const v = (layer.paint || {})[prop];
      if (parsePatternName(v)) names.add(v);
    }
  }
  return [...names];
}

// ============================ rasterizácia ============================

const hexToRgb = (hex) => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16)
];

/** Vzdialenosť bodu od úsečky (v jednotkových súradniciach). */
function distSegment(px, py, s, ox, oy) {
  const ax = s.ax + ox;
  const ay = s.ay + oy;
  const bx = s.bx + ox;
  const by = s.by + oy;
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

/**
 * Vykreslí dlaždicu vzoru. Vracia RGBA (priehľadné pozadie – vzor sa kreslí
 * ako vrstva nad plochou, takže jej vlastná farba zostáva vidieť).
 *
 * @param {object} spec  {id, color, size, weight}
 * @param {number} pixelRatio  1 alebo 2
 */
export function renderPattern(spec, pixelRatio = 1) {
  const s = patternSpec(spec);
  const def = PATTERN_BY_ID[s.id];
  const size = Math.max(4, Math.round(s.size * pixelRatio));
  const halfWidth = (s.weight * pixelRatio) / 2 / size; // v jednotkových súr.
  const [r, g, b] = hexToRgb(s.color);
  const data = new Uint8ClampedArray(size * size * 4);
  const SS = 3; // 3×3 nadvzorkovanie – vzory sú malé, kvalita je vidieť

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let hits = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const px = (x + (sx + 0.5) / SS) / size;
          const py = (y + (sy + 0.5) / SS) / size;
          let inside = false;
          // Susedné kópie dlaždice, aby vzor na hranách nadväzoval.
          for (let oy = -1; oy <= 1 && !inside; oy++) {
            for (let ox = -1; ox <= 1 && !inside; ox++) {
              for (const shape of def.shapes) {
                if (shape.t === "s") {
                  if (distSegment(px, py, shape, ox, oy) <= halfWidth) inside = true;
                } else {
                  const d = Math.hypot(px - shape.cx - ox, py - shape.cy - oy);
                  if (shape.t === "d" ? d <= shape.r : Math.abs(d - shape.r) <= halfWidth) {
                    inside = true;
                  }
                }
                if (inside) break;
              }
            }
          }
          if (inside) hits++;
        }
      }
      const i = (y * size + x) * 4;
      const a = Math.round((hits / (SS * SS)) * 255);
      // Predmultiplikovanie sa nerobí – MapLibre aj sprite čakajú priamu alfu.
      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
      data[i + 3] = a;
    }
  }

  return { width: size, height: size, data };
}
