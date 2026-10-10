import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { images, write, regionCountry, SETS } from "../rail/signs.mjs";
import { decodePng } from "../lib/png.mjs";
import { styleSpec } from "./spec.mjs";

const WORLD = fileURLToPath(new URL("../world/style.mjs", import.meta.url));

test("world style: every variant and theme, relative links, valid", () => {
  const spec = styleSpec();
  for (const variant of ["full", "basic"]) {
    const dir = mkdtempSync(join(tmpdir(), "world-"));
    try {
      execFileSync(process.execPath, [WORLD, `--out=${dir}`, `--variant=${variant}`], { stdio: "pipe" });
      const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
      assert.ok(files.length >= 2, variant);
      for (const f of files) {
        const style = JSON.parse(readFileSync(join(dir, f), "utf8"));
        for (const s of Object.values(style.sources)) {
          if (s.url) assert.ok(!/^https?:/.test(s.url), `${f}: ${s.url} is relative without --base-url`);
        }
        if (spec) assert.deepEqual(spec.validateStyleMin(style).map((e) => e.message), [], `${variant}/${f}`);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

test("world style: an unknown variant fails", () => {
  const r = spawnSync(process.execPath, [WORLD, "--out=/tmp/none", "--variant=tiny"], { encoding: "utf8" });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /unknown/);
});

test("rail signs: the index matches the packed image at both ratios", () => {
  const dir = mkdtempSync(join(tmpdir(), "signs-"));
  try {
    const base = join(dir, "r-signs");
    write("sk", base);
    for (const [suffix, ratio] of [["", 1], ["@2x", 2]]) {
      const index = JSON.parse(readFileSync(`${base}${suffix}.json`, "utf8"));
      const png = decodePng(readFileSync(`${base}${suffix}.png`));
      const boxes = Object.entries(index);
      assert.equal(boxes.length, Object.keys(SETS.sk()).length);
      for (const [i, [name, a]] of boxes.entries()) {
        assert.ok(name.startsWith("sk."), name);
        assert.equal(a.pixelRatio, ratio);
        assert.ok(a.x + a.width <= png.width && a.y + a.height <= png.height, `${name} in the atlas`);
        for (const [other, b] of boxes.slice(i + 1)) {
          const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
          assert.ok(apart, `${name} overlaps ${other}`);
        }
      }
    }
    const one = images("sk", 1)[0];
    const two = images("sk", 2)[0];
    assert.equal(two.image.width, one.image.width * 2);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("rail signs: a region takes its country, an area its position", () => {
  const regions = { slovensko: { iso: "SK", bbox: [16.8, 47.7, 22.6, 49.6] }, trnavsky: { country: "slovensko" } };
  const areas = { tatry: { bbox: [19.5, 49.0, 20.5, 49.4] }, alps: { bbox: [10, 46, 11, 47] } };
  assert.equal(regionCountry("trnavsky_test4km2", regions, areas), "sk");
  assert.equal(regionCountry("tatry", regions, areas), "sk");
  assert.equal(regionCountry("alps", regions, areas), "");
  assert.equal(regionCountry("bratislavsky"), "sk", "the real registry");
});
