/**
 * Signed distance field from a coverage mask – one implementation for every tintable sprite icon.
 */

const INF = 1e20;

/** Distance field reach in pixels – the MapLibre shader assumes 8. */
export const SDF_RADIUS = 8;

/** Alpha at the icon edge (0.75 · 255 ≈ 191). */
const SDF_CUTOFF = 0.25;

/** 1D distance transform (Felzenszwalb & Huttenlocher). */
function edt1d(f, d, v, z, n) {
  v[0] = 0;
  z[0] = -INF;
  z[1] = INF;
  for (let q = 1, k = 0; q < n; q++) {
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) {
      k--;
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    }
    k++;
    v[k] = q;
    z[k] = s;
    z[k + 1] = INF;
  }
  for (let q = 0, k = 0; q < n; q++) {
    while (z[k + 1] < q) k++;
    d[q] = (q - v[k]) * (q - v[k]) + f[v[k]];
  }
}

/** 2D distance transform over a grid of squared distances. */
function edt(grid, w, h, f, d, v, z) {
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) f[y] = grid[y * w + x];
    edt1d(f, d, v, z, h);
    for (let y = 0; y < h; y++) grid[y * w + x] = d[y];
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) f[x] = grid[y * w + x];
    edt1d(f, d, v, z, w);
    for (let x = 0; x < w; x++) grid[y * w + x] = d[x];
  }
}

/**
 * SDF in a (w+2p) × (h+2p) box from a coverage mask (0–1, w × h): `{ data, width, height }`.
 */
export function toSdf(coverage, w, h, pad, radius) {
  const bw = w + 2 * pad;
  const bh = h + 2 * pad;
  const size = bw * bh;
  const outer = new Float64Array(size);
  const inner = new Float64Array(size);

  for (let i = 0; i < size; i++) {
    outer[i] = INF;
    inner[i] = 0;
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const a = coverage[y * w + x];
      const i = (y + pad) * bw + (x + pad);
      if (a === 1) {
        outer[i] = 0;
        inner[i] = INF;
      } else if (a > 0) {
        const o = Math.max(0, 0.5 - a);
        const n = Math.max(0, a - 0.5);
        outer[i] = o * o;
        inner[i] = n * n;
      }
    }
  }

  const max = Math.max(bw, bh);
  const f = new Float64Array(max);
  const d = new Float64Array(max);
  const v = new Int32Array(max);
  const z = new Float64Array(max + 1);
  edt(outer, bw, bh, f, d, v, z);
  edt(inner, bw, bh, f, d, v, z);

  const out = new Uint8Array(size);
  for (let i = 0; i < size; i++) {
    const dist = Math.sqrt(outer[i]) - Math.sqrt(inner[i]);
    out[i] = Math.max(0, Math.min(255, Math.round(255 - 255 * (dist / radius + SDF_CUTOFF))));
  }
  return { data: out, width: bw, height: bh };
}

/**
 * SDF image from a PREDICATE over the unit square, 4 × 4 supersampled per pixel.
 * Width and height are separate: a square would pad a one-way arrow into collisions.
 *
 * @param {(u: number, v: number) => boolean} draw  shape in ⟨0,1⟩²
 * @param {number} w      image width in px (already times pixelRatio)
 * @param {number} h      image height in px
 * @param {number} pad    transparent frame (for the halo and atlas edge)
 * @param {number} radius distance field reach (scales with pixelRatio)
 */
export function sdfFromShape(draw, w, h, pad, radius = SDF_RADIUS) {
  const cov = new Float64Array(w * h);
  const SS = 4;
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      let n = 0;
      for (let sy = 0; sy < SS; sy += 1) {
        for (let sx = 0; sx < SS; sx += 1) {
          if (draw((x + (sx + 0.5) / SS) / w, (y + (sy + 0.5) / SS) / h)) n += 1;
        }
      }
      cov[y * w + x] = n / (SS * SS);
    }
  }
  return toSdf(cov, w, h, pad, radius);
}
