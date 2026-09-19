#!/usr/bin/env node
/**
 * Prepíše `poc/web/route-shield-americana.js` z OSM Americana.
 *
 * Americana popisuje štítky čísel ciest celého sveta ako dáta
 * (`src/js/shield_defs.js`, CC0). Tvarové sa dajú nakresliť, obrázkové
 * (`spriteBlank`, americké štítky) nie – tie sa vynechajú a ostane im záloha
 * podľa triedy cesty. Rozpis v `docs/stitky-ciest.md`.
 *
 *   git clone --depth 1 https://github.com/osm-americana/openstreetmap-americana /tmp/am
 *   node workers/tools/americana-shields.mjs --americana=/tmp/am
 */
import { readFileSync, writeFileSync, mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);
if (!args.americana) {
  console.error("Použitie: node workers/tools/americana-shields.mjs --americana=<checkout>");
  process.exit(2);
}

const koren = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const vystup = join(koren, "poc", "web", "route-shield-americana.js");

// Helpery Americany vracajú obyčajné objekty, tak sa nahradia rovnakými –
// tým odpadne `node_modules` aj celá knižnica.
const STUB = `
const def = (drawFunc, params, extra = {}) => ({ shapeBlank: { drawFunc, params }, ...extra });
export const textConstraint = (constraintFunc) => ({ constraintFunc });
export const roundedRectTextConstraint = (radius) => ({ constraintFunc: "roundedRect", options: { radius } });
export const roundedRectShield = (fillColor, strokeColor, textColor, rectWidth, radius) =>
  def("roundedRectangle", { fillColor, strokeColor, rectWidth, radius: radius ?? 2 }, { textColor: textColor ?? strokeColor });
export const ovalShield = (fillColor, strokeColor, textColor, rectWidth) =>
  def("ellipse", { fillColor, strokeColor, rectWidth }, { textColor: textColor ?? strokeColor });
export const circleShield = (fillColor, strokeColor, textColor) => ovalShield(fillColor, strokeColor, textColor, 20);
export const pillShield = (fillColor, strokeColor, textColor, rectWidth) =>
  def("pill", { fillColor, strokeColor, rectWidth }, { textColor: textColor ?? strokeColor });
export const escutcheonDownShield = (yOffset, fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("escutcheon", { yOffset, fillColor, strokeColor, rectWidth, radius: radius ?? 0 }, { textColor: textColor ?? strokeColor });
export const fishheadDownShield = (fillColor, strokeColor, textColor, rectWidth) =>
  def("fishhead", { fillColor, strokeColor, rectWidth }, { textColor: textColor ?? strokeColor });
export const triangleDownShield = (fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("triangle", { pointUp: false, fillColor, strokeColor, radius: radius ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const trapezoidDownShield = (sideAngle, fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("trapezoid", { shortSideUp: false, sideAngle, fillColor, strokeColor, radius: radius ?? 0, rectWidth }, { textColor: textColor ?? strokeColor });
export const trapezoidUpShield = (sideAngle, fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("trapezoid", { shortSideUp: true, sideAngle, fillColor, strokeColor, radius: radius ?? 0, rectWidth }, { textColor: textColor ?? strokeColor });
export const diamondShield = (fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("diamond", { fillColor, strokeColor, radius: radius ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const pentagonUpShield = (yOffset, sideAngle, fillColor, strokeColor, textColor, radius1, radius2, rectWidth) =>
  def("pentagon", { pointUp: true, yOffset, sideAngle, fillColor, strokeColor, radius1: radius1 ?? 2, radius2: radius2 ?? 0, rectWidth }, { textColor: textColor ?? strokeColor });
export const homePlateDownShield = (yOffset, fillColor, strokeColor, textColor, radius1, radius2, rectWidth) =>
  def("pentagon", { pointUp: false, yOffset, sideAngle: 0, fillColor, strokeColor, radius1: radius1 ?? 2, radius2: radius2 ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const homePlateUpShield = (yOffset, fillColor, strokeColor, textColor, radius1, radius2, rectWidth) =>
  def("pentagon", { pointUp: true, yOffset, sideAngle: 0, fillColor, strokeColor, radius1: radius1 ?? 2, radius2: radius2 ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const hexagonVerticalShield = (yOffset, fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("hexagonVertical", { yOffset, fillColor, strokeColor, radius: radius ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const hexagonHorizontalShield = (sideAngle, fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("hexagonHorizontal", { sideAngle, fillColor, strokeColor, radius: radius ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const octagonVerticalShield = (yOffset, sideAngle, fillColor, strokeColor, textColor, radius, rectWidth) =>
  def("octagonVertical", { yOffset, sideAngle, fillColor, strokeColor, radius: radius ?? 2, rectWidth }, { textColor: textColor ?? strokeColor });
export const banneredShield = (base, banners, bannerTextColor) => ({ ...base, banners, bannerTextColor });
export const paBeltShield = () => ({ spriteBlank: "pa_belt" });
export const bransonRouteShield = () => ({ spriteBlank: "branson" });
`;

const dir = mkdtempSync(join(tmpdir(), "americana-"));
let networks;
try {
  mkdirSync(join(dir, "js"), { recursive: true });
  mkdirSync(join(dir, "constants"), { recursive: true });
  writeFileSync(join(dir, "js", "stub.mjs"), STUB);
  writeFileSync(
    join(dir, "constants", "color.js"),
    readFileSync(join(args.americana, "src", "constants", "color.js"))
  );
  const defs = readFileSync(join(args.americana, "src", "js", "shield_defs.js"), "utf8")
    .replace('from "@americana/maplibre-shield-generator"', 'from "./stub.mjs"');
  writeFileSync(join(dir, "js", "shield_defs.mjs"), defs);
  const mod = await import(pathToFileURL(join(dir, "js", "shield_defs.mjs")).href);
  networks = mod.loadShields().networks;
} finally {
  rmSync(dir, { recursive: true, force: true });
}

/** `white` a `black` sú CSS mená; zvyšok paleta dáva ako hex. */
const MENA = { white: "#ffffff", black: "#000000" };
const farba = (v) => (v == null ? null : MENA[v] || String(v));

/** Z parametrov Americany len to, čo tvar naozaj potrebuje. */
function recept(shapeBlank, textColor) {
  const p = shapeBlank.params || {};
  const out = { shape: shapeBlank.drawFunc, fill: farba(p.fillColor) || "#ffffff" };
  if (farba(p.strokeColor)) out.stroke = farba(p.strokeColor);
  out.text = farba(textColor) || out.stroke || "#000000";
  for (const [key, value] of [
    ["width", p.rectWidth], ["radius", p.radius], ["radius1", p.radius1],
    ["radius2", p.radius2], ["yOffset", p.yOffset], ["sideAngle", p.sideAngle]
  ]) {
    if (value) out[key] = value;
  }
  if (p.pointUp !== undefined) out.pointUp = !!p.pointUp;
  if (p.shortSideUp !== undefined) out.shortSideUp = !!p.shortSideUp;
  return out;
}

const tvary = [];
const kluce = new Map();
const siete = {};
let obrazkove = 0;

for (const [network, def] of Object.entries(networks).sort(([a], [b]) => (a < b ? -1 : 1))) {
  if (!def || !def.shapeBlank) {
    if (def) obrazkove += 1;
    continue;
  }
  const r = recept(def.shapeBlank, def.textColor);
  const kluc = JSON.stringify(r);
  if (!kluce.has(kluc)) {
    kluce.set(kluc, tvary.length);
    tvary.push(r);
  }
  siete[network] = kluce.get(kluc);
}

const riadky = Object.entries(siete)
  .map(([n, i]) => `  ${JSON.stringify(n)}: ${i}`)
  .join(",\n");

writeFileSync(vystup, `/**
 * GENEROVANÉ – \`node workers/tools/americana-shields.mjs --americana=<checkout>\`.
 * Needituj ručne; vlastné siete patria do \`route-shield-defs.js\`.
 *
 * Tvary a farby štítkov čísel ciest z OSM Americana (\`src/js/shield_defs.js\`,
 * CC0): ${tvary.length} receptov, ${Object.keys(siete).length} sietí.
 * Vynechané sú siete kreslené hotovým obrázkom (\`spriteBlank\`, ${obrazkove} sietí)
 * – tým ostáva záloha podľa triedy cesty.
 */

export const AMERICANA_SHAPES = ${JSON.stringify(tvary, null, 2)};

export const AMERICANA_NETWORKS = {
${riadky}
};
`);

console.log(`✓ ${vystup}: ${Object.keys(siete).length} sietí, ${tvary.length} receptov ` +
  `(${obrazkove} obrázkových vynechaných)`);
