#!/usr/bin/env node
/**
 * Prerobí bežný sprite (osm-liberty) na **SDF sprite bez koliesok**.
 *
 * Dva problémy naraz:
 *
 * 1. **Kruh pod ikonou.** Ikony osm-liberty nie sú čisté symboly – každá je
 *    nakreslená ako biele koliesko so sivým obrysom a až v ňom je vlastný
 *    maki symbol. Na mape to vyzerá ako pole bodiek. Koliesko sa nedá
 *    „odfiltrovať" farbou (symbol býva svetlejší než obrys kolieska), ale
 *    dá sa odčítať: je vo všetkých ikonách rovnakej veľkosti **identické**,
 *    takže najčastejšia hodnota po pixeloch cez celú skupinu dá presnú
 *    šablónu pozadia a zvyšok (to, čím sa ikona od šablóny líši) je hľadaný
 *    symbol. Ikony, ktoré nie sú v koliesku ale na plnofarebnom podklade
 *    (biele „P" na modrom štvorci), sa spracujú voči vlastnej farbe.
 *
 * 2. **Farba ikony.** MapLibre vie ikone nastaviť farbu (`icon-color`,
 *    `icon-halo-color`) iba vtedy, ak je obrázok v sprite označený ako
 *    `sdf: true` a jeho alfa kanál nesie *signed distance field*. Symbol
 *    vytiahnutý v kroku 1 sa preto prepočíta na SDF – rovnaká konvencia ako
 *    mapbox/tiny-sdf: `alfa = 255 − 255·(d/radius + 0.25)`, teda hrana leží
 *    na hodnote 0.75, ktorú hľadá shader MapLibre.
 *
 * Okolo každej ikony pribudne rámik, aby mal `icon-halo-width` kam kresliť,
 * ikona sa oreže na symbol (súmerne okolo stredu, nech sa nepohne kotva) a
 * atlas sa preskladá jednoduchým „shelf" packerom.
 *
 * PNG sa číta aj zapisuje vlastným minimálnym kodekom (zlib je v Node),
 * takže pipeline nepotrebuje žiadnu npm závislosť.
 *
 * Použitie:
 *   node workers/assets/sprite.mjs --in=_site/sprites/osm-liberty \
 *        --out=_site/sprites/osm-liberty-sdf
 *   (spracuje aj varianty @2x, ak existujú)
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { decodePng, encodePng, packShelves } from "../lib/png.mjs";
// Matematika SDF je spoločná s `workers/assets/arrows.mjs`, ktorý si masku
// kreslí sám – rozpis v hlavičke `workers/lib/sdf.mjs`.
import { toSdf, SDF_RADIUS } from "../lib/sdf.mjs";

/** Hrúbka rámika okolo ikony (v pixeloch pri pixelRatio 1) pre halo. */
const PAD = 3;
/** Od koľkých ikon rovnakej veľkosti sa oplatí počítať šablónu pozadia. */
const TEMPLATE_MIN_GROUP = 12;
/** Minimálny kontrast symbolu voči šablóne, aby sme mu verili (0–255). */
const TEMPLATE_MIN_CONTRAST = 24;
/** Zostrenie masky symbolu okolo hrany (1 = bez zostrenia). */
const GLYPH_CONTRAST = 1.8;
/**
 * Odznak = ikona na plnofarebnom podklade (biele „P" na modrom štvorci).
 * Pozná sa podľa toho, že jej prevažujúca farba je sýta alebo tmavá –
 * nevýrazné sivé podklady sú bežné pozadie a rieši ich šablóna skupiny.
 */
const BADGE_MIN_SATURATION = 0.25;
const BADGE_MAX_LUMA = 120;
/**
 * Minimálny rozdiel jasu medzi symbolom a jeho svetlým halom, aby sa dali
 * oddeliť (ikony bez kolieska, napr. osm-bright).
 */
const HALO_MIN_CONTRAST = 60;

// ==================== odstránenie kolieska pod ikonou ====================

/** Ikona ako pole [R,G,B,A] s premultiplikovanou farbou (kvôli porovnávaniu). */
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
 * Spoločné pozadie skupiny ikon rovnakej veľkosti = **najčastejšia** hodnota
 * po pixeloch. Koliesko (biela plocha + sivý obrys) je vo všetkých ikonách
 * rovnaké až na pixel, kým symbol má každá ikona inde a inak – najčastejšia
 * hodnota preto vždy vyjde na pozadie.
 *
 * (Medián by tu nestačil: ikony s riedkym symbolom, napríklad písmeno „i",
 * majú väčšinu plochy bielu, ale medián cez skupinu je v strede tmavší, takže
 * by sa celý stred ikony tváril ako symbol.)
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


/** Z rozdielov spraví pokrytie 0–1 so zostrenou hranou, orezané siluetou. */
function toCoverage(diff, icon, w, h, hi) {
  const cov = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) {
    const ink = Math.max(0, Math.min(1, diff[p] / hi));
    // Zostrenie okolo 0,5: hodnoty tesne nad/pod hranou sa rozhodnú, takže v
    // ťahoch symbolu nezostanú „soľ a korenie" pixely. Samotná hrana (0,5)
    // sa nehýbe, silueta teda zostáva tam, kde bola.
    const sharp = Math.max(0, Math.min(1, (ink - 0.5) * GLYPH_CONTRAST + 0.5));
    // Symbol nikdy nesmie pretiecť mimo pôvodnú ikonu.
    cov[p] = sharp * Math.min(1, icon[p * 4 + 3] / 255);
  }
  return cov;
}

/** Najčastejšia farba nepriehľadných pixelov ikony – jej vlastné pozadie. */
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

/**
 * Odznak = ikona, ktorej prevažujúca farba nie je biele koliesko, ale plný
 * farebný podklad (doprava, parkovanie). Symbol je na ňom svetlý, takže
 * šablóna skupiny by ho nenašla – pozná sa podľa vlastnej farby.
 */
function isBadge(icon, w, h) {
  const base = dominantColor(icon, w, h);
  if (!base) return false;
  const luma = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2];
  const max = Math.max(base[0], base[1], base[2]);
  const min = Math.min(base[0], base[1], base[2]);
  const saturation = max ? (max - min) / max : 0;
  return saturation >= BADGE_MIN_SATURATION || luma < BADGE_MAX_LUMA;
}

/**
 * Symbol ikony, ktorá má vlastnú farbu podkladu (napr. biele „P" na modrom
 * štvorci). Tu šablóna skupiny nepomôže – symbol je oproti nej rovnaký ako
 * podklad. Referenciou je preto najčastejšia farba samotnej ikony.
 */
function badgeCoverage(icon, w, h) {
  const base = dominantColor(icon, w, h);
  if (!base) return null;

  const diff = new Float64Array(w * h);
  const inside = [];
  for (let p = 0; p < w * h; p++) {
    const a = icon[p * 4 + 3];
    // Iba plne krycie pixely: polopriehľadný okraj odznaku by inak vyšiel
    // ako obrys okolo celého symbolu.
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

/**
 * Pokrytie (0–1) vlastného symbolu ikony.
 *
 * Bežná ikona osm-liberty je symbol v bielom koliesku – symbol vyjde ako
 * odchýlka od šablóny skupiny. Časť ikon (doprava, parkovanie) je ale
 * „odznak": svetlý symbol na plnofarebnom podklade. Tie sa poznajú podľa
 * toho, že sa od šablóny líšia *celé*, a spracujú sa voči vlastnej farbe.
 *
 * Vracia `null`, ak sa nedá rozumne určiť symbol (napr. samotné koliesko) –
 * vtedy sa použije alfa silueta.
 */
function glyphCoverage(icon, template, w, h) {
  const diff = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) {
    let d = 0;
    for (let ch = 0; ch < 4; ch++) {
      d = Math.max(d, Math.abs(icon[p * 4 + ch] - template[p * 4 + ch]));
    }
    diff[p] = d;
  }

  // Prahovať sa smie len vnútri ikony. Priehľadné okolie má rozdiel nula a
  // keby sa počítalo do štatistiky, „pozadím" by sa stalo okolie ikony a
  // celé koliesko by prešlo ako symbol.
  const inside = [];
  for (let p = 0; p < w * h; p++) {
    if (icon[p * 4 + 3] >= 128) inside.push(diff[p]);
  }
  if (inside.length < 9) return null;

  // Konštantný posun pozadia (drobné odchýlky proti šablóne).
  const bg = median(inside);
  const rel = inside.map((d) => Math.max(0, d - bg));
  // Horná hranica cez percentil, nie maximum – jeden odľahlý pixel (napr. na
  // okraji kolieska) by inak celý symbol „stlačil" pod prah.
  const hi = percentile(rel, 0.98);
  if (hi < TEMPLATE_MIN_CONTRAST) return null;

  const shifted = diff.map((d) => Math.max(0, d - bg));
  return toCoverage(shifted, icon, w, h, hi);
}

/**
 * Symbol ikony, ktorá nemá koliesko, ale má okolo seba svetlé halo
 * (tak sú kreslené ikony osm-bright). Šablóna skupiny tu neexistuje, lebo
 * ikony nemajú spoločné pozadie – symbolom je jednoducho tmavá časť.
 *
 * Vracia `null` pre jednofarebné ikony (šípka, bodka), kde by sa nemalo
 * čo oddeľovať a správne je vziať celú siluetu.
 */
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

/** Alfa silueta ikony ako pokrytie 0–1 (pre jednofarebné ikony). */
function alphaCoverage(icon, w, h) {
  const cov = new Float64Array(w * h);
  for (let p = 0; p < w * h; p++) cov[p] = icon[p * 4 + 3] / 255;
  return cov;
}

/**
 * Oreže pokrytie na symbol. Výrez je súmerný okolo stredu ikony, aby sa
 * symbol voči kotve (`icon-anchor`) neposunul.
 */
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

// ============================ hlavná časť ============================

/** Prerobí jeden pár .json/.png na SDF variant. Vracia počet ikon. */
function convert(inBase, outBase, suffix) {
  const jsonPath = `${inBase}${suffix}.json`;
  const pngPath = `${inBase}${suffix}.png`;
  if (!existsSync(jsonPath) || !existsSync(pngPath)) return 0;

  const index = JSON.parse(readFileSync(jsonPath, "utf8"));
  const src = decodePng(readFileSync(pngPath));

  const entries = Object.entries(index).filter(
    ([, e]) => e && e.width > 0 && e.height > 0
  );
  if (!entries.length) throw new Error(`${jsonPath}: žiadne ikony`);

  // Ikony rovnakej veľkosti zdieľajú koliesko – z každej takej skupiny sa
  // dá vyrobiť šablóna pozadia a od nej odčítať samotný symbol.
  const pixels = new Map(entries.map(([name, e]) => [name, readIcon(src, e)]));
  const groups = new Map();
  for (const [name, e] of entries) {
    const key = `${e.width}x${e.height}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(name);
  }
  // Odznaky do šablóny nepatria – pokazili by pozadie ostatným ikonám.
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

    // Stratégie podľa toho, ako je ikona nakreslená, od najspoľahlivejšej:
    // spoločné pozadie skupiny → vlastný farebný podklad → svetlé halo.
    // Ak nesedí ani jedna, zostane celá silueta.
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
  console.log(`  symbol oddelený od podkladu: ${stripped}/${boxes.length} ikon`);

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
    `✓ ${outBase}${suffix}: ${boxes.length} ikon, atlas ${atlas.width}×${atlas.height}`
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
    console.error("Použitie: node workers/assets/sprite.mjs --in=<base> --out=<base>");
    process.exit(2);
  }

  const count = convert(inBase, outBase, "");
  if (!count) {
    console.error(`::error::Zdrojový sprite ${inBase}.json/.png neexistuje`);
    process.exit(1);
  }
  convert(inBase, outBase, "@2x");
}

main();
