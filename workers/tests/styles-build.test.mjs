import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { THEMES, DEFAULT_MAP_TYPE } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";
import { makeSdfSprite } from "./fixtures.mjs";
import { styleSpec } from "./spec.mjs";

const BUILD = fileURLToPath(new URL("../styles/build.mjs", import.meta.url));
const LAYERS = ["contours", "rocks", "trails", "features", "points", "transport", "boundaries", "water", "buildings"];

test("build.mjs writes every map type × theme, and each passes the style spec", () => {
  const dir = mkdtempSync(join(tmpdir(), "styles-"));
  try {
    makeSdfSprite(dir);
    const fonts = join(dir, "fonts");
    for (const stack of ["Noto Sans Regular", "Noto Sans Bold"]) {
      mkdirSync(join(fonts, stack), { recursive: true });
      writeFileSync(join(fonts, stack, "0-255.pbf"), "");
    }
    const out = join(dir, "out");
    execFileSync(process.execPath, [BUILD, "--base-url=https://example.org/maps", "--region=trnavsky",
      `--out=${out}`, `--sprite=${join(dir, "sdf.json")}`, `--fonts-dir=${fonts}`,
      "--dem-tiles=https://example.org/maps/tiles/trnavsky-terrain.pmtiles",
      ...LAYERS.map((l) => `--${l}=true`)], { stdio: "pipe" });

    const expected = [];
    for (const type of MAP_TYPE_IDS) {
      for (const theme of Object.keys(THEMES)) {
        expected.push(`trnavsky-${type}-${theme}.json`);
        if (type === DEFAULT_MAP_TYPE) expected.push(`trnavsky-${theme}.json`);
      }
    }
    assert.deepEqual(readdirSync(out).sort(), expected.sort());

    const spec = styleSpec();
    for (const file of expected) {
      const style = JSON.parse(readFileSync(join(out, file), "utf8"));
      assert.match(style.glyphs, /^https:\/\/example\.org\/maps\/fonts\//, file);
      assert.ok(style.layers.some((l) => l.layout?.["icon-image"]), `${file} draws icons`);
      for (const l of LAYERS) {
        assert.ok(Object.values(style.sources).some((s) => String(s.url).includes(`-${l}.pmtiles`)),
          `${file} has the ${l} source`);
      }
      if (spec) assert.deepEqual(spec.validateStyleMin(style).map((e) => e.message), [], file);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
