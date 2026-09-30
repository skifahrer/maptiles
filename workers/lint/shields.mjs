#!/usr/bin/env node
/**
 * Checks ROAD NUMBER SHIELDS (“D1”, “R1”, “I/18”). Run by `Check · workflow lint`.
 *
 * THREE QUIET THINGS – none fails anything and all show only in the map:
 *
 * 1. **A shield with nothing to lean on.** `SHIELD_DEFS` in `themes.js` says which
 *    sprite image a layer asks for. When that image is renamed (or
 *    `poc/web/shields.js` stops drawing it) the style DOESN'T FAIL – `hasIcon`
 *    quietly leaves it without a background and the number draws with a halo only.
 *
 * 2. **Lost stretch bands – and SDF come back.** A shield is a FINISHED COLOUR image,
 *    so nine-slice stretching works on it and must be there – without it a long
 *    number becomes a capsule. `sdf: true` must NOT return: stretching a distance
 *    field breaks the outline into a blurry CROSS. See `poc/web/shields.js`.
 *
 * 3. **A shield under a street name.** MapLibre places labels in layer order, first
 *    come first served. With `road-shield-*` AFTER `road-name`, road numbers would
 *    vanish on dense networks in favour of street names.
 *
 *   node workers/lint/shields.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { THEMES, buildStyle, SHIELD_DEFS } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";
import { SHIELD_SHAPE_IDS, SHIELD_SHAPES, SHIELD_RING } from "../../poc/web/shields.js";
import { encodePng } from "../lib/png.mjs";

let bad = 0;
const error = (file, text) => {
  console.log(`::error file=${file}::${text}`);
  bad += 1;
};

// 1. every shield has its image
for (const [id, , , , , shapeId] of SHIELD_DEFS) {
  if (!SHIELD_SHAPE_IDS.includes(shapeId)) {
    error(
      "poc/web/themes.js",
      `\`road-shield-${id}\` asks for image "${shapeId}", which ` +
        `poc/web/shields.js doesn't draw (it draws: ${SHIELD_SHAPE_IDS.join(", ")}). ` +
        `The style won't fail – the road number stays without a background.`
    );
  }
}

// 1b. the inner field is rounded too – insetting shrinks the radius by the same amount
for (const shape of SHIELD_SHAPES) {
  const inner = shape.radius - 2 * SHIELD_RING;
  if (inner <= 0) {
    error(
      "poc/web/shields.js",
      `shape "${shape.id}" has a ${shape.radius} px radius and a ` +
        `${SHIELD_RING} px ring, leaving the inner field ${inner.toFixed(1)} px ` +
        `– it will have SHARP corners though the outer shape is round. All three ` +
        `shapes must be round: the radius must exceed 2 × the ring ` +
        `(so above ${(2 * SHIELD_RING).toFixed(1)} px).`
    );
  }
}

// 2. stretch bands survive sprite repacking – on a really made sprite
const dir = mkdtempSync(join(tmpdir(), "shields-lint-"));
try {
  const base = join(dir, "sprite");
  // the smallest sprite: one white square
  writeFileSync(
    `${base}.png`,
    encodePng({ width: 4, height: 4, data: Buffer.alloc(4 * 4 * 4, 255) })
  );
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );

  execFileSync("node", ["workers/assets/shields.mjs", `--sprite=${base}`], { stdio: "pipe" });
  const afterShields = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  const names = [];
  for (const shape of SHIELD_SHAPES) {
    for (const [id] of SHIELD_DEFS) {
      for (const theme2 of Object.keys(THEMES)) names.push(`${shape.id}-${id}-${theme2}`);
    }
  }
  for (const name of names) {
    const e = afterShields[name];
    if (!e) {
      error("workers/assets/shields.mjs", `shield "${name}" didn't bake into the sprite.`);
      continue;
    }
    for (const key of ["stretchX", "stretchY", "content"]) {
      if (!e[key]) {
        error("workers/assets/shields.mjs",
          `shield "${name}" has no \`${key}\` in the index – without stretch ` +
          `bands the image scales whole with its corners and a long number becomes a capsule.`);
      }
    }
    if (e.sdf) {
      error("workers/assets/shields.mjs",
        `shield "${name}" is marked \`sdf\` – stretching then breaks the distance ` +
        `field and the shield becomes a blurry cross in the map. The image is ` +
        `coloured; SDF doesn't belong there.`);
    }
  }

  // and the same after the repack pattern baking does
  const styles = join(dir, "styles");
  execFileSync("mkdir", ["-p", styles]);
  writeFileSync(
    join(styles, "x.json"),
    JSON.stringify({
      layers: [{ id: "p", type: "fill", paint: { "fill-pattern": "pat:hatch:3a5a34:16:12" } }]
    })
  );
  execFileSync("node", ["workers/styles/patterns.mjs", `--sprite=${base}`, `--styles=${styles}`],
    { stdio: "pipe" });
  const afterPatterns = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  for (const name of names) {
    const before = afterShields[name] || {};
    const after = afterPatterns[name] || {};
    for (const key of ["stretchX", "stretchY", "content", "sdf"]) {
      if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) {
        error("workers/styles/patterns.mjs",
          `repacking the sprite lost \`${key}\` of shield "${name}" ` +
          `(${JSON.stringify(before[key])} → ${JSON.stringify(after[key])}). ` +
          `Sprite and style stay valid, the shield is just distorted.`);
      }
    }
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

// 3. the shield is above the street name
let checks = 0;
for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    const style = buildStyle({
      theme,
      mapType,
      tilesUrl: "pmtiles://x/t.pmtiles",
      spriteUrl: "https://x/sprite",
      glyphsUrl: "https://x/{fontstack}/{range}.pbf",
      // names are shape × class × theme – a shield is a baked image, not SDF
      icons: SHIELD_SHAPE_IDS.flatMap((shape2) =>
        SHIELD_DEFS.flatMap(([id]) => Object.keys(THEMES).map((t) => `${shape2}-${id}-${t}`)))
    });
    const order = new Map(style.layers.map((l, i) => [l.id, i]));
    const name = order.get("road-name");
    for (const [id] of SHIELD_DEFS) {
      const shieldAt = order.get(`road-shield-${id}`);
      checks += 1;
      if (shieldAt == null) {
        error("poc/web/themes.js", `layer \`road-shield-${id}\` isn't in the style (${theme} × ${mapType}).`);
      } else if (name != null && shieldAt > name) {
        error("poc/web/themes.js",
          `\`road-shield-${id}\` comes AFTER \`road-name\` in the style (${theme} × ${mapType}). ` +
          `MapLibre places labels in layer order, so on a dense network the street ` +
          `name would win and the road number vanish.`);
      }
    }
    // the shield must use its image when the sprite has it
    for (const [id] of SHIELD_DEFS) {
      const l = style.layers.find((x) => x.id === `road-shield-${id}`);
      if (l && !(l.layout || {})["icon-image"]) {
        error("poc/web/themes.js",
          `\`road-shield-${id}\` draws no background even when the shield is in the sprite.`);
      }
    }
  }
}

// 4. a shape switched in developer mode has its image – every shape per class and theme
const baked = new Set(
  SHIELD_SHAPES.flatMap((shape) =>
    SHIELD_DEFS.flatMap(([id]) => Object.keys(THEMES).map((t) => `${shape.id}-${id}-${t}`))
  )
);
for (const theme of Object.keys(THEMES)) {
  for (const shape of SHIELD_SHAPES) {
    const style = buildStyle({
      theme,
      tilesUrl: "pmtiles://x/t.pmtiles",
      spriteUrl: "https://x/sprite",
      glyphsUrl: "https://x/{fontstack}/{range}.pbf",
      icons: [...baked],
      overrides: {
        shields: Object.fromEntries(SHIELD_DEFS.map(([id]) => [id, { shape: shape.id }]))
      }
    });
    for (const [id] of SHIELD_DEFS) {
      const l = style.layers.find((x) => x.id === `road-shield-${id}`);
      const name = (l?.layout || {})["icon-image"];
      if (!name) {
        error(
          "poc/web/themes.js",
          `shield "${id}" lost its background after switching to shape "${shape.id}" (${theme}) – ` +
            `developer mode offers a shape that isn't baked into the sprite.`
        );
      } else if (!baked.has(name)) {
        error(
          "workers/assets/shields.mjs",
          `shield "${id}" asks for image "${name}" after switching shape, which isn't baked.`
        );
      }
    }
  }
}

console.log(
  `road shields: ${bad} errors (${SHIELD_DEFS.length} classes, ${SHIELD_SHAPES.length} shapes, ` +
    `${checks} order checks)`
);
process.exit(bad ? 1 : 0);
