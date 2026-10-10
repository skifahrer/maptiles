import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync, mkdirSync, readdirSync, readFileSync, writeFileSync, copyFileSync,
  symlinkSync, existsSync, rmSync
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { emptyOverrides, normalizeOverrides } from "../../poc/web/themes.js";
import { PATTERN_IDS, patternImageName, patternSpec } from "../../poc/web/patterns.js";
import { decodePng } from "../lib/png.mjs";
import { makeSdfSprite } from "./fixtures.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));

/** A repo of symlinks with `script` copied, so what it writes into `poc/web` stays here. */
function shadowRepo(script, keep = []) {
  const dir = mkdtempSync(join(tmpdir(), "repo-"));
  mkdirSync(join(dir, "poc", "web"), { recursive: true });
  for (const f of readdirSync(join(ROOT, "poc", "web"))) {
    if (!keep.includes(f)) symlinkSync(join(ROOT, "poc", "web", f), join(dir, "poc", "web", f));
  }
  const [job] = script.split("/");
  mkdirSync(join(dir, "workers", job), { recursive: true });
  for (const f of readdirSync(join(ROOT, "workers"))) {
    if (f !== job) symlinkSync(join(ROOT, "workers", f), join(dir, "workers", f));
  }
  copyFileSync(join(ROOT, "workers", script), join(dir, "workers", script));
  return dir;
}

function node(dir, script, ...args) {
  return spawnSync(process.execPath, [join(dir, "workers", script), ...args],
    { encoding: "utf8", cwd: dir });
}

test("overrides.mjs writes every section the browser reads back", () => {
  const dir = shadowRepo("styles/overrides.mjs", ["style-overrides.json"]);
  try {
    const input = join(dir, "in.json");
    writeFileSync(input, JSON.stringify({ ...emptyOverrides(), hillshade: true, routeShields: false }));
    const r = node(dir, "styles/overrides.mjs", `--file=${input}`);
    assert.equal(r.status, 0, r.stderr);
    const saved = JSON.parse(readFileSync(join(dir, "poc", "web", "style-overrides.json"), "utf8"));
    for (const key of Object.keys(emptyOverrides())) assert.ok(key in saved, `${key} isn't saved`);
    const back = normalizeOverrides(saved).overrides;
    assert.equal(back.hillshade, true);
    assert.equal(back.routeShields, false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("overrides.mjs: --check writes nothing, --reset writes the empty set", () => {
  const dir = shadowRepo("styles/overrides.mjs", ["style-overrides.json"]);
  const target = join(dir, "poc", "web", "style-overrides.json");
  try {
    const input = join(dir, "in.json");
    writeFileSync(input, JSON.stringify({ hillshade: true }));
    const r = node(dir, "styles/overrides.mjs", `--file=${input}`, "--check");
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /hillshading: on/);
    assert.ok(!existsSync(target));
    assert.equal(node(dir, "styles/overrides.mjs", "--reset").status, 0);
    const saved = JSON.parse(readFileSync(target, "utf8"));
    assert.deepEqual(normalizeOverrides(saved).overrides, normalizeOverrides(emptyOverrides()).overrides);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("overrides.mjs: bad JSON fails, no input is usage, problems are warnings", () => {
  const dir = shadowRepo("styles/overrides.mjs", ["style-overrides.json"]);
  try {
    const input = join(dir, "in.json");
    writeFileSync(input, "{not json");
    const bad = node(dir, "styles/overrides.mjs", `--file=${input}`);
    assert.equal(bad.status, 1);
    assert.match(bad.stderr, /couldn't be read as JSON/);
    assert.equal(node(dir, "styles/overrides.mjs").status, 2);
    writeFileSync(input, JSON.stringify({ customIcons: [{ name: "bad name", png: "x" }] }));
    const warned = node(dir, "styles/overrides.mjs", `--file=${input}`, "--check");
    assert.equal(warned.status, 0);
    assert.match(warned.stdout, /::warning::/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("patterns.mjs bakes exactly the patterns the styles use", () => {
  const dir = mkdtempSync(join(tmpdir(), "patterns-"));
  try {
    makeSdfSprite(dir);
    const base = join(dir, "sdf");
    const styles = join(dir, "styles");
    mkdirSync(styles);
    const used = patternImageName(patternSpec({ id: PATTERN_IDS[0], color: "#336699", size: 8, weight: 1 }));
    writeFileSync(join(styles, "a.json"), JSON.stringify({
      layers: [{ id: "x", type: "fill", paint: { "fill-pattern": used } },
               { id: "y", type: "fill", paint: { "fill-pattern": "bus" } }]
    }));
    writeFileSync(join(styles, "broken.json"), "{");
    const script = join(ROOT, "workers", "styles", "patterns.mjs");
    const run = () => spawnSync(process.execPath, [script, `--sprite=${base}`, `--styles=${styles}`],
      { encoding: "utf8" });
    const r = run();
    assert.equal(r.status, 0, r.stderr);
    for (const suffix of ["", "@2x"]) {
      const index = JSON.parse(readFileSync(`${base}${suffix}.json`, "utf8"));
      assert.deepEqual(Object.keys(index).filter((n) => n.startsWith("pat:")), [used]);
      const png = decodePng(readFileSync(`${base}${suffix}.png`));
      assert.ok(index[used].x + index[used].width <= png.width);
    }
    const size = readFileSync(`${base}.png`).length;
    assert.equal(run().status, 0);
    assert.equal(readFileSync(`${base}.png`).length, size, "a second bake changes the sprite");

    rmSync(join(styles, "a.json"));
    const none = run();
    assert.equal(none.status, 0);
    assert.match(none.stdout, /no patterns/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

const SHIELD_DEFS = `
import { roundedRectShield, circleShield, banneredShield, paBeltShield } from "@americana/maplibre-shield-generator";
import * as Color from "../constants/color.js";
export function loadShields() {
  const networks = {
    "zz:b": roundedRectShield(Color.shields.green, "white"),
    "zz:a": roundedRectShield(Color.shields.green, "white"),
    "zz:c": circleShield("white", "black", Color.shields.green),
    "zz:d": banneredShield(circleShield("white", "black"), ["ALT"]),
    "zz:img": paBeltShield()
  };
  return { networks };
}
`;

test("americana-shields.mjs turns shape shields into shared recipes", async () => {
  const dir = shadowRepo("tools/americana-shields.mjs", ["route-shield-americana.js"]);
  try {
    const am = join(dir, "americana");
    mkdirSync(join(am, "src", "js"), { recursive: true });
    mkdirSync(join(am, "src", "constants"), { recursive: true });
    writeFileSync(join(am, "src", "constants", "color.js"), 'export const shields = { green: "#006747" };\n');
    writeFileSync(join(am, "src", "js", "shield_defs.js"), SHIELD_DEFS);
    const r = node(dir, "tools/americana-shields.mjs", `--americana=${am}`);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /4 networks, 3 recipes \(1 image ones skipped\)/);
    const out = join(dir, "poc", "web", "route-shield-americana.js");
    const { AMERICANA_SHAPES, AMERICANA_NETWORKS } = await import(pathToFileURL(out).href);
    assert.deepEqual(Object.keys(AMERICANA_NETWORKS), ["zz:a", "zz:b", "zz:c", "zz:d"]);
    assert.equal(AMERICANA_NETWORKS["zz:a"], AMERICANA_NETWORKS["zz:b"]);
    assert.deepEqual(AMERICANA_SHAPES[AMERICANA_NETWORKS["zz:a"]],
      { shape: "roundedRectangle", fill: "#006747", stroke: "#ffffff", text: "#ffffff", radius: 2 });
    assert.deepEqual(AMERICANA_SHAPES[AMERICANA_NETWORKS["zz:c"]],
      { shape: "ellipse", fill: "#ffffff", stroke: "#000000", text: "#006747", width: 20 });
    assert.ok(!("zz:img" in AMERICANA_NETWORKS));
    assert.equal(node(dir, "tools/americana-shields.mjs").status, 2);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
