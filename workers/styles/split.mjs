#!/usr/bin/env node
/**
 * Every built style as one fragment per package: the layers it draws, in their place
 * (`riki:z`), the sources they read and a sprite of only its icons, named `<package>:`.
 */
import { readFileSync, writeFileSync, readdirSync, mkdirSync, existsSync } from "node:fs";
import { packageOf } from "../../poc/web/packages.js";
import { cutSprite } from "../lib/sprite-cut.mjs";

export const FRAGMENTS = "fragments";
// the base map's archive, cut per package by `workers/tiles/cut.py`
const BASE_SOURCES = new Set(["omt", "base"]);
const ICON_KEYS = [["layout", "icon-image"], ["paint", "fill-pattern"],
  ["paint", "line-pattern"], ["paint", "fill-extrusion-pattern"]];

function literals(expression, out = new Set()) {
  if (typeof expression === "string") out.add(expression);
  else if (Array.isArray(expression)) expression.forEach((e) => literals(e, out));
  return out;
}

/** Sheet images an expression can give: its strings, names a `"mark-"` begins or `"_11"` ends. */
export function iconsOf(expression, sheet) {
  const words = [...literals(expression)].filter((w) => w.length > 2);
  const heads = words.filter((w) => /[-:_]$/.test(w));
  const tails = words.filter((w) => /^[-:_]/.test(w));
  const exact = new Set(words);
  return new Set(sheet.filter((name) => exact.has(name)
    || heads.some((head) => name.startsWith(head)) || tails.some((tail) => name.endsWith(tail))));
}

/** The expression with its own images named `<package>:`, anything else as it was. */
export function prefixed(expression, own, pkg) {
  if (typeof expression === "string") {
    return own.has(expression) ? `${pkg}:${expression}` : expression;
  }
  const names = [...own].sort();
  return ["let", "riki_icon", expression,
    ["case", ["in", ["var", "riki_icon"], ["literal", names]],
      ["concat", `${pkg}:`, ["var", "riki_icon"]], ["var", "riki_icon"]]];
}

function cutFile(url, pkg) {
  const file = url.slice(url.lastIndexOf("/") + 1);
  return `${url.slice(0, url.length - file.length)}${file.replace(/\.pmtiles$/, "")}-omt-${pkg}.pmtiles`;
}

/** `{package: fragment}` of one full style; `sheet` is the image names of its sprite. */
export function split(style, sheet, spriteUrl) {
  const byPackage = {};
  style.layers.forEach((source, z) => {
    const pkg = packageOf(source);
    const layer = structuredClone(source);
    layer.metadata = { ...(layer.metadata || {}), "riki:z": z };
    const frag = (byPackage[pkg] ||= { layers: [], sources: {}, icons: new Set() });
    if (BASE_SOURCES.has(layer.source)) {
      const id = `omt-${pkg}`;
      const base = style.sources[layer.source];
      frag.sources[id] = { ...base, url: cutFile(base.url, pkg) };
      layer.source = id;
    } else if (layer.source) {
      frag.sources[layer.source] = style.sources[layer.source];
    }
    for (const [part, key] of ICON_KEYS) {
      const expression = layer[part]?.[key];
      if (expression === undefined) continue;
      const own = iconsOf(expression, sheet);
      if (!own.size) continue;
      own.forEach((name) => frag.icons.add(name));
      layer[part][key] = prefixed(expression, own, pkg);
    }
    frag.layers.push(layer);
  });

  const { layers: _layers, sources: _sources, sprite: _sprite, terrain, ...frame } = style;
  const out = {};
  for (const [pkg, frag] of Object.entries(byPackage)) {
    const fragment = { ...frame, metadata: { ...(style.metadata || {}), "riki:package": pkg } };
    if (terrain && frag.sources[terrain.source]) fragment.terrain = terrain;
    if (frag.icons.size && spriteUrl) {
      fragment.sprite = [{ id: pkg, url: sheetUrl(spriteUrl, pkg) }];
    }
    fragment.sources = frag.sources;
    fragment.layers = frag.layers;
    out[pkg] = { fragment, icons: frag.icons };
  }
  return out;
}

/** `…/sprites/osm-liberty` → `…/fragments/<package>/sprites/<package>-osm-liberty`. */
export function sheetUrl(spriteUrl, pkg) {
  const set = spriteUrl.slice(spriteUrl.lastIndexOf("/") + 1);
  const root = spriteUrl.slice(0, spriteUrl.lastIndexOf("/sprites/"));
  return `${root}/${FRAGMENTS}/${pkg}/sprites/${pkg}-${set}`;
}

/** Every style of `site` split; icons of every style of a package go into its one sheet. */
export function splitSite(site) {
  const dir = `${site}/styles`;
  const icons = {};
  let sheetSet = null;
  let written = 0;
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".json")).sort()) {
    const style = JSON.parse(readFileSync(`${dir}/${file}`, "utf8"));
    const spriteUrl = typeof style.sprite === "string" ? style.sprite : null;
    const set = spriteUrl && spriteUrl.slice(spriteUrl.lastIndexOf("/") + 1);
    const sheetPath = set && `${site}/sprites/${set}.json`;
    const sheet = sheetPath && existsSync(sheetPath)
      ? Object.keys(JSON.parse(readFileSync(sheetPath, "utf8"))) : [];
    if (set) sheetSet = set;
    for (const [pkg, { fragment, icons: own }] of Object.entries(split(style, sheet, spriteUrl))) {
      mkdirSync(`${site}/${FRAGMENTS}/${pkg}`, { recursive: true });
      writeFileSync(`${site}/${FRAGMENTS}/${pkg}/${file}`, JSON.stringify(fragment));
      own.forEach((name) => (icons[pkg] ||= new Set()).add(name));
      written++;
    }
  }
  for (const [pkg, own] of Object.entries(icons)) {
    const count = cutSprite(`${site}/sprites/${sheetSet}`,
      `${site}/${FRAGMENTS}/${pkg}/sprites/${pkg}-${sheetSet}`, own);
    console.log(`${pkg}: ${count} icons of ${sheetSet}`);
  }
  console.log(`${written} fragments in ${site}/${FRAGMENTS}`);
  return written;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, "").split("=")));
  if (!splitSite(args.site || "_site")) {
    console.error("::error::No style was split – the site has no styles/*.json.");
    process.exit(1);
  }
}
