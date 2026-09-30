#!/usr/bin/env node
/**
 * Turns a plain sprite (osm-liberty) into an SDF sprite without the discs under icons.
 *
 *   node workers/assets/sprite.mjs --in=_site/sprites/osm-liberty \
 *        --out=_site/sprites/osm-liberty-sdf
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { decodePng, encodePng, packShelves } from "../lib/png.mjs";
import { toSdf, SDF_RADIUS } from "../lib/sdf.mjs";

/** Frame around the icon for the halo (px at pixelRatio 1). */
const PAD = 3;
/** Icons of one size needed before a background template pays off. */
const TEMPLATE_MIN_GROUP = 12;
/** Minimum symbol contrast against the template to trust it (0–255). */
const TEMPLATE_MIN_CONTRAST = 24;
/** Symbol mask sharpening at the edge (1 = none). */
const GLYPH_CONTRAST = 1.8;
/** A badge is an icon on a saturated or dark solid base (white "P" on blue). */
const BADGE_MIN_SATURATION = 0.25;
const BADGE_MAX_LUMA = 120;
/** Minimum luma gap between a symbol and its light halo (disc-less icons, osm-bright). */
const HALO_MIN_CONTRAST = 60;

/** Icon as [R,G,B,A] with premultiplied colour, for comparing. */
function readIcon(src, e) {
  const out = new Float64Array(e.width * e.height * 4);
  for (let y = 0; y < e.height; y++) {
    for (let x = 0; x < e.width; x++) {
      const sx = e.x + x;
      const sy = e.y + y;
      const i = (y * e.width + x) * 4;
      if (sx >= src.width || sy >= src.height) continue;
      const o = (sy * src.width + sx) * 4;
      const a = src.data[o + 3];
      const f = a / 255;
      out[i] = src.data[o] * f;
      out[i + 1] = src.data[o + 1] * f;
      out[i + 2] = src.data[o + 2] * f;
      out[i + 3] = a;
    }
  }
  return out;
}

/**
 * Shared background of same-size icons = the per-pixel **mode** (the disc is identical
 * in all); a median would darken the centre into a symbol.
 */
function modeTemplate(icons, w, h) {
  const t = new Float64Array(w * h * 4);
  const counts = new Map();
  for (let p = 0; p < w * h; p++) {
    counts.clear();
    for (const icon of icons) {
      const key =
        (Math.round(icon[p * 4]) << 24) |
        (Math.round(icon[p * 4 + 1]) << 16) |
        (Math.round(icon[p * 4 + 2]) << 8) |
        Math.round(icon[p * 4 + 3]);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    let bestKey = 0;
    let best = -1;
    for (const [key, n] of counts) {
      if (n > best) {
        best = n;
        bestKey = key;
      }
    }
    t[p * 4] = (bestKey >>> 24) & 0xff;
    t[p * 4 + 1] = (bestKey >>> 16) & 0xff;
    t[p * 4 + 2] = (bestKey >>> 8) & 0xff;
    t[p * 4 + 3] = bestKey & 0xff;
  }
  return t;
}

const percentile = (values, q) => {
  const sorted = Array.prototype.slice.call(values).sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.round(q * (sorted.length - 1)))];
};

const median = (values) => percentile(values, 0.5);

/** Differences → coverage 0–1 with a sharpened edge, clipped to the silhouette. */
function toCoverage(diff, icon, w, h, hi) {
  const cov = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) {
    const ink = Math.max(0, Math.min(1, diff[p] / hi));
    // sharpen around 0.5 against salt-and-pepper pixels; the edge stays put
    const sharp = Math.max(0, Math.min(1, (ink - 0.5) * GLYPH_CONTRAST + 0.5));
    // the symbol never spills outside the original icon
    cov[p] = sharp * Math.min(1, icon[p * 4 + 3] / 255);
  }
  return cov;
}

/** Most common colour of opaque icon pixels – its own background. */
function dominantColor(icon, w, h) {
  const counts = new Map();
  for (let p = 0; p < w * h; p++) {
    if (icon[p * 4 + 3] < 250) continue;
    const a = icon[p * 4 + 3] / 255;
    const key =
      ((icon[p * 4] / a) >> 3) * 4096 +
      ((icon[p * 4 + 1] / a) >> 3) * 64 +
      ((icon[p * 4 + 2] / a) >> 3);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  if (!counts.size) return null;
  let best = 0;
  let bestKey = 0;
  for (const [key, n] of counts) {
    if (n > best) {
      best = n;
      bestKey = key;
    }
  }
  return [
    ((bestKey / 4096) | 0) * 8 + 4,
    (((bestKey / 64) | 0) % 64) * 8 + 4,
    (bestKey % 64) * 8 + 4
  ];
}

/** A badge's light symbol on a solid base escapes the group template. */
function isBadge(icon, w, h) {
  const base = dominantColor(icon, w, h);
  if (!base) return false;
  const luma = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2];
  const max = Math.max(base[0], base[1], base[2]);
  const min = Math.min(base[0], base[1], base[2]);
  const saturation = max ? (max - min) / max : 0;
  return saturation >= BADGE_MIN_SATURATION || luma < BADGE_MAX_LUMA;
}

/** Symbol of an icon with its own base colour, measured against that colour. */
function badgeCoverage(icon, w, h) {
  const base = dominantColor(icon, w, h);
  if (!base) return null;

  const diff = new Float64Array(w * h);
  const inside = [];
  for (let p = 0; p < w * h; p++) {
    const a = icon[p * 4 + 3];
    // opaque only – the badge's soft edge would come out as an outline
    if (a < 250) continue;
    const f = a / 255;
    const d = Math.max(
      Math.abs(icon[p * 4] / f - base[0]),
      Math.abs(icon[p * 4 + 1] / f - base[1]),
      Math.abs(icon[p * 4 + 2] / f - base[2])
    );
    diff[p] = d;
    inside.push(d);
  }
  if (inside.length < 9) return null;
  const hi = percentile(inside, 0.98);
  if (hi < TEMPLATE_MIN_CONTRAST) return null;
  return toCoverage(diff, icon, w, h, hi);
}

/** Coverage (0–1) of the icon's symbol as its difference from the group template, or `null`. */
function glyphCoverage(icon, template, w, h) {
  const diff = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) {
    let d = 0;
    for (let ch = 0; ch < 4; ch++) {
      d = Math.max(d, Math.abs(icon[p * 4 + ch] - template[p * 4 + ch]));
    }
    diff[p] = d;
  }

  // threshold inside the icon only, or the transparent zeros become "background"
  const inside = [];
  for (let p = 0; p < w * h; p++) {
    if (icon[p * 4 + 3] >= 128) inside.push(diff[p]);
  }
  if (inside.length < 9) return null;

  // constant background shift against the template
  const bg = median(inside);
  const rel = inside.map((d) => Math.max(0, d - bg));
  // a percentile, since one outlier would push the whole symbol under the threshold
  const hi = percentile(rel, 0.98);
  if (hi < TEMPLATE_MIN_CONTRAST) return null;

  const shifted = diff.map((d) => Math.max(0, d - bg));
  return toCoverage(shifted, icon, w, h, hi);
}

/** Symbol of a disc-less icon with a light halo: the dark part; `null` for one-colour icons. */
function contrastCoverage(icon, w, h) {
  const luma = new Float64Array(w * h);
  const inside = [];
  for (let p = 0; p < w * h; p++) {
    const a = icon[p * 4 + 3];
    if (a < 128) continue;
    const f = a / 255;
    const l =
      (0.299 * icon[p * 4] + 0.587 * icon[p * 4 + 1] + 0.114 * icon[p * 4 + 2]) / f;
    luma[p] = l;
    inside.push(l);
  }
  if (inside.length < 9) return null;

  const light = percentile(inside, 0.95);
  const dark = percentile(inside, 0.05);
  if (light - dark < HALO_MIN_CONTRAST) return null;

  const cov = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) {
    const a = icon[p * 4 + 3];
    if (a < 128) continue;
    const ink = Math.max(0, Math.min(1, (light - luma[p]) / (light - dark)));
    const sharp = Math.max(0, Math.min(1, (ink - 0.5) * GLYPH_CONTRAST + 0.5));
    cov[p] = sharp * Math.min(1, a / 255);
  }
  return cov;
}

/** The icon's alpha silhouette as coverage 0–1 (one-colour icons). */
function alphaCoverage(icon, w, h) {
  const cov = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) cov[p] = icon[p * 4 + 3] / 255;
  return cov;
}

/** Crops coverage to the symbol, symmetric around the centre so `icon-anchor` holds. */
function cropToInk(cov, w, h) {
  let minX = w;
  let minY = h;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (cov[y * w + x] >= 0.5) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (maxX < 0) return { cov, width: w, height: h };

  const cx = (w - 1) / 2;
  const cy = (h - 1) / 2;
  const halfX = Math.ceil(Math.max(cx - minX, maxX - cx)) + 1;
  const halfY = Math.ceil(Math.max(cy - minY, maxY - cy)) + 1;
  const x0 = Math.max(0, Math.round(cx - halfX));
  const x1 = Math.min(w - 1, Math.round(cx + halfX));
  const y0 = Math.max(0, Math.round(cy - halfY));
  const y1 = Math.min(h - 1, Math.round(cy + halfY));
  const cw = x1 - x0 + 1;
  const ch = y1 - y0 + 1;

  const out = new Float64Array(cw * ch);
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) out[y * cw + x] = cov[(y + y0) * w + x + x0];
  }
  return { cov: out, width: cw, height: ch };
}

/** Converts one .json/.png pair to its SDF variant; returns the icon count. */
function convert(inBase, outBase, suffix) {
  const jsonPath = `${inBase}${suffix}.json`;
  const pngPath = `${inBase}${suffix}.png`;
  if (!existsSync(jsonPath) || !existsSync(pngPath)) return 0;

  const index = JSON.parse(readFileSync(jsonPath, "utf8"));
  const src = decodePng(readFileSync(pngPath));

  const entries = Object.entries(index).filter(
    ([, e]) => e && e.width > 0 && e.height > 0
  );
  if (!entries.length) throw new Error(`${jsonPath}: no icons`);

  // same-size icons share the disc, so each group yields a background template
  const pixels = new Map(entries.map(([name, e]) => [name, readIcon(src, e)]));
  const groups = new Map();
  for (const [name, e] of entries) {
    const key = `${e.width}x${e.height}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(name);
  }
  // badges would spoil the template for the others
  const badges = new Set();
  for (const [name, e] of entries) {
    if (isBadge(pixels.get(name), e.width, e.height)) badges.add(name);
  }

  const templates = new Map();
  for (const [key, names] of groups) {
    const discs = names.filter((n) => !badges.has(n));
    if (discs.length < TEMPLATE_MIN_GROUP) continue;
    const [w, h] = key.split("x").map(Number);
    templates.set(key, modeTemplate(discs.map((n) => pixels.get(n)), w, h));
  }

  let stripped = 0;
  const boxes = entries.map(([name, e]) => {
    const ratio = e.pixelRatio || 1;
    const pad = PAD * ratio;
    const icon = pixels.get(name);
    const template = templates.get(`${e.width}x${e.height}`);

    // most reliable first: group background → own base colour → light halo → silhouette
    let coverage =
      template && !badges.has(name)
        ? glyphCoverage(icon, template, e.width, e.height)
        : null;
    if (!coverage) coverage = badgeCoverage(icon, e.width, e.height);
    if (!coverage) coverage = contrastCoverage(icon, e.width, e.height);
    if (coverage) stripped++;
    else coverage = alphaCoverage(icon, e.width, e.height);

    const cropped = cropToInk(coverage, e.width, e.height);
    const sdf = toSdf(
      cropped.cov,
      cropped.width,
      cropped.height,
      pad,
      SDF_RADIUS * ratio
    );
    return { name, entry: e, sdf, width: sdf.width, height: sdf.height, ratio };
  });
  console.log(`  symbol separated from its base: ${stripped}/${boxes.length} icons`);

  const maxWidth = suffix ? 1024 : 512;
  const atlas = packShelves(boxes, maxWidth);
  const data = Buffer.alloc(atlas.width * atlas.height * 4);

  const outIndex = {};
  for (const box of boxes) {
    for (let y = 0; y < box.height; y++) {
      for (let x = 0; x < box.width; x++) {
        const d = ((box.y + y) * atlas.width + box.x + x) * 4;
        data[d] = 255;
        data[d + 1] = 255;
        data[d + 2] = 255;
        data[d + 3] = box.sdf.data[y * box.width + x];
      }
    }
    outIndex[box.name] = {
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      pixelRatio: box.entry.pixelRatio || 1,
      sdf: true
    };
  }

  writeFileSync(`${outBase}${suffix}.png`, encodePng({ ...atlas, data }));
  writeFileSync(`${outBase}${suffix}.json`, JSON.stringify(outIndex));
  console.log(
    `✓ ${outBase}${suffix}: ${boxes.length} icons, atlas ${atlas.width}×${atlas.height}`
  );
  return boxes.length;
}

function main() {
  const args = Object.fromEntries(
    process.argv.slice(2).map((a) => {
      const [k, ...v] = a.replace(/^--/, "").split("=");
      return [k, v.join("=") || "true"];
    })
  );
  const inBase = args.in;
  const outBase = args.out;
  if (!inBase || !outBase) {
    console.error("Usage: node workers/assets/sprite.mjs --in=<base> --out=<base>");
    process.exit(2);
  }

  const count = convert(inBase, outBase, "");
  if (!count) {
    console.error(`::error::Source sprite ${inBase}.json/.png doesn't exist`);
    process.exit(1);
  }
  convert(inBase, outBase, "@2x");
}

main();
