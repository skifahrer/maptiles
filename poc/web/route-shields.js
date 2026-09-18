/**
 * Štítok čísla cesty podľa SIETE – „D1" na červenej, „E 75" na zelenej,
 * chorvátske „A1" v zelenom šesťuholníku.
 *
 * Tabuľka sieť → štítok je v `route-shield-defs.js` (generovaná z OSM
 * Americana), tvary v `route-shield-shapes.js`. Tu z toho vzniká obrázok pre
 * sprite a meno, ktorým si ho štýl pýta. Rozpis v `docs/stitky-ciest.md`.
 */
import { ROUTE_SHIELD_SHAPES, ROUTE_SHIELD_BY_NETWORK } from "./route-shield-defs.js";
import { SHIELD_SIZE, blankWidth, blankHeight, stretchable, outline }
  from "./route-shield-shapes.js";

export { SHIELD_SIZE as ROUTE_SHIELD_SIZE };

/** Priehľadný okraj, aby sa hrana pri škálovaní nemala o čo oprieť. */
export const ROUTE_SHIELD_PAD = 1;

/** Prefix mien v sprite – podľa mena musí byť vidieť, kto obrázok upiekol. */
export const ROUTE_SHIELD_PREFIX = "route-shield";

export const ROUTE_SHIELD_NETWORKS = Object.keys(ROUTE_SHIELD_BY_NETWORK);

/** Recept tej siete, alebo `null`. */
export function routeShieldDef(network) {
  const i = ROUTE_SHIELD_BY_NETWORK[network];
  return i === undefined ? null : ROUTE_SHIELD_SHAPES[i];
}

/** Meno obrázka v sprite; rovnaký recept = rovnaký obrázok. */
export function routeShieldName(network) {
  const i = ROUTE_SHIELD_BY_NETWORK[network];
  return i === undefined ? null : recipeName(ROUTE_SHIELD_SHAPES[i], i);
}

const recipeName = (def, i) => `${ROUTE_SHIELD_PREFIX}-${def.shape}-${i}`;

/** Farba čísla na štítku tej siete. */
export function routeShieldTextColor(network) {
  return routeShieldDef(network)?.text || null;
}

/** Recepty bez opakovania – toľko obrázkov sa pečie do spritu. */
export function routeShieldRecipes() {
  return ROUTE_SHIELD_SHAPES.map((def, i) => ({ name: recipeName(def, i), def }));
}

function rozlozFarbu(hex6) {
  const h = String(hex6 || "#000000").replace("#", "");
  const n = h.length === 3 ? h.split("").map((ch) => ch + ch).join("") : h;
  return [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) || 0);
}

/** Vzdialenosť bodu od lomenej čiary a či je vnútri (párny počet prekrížení). */
function distance(px, py, pts) {
  let best = Infinity;
  let vnutri = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
    const [ax, ay] = pts[j];
    const [bx, by] = pts[i];
    const ex = bx - ax;
    const ey = by - ay;
    const len2 = ex * ex + ey * ey;
    const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * ex + (py - ay) * ey) / len2)) : 0;
    const dx = px - (ax + ex * t);
    const dy = py - (ay + ey * t);
    const d2 = dx * dx + dy * dy;
    if (d2 < best) best = d2;
    if ((ay > py) !== (by > py) && px < ax + ((py - ay) / (by - ay)) * ex) vnutri = !vnutri;
  }
  return vnutri ? -Math.sqrt(best) : Math.sqrt(best);
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
  const line = r;
  const pts = outline(def, r);
  const width = Math.round(blankWidth(def) * r) + 2 * pad;
  const height = Math.round(blankHeight(def) * r) + 2 * pad;
  const data = new Uint8Array(width * height * 4);
  if (!pts) return { width, height, data };

  const pole = rozlozFarbu(def.fill);
  const obrys = def.stroke ? rozlozFarbu(def.stroke) : null;
  const kryt = (d, hranica) => Math.max(0, Math.min(1, 0.5 - (d - hranica)));

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const d = distance(x + 0.5 - pad, y + 0.5 - pad, pts);
      const aVonku = kryt(d, 0);
      if (aVonku <= 0) continue;
      const aPole = obrys ? kryt(d, -line) : aVonku;

      const i = (y * width + x) * 4;
      for (let k = 0; k < 3; k += 1) {
        const v = (obrys ? obrys[k] : pole[k]) * (aVonku - aPole) + pole[k] * aPole;
        data[i + k] = Math.round(Math.min(255, v / aVonku));
      }
      data[i + 3] = Math.round(255 * aVonku);
    }
  }

  // Naťahuje sa len rovná časť hrán; tvar s hrotom rovnú časť nemá a škáluje
  // sa celý – ostane sebou, len sa roztiahne.
  if (!stretchable(def)) return { width, height, data };
  const rr = (def.shape === "pill" ? SHIELD_SIZE / 2 : def.radius || 0) * r;
  const od = pad + rr;
  return {
    width,
    height,
    data,
    stretchX: [[od, Math.max(od + 1, width - pad - rr)]],
    stretchY: [[od, Math.max(od + 1, height - pad - rr)]],
    content: [pad + line, pad + line, width - pad - line, height - pad - line]
  };
}
