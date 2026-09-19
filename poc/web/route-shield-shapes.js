/**
 * Tvary štítkov čísel ciest – port kresliacich funkcií OSM Americana
 * (`shieldlib/src/shield_canvas_draw.ts`, CC0) bez canvasu.
 *
 * Americana kreslí do `canvas`. Pipeline canvas nemá a obrázok musí vzniknúť
 * pri builde, tak sa tá istá cesta poskladá do lomenej čiary a vyplní sa sama.
 * Rozpis v `docs/stitky-ciest.md`.
 */

/** Výška štítka pri `pixelRatio` 1 – `shieldSize` Americany. */
export const SHIELD_SIZE = 20;

/** Šírka, keď ju definícia nedáva napevno; Americana ju berie z dĺžky čísla. */
const DEFAULT_WIDTH = 24;
const MAX_WIDTH = 34;

/** Cesta ako lomená čiara; `arcTo` a `bezierCurveTo` sa rovno rozsekajú. */
class Path {
  constructor() {
    this.pts = [];
  }

  get last() {
    return this.pts[this.pts.length - 1];
  }

  point(x, y) {
    const p = this.last;
    if (p && Math.abs(p[0] - x) < 1e-9 && Math.abs(p[1] - y) < 1e-9) return;
    this.pts.push([x, y]);
  }

  moveTo(x, y) {
    this.point(x, y);
  }

  lineTo(x, y) {
    this.point(x, y);
  }

  /** Oblúk vpísaný do rohu – tá istá dohoda, akú má canvas. */
  arcTo(x1, y1, x2, y2, r) {
    const [x0, y0] = this.last;
    const a1 = Math.atan2(y0 - y1, x0 - x1);
    const a2 = Math.atan2(y2 - y1, x2 - x1);
    let uhol = a2 - a1;
    while (uhol <= -Math.PI) uhol += 2 * Math.PI;
    while (uhol > Math.PI) uhol -= 2 * Math.PI;
    const pol = Math.abs(uhol) / 2;
    if (!(r > 0) || pol < 1e-6 || Math.PI - pol * 2 < 1e-6) {
      this.point(x1, y1);
      return;
    }
    const odsun = r / Math.tan(pol);
    const stred = [
      x1 + Math.cos(a1 + uhol / 2) * (r / Math.sin(pol)),
      y1 + Math.sin(a1 + uhol / 2) * (r / Math.sin(pol))
    ];
    const zac = [x1 + Math.cos(a1) * odsun, y1 + Math.sin(a1) * odsun];
    const kon = [x1 + Math.cos(a2) * odsun, y1 + Math.sin(a2) * odsun];
    this.point(zac[0], zac[1]);

    const od = Math.atan2(zac[1] - stred[1], zac[0] - stred[0]);
    const po = Math.atan2(kon[1] - stred[1], kon[0] - stred[0]);
    let sweep = po - od;
    while (sweep <= -Math.PI) sweep += 2 * Math.PI;
    while (sweep > Math.PI) sweep -= 2 * Math.PI;
    const krokov = Math.max(2, Math.ceil(Math.abs(sweep) / 0.15));
    for (let i = 1; i <= krokov; i += 1) {
      const a = od + (sweep * i) / krokov;
      this.point(stred[0] + Math.cos(a) * r, stred[1] + Math.sin(a) * r);
    }
  }

  bezierCurveTo(x1, y1, x2, y2, x3, y3) {
    const [x0, y0] = this.last;
    const krokov = 24;
    for (let i = 1; i <= krokov; i += 1) {
      const t = i / krokov;
      const u = 1 - t;
      this.point(
        u * u * u * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
        u * u * u * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3
      );
    }
  }

  ellipse(cx, cy, rx, ry) {
    const krokov = 96;
    for (let i = 0; i <= krokov; i += 1) {
      const a = (2 * Math.PI * i) / krokov;
      this.point(cx + Math.cos(a) * rx, cy + Math.sin(a) * ry);
    }
  }
}

/** Šírka štítka v pixeloch pri `pixelRatio` 1. */
export function blankWidth(def) {
  if (def.width) return def.width;
  const tan = Math.tan(((def.sideAngle || 0) * Math.PI) / 180);
  let w = DEFAULT_WIDTH;
  switch (def.shape) {
    case "pentagon":
      w += ((SHIELD_SIZE - (def.yOffset || 0)) * tan) / 2;
      break;
    case "trapezoid":
      w += (SHIELD_SIZE * tan) / 2;
      break;
    case "triangle":
      w += 2;
      break;
    case "diamond":
    case "hexagonHorizontal":
      w += 4;
      break;
    default:
      break;
  }
  return Math.min(MAX_WIDTH, Math.round(w * 2) / 2);
}

/** Výška štítka; kosoštvorec je jediný vyšší než ostatné. */
export function blankHeight(def) {
  return def.shape === "diamond" ? SHIELD_SIZE + 4 : SHIELD_SIZE;
}

/** Ktoré tvary majú rovnú časť hrany, a teda sa dajú deväťdielne naťahovať. */
export function stretchable(def) {
  return def.shape === "roundedRectangle" || def.shape === "pill";
}

/**
 * Obrys štítka ako lomená čiara v pixeloch podľa `r` (= pixelRatio).
 * Kroky sú prepísané z Americany jeden k jednému, aby sa dal rozdiel dohľadať.
 */
export function outline(def, r) {
  const p = new Path();
  const line = r;                              // outlineWidth je vždy 1
  const half = line / 2;
  const width = blankWidth(def) * r;
  const height = blankHeight(def) * r;
  const size = SHIELD_SIZE * r;
  const radius = (def.radius || 0) * r;
  const offset = (def.yOffset || 0) * r;
  const uhol = ((def.sideAngle || 0) * Math.PI) / 180;
  const sin = Math.sin(uhol);
  const cos = Math.cos(uhol);
  const tan = Math.tan(uhol);

  switch (def.shape) {
    case "ellipse": {
      p.ellipse(width / 2, size / 2, width / 2 - line, size / 2 - line);
      break;
    }
    case "pill":
    case "roundedRectangle": {
      const rr = def.shape === "pill" ? size / 2 : radius;
      const x0 = half;
      const x1 = half + rr;
      const x2 = width - half - rr;
      const x3 = width - half;
      const y0 = half;
      const y1 = half + rr;
      const y2 = size - half - rr;
      const y3 = size - half;
      p.moveTo(x2, y0);
      p.arcTo(x3, y0, x3, y1, rr);
      p.arcTo(x3, y3, x2, y3, rr);
      p.arcTo(x0, y3, x0, y2, rr);
      p.arcTo(x0, y0, x1, y0, rr);
      break;
    }
    case "escutcheon": {
      const x0 = half;
      const x5 = width - half;
      const y0 = half;
      const y5 = size - half;
      const x1 = x0 + radius;
      const x3 = (x0 + x5) / 2;
      const y1 = y0 + radius;
      const y2 = y5 - offset;
      const x2 = (2 * x0 + x3) / 3;
      const x4 = (x3 + 2 * x5) / 3;
      const y3 = (y2 + y5) / 2;
      const y4 = (y3 + 2 * y5) / 3;
      p.moveTo(x3, y5);
      p.bezierCurveTo(x2, y4, x0, y3, x0, y2);
      p.arcTo(x0, y0, x1, y0, radius);
      p.arcTo(x5, y0, x5, y1, radius);
      p.lineTo(x5, y2);
      p.bezierCurveTo(x5, y3, x4, y4, x3, y5);
      break;
    }
    case "fishhead": {
      const znak = def.pointUp ? -1 : 1;
      const x0 = half;
      const x8 = width - half;
      const y0 = def.pointUp ? size - half : half;
      const y6 = def.pointUp ? half : size - half;
      const x1 = x0 + r;
      const x2 = x0 + 2.5 * r;
      const x4 = (x0 + x8) / 2;
      const x6 = x8 - 2.5 * r;
      const x7 = x8 - r;
      const y1 = y0 + znak * 2 * r;
      const y2 = y0 + znak * 4.5 * r;
      const y3 = y0 + znak * 7 * r;
      const y4 = y6 - znak * 6 * r;
      const y5 = y6 - znak * r;
      const x3 = (x0 + x4) / 2;
      const x5 = (x4 + x8) / 2;
      p.moveTo(x4, y6);
      p.bezierCurveTo(x3, y5, x0, y4, x0, y3);
      p.bezierCurveTo(x0, y2, x1, y1, x2, y0);
      p.lineTo(x6, y0);
      p.bezierCurveTo(x7, y1, x8, y2, x8, y3);
      p.bezierCurveTo(x8, y4, x5, y5, x4, y6);
      break;
    }
    case "triangle": {
      const znak = def.pointUp ? -1 : 1;
      const x0 = half;
      const x8 = width - half;
      const y0 = def.pointUp ? size - half : half;
      const y5 = def.pointUp ? half : size - half;
      const x2 = x0 + radius;
      const x4 = (x0 + x8) / 2;
      const x6 = x8 - radius;
      const y1 = y0 + znak * radius;
      const a = Math.atan((x4 - x2) / Math.abs(y5 - radius - y1));
      const x1 = x2 - radius * Math.cos(a);
      const x3 = x4 - radius * Math.tan(Math.PI / 4 - a / 2);
      const x5 = x4 + radius * Math.tan(Math.PI / 4 - a / 2);
      const x7 = x6 + radius * Math.cos(a);
      const y2 = y1 + znak * radius * Math.tan(a / 2);
      const y3 = y1 + znak * radius * Math.sin(a);
      p.moveTo(x4, y5);
      p.arcTo(x3, y5, x1, y3, radius);
      p.arcTo(x0, y2, x0, y1, radius);
      p.arcTo(x0, y0, x2, y0, radius);
      p.arcTo(x8, y0, x8, y1, radius);
      p.arcTo(x8, y2, x7, y3, radius);
      p.arcTo(x5, y5, x4, y5, radius);
      break;
    }
    case "trapezoid": {
      const znak = def.shortSideUp ? -1 : 1;
      const x0 = half;
      const x9 = width - half;
      const y0 = def.shortSideUp ? size - half : half;
      const y3 = def.shortSideUp ? half : size - half;
      const y1 = y0 + znak * radius * (1 + sin);
      const y2 = y3 - znak * radius * (1 - sin);
      const x1 = x0 + (y1 - y0) * tan;
      const x2 = x1 + radius * cos;
      const x3 = x0 + znak * (y2 - y0) * tan;
      const x4 = x0 + znak * (y3 - y0) * tan;
      const x5 = x3 + znak * radius * cos;
      const x6 = width - x4;
      const x7 = width - x3;
      const x8 = width - x2;
      p.moveTo(x8, y0);
      p.arcTo(x9, y0, x7, y2, radius);
      p.arcTo(x6, y3, x5, y3, radius);
      p.arcTo(x4, y3, x1, y1, radius);
      p.arcTo(x0, y0, x8, y0, radius);
      break;
    }
    case "diamond": {
      const x0 = half;
      const x8 = width - half;
      const y0 = half;
      const y8 = height - half;
      const x4 = (x0 + x8) / 2;
      const y4 = (y0 + y8) / 2;
      const a = Math.atan((x4 - radius - x0) / (y8 - radius - y4));
      const sn = Math.sin(a);
      const cs = Math.cos(a);
      const x1 = x0 + radius * (1 - cs);
      const x2 = x4 - radius * cs;
      const x3 = x4 - radius * Math.tan(Math.PI / 4 - a / 2);
      const x5 = x4 + radius * Math.tan(Math.PI / 4 - a / 2);
      const x6 = x4 + radius * cs;
      const x7 = x8 - radius * (1 - cs);
      const y1 = y0 + radius * (1 - sn);
      const y2 = y4 - radius * sn;
      const y3 = y4 - radius * Math.tan(a / 2);
      const y5 = y4 + radius * Math.tan(a / 2);
      const y6 = y4 + radius * sn;
      const y7 = y8 - radius * (1 - sn);
      p.moveTo(x4, y8);
      p.arcTo(x3, y8, x1, y6, radius);
      p.arcTo(x0, y5, x0, y4, radius);
      p.arcTo(x0, y3, x2, y1, radius);
      p.arcTo(x3, y0, x4, y0, radius);
      p.arcTo(x5, y0, x7, y2, radius);
      p.arcTo(x8, y3, x8, y4, radius);
      p.arcTo(x8, y5, x6, y7, radius);
      p.arcTo(x5, y8, x4, y8, radius);
      break;
    }
    case "pentagon": {
      const hore = def.pointUp !== false;
      const znak = hore ? -1 : 1;
      const r1 = (def.radius1 || 0) * r;
      const r2 = (def.radius2 || 0) * r;
      const x0 = half;
      const x8 = width - half;
      const y0 = hore ? size - half : half;
      const y3 = hore ? half : size - half;
      const y2 = y3 - znak * offset;
      const x2 = x0 + znak * (y2 - y0) * tan;
      const x4 = (x0 + x8) / 2;
      const x6 = x8 - znak * (y2 - y0) * tan;
      const uhol1 = (Math.PI / 2 - Math.atan(offset / (x4 - x0)) + uhol) / 2;
      const t1 = Math.tan(uhol1);
      const t2 = Math.tan((Math.PI / 2 - uhol) / 2);
      const x1 = x0 + r1 * t1 * sin;
      const x3 = x2 + r2 * t2;
      const x5 = x6 - r2 * t2;
      const x7 = x8 - r1 * t1 * sin;
      const y1 = y2 - znak * r1 * t1 * cos;
      p.moveTo(x4, y3);
      p.arcTo(x0, y2, x1, y1, r1);
      p.arcTo(x2, y0, x3, y0, r2);
      p.lineTo(x5, y0);
      p.arcTo(x6, y0, x7, y1, r2);
      p.arcTo(x8, y2, x4, y3, r1);
      break;
    }
    case "hexagonVertical": {
      const x0 = half;
      const x2 = width - half;
      const y0 = half;
      const y5 = size - half;
      const x1 = (x0 + x2) / 2;
      const y1 = y0 + offset;
      const y4 = y5 - offset;
      const dot = radius * Math.tan(Math.PI / 4 - Math.asin(offset / (x1 - x0)) / 2);
      const y2 = y1 + dot;
      const y3 = y4 - dot;
      p.moveTo(x1, y5);
      p.arcTo(x0, y4, x0, y3, radius);
      p.arcTo(x0, y1, x1, y0, radius);
      p.lineTo(x1, y0);
      p.arcTo(x2, y1, x2, y2, radius);
      p.arcTo(x2, y4, x1, y5, radius);
      break;
    }
    case "hexagonHorizontal": {
      const t = Math.tan(Math.PI / 4 - uhol / 2);
      const x0 = half;
      const x9 = width - half;
      const y0 = half;
      const y6 = size - half;
      const y3 = (y0 + y6) / 2;
      const y1 = y0 + radius * t * cos;
      const y2 = y3 - radius * sin;
      const y4 = y3 + radius * sin;
      const y5 = y6 - radius * t * cos;
      const x1 = x0 + (y3 - y2) * tan;
      const x3 = x0 + (y3 - y0) * tan;
      const x6 = x9 - (y3 - y0) * tan;
      const x8 = x9 - (y3 - y2) * tan;
      const x2 = x3 - radius * t * sin;
      const x4 = x3 + radius * t;
      const x5 = x6 - radius * t;
      const x7 = x6 + radius * t * sin;
      p.moveTo(x4, y0);
      p.arcTo(x6, y0, x7, y1, radius);
      p.arcTo(x9, y3, x8, y4, radius);
      p.arcTo(x6, y6, x5, y6, radius);
      p.arcTo(x3, y6, x2, y5, radius);
      p.arcTo(x0, y3, x1, y2, radius);
      p.arcTo(x3, y0, x4, y0, radius);
      break;
    }
    case "octagonVertical": {
      const x0 = half;
      const x10 = width - half;
      const y0 = half;
      const y10 = size - half;
      const x1 = x0 + radius * tan * sin;
      const x5 = (x0 + x10) / 2;
      const x9 = x10 - radius * tan * sin;
      const y2 = y0 + offset;
      const y5 = (y0 + y10) / 2;
      const y8 = y10 - offset;
      const x3 = x0 + (y5 - y2) * tan;
      const x7 = x10 - (y5 - y2) * tan;
      const y4 = y5 - radius * tan * cos;
      const y6 = y5 + radius * tan * cos;
      const uhol2 = Math.atan(offset / (x5 - x3));
      const polovica = (Math.PI / 2 - uhol - uhol2) / 2;
      const dx = (radius * Math.cos(uhol + polovica)) / Math.cos(polovica);
      const dy = (radius * Math.sin(uhol + polovica)) / Math.cos(polovica);
      const x2 = x3 + dx - radius * cos;
      const x4 = x3 + dx - radius * Math.sin(uhol2);
      const x6 = x7 - dx + radius * Math.sin(uhol2);
      const x8 = x7 - dx + radius * cos;
      const y1 = y2 + dy - radius * Math.cos(uhol2);
      const y3 = y2 + dy - radius * sin;
      const y7 = y8 - dy + radius * sin;
      const y9 = y8 - dy + radius * Math.cos(uhol2);
      p.moveTo(x5, y10);
      p.arcTo(x3, y8, x2, y7, radius);
      p.arcTo(x0, y5, x1, y4, radius);
      p.arcTo(x3, y2, x4, y1, radius);
      p.lineTo(x5, y0);
      p.arcTo(x7, y2, x8, y3, radius);
      p.arcTo(x10, y5, x9, y6, radius);
      p.arcTo(x7, y8, x6, y9, radius);
      p.lineTo(x5, y10);
      break;
    }
    default:
      return null;
  }
  return p.pts;
}
