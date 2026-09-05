#!/usr/bin/env node
/**
 * Tieňovanie reliéfu: koľko z mapy pod sebou prekryje. Volá to
 * `Kontrola · lint workflowov`.
 *
 * `hillshade` nie je filter, je to prekryvná vrstva – krytie je `sin` zo
 * sklonu natiahnutý prevýšením, takže nad ~20° je 0,97–1,0 a pod tieňovaním
 * nie je vidieť mapu, ale samotnú farbu tieňovania. Tak bola z lesa na
 * privrátenom svahu biela plocha. Štýl je pritom platný a mapa vyzerá „len
 * veľmi kontrastne", takže to chytí jedine dopočítanie toho istého shadera.
 *
 *   1. privrátený svah nesmie byť prekrytý viac než {@link LIT_MAX},
 *   2. odvrátený viac než {@link SHADOW_MAX},
 *   3. rozdiel krytia medzi stranami aspoň {@link RELIEF_MIN},
 *   4. svetlo nesmie svietiť takmer od severu ({@link NORTH_GAP}) a musí byť
 *      napísané v štýle – predvolená hodnota MapLibre je práve tá zlá.
 *
 * Počíta sa každá téma × typ mapy a každý zlom krivky prevýšenia zvlášť.
 *
 *   node workers/lint/hillshade.mjs
 */
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const PI = Math.PI;

/** Strop krytia na strane privrátenej k svetlu (les musí ostať zelený). */
const LIT_MAX = 0.55;
/** Strop krytia na odvrátenej strane (tmavý svah, ale ešte s obsahom). */
const SHADOW_MAX = 0.85;
/** Rozdiel krytia medzi stranami, pod ktorým už reliéf nie je vidieť. */
const RELIEF_MIN = 0.25;
/** O koľko stupňov musí byť svetlo od severu. */
const NORTH_GAP = 40;
/** Na akom svahu sa to meria – bežný horský svah, nie extrém. */
const SLOPE_DEG = 30;
/** Kde: zemepisná šírka Slovenska a najvyšší zoom výškových dlaždíc. */
const LAT = 49;
const ZOOM = 15;

/** `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa` → `[r, g, b, a]` v 0–1. */
function parseColor(raw) {
  let s = String(raw).trim().toLowerCase();
  const short = /^#([0-9a-f]{3,4})$/.exec(s);
  if (short) s = `#${[...short[1]].map((c) => c + c).join("")}`;
  const m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/.exec(s);
  if (!m) throw new Error(`neznámy zápis farby: ${raw}`);
  const ch = (i) => parseInt(m[1].slice(i * 2, i * 2 + 2), 16) / 255;
  return [ch(0), ch(1), ch(2), m[2] ? parseInt(m[2], 16) / 255 : 1];
}

/**
 * Krytie tieňovania na svahu – prepísané z `hillshade.fragment.glsl`
 * (maplibre-gl-js v4.7.1) a z prípravného passu pred ním. `shade` je 1 na
 * strane privrátenej k svetlu a 0 na odvrátenej.
 *
 * Prípravný pass robí z výšok gradient: sobel po 3×3 delený
 * `pow(2, exaggeration + (19.2562 - zoom))`, takže pre svah θ na šírke `lat`
 * vyjde `deriv = 8 · (m/px) · tan θ / 2^…`. Hlavný pass ho premení na uhol,
 * natiahne prevýšením a z `sin` toho uhla spraví krytie.
 */
function coverage({ slopeDeg, shade, exaggeration, shadowA, highlightA, accentA }) {
  const exag = ZOOM < 2 ? 0.4 : ZOOM < 4.5 ? 0.35 : 0.3;
  const zoomTerm = ZOOM < 15 ? (ZOOM - 15) * exag : 0;
  const metresPerPx = (156543.03392 * Math.cos((LAT * PI) / 180)) / 2 ** ZOOM;
  const deriv =
    (8 * metresPerPx * Math.tan((slopeDeg * PI) / 180)) /
    2 ** (zoomTerm + (19.2562 - ZOOM));
  const slope = Math.atan((1.25 * deriv) / Math.cos((LAT * PI) / 180));
  const base = 1.875 - exaggeration * 1.75;
  const maxValue = 0.5 * PI;
  const scaled =
    exaggeration !== 0.5
      ? ((base ** slope - 1) / (base ** maxValue - 1)) * maxValue
      : slope;
  const k = Math.min(Math.max(exaggeration * 2, 0), 1);
  const shadeA = (shadowA + (highlightA - shadowA) * shade) * Math.sin(scaled) * k;
  const accA = (1 - Math.cos(scaled)) * accentA * k;
  // `fragColor = accent * (1 - shade.a) + shade` – tá istá skladačka.
  return accA * (1 - shadeA) + shadeA;
}

/** Zlomy krivky prevýšenia: `["interpolate", …, z, v, z, v]` aj holé číslo. */
function exaggerationStops(value) {
  if (typeof value === "number") return [value];
  if (!Array.isArray(value) || value[0] !== "interpolate")
    throw new Error(`neznámy zápis prevýšenia: ${JSON.stringify(value)}`);
  const out = [];
  for (let i = 4; i < value.length; i += 2) out.push(value[i]);
  return out;
}

const problems = [];
let checks = 0;

for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    const style = buildStyle({
      theme,
      mapType,
      tilesUrl: "https://x/tiles.pmtiles",
      spriteUrl: "https://x/sprite",
      glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
      demTiles: "https://x/dem/{z}/{x}/{y}.png",
      hillshade: true
    });
    const layer = style.layers.find((l) => l.type === "hillshade");
    if (!layer) {
      problems.push(`${theme}/${mapType}: štýl so zapnutým tieňovaním nemá vrstvu \`hillshade\``);
      continue;
    }
    const where = `${theme}/${mapType}`;
    const paint = layer.paint || {};

    // 4. odkiaľ svieti
    const dir = paint["hillshade-illumination-direction"];
    if (typeof dir !== "number") {
      problems.push(
        `${where}: \`hillshade-illumination-direction\` v štýle chýba – ` +
          "MapLibre dosadí 335°, čo je 25° od severu a severné svahy dostanú " +
          "plné svetlo. Napíš smer do štýlu (konvencia je 315°, od SZ)."
      );
    } else {
      const deg = (((dir % 360) + 360) % 360);
      const fromNorth = Math.min(deg, 360 - deg);
      if (fromNorth < NORTH_GAP)
        problems.push(
          `${where}: svetlo svieti ${fromNorth.toFixed(0)}° od severu ` +
            `(smer ${dir}°) – severné svahy tým dostanú plné svetlo. ` +
            `Nechaj aspoň ${NORTH_GAP}° (konvencia je 315°, od SZ).`
        );
    }
    if (paint["hillshade-illumination-anchor"] !== "map")
      problems.push(
        `${where}: \`hillshade-illumination-anchor\` má byť "map". Pri ` +
          '"viewport" (predvolené) je svetlo priviazané k obrazovke, takže sa ' +
          "otočením mapy prelieva na druhú stranu hrebeňa a to isté údolie " +
          "raz vyzerá ako údolie a raz ako chrbát."
      );

    const [, , , shadowA] = parseColor(paint["hillshade-shadow-color"]);
    const [, , , highlightA] = parseColor(paint["hillshade-highlight-color"]);
    const [, , , accentA] = parseColor(paint["hillshade-accent-color"]);

    for (const exaggeration of exaggerationStops(paint["hillshade-exaggeration"])) {
      const at = (shade) =>
        coverage({ slopeDeg: SLOPE_DEG, shade, exaggeration, shadowA, highlightA, accentA });
      const lit = at(1);
      const dark = at(0);
      const tag = `${where}, prevýšenie ${exaggeration}`;
      checks += 1;

      // 1. privrátená strana
      if (lit > LIT_MAX)
        problems.push(
          `${tag}: svah ${SLOPE_DEG}° privrátený k svetlu je prekrytý na ` +
            `${(lit * 100).toFixed(0)} % (strop ${(LIT_MAX * 100).toFixed(0)} %) – ` +
            `z lesa pod ním je plocha vo farbe \`hillHighlight\` ` +
            `(${paint["hillshade-highlight-color"]}). Daj tej farbe alfu.`
        );
      // 2. odvrátená strana
      if (dark > SHADOW_MAX)
        problems.push(
          `${tag}: svah ${SLOPE_DEG}° odvrátený od svetla je prekrytý na ` +
            `${(dark * 100).toFixed(0)} % (strop ${(SHADOW_MAX * 100).toFixed(0)} %) – ` +
            `pod tieňom nie je vidieť ani les, ani cestu, ani vrstevnicu. ` +
            `Daj alfu \`hillShadow\` (${paint["hillshade-shadow-color"]}).`
        );
      // 3. a reliéf musí ostať vidieť
      if (Math.abs(dark - lit) < RELIEF_MIN)
        problems.push(
          `${tag}: medzi privrátenou (${(lit * 100).toFixed(0)} %) a odvrátenou ` +
            `(${(dark * 100).toFixed(0)} %) stranou je rozdiel len ` +
            `${(Math.abs(dark - lit) * 100).toFixed(0)} % – reliéf sa tým ` +
            `stráca. Priehľadnosť sa dá uberať len po ${(RELIEF_MIN * 100).toFixed(0)} %.`
        );
    }
  }
}

if (problems.length) {
  console.error(`tieňovanie reliéfu: ${problems.length} chýb\n`);
  for (const p of problems) console.error(`  ✗ ${p}`);
  process.exit(1);
}
console.log(
  `tieňovanie reliéfu: 0 chýb (${checks} meraní krytia na svahu ${SLOPE_DEG}°, ` +
    `${Object.keys(THEMES).length} tém × ${MAP_TYPE_IDS.length} typov mapy)`
);
