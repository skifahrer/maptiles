#!/usr/bin/env node
/**
 * Rewrites `poc/web/route-shield-americana.js` from OSM Americana.
 *
 * Americana describes the world's route number shields as data
 * (`src/js/shield_defs.js`, CC0). Shape shields can be drawn, image ones
 * (`spriteBlank`, US shields) can't – they're skipped and keep the road-class
 * fallback. Details in `docs/stitky-ciest.md`.
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
  console.error("Usage: node workers/tools/americana-shields.mjs --americana=<checkout>");
  process.exit(2);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const output = join(root, "poc", "web", "route-shield-americana.js");

// Americana's helpers return plain objects, so stand-ins do – no `node_modules` needed
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

/** `white` and `black` are CSS names; the palette gives the rest as hex. */
const NAMES = { white: "#ffffff", black: "#000000" };
const color = (v) => (v == null ? null : NAMES[v] || String(v));

/** Only the Americana params a shape really needs. */
function recipe(shapeBlank, textColor) {
  const p = shapeBlank.params || {};
  const out = { shape: shapeBlank.drawFunc, fill: color(p.fillColor) || "#ffffff" };
  if (color(p.strokeColor)) out.stroke = color(p.strokeColor);
  out.text = color(textColor) || out.stroke || "#000000";
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

const shapes = [];
const keys = new Map();
const nets = {};
let images = 0;

for (const [network, def] of Object.entries(networks).sort(([a], [b]) => (a < b ? -1 : 1))) {
  if (!def || !def.shapeBlank) {
    if (def) images += 1;
    continue;
  }
  const r = recipe(def.shapeBlank, def.textColor);
  const key = JSON.stringify(r);
  if (!keys.has(key)) {
    keys.set(key, shapes.length);
    shapes.push(r);
  }
  nets[network] = keys.get(key);
}

const rows = Object.entries(nets)
  .map(([n, i]) => `  ${JSON.stringify(n)}: ${i}`)
  .join(",\n");

writeFileSync(output, `/**
 * GENERATED – \`node workers/tools/americana-shields.mjs --americana=<checkout>\`.
 * Don't edit by hand; our own networks belong in \`route-shield-defs.js\`.
 *
 * Route number shield shapes and colours from OSM Americana (\`src/js/shield_defs.js\`,
 * CC0): ${shapes.length} recipes, ${Object.keys(nets).length} networks.
 * Networks drawn from a ready image (\`spriteBlank\`, ${images} networks) are
 * skipped – they keep the road-class fallback.
 */

export const AMERICANA_SHAPES = ${JSON.stringify(shapes, null, 2)};

export const AMERICANA_NETWORKS = {
${rows}
};
`);

console.log(`✓ ${output}: ${Object.keys(nets).length} networks, ${shapes.length} recipes ` +
  `(${images} image ones skipped)`);
