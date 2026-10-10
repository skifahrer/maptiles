import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { decodePng, encodePng } from "../lib/png.mjs";
import { draw, color, rect } from "../lib/draw.mjs";
import { makeSdfSprite } from "./fixtures.mjs";
import { ARROW_PREFIX } from "../../poc/web/arrows.js";
import { MARK_PREFIX, markImages } from "../../poc/web/marks.js";
import { routeShieldRecipes } from "../../poc/web/route-shields.js";
import { CUSTOM_ICON_PREFIX, THEMES, SHIELD_DEFS } from "../../poc/web/themes.js";
import { SHIELD_SHAPES } from "../../poc/web/shields.js";

const ASSETS = fileURLToPath(new URL("../assets/", import.meta.url));

function run(script, ...args) {
  return spawnSync(process.execPath, [join(ASSETS, script), ...args], { encoding: "utf8" });
}

function read(base, suffix) {
  return {
    index: JSON.parse(readFileSync(`${base}${suffix}.json`, "utf8")),
    png: decodePng(readFileSync(`${base}${suffix}.png`))
  };
}

function pixels({ index, png }, name) {
  const e = index[name];
  const out = [];
  for (let y = 0; y < e.height; y++) {
    const s = ((e.y + y) * png.width + e.x) * 4;
    out.push(Buffer.from(png.data.subarray(s, s + e.width * 4)).toString("hex"));
  }
  return out.join("");
}

function overlaps(a, b) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function withSprite(fn) {
  const dir = mkdtempSync(join(tmpdir(), "bake-"));
  try {
    const names = makeSdfSprite(dir);
    return fn(join(dir, "sdf"), names, dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** What every baker must keep: old icons untouched, new ones packed apart, twice = once. */
function checkBaker(script, isMine, extra = []) {
  withSprite((base, names) => {
    const before = { "": read(base, ""), "@2x": read(base, "@2x") };
    const r = run(script, `--sprite=${base}`, ...extra);
    assert.equal(r.status, 0, r.stderr);
    for (const suffix of ["", "@2x"]) {
      const after = read(base, suffix);
      const all = Object.keys(after.index);
      const added = all.filter(isMine);
      assert.ok(added.length > 0, `${script} added nothing to ${suffix || "1x"}`);
      for (const n of names) {
        assert.equal(pixels(after, n), pixels(before[suffix], n), `${n} changed in ${suffix || "1x"}`);
        assert.equal(after.index[n].sdf, true, `${n} lost sdf`);
      }
      const boxes = Object.entries(after.index).map(([name, e]) => ({ name, ...e }));
      for (const [i, a] of boxes.entries()) {
        assert.ok(a.x + a.width <= after.png.width && a.y + a.height <= after.png.height, `${a.name} outside`);
        for (const b of boxes.slice(i + 1)) assert.ok(!overlaps(a, b), `${a.name} overlaps ${b.name}`);
      }
    }
    const once = read(base, "");
    const again = run(script, `--sprite=${base}`, ...extra);
    assert.equal(again.status, 0, again.stderr);
    const twice = read(base, "");
    assert.deepEqual(Object.keys(twice.index).sort(), Object.keys(once.index).sort());
    assert.deepEqual([twice.png.width, twice.png.height], [once.png.width, once.png.height],
      "a second bake duplicates images");
    const count = (out) => Number(out.match(/: (\d+) images/)[1]);
    assert.equal(count(again.stdout), Object.keys(once.index).length, "a second bake duplicates images");
  });
}

test("arrows.mjs bakes SDF arrows, at both ratios", () => {
  checkBaker("arrows.mjs", (n) => n.startsWith(ARROW_PREFIX));
  withSprite((base) => {
    run("arrows.mjs", `--sprite=${base}`);
    for (const [suffix, ratio] of [["", 1], ["@2x", 2]]) {
      const arrows = Object.entries(read(base, suffix).index).filter(([n]) => n.startsWith(ARROW_PREFIX));
      for (const [n, e] of arrows) {
        assert.equal(e.sdf, true, n);
        assert.equal(e.pixelRatio, ratio, n);
      }
    }
  });
});

test("shields.mjs bakes stretchable coloured shields", () => {
  const want = new Set(SHIELD_SHAPES.flatMap((shape) => SHIELD_DEFS.flatMap(([id]) =>
    Object.keys(THEMES).map((theme) => `${shape.id}-${id}-${theme}`))));
  checkBaker("shields.mjs", (n) => want.has(n));
  withSprite((base, names) => {
    run("shields.mjs", `--sprite=${base}`);
    const { index } = read(base, "");
    assert.deepEqual(Object.keys(index).filter((n) => !names.includes(n)).sort(), [...want].sort());
    const shields = Object.entries(index).filter(([n]) => want.has(n));
    for (const [n, e] of shields) {
      assert.ok(!e.sdf, `${n} is coloured, not SDF`);
      assert.ok(Array.isArray(e.stretchX) && Array.isArray(e.content), `${n} has no stretch bands`);
    }
  });
});

test("route-shields.mjs bakes every network recipe", () => {
  const want = new Set(routeShieldRecipes().map((r) => r.name));
  checkBaker("route-shields.mjs", (n) => want.has(n));
  withSprite((base) => {
    run("route-shields.mjs", `--sprite=${base}`);
    const have = Object.keys(read(base, "").index);
    for (const n of want) assert.ok(have.includes(n), `${n} missing`);
  });
});

test("marks.mjs bakes every trail mark", () => {
  const want = markImages().map((m) => m.name);
  checkBaker("marks.mjs", (n) => n.startsWith(MARK_PREFIX));
  withSprite((base) => {
    run("marks.mjs", `--sprite=${base}`);
    const have = Object.keys(read(base, "@2x").index);
    for (const n of want) assert.ok(have.includes(n), `${n} missing`);
  });
});

function iconPng(hex) {
  const img = draw(8, 8, [{ fill: rect(0, 0, 8, 8), color: color(hex) }], 1);
  return "data:image/png;base64," + encodePng({ ...img, data: Buffer.from(img.data) }).toString("base64");
}

test("custom-icons.mjs bakes the overrides' icons with their own ratio", () => {
  withSprite((base, names, dir) => {
    const overrides = join(dir, "overrides.json");
    writeFileSync(overrides, JSON.stringify({
      customIcons: [
        { name: `${CUSTOM_ICON_PREFIX}red`, png: iconPng("#ff0000") },
        { name: `${CUSTOM_ICON_PREFIX}retina`, png: iconPng("#00ff00"), pixelRatio: 2 },
        { name: `${CUSTOM_ICON_PREFIX}broken`, png: "data:image/png;base64,bm90IGEgcG5n" }
      ]
    }));
    const r = run("custom-icons.mjs", `--sprite=${base}`, `--overrides=${overrides}`);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /broken.*skipping/);
    const after = read(base, "");
    assert.equal(after.index[`${CUSTOM_ICON_PREFIX}red`].pixelRatio, 1);
    assert.equal(after.index[`${CUSTOM_ICON_PREFIX}retina`].pixelRatio, 2);
    assert.ok(!(`${CUSTOM_ICON_PREFIX}broken` in after.index));
    assert.equal(pixels(after, `${CUSTOM_ICON_PREFIX}red`).slice(0, 8), "ff0000ff");
    for (const n of names) assert.ok(n in after.index);
  });
  withSprite((base, names, dir) => {
    const overrides = join(dir, "overrides.json");
    writeFileSync(overrides, JSON.stringify({ customIcons: [
      { name: `${CUSTOM_ICON_PREFIX}red`, png: iconPng("#ff0000") }] }));
    checkBaker("custom-icons.mjs", (n) => n.startsWith(CUSTOM_ICON_PREFIX), [`--overrides=${overrides}`]);
  });
});

test("custom-icons.mjs without icons leaves the sprite alone", () => {
  withSprite((base, names, dir) => {
    const overrides = join(dir, "overrides.json");
    writeFileSync(overrides, "{}");
    const before = readFileSync(`${base}.png`);
    const r = run("custom-icons.mjs", `--sprite=${base}`, `--overrides=${overrides}`);
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(readFileSync(`${base}.png`), before);
  });
});

test("custom-icons.mjs fails on unreadable overrides", () => {
  withSprite((base, names, dir) => {
    const overrides = join(dir, "overrides.json");
    writeFileSync(overrides, "{not json");
    const r = run("custom-icons.mjs", `--sprite=${base}`, `--overrides=${overrides}`);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /can't be read/);
  });
});

test("a missing @2x is optional, a missing 1x sprite fails, no --sprite is usage", () => {
  withSprite((base, names, dir) => {
    rmSync(`${base}@2x.json`);
    rmSync(`${base}@2x.png`);
    assert.equal(run("arrows.mjs", `--sprite=${base}`).status, 0);
    const r = run("arrows.mjs", `--sprite=${join(dir, "nothing")}`);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /doesn't exist/);
  });
  for (const script of ["arrows.mjs", "shields.mjs", "route-shields.mjs", "marks.mjs", "custom-icons.mjs"]) {
    assert.equal(run(script).status, 2, script);
  }
});
