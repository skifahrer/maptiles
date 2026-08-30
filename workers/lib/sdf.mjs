/**
 * SIGNED DISTANCE FIELD z masky pokrytia – jedna implementácia pre všetkých,
 * čo do spritu dávajú farbiteľnú ikonu.
 *
 * PREČO SAMOSTATNÝ SÚBOR. Pýtajú sa naň dve miesta a každé z inej strany:
 * `workers/assets/sprite.mjs` prerába na SDF CUDZIU sadu ikoniek (masku si
 * najprv vypreparuje z hotového obrázka), `workers/assets/arrows.mjs` si
 * masku KRESLÍ sám. Je to tá istá matematika a tie isté dve konštanty, ktoré
 * musia sedieť so shaderom MapLibre – a keby ich mal každý svoje, rozišli by
 * sa ticho: ikona by sa vykreslila, len by mala inak hrubú hranu a halo by
 * sedelo inde než pri ostatných.
 *
 * ČO JE SDF a prečo nie obyčajný obrázok: v alfe nie je krytie, ale
 * VZDIALENOSŤ od hrany tvaru. Vďaka tomu vie MapLibre tú istú ikonu nakresliť
 * v ľubovoľnej veľkosti ostro, dať jej farbu (`icon-color`) aj halo. Cenou je,
 * že ikona smie mať JEDNU farbu – preto sú značky trás (`poc/web/marks.js`)
 * hotové farebné obrázky a nie SDF.
 */

const INF = 1e20;

/** Dosah distance fieldu v pixeloch – shader MapLibre počíta s 8. */
export const SDF_RADIUS = 8;

/** Hodnota alfy, na ktorej leží hrana ikony (0.75 · 255 ≈ 191). */
const SDF_CUTOFF = 0.25;

/** 1D vzdialenostná transformácia (Felzenszwalb & Huttenlocher). */
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

/** 2D vzdialenostná transformácia nad mriežkou štvorcov vzdialeností. */
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
 * Z masky pokrytia (0–1, w × h) vyrobí SDF v boxe (w+2p) × (h+2p).
 * Vracia `{ data, width, height }`, kde `data` sú alfa hodnoty.
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
 * SDF obrázok z PREDIKÁTU nad jednotkovým štvorcom – to isté zadanie tvaru,
 * aké má `poc/web/marks.js` (`draw(u, v)`), len na výstupe je farbiteľná
 * ikona namiesto hotového obrázka.
 *
 * Vyhladenie je 4 × 4 prevzorkovanie na pixel, rovnako ako pri značkách: tvar
 * je podmienka, nie cesta, takže je to najkratšia cesta k mäkkej hrane – a
 * SDF si z pokrytia aj tak počíta vzdialenosť, takže väčšia presnosť by sa
 * v ňom stratila.
 *
 * ŠÍRKA A VÝŠKA SÚ ZVLÁŠŤ, hoci tvar sa zadáva v jednotkovom štvorci: šípka
 * jednosmerky je širšia než vyššia (leží pozdĺž cesty) a v štvorci by okolo
 * nej ostal prázdny pás, ktorý MapLibre počíta do kolízie – teda by sa jej
 * na cestu zmestilo menej, než sa zdá.
 *
 * @param {(u: number, v: number) => boolean} draw  tvar v ⟨0,1⟩²
 * @param {number} w      šírka obrázka v px (už vynásobená pixelRatiom)
 * @param {number} h      výška obrázka v px
 * @param {number} pad    priehľadný rámik okolo (kvôli halu a hrane atlasu)
 * @param {number} radius dosah distance fieldu (škáluje s pixelRatiom)
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
