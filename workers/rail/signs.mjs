#!/usr/bin/env node
/**
 * A country's trackside and road signs → sprite `{region}-signs` beside the railway tiles.
 *
 *   node workers/rail/signs.mjs --region=bratislavsky --out=_site/tiles/bratislavsky-signs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { encodePng, packShelves } from "../lib/png.mjs";
import { arc, circle, color, draw, rect, roundedRect } from "../lib/draw.mjs";

const INK = color("#000000");
const MAST = color("#808080");
const WHITE = color("#FFFFFF");
const YELLOW = "#FFD000";
const RED = "#E30513";
const GREEN = "#00D933";
const BLUE = "#1F6BFF";
const BLUE_BOARD = color("#004D9E");

const fill = (poly, c) => ({ fill: poly, color: c });
const stroke = (pts, width, c, closed = false) => ({ stroke: pts, width, color: c, closed });
// white rim, so the sign shows on a dark map too
const rim = (...polys) => polys.map((p) => stroke(p, 2.4, WHITE, true));
const lamp = (x, y, r, c) => fill(circle(x, y, r, 24), c);

function head(lamps, lit) {
  const step = 3.8;
  const height = step * lamps.length + 2.4;
  const body = roundedRect(7, 1, 8, height, 4);
  const post = rect(10.1, 1 + height, 1.8, 20.5 - height);
  return [...rim(body, post), fill(post, MAST), fill(body, INK),
    ...lamps.map((hex, i) => lamp(11, 2.2 + step * (i + 0.5), 1.5,
      color(hex, i === lit ? 1 : 0.18)))];
}

function dwarf() {
  const box = roundedRect(3, 8, 16, 9, 4.5);
  const foot = rect(6, 17, 10, 2.5);
  return [...rim(box, foot), fill(foot, MAST), fill(box, INK),
    lamp(7.5, 12.5, 2.2, color("#FFFFFF", 0.3)), lamp(14.5, 12.5, 2.2, color(BLUE))];
}

function crossingSignal() {
  const body = roundedRect(5, 1, 12, 12, 3);
  const post = rect(9.8, 13, 2.4, 8.5);
  const stripes = [14.5, 17.9, 21.3].map((y) => fill(rect(9.8, y, 2.4, 1.7), WHITE));
  return [...rim(body, post), fill(body, INK), fill(post, INK), ...stripes,
    lamp(11, 4.6, 2, WHITE), lamp(8.2, 9.4, 1.7, color(YELLOW, 0.35)),
    lamp(13.8, 9.4, 1.7, color(YELLOW, 0.35))];
}

function speedBoard() {
  const board = rect(4, 1.5, 14, 19);
  return [...rim(board), fill(board, WHITE), stroke(board, 1.4, INK, true)];
}

function speedWarning() {
  const triangle = [[1.5, 2], [20.5, 2], [11, 20.5]];
  return [stroke(triangle, 3.4, WHITE, true), fill(triangle, color(YELLOW)),
    stroke(triangle, 1.4, INK, true)];
}

function powerOff() {
  const square = [[11, 1], [21, 11], [11, 21], [1, 11]];
  return [...rim(square), fill(square, BLUE_BOARD), stroke(square, 1.2, WHITE, true),
    stroke([[7.5, 6.5], [7.5, 12.5]], 1.8, WHITE), stroke([[14.5, 6.5], [14.5, 12.5]], 1.8, WHITE),
    stroke(arc(11, 12.5, 3.5, 111.6, 180, 10), 1.8, WHITE),
    stroke(arc(11, 12.5, 3.5, 0, 68.4, 10), 1.8, WHITE)];
}

function whistle() {
  const post = rect(8, 1.5, 6, 19);
  const stripes = [1.5, 9.1, 16.7].map((y) => fill(rect(8, y, 6, 3.8), color(RED)));
  return [...rim(post), fill(post, WHITE), ...stripes, stroke(post, 0.8, INK, true)];
}

function platformEnd() {
  const board = rect(2, 4, 18, 14);
  return [...rim(board), fill(board, WHITE), stroke(board, 1, INK, true),
    stroke(rect(5, 7, 12, 8), 2.2, INK, true)];
}

function speedLimit(side, share) {
  const r = side / 2;
  const band = side * share;
  return [fill(circle(r, r, r, 96), color(RED)), fill(circle(r, r, r - band, 96), WHITE)];
}

/** Area for the number in points: `[x, y, width, height]`. */
const number = (x, y, w, h, figures) => ({ content: [x, y, x + w, y + h], figures });

const SIGNS_SK = () => {
  const side = 44;
  const band = side * 0.1;
  const inset = band * 1.35;
  const inner = side - 2 * inset;
  return {
    "rail.signal": { art: head([YELLOW, GREEN, RED, "#FFFFFF"], 2) },
    "rail.combinedSignal": { art: head([YELLOW, GREEN, RED, "#FFFFFF"], 0) },
    "rail.distantSignal": { art: head([YELLOW, GREEN], 0) },
    "rail.shuntingSignal": { art: dwarf() },
    "rail.crossingSignal": { art: crossingSignal() },
    // speed boards show tens of km/h
    "rail.speedLimit": { art: speedBoard(), ...number(5.5, 3.5, 11, 15, "tens") },
    "rail.speedLimitDistant": { art: speedWarning(), ...number(6.5, 3.5, 9, 9, "tens") },
    "rail.electricity": { art: powerOff() },
    "rail.whistle": { art: whistle() },
    "rail.stopPosition": { art: platformEnd() },
    "road.speedLimit": {
      side,
      art: speedLimit(side, 0.1),
      ...number(inset, inset + inner * 0.12, inner, inner * 0.76, "whole")
    }
  };
};

export const SETS = { sk: SIGNS_SK };

/** The set's images at a pixelRatio, named like `sk.rail.signal`. */
export function images(country, ratio) {
  return Object.entries(SETS[country]()).map(([name, z]) => {
    const side = z.side || 22;
    const entry = { pixelRatio: ratio };
    if (z.content) {
      entry.content = z.content.map((v) => Math.round(v * ratio));
      entry.figures = z.figures;
    }
    return { name: `${country}.${name}`, image: draw(side, side, z.art, ratio), entry };
  });
}

export function write(country, base) {
  for (const [suffix, ratio] of [["", 1], ["@2x", 2]]) {
    const boxes = images(country, ratio).map((o) => ({ ...o, width: o.image.width, height: o.image.height }));
    const atlas = packShelves(boxes, 256 * ratio);
    const data = Buffer.alloc(atlas.width * atlas.height * 4);
    const index = {};
    for (const b of boxes) {
      for (let y = 0; y < b.height; y++) {
        data.set(b.image.data.subarray(y * b.width * 4, (y + 1) * b.width * 4),
          ((b.y + y) * atlas.width + b.x) * 4);
      }
      index[b.name] = { x: b.x, y: b.y, width: b.width, height: b.height, ...b.entry };
    }
    writeFileSync(`${base}${suffix}.png`, encodePng({ width: atlas.width, height: atlas.height, data }));
    writeFileSync(`${base}${suffix}.json`, JSON.stringify(index, null, 1) + "\n");
  }
}

const readData = (name) => JSON.parse(readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "data", name), "utf8"));

/** The region's lower-case ISO country code; a region takes its country's, an area by position. */
export function regionCountry(key, regions = readData("regions.json"), areas = readData("areas.json")) {
  const bare = key.replace(/_test[\d.]+km2$/, "");
  const r = regions[bare];
  if (r) return (r.iso || (regions[r.country] || {}).iso || "").toLowerCase();
  const box = (areas[bare] || {}).bbox;
  if (!box) return "";
  const [x, y] = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  const country = Object.values(regions).find(({ iso, bbox: b }) =>
    iso && b && x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]);
  return (country?.iso || "").toLowerCase();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = Object.fromEntries(process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=")];
  }));
  if (!args.region || !args.out) {
    console.error("Usage: node workers/rail/signs.mjs --region=<key> --out=<base>");
    process.exit(2);
  }
  const country = regionCountry(args.region);
  if (!SETS[country]) {
    console.log(`Country “${country || "?"}” has no signs of its own – the app draws the defaults.`);
    process.exit(0);
  }
  write(country, args.out);
  console.log(`Signs ${country} → ${args.out}.json/.png (+@2x)`);
}
