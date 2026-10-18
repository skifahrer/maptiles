import { test } from "node:test";
import assert from "node:assert/strict";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import {
  BASE_PACKAGE, PACKAGE_IDS, packagesOf, normalizePackage, packageStyle
} from "../../poc/web/packages.js";
import { styleSpec, NEEDS_SPEC } from "./spec.mjs";

const spec = styleSpec();
const ARCHIVES = {
  contoursUrl: "https://x/contours.pmtiles",
  rocksUrl: "https://x/rocks.pmtiles",
  trailsUrl: "https://x/trails.pmtiles",
  featuresUrl: "https://x/features.pmtiles",
  pointsUrl: "https://x/points.pmtiles",
  transportUrl: "https://x/transport.pmtiles",
  boundariesUrl: "https://x/boundaries.pmtiles",
  waterUrl: "https://x/water.pmtiles",
  buildingsUrl: "https://x/buildings.pmtiles",
  roadSigns: true
};
const OWN = { railUrl: "https://x/rail.pmtiles", historyUrl: "https://x/history.pmtiles" };

function packageMap(id, { theme = "svetla", own = OWN } = {}) {
  const style = buildStyle({
    theme,
    mapType: "zakladna",
    tilesUrl: "https://x/tiles.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
    ...ARCHIVES
  });
  return packageStyle(style, id, { dark: theme === "tmava", ...own });
}

const ids = (style) => style.layers.map((l) => l.id);

for (const theme of Object.keys(THEMES)) {
  for (const id of PACKAGE_IDS) {
    test(`${id} / ${theme} passes the style spec`, { skip: !spec && NEEDS_SPEC }, () => {
      const errors = spec.validateStyleMin(packageMap(id, { theme })).map((e) => e.message);
      assert.deepEqual(errors, []);
    });
  }
}

test("every package map draws something, and only from sources it keeps", () => {
  for (const id of PACKAGE_IDS) {
    const style = packageMap(id);
    const drawn = style.layers.filter((l) => l.source);
    assert.ok(drawn.length > 0, id);
    for (const layer of drawn) assert.ok(style.sources[layer.source], `${id}: ${layer.id}`);
    assert.equal(style.layers[0].type, "background", id);
  }
});

test("roads keep the car roads, paths take the footways and the trails", () => {
  const roads = ids(packageMap("roads"));
  const paths = ids(packageMap("paths"));
  assert.ok(roads.includes("road-motorway") && roads.includes("road-maxspeed"));
  assert.ok(!roads.includes("road-path") && !roads.includes("rail-bg"));
  assert.ok(paths.includes("road-path") && paths.includes("road-pedestrian"));
  assert.ok(paths.some((l) => l.startsWith("trail-")));
  assert.ok(!paths.includes("road-motorway") && !paths.includes("landcover-wood"));
});

test("railways draw from their archive, else from the base map", () => {
  const own = ids(packageMap("railways"));
  assert.ok(own.includes("pkg-rail-main") && own.includes("pkg-rail-station"));
  assert.ok(!own.includes("rail-bg"));
  const base = ids(packageMap("railways", { own: {} }));
  assert.ok(base.includes("rail-bg") && base.includes("aerialway"));
  assert.ok(!base.some((l) => l.startsWith("pkg-rail-")));
});

test("history draws its five themes and nothing of the base map", () => {
  const style = packageMap("history");
  assert.deepEqual(Object.keys(style.sources).sort(), ["dem", "history"]);
  for (const theme of ["army", "mining", "embankment", "history", "gone"]) {
    assert.ok(ids(style).includes(`pkg-history-${theme}-fill`), theme);
  }
});

test("the base map is the style as built", () => {
  const style = buildStyle({
    theme: "svetla", tilesUrl: "https://x/t.pmtiles", spriteUrl: "s", glyphsUrl: "g"
  });
  assert.equal(packageStyle(style, BASE_PACKAGE, OWN), style);
});

test("a region offers only the packages it has", () => {
  const bare = packagesOf({}).map((p) => p.id);
  assert.ok(bare.includes("roads") && bare.includes("railways"));
  assert.ok(!bare.includes("history") && !bare.includes("settlements"));
  const full = packagesOf({ history: "h", buildings: "b", points: "p" }).map((p) => p.id);
  assert.deepEqual(full, PACKAGE_IDS);
  assert.equal(normalizePackage("history", {}), BASE_PACKAGE);
  assert.equal(normalizePackage("history", { history: "h" }), "history");
  assert.equal(normalizePackage(null, {}), BASE_PACKAGE);
});
