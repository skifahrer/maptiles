#!/usr/bin/env node
/**
 * Checks hiking and cycling waymarks along trails. Run by `Check · workflow lint`.
 *
 * A mark's image name is assembled from data: `trails/tags.py` writes shape,
 * background and colour, the style `concat`s a name from them and
 * `assets/marks.mjs` must have it in the sprite. Three places – drifted, MapLibre
 * quietly skips the unknown image and the trail shows nothing.
 *
 *   1. every `OSMC_SHAPES` shape is drawn by `poc/web/marks.js`;
 *   2. background × colour pairs (`MARK_FACES`) match on both sides;
 *   3. the stripe colour differs from the background (else an empty square);
 *   4. the name the style assembles equals `markImage()`;
 *   5. the attributes are in the tile schema;
 *   6. every trail type has a mark layer and the type icon draws only without a mark;
 *   7. two trails' marks stack – without `side` and `off` offsets they land on one
 *      spot and collision always keeps the same one;
 *   8. marks really bake and none is `sdf` (SDF would make one colour of three).
 *
 *   node workers/lint/marks.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { encodePng } from "../lib/png.mjs";
import {
  MARK_SHAPE_IDS,
  MARK_FACES,
  MARK_COLOURS,
  MARK_IMAGE,
  markImage,
  markImages
} from "../../poc/web/marks.js";
import {
  THEMES,
  TRAIL_TYPES,
  TRAIL_MARK_STACK,
  TRAIL_MARK_STACK_MAX,
  TRAIL_MARK_PADDING,
  buildStyle
} from "../../poc/web/themes.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const TAGS = join(ROOT, "workers", "trails", "tags.py");
const SCHEMA = join(ROOT, "workers", "trails", "trails.yml");

let bad = 0;
const error = (file, text) => {
  console.log(`::error file=${file}::${text}`);
  bad += 1;
};

const py = readFileSync(TAGS, "utf8");

// 1. the shapes the data can send
const shapesBlock = py.match(/OSMC_SHAPES\s*=\s*\{([\s\S]*?)\n\}/);
if (!shapesBlock) {
  error("workers/trails/tags.py", "`OSMC_SHAPES` not found – without it the shapes going into tiles can't be checked.");
} else {
  const shapes = new Set(
    [...shapesBlock[1].matchAll(/"[a-z_]+"\s*:\s*"([a-z_]+)"/g)].map((m) => m[1])
  );
  if (!shapes.size) {
    error("workers/trails/tags.py", "`OSMC_SHAPES` is empty – no trail would get a mark.");
  }
  for (const shape of shapes) {
    if (!MARK_SHAPE_IDS.includes(shape)) {
      error(
        "workers/trails/tags.py",
        `\`OSMC_SHAPES\` sends shape "${shape}" into tiles, which poc/web/marks.js ` +
          `doesn't draw (it draws: ${MARK_SHAPE_IDS.join(", ")}). The sprite won't have ` +
          `the image and the trail no mark – MapLibre quietly skips it.`
      );
    }
  }
}

// 2. + 3. background × colour pairs
const facesBlock = py.match(/MARK_FACES\s*=\s*\{([\s\S]*?)\n\}/);
const jsFaces = new Set(MARK_FACES.map(([bg, fg]) => `${bg}-${fg}`));
if (!facesBlock) {
  error("workers/trails/tags.py", "`MARK_FACES` not found – the pairs going into tiles can't be checked.");
} else {
  const pyFaces = new Set(
    [...facesBlock[1].matchAll(/\("([a-z]+)",\s*"([a-z]+)"\)/g)].map((m) => `${m[1]}-${m[2]}`)
  );
  for (const face of pyFaces) {
    if (!jsFaces.has(face)) {
      error(
        "workers/trails/tags.py",
        `background-colour pair "${face}" is in the data, but marks.js doesn't bake ` +
          `it – such a trail stays without a mark in the map.`
      );
    }
  }
  for (const face of jsFaces) {
    if (!pyFaces.has(face)) {
      error(
        "poc/web/marks.js",
        `pair "${face}" is baked into the sprite, but tags.py never writes it – ` +
          `a spare image. Either add it to MARK_FACES in tags.py or delete it here.`
      );
    }
  }
}
for (const [bg, fg] of MARK_FACES) {
  if (bg === fg) {
    error("poc/web/marks.js", `pair "${bg}-${fg}" has the stripe in the background colour – such a mark is an empty square.`);
  }
  for (const [role, colour] of [["background", bg], ["colour", fg]]) {
    if (!MARK_COLOURS[colour]) {
      error("poc/web/marks.js", `pair "${bg}-${fg}": ${role} "${colour}" isn't in MARK_COLOURS.`);
    }
  }
}

// 5. attributes in the tile schema
const yml = readFileSync(SCHEMA, "utf8");
for (const key of ["mark", "mark_bg", "mark_fg"]) {
  if (!new RegExp(`- key: ${key}\\s`).test(yml)) {
    error(
      "workers/trails/trails.yml",
      `attribute \`${key}\` isn't in the tile schema – the style would read nothing ` +
        `from it and the image name would be nonsense. Trails would have no marks.`
    );
  }
}

// 4., 6., 7. what the style makes of it
/** Evaluates `["concat", …]` over one feature – that much of expressions will do. */
function evalConcat(expr, props) {
  if (typeof expr === "string") return expr;
  if (!Array.isArray(expr)) return String(expr);
  if (expr[0] === "get") return String(props[expr[1]] ?? "");
  if (expr[0] === "concat") return expr.slice(1).map((e) => evalConcat(e, props)).join("");
  return `?${expr[0]}?`;
}

const style = buildStyle({
  theme: Object.keys(THEMES)[0],
  tilesUrl: "pmtiles://x/t.pmtiles",
  spriteUrl: "https://x/sprite",
  glyphsUrl: "https://x/{fontstack}/{range}.pbf",
  trailsUrl: "pmtiles://x/trails.pmtiles",
  icons: markImages().map((m) => m.name)
});
const order = new Map(style.layers.map((l, i) => [l.id, i]));
const spacings = new Map();
for (const t of TRAIL_TYPES) {
  const mark = style.layers.find((l) => l.id === `trail-${t.id}-mark`);
  if (!mark) {
    error(
      "poc/web/themes.js",
      `layer \`trail-${t.id}-mark\` isn't in the style though the sprite has marks – ` +
        `trails of this type would stay unmarked.`
    );
    continue;
  }
  const name = evalConcat(mark.layout["icon-image"], {
    mark_bg: "white",
    mark_fg: "red",
    mark: "bar"
  });
  if (name !== markImage("white", "red", "bar")) {
    error(
      "poc/web/themes.js",
      `\`trail-${t.id}-mark\` assembles the image name as "${name}", but marks.js ` +
        `bakes it as "${markImage("white", "red", "bar")}". Two paths to one name – ` +
        `drifted, they mean emptiness in the map.`
    );
  }
  // a lane offset reads `off` and `side`, and every `(side, off)` pair shifts ELSEWHERE
  const offset = JSON.stringify(mark.layout["icon-offset"] || null);
  for (const key of ["side", "off"]) {
    if (!offset.includes(`"${key}"`)) {
      error(
        "poc/web/themes.js",
        `\`trail-${t.id}-mark\` doesn't read \`${key}\` when offsetting the mark. ` +
          `Trails on one road share the geometry, so marks would land on one spot ` +
          `and collision would keep one – the rest wouldn't be in the map at all.`
      );
      break;
    }
  }
  const offsets = new Set();
  for (const side of [1, -1]) {
    for (let off = 0; off <= TRAIL_MARK_STACK_MAX; off += 1) {
      const y = -side * (TRAIL_MARK_STACK.base + TRAIL_MARK_STACK.step * off);
      const key = `${side}:${off}`;
      if (offsets.has(String(y))) {
        error(
          "poc/web/themes.js",
          `the mark offset for lane ${key} equals another lane's (y = ${y}) – ` +
            `two trails would have their mark in one place.`
        );
      }
      offsets.add(String(y));
    }
  }
  spacings.set(offset, t.id);

  // a tight stack must ignore collisions: the box is the WHOLE image plus padding
  const tight = TRAIL_MARK_STACK.step < MARK_IMAGE + 2 * TRAIL_MARK_PADDING;
  if (tight && mark.layout["icon-allow-overlap"] !== true) {
    error(
      "poc/web/themes.js",
      `\`trail-${t.id}-mark\` has a ${TRAIL_MARK_STACK.step} px stack step, but ` +
        `the mark's collision box is ${MARK_IMAGE + 2 * TRAIL_MARK_PADDING} px ` +
        `(image ${MARK_IMAGE} + 2 × padding ${TRAIL_MARK_PADDING}) – without ` +
        `\`icon-allow-overlap\` only the first mark of the stack would stay.`
    );
  }

  // the trail type icon REPLACES the mark, it isn't a second symbol
  const icon = style.layers.find((l) => l.id === `trail-${t.id}-icon`);
  // the type icon stands in the same stack, so it needs `icon-allow-overlap` too
  if (icon && JSON.stringify(icon.layout["icon-offset"] || null).includes('"off"')
      && icon.layout["icon-allow-overlap"] !== true) {
    error(
      "poc/web/themes.js",
      `\`trail-${t.id}-icon\` shifts by lane but draws with collisions – of the ` +
        `icons of several trails on one road only one would stay.`
    );
  }
  if (icon && !JSON.stringify(icon.filter).includes('["!",["has","mark"]]')) {
    error(
      "poc/web/themes.js",
      `\`trail-${t.id}-icon\` draws where the trail has a mark too – one line ` +
        `would carry two symbols fighting for space.`
    );
  }
  const label = order.get(`trail-${t.id}-label`);
  if (label != null && order.get(`trail-${t.id}-mark`) > label) {
    error(
      "poc/web/themes.js",
      `\`trail-${t.id}-mark\` comes after the trail labels. MapLibre places symbols ` +
        `in layer order, so the trail name would take the mark's place – and the mark ` +
        `is what one follows in the field.`
    );
  }
}

// 8. marks really bake
const dir = mkdtempSync(join(tmpdir(), "marks-lint-"));
try {
  const base = join(dir, "sprite");
  // the smallest sprite: one square, so there's something to repack
  writeFileSync(`${base}.png`, encodePng({ width: 4, height: 4, data: Buffer.alloc(64, 255) }));
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );
  execFileSync("node", ["workers/assets/marks.mjs", `--sprite=${base}`], {
    stdio: "pipe",
    cwd: ROOT
  });
  const index = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  let missing = 0;
  for (const { name } of markImages()) {
    const e = index[name];
    if (!e) {
      missing += 1;
      if (missing <= 3) {
        error("workers/assets/marks.mjs", `mark "${name}" didn't bake into the sprite.`);
      }
      continue;
    }
    if (e.sdf) {
      error(
        "workers/assets/marks.mjs",
        `mark "${name}" is marked \`sdf\` – a distance field carries one colour, ` +
          `while a mark has three (background, stripe, rim).`
      );
    }
  }
  if (missing > 3) {
    error("workers/assets/marks.mjs", `… and ${missing - 3} more marks are missing.`);
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

console.log(
  `trail marks: ${bad} errors (${MARK_SHAPE_IDS.length} shapes × ${MARK_FACES.length} pairs ` +
    `= ${markImages().length} images, ${TRAIL_TYPES.length} trail types)`
);
process.exit(bad ? 1 : 0);
