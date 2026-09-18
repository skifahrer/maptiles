/**
 * Štítok čísla cesty podľa SIETE – „D1" na červenej, „E 75" na zelenej,
 * chorvátsky „A1" v zelenom šesťuholníku.
 *
 * Tvary a farby sú prevzaté z OSM Americana (`src/js/shield_defs.js`, CC0);
 * rozpis, čo sa prebralo a čo nie, je v `docs/stitky-ciest.md`.
 */

/** Výška štítka v pixeloch pri `pixelRatio` 1 – `shieldSize` Americany. */
export const ROUTE_SHIELD_SIZE = 20;

/** Priehľadný okraj, aby sa hrana pri škálovaní nemala o čo oprieť. */
export const ROUTE_SHIELD_PAD = 1;

/** Prefix mien v sprite – podľa mena musí byť vidieť, kto obrázok upiekol. */
export const ROUTE_SHIELD_PREFIX = "route-shield";

const OUTLINE = 1;
const DEFAULT_WIDTH = 24;
const RRECT_RADIUS = 2;

/** Paleta Americany (Pantone čísla dopravných značiek). */
export const ROUTE_SHIELD_COLORS = {
  black: "#000000",
  blue: "#003f87",
  brown: "#693f23",
  green: "#006747",
  orange: "#f38f00",
  red: "#bf2033",
  white: "#ffffff",
  yellow: "#ffcd00"
};

const rrect = (fill, stroke, text = stroke, width = 0) =>
  ({ shape: "rrect", fill, stroke, text, width });
const hex = (offset, fill, stroke, text = stroke, width = 0) =>
  ({ shape: "hex", offset, fill, stroke, text, width });
const oct = (offset, angle, fill, stroke, text = stroke, width = 0) =>
  ({ shape: "oct", offset, angle, fill, stroke, text, width });

/**
 * Sieť z `route_*_network` → štítok. Sieť, ktorá tu nie je, dostane klasický
 * štítok podľa triedy cesty – tá cesta je záloha, nie výnimka.
 */
export const ROUTE_SHIELDS = {
  "e-road": rrect("green", "white"),

  "AL:A": oct(2, 10, "green", "white"),
  "AT:A-road": rrect("blue", "white"),
  "AT:S-road": rrect("blue", "white"),
  "AX:main": rrect("red", "white"),
  "AX:province": rrect("blue", "white"),
  "ba:Autoceste": rrect("green", "white", "white", 34),
  "ba:Magistralne ceste": rrect("blue", "white", "white", 34),
  "BE:A-road": rrect("white", "black"),
  "BE:B-road": rrect("white", "black"),
  "BE:N-road": rrect("blue", "white"),
  "BE:R-road": rrect("white", "black"),
  "BE:VLG:Ring_Antwerpen": rrect("yellow", "black"),
  "bg:motorway": rrect("green", "white", "white", 34),
  "bg:national": rrect("blue", "white", "white", 34),
  "by:national": rrect("red", "white"),
  "ch:national": rrect("blue", "white"),
  "CY:B": rrect("blue", "yellow", "yellow"),
  "CY:E": rrect("blue", "yellow", "yellow"),
  "CY:F": rrect("blue", "yellow", "yellow"),
  "CY:motorway": hex(2, "green", "yellow", "yellow"),
  "CY:national": rrect("blue", "white", "white"),
  // veľké písmená = diaľnica, malé = cesta I. triedy; v OSM sú obe
  "CZ:national": rrect("red", "white", "white", 34),
  "cz:national": rrect("blue", "white", "white", 34),
  "DE:national": rrect("yellow", "black", "black", 34),
  "ee:national": rrect("red", "white"),
  "ES:A-road": rrect("blue", "white"),
  "fi:link": rrect("blue", "white"),
  "fi:national": rrect("red", "white"),
  "fi:regional": rrect("white", "black"),
  "fi:trunk": rrect("yellow", "black"),
  "FO": rrect("white", "black", "black", 34),
  "FR:A-road": rrect("red", "white"),
  "FR:N-road": rrect("red", "white"),
  "GR:motorway": hex(3, "green", "white", "white", 34),
  "GR:national": rrect("blue", "white", "white", 34),
  "HR:Autoceste": hex(3, "green", "white", "white", 34),
  "HR:Državne ceste": rrect("blue", "white", "white"),
  "HR:Lokalne ceste": rrect("white", "black", "black"),
  "HR:Županijske ceste": rrect("yellow", "black", "black"),
  "IS": rrect("white", "black", "black", 34),
  "IT:A-road": oct(2, 10, "green", "white"),
  "lt:national": rrect("red", "white"),
  "LU:A-road": rrect("blue", "white"),
  "LU:B-road": rrect("blue", "white"),
  "LU:CR-road": rrect("yellow", "black"),
  "LU:N-road": rrect("red", "white"),
  "lv:national": rrect("red", "white", "white", 34),
  "lv:regional": rrect("blue", "white", "white", 34),
  "ME:Magistralni putevi": rrect("blue", "white", "white", 34),
  "mk:national": hex(3, "green", "white", "white", 34),
  "NL:A": rrect("red", "white"),
  "NL:N": rrect("yellow", "black"),
  "omt-gb-motorway": rrect("blue", "white"),
  "omt-gb-primary": rrect("white", "black"),
  "omt-gb-trunk": rrect("green", "white", "yellow"),
  "omt-ie-motorway": rrect("blue", "white"),
  "omt-ie-national": rrect("green", "white", "yellow"),
  "omt-ie-regional": rrect("white", "black"),
  "PL:expressway": rrect("red", "white", "white", 34),
  "PL:motorway": rrect("red", "white", "white", 34),
  "pl:national": rrect("red", "white"),
  "PT:national": rrect("blue", "white"),
  "PT:regional": rrect("blue", "white"),
  "RO:A": rrect("green", "white", "white", 34),
  "RS:motorway": hex(3, "green", "white", "white", 34),
  "ru:national": rrect("blue", "white"),
  "SI:AC": hex(3, "green", "white", "white", 34),
  "sk:national": rrect("red", "white", "white", 34),
  "ua:international": rrect("blue", "white"),
  "XK:motorway": hex(3, "green", "white", "white", 34),

  // Americana ich nemá, a bez nich by na slovenskej mape ostal štítok podľa
  // siete len diaľniciam: I. trieda má modrú tabuľku, II./III. bielu
  "sk:primary": rrect("blue", "white", "white", 34),
  "sk:regional": rrect("white", "black", "black", 34)
};

export const ROUTE_SHIELD_NETWORKS = Object.keys(ROUTE_SHIELDS);

/** Meno obrázka v sprite; rovnaký recept = rovnaký obrázok. */
export function routeShieldName(network) {
  const def = ROUTE_SHIELDS[network];
  if (!def) return null;
  const casti = [ROUTE_SHIELD_PREFIX, def.shape, def.fill, def.stroke];
  if (def.width) casti.push(`w${def.width}`);
  if (def.offset) casti.push(`o${def.offset}`);
  if (def.angle) casti.push(`a${def.angle}`);
  return casti.join("-");
}

/** Farba čísla na štítku tej siete. */
export function routeShieldTextColor(network) {
  const def = ROUTE_SHIELDS[network];
  return def ? ROUTE_SHIELD_COLORS[def.text] : null;
}

/** Recepty bez opakovania – toľko obrázkov sa pečie do spritu. */
export function routeShieldRecipes() {
  const out = new Map();
  for (const network of ROUTE_SHIELD_NETWORKS) {
    const name = routeShieldName(network);
    if (!out.has(name)) out.set(name, { name, def: ROUTE_SHIELDS[network] });
  }
  return [...out.values()];
}

function rozlozFarbu(hex6) {
  const h = String(hex6).replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) || 0);
}

/** Vzdialenosť od zaobleného obdĺžnika (záporná vnútri). */
function rrectDistance(px, py, w, h, r) {
  const dx = Math.abs(px - w / 2) - (w / 2 - r);
  const dy = Math.abs(py - h / 2) - (h / 2 - r);
  const vx = Math.max(dx, 0);
  const vy = Math.max(dy, 0);
  return Math.sqrt(vx * vx + vy * vy) + Math.min(Math.max(dx, dy), 0) - r;
}

/** Vrcholy šesť- a osemuholníka Americany (hrot hore aj dole). */
function polygon(def, w, h) {
  const o = (def.offset || 0);
  if (def.shape === "hex") {
    return [[w / 2, 0], [w, o], [w, h - o], [w / 2, h], [0, h - o], [0, o]];
  }
  const t = Math.tan(((def.angle || 0) * Math.PI) / 180);
  const dx = (h / 2 - o) * t;
  return [[w / 2, h], [dx, h - o], [0, h / 2], [dx, o],
          [w / 2, 0], [w - dx, o], [w, h / 2], [w - dx, h - o]];
}

/** Presné vnútri konvexného mnohouholníka, vonku dosť presné na jeden pixel. */
function polygonDistance(px, py, pts, flip) {
  let best = -Infinity;
  for (let i = 0; i < pts.length; i += 1) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[(i + 1) % pts.length];
    const ex = bx - ax;
    const ey = by - ay;
    const len = Math.hypot(ex, ey) || 1;
    const d = ((px - ax) * ey - (py - ay) * ex) / len;
    if (d > best) best = d;
  }
  return flip ? -best : best;
}

function orientationFlip(pts) {
  let area = 0;
  for (let i = 0; i < pts.length; i += 1) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[(i + 1) % pts.length];
    area += ax * by - bx * ay;
  }
  return area < 0;
}

/**
 * Hotový farebný obrázok štítka (nie SDF – obrys má vlastnú farbu).
 *
 * @returns {{width:number, height:number, data:Uint8Array,
 *            stretchX?:number[][], stretchY?:number[][], content?:number[]}}
 */
export function renderRouteShield(def, pixelRatio = 1) {
  const r = pixelRatio;
  const pad = ROUTE_SHIELD_PAD * r;
  const line = OUTLINE * r;
  const w = (def.width || DEFAULT_WIDTH) * r;
  const h = ROUTE_SHIELD_SIZE * r;
  const width = w + 2 * pad;
  const height = h + 2 * pad;

  const pole = rozlozFarbu(ROUTE_SHIELD_COLORS[def.fill]);
  const obrys = rozlozFarbu(ROUTE_SHIELD_COLORS[def.stroke]);
  const data = new Uint8Array(width * height * 4);

  const pts = def.shape === "rrect" ? null : polygon(def, w, h);
  const flip = pts ? orientationFlip(pts) : false;
  const radius = Math.min(RRECT_RADIUS * r, Math.min(w, h) / 2);
  const kryt = (d, hranica) => Math.max(0, Math.min(1, 0.5 - (d - hranica)));

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const fx = x + 0.5 - pad;
      const fy = y + 0.5 - pad;
      const d = pts
        ? polygonDistance(fx, fy, pts, flip)
        : rrectDistance(fx, fy, w, h, radius);
      const aVonku = kryt(d, 0);
      const aPole = kryt(d, -line);

      const i = (y * width + x) * 4;
      for (let k = 0; k < 3; k += 1) {
        const v = obrys[k] * (aVonku - aPole) + pole[k] * aPole;
        data[i + k] = Math.round(Math.min(255, v / Math.max(aVonku, 1e-6)));
      }
      data[i + 3] = Math.round(255 * aVonku);
    }
  }

  // Naťahuje sa len rovná časť hrán. Hrot šesť- a osemuholníka rovnú časť
  // nemá, takže tie sa škálujú celé – tvar ostane, len sa roztiahne.
  if (pts) return { width, height, data };
  const od = pad + radius;
  return {
    width,
    height,
    data,
    stretchX: [[od, Math.max(od + 1, width - pad - radius)]],
    stretchY: [[od, Math.max(od + 1, height - pad - radius)]],
    content: [pad + line, pad + line, width - pad - line, height - pad - line]
  };
}
