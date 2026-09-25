/**
 * Vektorová kresba do RGBA bez závislostí – tvary na mriežke v bodoch, výstup v pixeloch.
 */

const SS = 4;

export function farba(hex, alfa = 1) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).concat(alfa);
}

export const obdlznik = (x, y, w, h) => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];

export function kruh(cx, cy, r, n = 48) {
  return Array.from({ length: n }, (_, i) => {
    const a = (2 * Math.PI * i) / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });
}

export function zaoblenyObdlznik(x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  const rohy = [[x + w - rr, y + rr, -90], [x + w - rr, y + h - rr, 0],
                [x + rr, y + h - rr, 90], [x + rr, y + rr, 180]];
  return rohy.flatMap(([cx, cy, od]) => obluk(cx, cy, rr, od, od + 90, 8));
}

/** Oblúk v stupňoch, v smere hodinových ručičiek (y ide nadol). */
export function obluk(cx, cy, r, od, po, n = 16) {
  return Array.from({ length: n + 1 }, (_, i) => {
    const a = ((od + ((po - od) * i) / n) * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });
}

function vnutri(bod, poly) {
  let dnu = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > bod[1] !== yj > bod[1]
        && bod[0] < ((xj - xi) * (bod[1] - yi)) / (yj - yi) + xi) dnu = !dnu;
  }
  return dnu;
}

function vzdialenost2(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
  const x = a[0] + t * dx - p[0];
  const y = a[1] + t * dy - p[1];
  return x * x + y * y;
}

function naCiare(bod, body, polovica2, zavreta) {
  const n = body.length;
  for (let i = 0; i < n - (zavreta ? 0 : 1); i++) {
    if (vzdialenost2(bod, body[i], body[(i + 1) % n]) <= polovica2) return true;
  }
  return false;
}

/**
 * Kreslí `op` po poradí cez seba: `{vypln: poly}` alebo `{tah: body, sirka, zavreta}`.
 * Rozmery sú v bodoch; `pomer` je pixelRatio.
 */
export function nakresli(sirka, vyska, ops, pomer = 1) {
  const w = Math.round(sirka * pomer);
  const h = Math.round(vyska * pomer);
  const data = new Float64Array(w * h * 4);
  for (const op of ops) {
    const [r, g, b, a] = op.farba;
    const polovica2 = op.tah ? (op.sirka / 2) ** 2 : 0;
    const zasah = op.tah
      ? (p) => naCiare(p, op.tah, polovica2, op.zavreta)
      : (p) => vnutri(p, op.vypln);
    const body = op.tah || op.vypln;
    const okraj = op.tah ? op.sirka / 2 : 0;
    const x0 = Math.max(0, Math.floor((Math.min(...body.map((q) => q[0])) - okraj) * pomer));
    const x1 = Math.min(w, Math.ceil((Math.max(...body.map((q) => q[0])) + okraj) * pomer));
    const y0 = Math.max(0, Math.floor((Math.min(...body.map((q) => q[1])) - okraj) * pomer));
    const y1 = Math.min(h, Math.ceil((Math.max(...body.map((q) => q[1])) + okraj) * pomer));
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        let n = 0;
        for (let sy = 0; sy < SS; sy++) {
          for (let sx = 0; sx < SS; sx++) {
            if (zasah([(x + (sx + 0.5) / SS) / pomer, (y + (sy + 0.5) / SS) / pomer])) n++;
          }
        }
        if (!n) continue;
        const k = (a * n) / (SS * SS);
        const i = (y * w + x) * 4;
        // predvynásobené alfou, prevod späť až na konci
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
