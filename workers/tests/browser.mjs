#!/usr/bin/env node
/**
 * The viewer in Chromium over the mini region's packages: every map type × theme reaches
 * `idle` without an error or an image nobody draws, and developer mode applies an override.
 *
 *   node workers/tests/browser.mjs --work=<integration.py --work> --deps=<npm prefix>
 */
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { cpSync, copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { THEMES } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const KEY = "mini";
const BBOX = [17.1, 48.1, 17.2, 48.16];
const PACKAGES = ["trails", "features", "points", "transport", "boundaries", "water", "rail", "history", "buildings"];
const OVERRIDE = { layer: "road-tertiary", prop: "line-color", value: "#123456" };
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json",
  ".png": "image/png", ".pbf": "application/x-protobuf", ".css": "text/css" };

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const [k, ...v] = a.replace(/^--/, "").split("=");
  return [k, v.join("=")];
}));
const work = args.work;
const deps = args.deps || process.env.BROWSER_DEPS || "";
if (!work) {
  console.error("Usage: node workers/tests/browser.mjs --work=<dir> [--deps=<npm prefix>]");
  process.exit(2);
}
const require = createRequire(join(deps || ROOT, "noop.js"));
const pkg = (name) => join(deps, "node_modules", name);

/** `work/_site` as a deploy: the viewer, sprites and glyphs from the assets job, the packages, a manifest. */
function site() {
  const out = join(work, "_site");
  for (const link of ["workers", "poc"]) {
    if (!existsSync(join(work, link))) symlinkSync(join(ROOT, link), join(work, link));
  }
  const env = { ...process.env, GITHUB_OUTPUT: join(work, "assets.out"),
    GLYPHS_ZIP: process.env.GLYPHS_ZIP || "https://github.com/openmaptiles/fonts/releases/download/v2.0/noto-sans.zip" };
  for (const script of ["workers/assets/icons.sh", "workers/assets/glyphs.sh"]) {
    try {
      execFileSync("bash", [script], { cwd: work, env, stdio: "pipe" });
    } catch (err) {
      console.error(`::error::${script} failed:\n${String(err.stdout).slice(-3000)}`);
      throw err;
    }
  }
  cpSync(join(ROOT, "poc", "web"), out, { recursive: true });
  const tiles = join(out, "tiles");
  // a base archive the style can read; its layers aren't OpenMapTiles', so it simply draws less
  copyFileSync(join(tiles, `${KEY}-boundaries.pmtiles`), join(tiles, `${KEY}.pmtiles`));
  copyFileSync(join(work, "contours-out", "contours.pmtiles"), join(tiles, `${KEY}-contours.pmtiles`));
  const region = { name: "Mini", bbox: BBOX, pmtiles: `tiles/${KEY}.pmtiles`, maxzoom: 14,
    contours: `tiles/${KEY}-contours.pmtiles`, contours_maxzoom: 14 };
  for (const p of PACKAGES) {
    if (existsSync(join(tiles, `${KEY}-${p}.pmtiles`))) {
      region[p] = `tiles/${KEY}-${p}.pmtiles`;
      region[`${p}_maxzoom`] = 14;
    }
  }
  const sprites = readdirSync(join(out, "sprites")).filter((f) => /^[^@]+\.json$/.test(f));
  writeFileSync(join(tiles, "manifest.json"), JSON.stringify({
    default_region: KEY, built_at: new Date().toISOString(), maxzoom: 14,
    glyphs: "LOCAL/fonts/{fontstack}/{range}.pbf",
    sprite: "sprites/osm-liberty",
    icon_sources: sprites.map((f) => ({ id: f.replace(/\.json$/, ""), sprite: `sprites/${f.replace(/\.json$/, "")}` })),
    dem: null, regions: { [KEY]: region }
  }));
  return out;
}

/** A static server with Range, as Pages serves PMTiles. */
function serve(dir) {
  const server = createServer((req, res) => {
    const path = join(dir, decodeURIComponent(new URL(req.url, "http://x").pathname));
    let file = path;
    if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
    if (!existsSync(file)) {
      res.writeHead(404).end();
      return;
    }
    const body = readFileSync(file);
    const type = TYPES[extname(file)] || "application/octet-stream";
    const range = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
    if (range) {
      const a = Number(range[1]);
      const b = Math.min(range[2] ? Number(range[2]) : body.length - 1, body.length - 1);
      res.writeHead(206, { "Content-Type": type, "Content-Range": `bytes ${a}-${b}/${body.length}`,
        "Content-Length": b - a + 1, "Accept-Ranges": "bytes" });
      res.end(body.subarray(a, b + 1));
      return;
    }
    res.writeHead(200, { "Content-Type": type, "Content-Length": body.length });
    res.end(body);
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

// wraps the Map the page makes, so its events can be read without touching app.js
const WATCH = () => {
  window.__t = { maps: [], errors: [], missing: [], idle: false };
  let real;
  Object.defineProperty(window, "maplibregl", {
    configurable: true,
    get: () => real,
    set(lib) {
      const Base = lib.Map;
      lib.Map = class extends Base {
        constructor(opts) {
          super(opts);
          window.__t.maps.push(this);
          this.on("error", (ev) => window.__t.errors.push(`${ev?.error?.message || ev}${ev?.error?.url ? ` (${ev.error.url})` : ""}`));
          this.on("styleimagemissing", (ev) => setTimeout(() => {
            if (!this.hasImage(ev.id)) window.__t.missing.push(ev.id);
          }, 0));
          this.on("idle", () => { window.__t.idle = true; });
        }
      };
      real = lib;
    }
  });
};

async function main() {
  const dir = site();
  const server = await serve(dir);
  const base = `http://127.0.0.1:${server.address().port}`;
  // the manifest can't know the port before the server has one
  const manifestPath = join(dir, "tiles", "manifest.json");
  writeFileSync(manifestPath, readFileSync(manifestPath, "utf8").replace("LOCAL", base));

  const { chromium } = require(pkg("playwright"));
  const browser = await chromium.launch();
  const problems = [];
  const page = async (query, storage) => {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    const console_ = [];
    p.on("console", (m) => m.type() === "error" && console_.push(m.text()));
    p.on("pageerror", (e) => console_.push(String(e)));
    await p.route("https://unpkg.com/**", (route) => {
      const url = route.request().url();
      const file = url.includes("maplibre-gl")
        ? join(pkg("maplibre-gl"), "dist", url.split("/dist/")[1])
        : join(pkg("pmtiles"), "dist", "pmtiles.js");
      return route.fulfill({ path: file });
    });
    await p.addInitScript(WATCH);
    if (storage) await p.addInitScript((s) => Object.entries(s).forEach(([k, v]) => localStorage.setItem(k, v)), storage);
    await p.goto(`${base}/${query}`);
    try {
      await p.waitForFunction(() => window.__viewerBooted && window.__t.idle, null, { timeout: 60000 });
    } catch {
      problems.push(`${query || "first load"}: the viewer never booted and reached idle`);
    }
    return { p, console_ };
  };
  const report = async (p, console_, where) => {
    const t = await p.evaluate(() => ({ errors: window.__t.errors, missing: [...new Set(window.__t.missing)] }));
    for (const e of t.errors) problems.push(`${where}: map error: ${e}`);
    for (const id of t.missing) problems.push(`${where}: image \`${id}\` is in no sprite and nobody draws it`);
    for (const c of console_) problems.push(`${where}: console: ${c}`);
    await p.evaluate(() => { window.__t.errors = []; window.__t.missing = []; });
    console_.length = 0;
  };

  const { p, console_ } = await page("");
  for (const type of MAP_TYPE_IDS) {
    for (const theme of Object.keys(THEMES)) {
      // the panel starts folded, so the selects are set as its own controls set them
      await p.evaluate(([t, th]) => {
        for (const [id, v] of [["maptype", t], ["theme", th]]) {
          const el = document.getElementById(id);
          if (el.value === v) continue;
          window.__t.idle = false;
          el.value = v;
          el.dispatchEvent(new Event("change"));
        }
      }, [type, theme]);
      try {
        await p.waitForFunction(() => window.__t.idle, null, { timeout: 30000 });
      } catch {
        problems.push(`${type} / ${theme}: the map never reached idle`);
      }
      await report(p, console_, `${type} / ${theme}`);
      console.log(`  ${type} / ${theme}`);
    }
  }

  const overrides = { version: 2, layers: { [OVERRIDE.layer]: { paint: { [OVERRIDE.prop]: OVERRIDE.value } } } };
  const dev = await page("?dev=1", { "fricomaps.overrides": JSON.stringify(overrides) });
  const got = await dev.p.evaluate((o) => window.__t.maps.at(-1).getPaintProperty(o.layer, o.prop), OVERRIDE);
  if (got !== OVERRIDE.value) problems.push(`developer mode: ${OVERRIDE.layer} ${OVERRIDE.prop} is ${got}, the override says ${OVERRIDE.value}`);
  if (await dev.p.evaluate(() => document.getElementById("dev").hidden)) problems.push("developer mode: ?dev=1 didn't open it");
  await report(dev.p, dev.console_, "developer mode");

  // the watch itself: an icon nobody has must be heard
  const heard = await p.evaluate(async () => {
    const map = window.__t.maps.at(-1);
    const source = Object.keys(map.getStyle().sources).find((id) => /points/.test(id));
    map.addLayer({ id: "probe", type: "symbol", source, "source-layer": "feature_point",
      layout: { "icon-image": "probe-missing", "icon-allow-overlap": true } });
    await new Promise((ok) => setTimeout(ok, 3000));
    return window.__t.missing.includes("probe-missing");
  });
  if (!heard) problems.push("the watch doesn't hear `styleimagemissing` – the image check verifies nothing");
  await browser.close();
  server.close();
  for (const pr of [...new Set(problems)]) console.log(`::error::${pr}`);
  console.log(`Viewer: ${MAP_TYPE_IDS.length * Object.keys(THEMES).length} styles, ${new Set(problems).size} problems`);
  process.exit(problems.length ? 1 : 0);
}

main().catch((err) => {
  console.error(`::error::${err.stack || err}`);
  process.exit(1);
});
