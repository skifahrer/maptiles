/**
 * Dependency-free vector drawing into RGBA – shapes on a grid of points, output in pixels.
 */

const SS = 4;

export function color(hex, alpha = 1) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).concat(alpha);
}

export const rect = (x, y, w, h) => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];

export function circle(cx, cy, r, n = 48) {
  return Array.from({ length: n }, (_, i) => {
    const a = (2 * Math.PI * i) / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });
}

export function roundedRect(x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  const corners = [[x + w - rr, y + rr, -90], [x + w - rr, y + h - rr, 0],
                [x + rr, y + h - rr, 90], [x + rr, y + rr, 180]];
  return corners.flatMap(([cx, cy, from]) => arc(cx, cy, rr, from, from + 90, 8));
}

/** Arc in degrees, clockwise (y goes down). */
export function arc(cx, cy, r, from, to, n = 16) {
  return Array.from({ length: n + 1 }, (_, i) => {
    const a = ((from + ((to - from) * i) / n) * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });
}

function inside(pt, poly) {
  let isIn = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > pt[1] !== yj > pt[1]
        && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) isIn = !isIn;
  }
  return isIn;
}

function dist2(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
  const x = a[0] + t * dx - p[0];
  const y = a[1] + t * dy - p[1];
  return x * x + y * y;
}

function onLine(pt, pts, half2, closed) {
  const n = pts.length;
  for (let i = 0; i < n - (closed ? 0 : 1); i++) {
    if (dist2(pt, pts[i], pts[(i + 1) % n]) <= half2) return true;
  }
  return false;
}

/**
 * Draws `ops` in order over each other: `{fill: poly}` or `{stroke: pts, width, closed}`.
 * Sizes are in points; `ratio` is the pixelRatio.
 */
export function draw(width, height, ops, ratio = 1) {
  const w = Math.round(width * ratio);
  const h = Math.round(height * ratio);
  const data = new Float64Array(w * h * 4);
  for (const op of ops) {
    const [r, g, b, a] = op.color;
    const half2 = op.stroke ? (op.width / 2) ** 2 : 0;
    const hit = op.stroke
      ? (p) => onLine(p, op.stroke, half2, op.closed)
      : (p) => inside(p, op.fill);
    const pts = op.stroke || op.fill;
    const margin = op.stroke ? op.width / 2 : 0;
    const x0 = Math.max(0, Math.floor((Math.min(...pts.map((q) => q[0])) - margin) * ratio));
    const x1 = Math.min(w, Math.ceil((Math.max(...pts.map((q) => q[0])) + margin) * ratio));
    const y0 = Math.max(0, Math.floor((Math.min(...pts.map((q) => q[1])) - margin) * ratio));
    const y1 = Math.min(h, Math.ceil((Math.max(...pts.map((q) => q[1])) + margin) * ratio));
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        let n = 0;
        for (let sy = 0; sy < SS; sy++) {
          for (let sx = 0; sx < SS; sx++) {
            if (hit([(x + (sx + 0.5) / SS) / ratio, (y + (sy + 0.5) / SS) / ratio])) n++;
          }
        }
        if (!n) continue;
        const k = (a * n) / (SS * SS);
        const i = (y * w + x) * 4;
        // premultiplied by alpha, converted back at the end
        data[i] = r * k + data[i] * (1 - k);
        data[i + 1] = g * k + data[i + 1] * (1 - k);
        data[i + 2] = b * k + data[i + 2] * (1 - k);
        data[i + 3] = k + data[i + 3] * (1 - k);
      }
    }
  }
  const out = new Uint8Array(w * h * 4);
  for (let i = 0; i < w * h * 4; i += 4) {
    const a = data[i + 3];
    if (!a) continue;
    for (let c = 0; c < 3; c++) out[i + c] = Math.round(Math.min(255, data[i + c] / a));
    out[i + 3] = Math.round(a * 255);
  }
  return { width: w, height: h, data: out };
}
