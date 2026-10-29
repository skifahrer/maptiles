import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildStyle } from "../../poc/web/themes.js";
import { composeFragments } from "../../poc/web/packages.js";
import { split, splitSite, iconsOf, prefixed, sheetUrl } from "../styles/split.mjs";
import { encodePng } from "../lib/png.mjs";
import { styleSpec, NEEDS_SPEC } from "./spec.mjs";

const spec = styleSpec();
const SPRITE = "https://x/sprites/osm-liberty";

function fullStyle() {
  return buildStyle({
    theme: "svetla", mapType: "zakladna",
    tilesUrl: "pmtiles://https://x/tiles/r.pmtiles", spriteUrl: SPRITE,
    glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
    contoursUrl: "https://x/r-contours.pmtiles", rocksUrl: "https://x/r-rocks.pmtiles",
    trailsUrl: "https://x/r-trails.pmtiles", featuresUrl: "https://x/r-features.pmtiles",
    pointsUrl: "https://x/r-points.pmtiles", transportUrl: "https://x/r-transport.pmtiles",
    boundariesUrl: "https://x/r-boundaries.pmtiles", waterUrl: "https://x/r-water.pmtiles",
    buildingsUrl: "https://x/r-buildings.pmtiles", roadSigns: true
  });
}

const SHEET = ["mountain_11", "volcano_11", "bank", "cafe", "mark-white-red-bar",
  "shield-primary-svetla", "nobody-draws-me"];

test("the fragments together are the full style, layer for layer", () => {
  const style = fullStyle();
  const parts = split(style, SHEET, SPRITE);
  const back = composeFragments(Object.values(parts).map((p) => p.fragment));
  assert.deepEqual(back.layers.map((l) => l.id), style.layers.map((l) => l.id));
  for (const [pkg, { fragment }] of Object.entries(parts)) {
    for (const layer of fragment.layers) {
      assert.ok(fragment.sources[layer.source] || !layer.source, `${pkg}: ${layer.id}`);
    }
  }
});

test("a package reads its own cut of the base map", () => {
  const { roads, landscape } = split(fullStyle(), SHEET, SPRITE);
  assert.equal(roads.fragment.sources["omt-roads"].url, "pmtiles://https://x/tiles/r-omt-roads.pmtiles");
  assert.ok(!roads.fragment.sources.omt);
  const land = landscape.fragment.layers.find((l) => l.id === "landcover-wood");
  assert.equal(land.source, "omt-landscape");
  assert.ok(!roads.fragment.layers.some((l) => l.id.startsWith("landcover")));
});

test("each package names only its own icons, and the rest stay as they were", () => {
  const parts = split(fullStyle(), SHEET, SPRITE);
  assert.ok(parts.points.icons.has("bank") && !parts.points.icons.has("mark-white-red-bar"));
  assert.ok(parts.paths.icons.has("mark-white-red-bar"));
  assert.ok(parts.landscape.icons.has("mountain_11"));
  assert.ok(!Object.values(parts).some((p) => p.icons.has("nobody-draws-me")));
  assert.deepEqual(parts.points.fragment.sprite, [{ id: "points", url: sheetUrl(SPRITE, "points") }]);
  assert.equal(sheetUrl(SPRITE, "points"), "https://x/fragments/points/sprites/points-osm-liberty");
  assert.equal(prefixed("cafe", new Set(["cafe"]), "points"), "points:cafe");
  assert.equal(prefixed("arrow-triangle", new Set(["cafe"]), "roads"), "arrow-triangle");
  assert.deepEqual([...iconsOf(["concat", "mark-", ["get", "bg"]], SHEET)], ["mark-white-red-bar"]);
  assert.deepEqual([...iconsOf(["concat", ["get", "class"], "_11"], SHEET)], ["mountain_11", "volcano_11"]);
});

test("fragments and their sum pass the style spec", { skip: !spec && NEEDS_SPEC }, () => {
  const parts = split(fullStyle(), SHEET, SPRITE);
  for (const [pkg, { fragment }] of Object.entries(parts)) {
    assert.deepEqual(spec.validateStyleMin(fragment).map((e) => e.message), [], pkg);
  }
  const back = composeFragments(Object.values(parts).map((p) => p.fragment));
  assert.deepEqual(spec.validateStyleMin(back).map((e) => e.message), []);
});

test("a site's styles become fragments and one sheet a package", () => {
  const site = mkdtempSync(join(tmpdir(), "split-"));
  mkdirSync(join(site, "styles"));
  mkdirSync(join(site, "sprites"));
  writeFileSync(join(site, "styles", "r-zakladna-svetla.json"), JSON.stringify(fullStyle()));
  const index = {};
  SHEET.forEach((name, i) => (index[name] = { x: i * 2, y: 0, width: 2, height: 2, pixelRatio: 1 }));
  writeFileSync(join(site, "sprites", "osm-liberty.json"), JSON.stringify(index));
  const data = Buffer.alloc(SHEET.length * 2 * 2 * 4, 255);
  writeFileSync(join(site, "sprites", "osm-liberty.png"), encodePng({ width: SHEET.length * 2, height: 2, data }));
  assert.ok(splitSite(site) > 0);
  const points = JSON.parse(readFileSync(join(site, "fragments", "points", "sprites", "points-osm-liberty.json")));
  assert.ok(points.bank && points.cafe && !points["mark-white-red-bar"] && !points["nobody-draws-me"]);
  assert.ok(readdirSync(join(site, "fragments", "roads")).includes("r-zakladna-svetla.json"));
});
