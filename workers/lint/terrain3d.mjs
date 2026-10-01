#!/usr/bin/env node
/**
 * 3D terrain: the elevation model promise holds all the way into the style. Run by
 * `Check · workflow lint`.
 *
 * 3D terrain is one style line (`terrain: { source, exaggeration }`) and all of it
 * is quiet: without it the map is flat, pointing at a missing source makes MapLibre
 * refuse the whole style, and a source other than `raster-dem` gives random terrain.
 *
 *   1. without elevation tiles the style mustn't have `terrain`,
 *   2. with tiles and `terrain3d` it must – pointing at a `raster-dem` source,
 *   3. the exaggeration is a positive finite number (0 is the quietest 3D-off),
 *   4. 3D off mustn't take the hillshading – they're the same tiles.
 *
 * Outside the style: `deploy/site.sh` writes `terrain_3d` from the finished
 * style, not the switch (`auto` says nothing about the result).
 *
 *   node workers/lint/terrain3d.mjs
 */
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** Own tiles from `workers/terrain/pack.py` – one `.pmtiles`. */
const OWN_TILES = "pmtiles://https://x/tiles/region-terrain.pmtiles";

const problems = [];
let checks = 0;

function style(opts) {
  return buildStyle({
    tilesUrl: "https://x/tiles.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
    ...opts
  });
}

for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    const where = `${theme}/${mapType}`;

    // 1. no tiles, no 3D
    checks += 1;
    const noTiles = style({ theme, mapType, demTiles: null, terrain3d: true });
    if (noTiles.terrain) {
      problems.push(
        `${where}: a style without elevation tiles carries \`terrain\` – ` +
          "it points at a missing source and MapLibre refuses the whole style."
      );
    }

    // 2. with tiles and 3D on it must exist and point at raster-dem
    checks += 1;
    const s3d = style({
      theme,
      mapType,
      demTiles: OWN_TILES,
      hillshade: true,
      terrain3d: true
    });
    if (!s3d.terrain) {
      problems.push(
        `${where}: the style has elevation tiles and \`terrain3d\` is on, but ` +
          "it carries no `terrain` – the client draws a flat map and nobody " +
          "says anything."
      );
    } else {
      const id = s3d.terrain.source;
      const source = (s3d.sources || {})[id];
      if (!source) {
        problems.push(`${where}: \`terrain.source\` = "${id}", the style has no such source.`);
      } else if (source.type !== "raster-dem") {
        problems.push(
          `${where}: \`terrain\` points at source "${id}" of type "${source.type}" – ` +
            "heights can only be read from `raster-dem`."
        );
      }

      // 3. exaggeration
      const exag = s3d.terrain.exaggeration;
      if (!Number.isFinite(exag) || exag <= 0) {
        problems.push(
          `${where}: the 3D terrain exaggeration is ${JSON.stringify(exag)} – ` +
            "a flat map with 3D on is the quietest form of 3D off."
        );
      }
    }

    // 4. 3D off mustn't take the hillshading
    checks += 1;
    const no3d = style({
      theme,
      mapType,
      demTiles: OWN_TILES,
      hillshade: true,
      terrain3d: false
    });
    if (no3d.terrain) {
      problems.push(`${where}: \`terrain3d\` is off, but the style carries \`terrain\`.`);
    }
    if (!(no3d.sources || {}).dem) {
      problems.push(
        `${where}: 3D off took the \`dem\` source too – they're the same tiles ` +
          "and hillshading is their second use."
      );
    }
    if (!(no3d.layers || []).some((l) => l.type === "hillshade")) {
      problems.push(`${where}: 3D off took the \`hillshade\` layer too.`);
    }
  }
}

// 5. the manifest speaks of 3D from the finished style, not the switch
checks += 1;
const site = fs.readFileSync(path.join(ROOT, "workers/deploy/site.sh"), "utf8");
if (!site.includes("terrain_3d:")) {
  problems.push(
    "workers/deploy/site.sh: the manifest has no `terrain_3d` – the app can't " +
      "know which region has 3D and would have to take the style apart."
  );
} else if (!/_site\/styles/.test(site.slice(0, site.indexOf("terrain_3d:")))) {
  problems.push(
    "workers/deploy/site.sh: `terrain_3d` isn't taken from the finished style in " +
      "`_site/styles`. The switch is `auto` (“on if we have the data”), so it says " +
      "nothing about the result – two answers to one question drift."
  );
}

// 6. the map run passes the switch on at all
checks += 1;
const workflow = fs.readFileSync(
  path.join(ROOT, ".github/workflows/build-map-region.yml"),
  "utf8"
);
if (!workflow.includes("--terrain-3d=")) {
  problems.push(
    ".github/workflows/build-map-region.yml: `workers/styles/build.mjs` doesn't get " +
      "`--terrain-3d`, so the form choice never reaches the style."
  );
}

console.log(`checks: ${checks}`);
if (problems.length) {
  for (const p of problems) console.log(`::error::${p}`);
  console.log(`3D terrain: ${problems.length} problems`);
  process.exit(1);
}
console.log("3D terrain: fine");
