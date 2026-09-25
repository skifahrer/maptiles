#!/usr/bin/env node
/**
 * Značky krajiny pri trati a na ceste → sprite `{región}-signs` vedľa dlaždíc železníc.
 *
 *   node workers/rail/signs.mjs --region=bratislavsky --out=_site/tiles/bratislavsky-signs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { encodePng, packShelves } from "../lib/png.mjs";
import { farba, kruh, nakresli, obdlznik, obluk, zaoblenyObdlznik } from "../lib/kresba.mjs";

const INK = farba("#000000");
const STOZIAR = farba("#808080");
const BIELA = farba("#FFFFFF");
const ZLTA = "#FFD000";
const CERVENA = "#E30513";
const ZELENA = "#00D933";
const MODRA = "#1F6BFF";
const MODRA_TABULA = farba("#004D9E");

const vypln = (poly, f) => ({ vypln: poly, farba: f });
const tah = (body, sirka, f, zavreta = false) => ({ tah: body, sirka, farba: f, zavreta });
// biely lem, aby značka bola vidno aj na tmavej mape
const lem = (...polys) => polys.map((p) => tah(p, 2.4, BIELA, true));
const lampa = (x, y, r, f) => vypln(kruh(x, y, r, 24), f);

function hlava(lampy, svieti) {
  const krok = 3.8;
  const vyska = krok * lampy.length + 2.4;
  const telo = zaoblenyObdlznik(7, 1, 8, vyska, 4);
  const stlp = obdlznik(10.1, 1 + vyska, 1.8, 20.5 - vyska);
  return [...lem(telo, stlp), vypln(stlp, STOZIAR), vypln(telo, INK),
    ...lampy.map((hex, i) => lampa(11, 2.2 + krok * (i + 0.5), 1.5,
      farba(hex, i === svieti ? 1 : 0.18)))];
}

function trpaslik() {
  const skrina = zaoblenyObdlznik(3, 8, 16, 9, 4.5);
  const noha = obdlznik(6, 17, 10, 2.5);
  return [...lem(skrina, noha), vypln(noha, STOZIAR), vypln(skrina, INK),
    lampa(7.5, 12.5, 2.2, farba("#FFFFFF", 0.3)), lampa(14.5, 12.5, 2.2, farba(MODRA))];
}

function priecestnik() {
  const telo = zaoblenyObdlznik(5, 1, 12, 12, 3);
  const stlp = obdlznik(9.8, 13, 2.4, 8.5);
  const pasy = [14.5, 17.9, 21.3].map((y) => vypln(obdlznik(9.8, y, 2.4, 1.7), BIELA));
  return [...lem(telo, stlp), vypln(telo, INK), vypln(stlp, INK), ...pasy,
    lampa(11, 4.6, 2, BIELA), lampa(8.2, 9.4, 1.7, farba(ZLTA, 0.35)),
    lampa(13.8, 9.4, 1.7, farba(ZLTA, 0.35))];
}

function rychlostnik() {
  const tabula = obdlznik(4, 1.5, 14, 19);
  return [...lem(tabula), vypln(tabula, BIELA), tah(tabula, 1.4, INK, true)];
}

function predzvestnik() {
  const trojuholnik = [[1.5, 2], [20.5, 2], [11, 20.5]];
  return [tah(trojuholnik, 3.4, BIELA, true), vypln(trojuholnik, farba(ZLTA)),
    tah(trojuholnik, 1.4, INK, true)];
}

function vypnitePrud() {
  const stvorec = [[11, 1], [21, 11], [11, 21], [1, 11]];
  return [...lem(stvorec), vypln(stvorec, MODRA_TABULA), tah(stvorec, 1.2, BIELA, true),
    tah([[7.5, 6.5], [7.5, 12.5]], 1.8, BIELA), tah([[14.5, 6.5], [14.5, 12.5]], 1.8, BIELA),
    tah(obluk(11, 12.5, 3.5, 111.6, 180, 10), 1.8, BIELA),
    tah(obluk(11, 12.5, 3.5, 0, 68.4, 10), 1.8, BIELA)];
}

function piskajte() {
  const stlp = obdlznik(8, 1.5, 6, 19);
  const pasy = [1.5, 9.1, 16.7].map((y) => vypln(obdlznik(8, y, 6, 3.8), farba(CERVENA)));
  return [...lem(stlp), vypln(stlp, BIELA), ...pasy, tah(stlp, 0.8, INK, true)];
}

function koniecNastupista() {
  const tabula = obdlznik(2, 4, 18, 14);
  return [...lem(tabula), vypln(tabula, BIELA), tah(tabula, 1, INK, true),
    tah(obdlznik(5, 7, 12, 8), 2.2, INK, true)];
}

function obmedzenieRychlosti(strana, podiel) {
  const r = strana / 2;
  const pas = strana * podiel;
  return [vypln(kruh(r, r, r, 96), farba(CERVENA)), vypln(kruh(r, r, r - pas, 96), BIELA)];
}

/** Plocha na číslo v bodoch: `[x, y, šírka, výška]`. */
const cislo = (x, y, w, h, cifry) => ({ obsah: [x, y, x + w, y + h], cifry });

const ZNACKY_SK = () => {
  const strana = 44;
  const pas = strana * 0.1;
  const dnu = pas * 1.35;
  const vnutro = strana - 2 * dnu;
  return {
    "rail.signal": { kresba: hlava([ZLTA, ZELENA, CERVENA, "#FFFFFF"], 2) },
    "rail.combinedSignal": { kresba: hlava([ZLTA, ZELENA, CERVENA, "#FFFFFF"], 0) },
    "rail.distantSignal": { kresba: hlava([ZLTA, ZELENA], 0) },
    "rail.shuntingSignal": { kresba: trpaslik() },
    "rail.crossingSignal": { kresba: priecestnik() },
    // rýchlostník aj predzvestník ukazujú desiatky km/h
    "rail.speedLimit": { kresba: rychlostnik(), ...cislo(5.5, 3.5, 11, 15, "tens") },
    "rail.speedLimitDistant": { kresba: predzvestnik(), ...cislo(6.5, 3.5, 9, 9, "tens") },
    "rail.electricity": { kresba: vypnitePrud() },
    "rail.whistle": { kresba: piskajte() },
    "rail.stopPosition": { kresba: koniecNastupista() },
    "road.speedLimit": {
      strana,
      kresba: obmedzenieRychlosti(strana, 0.1),
      ...cislo(dnu, dnu + vnutro * 0.12, vnutro, vnutro * 0.76, "whole")
    }
  };
};

export const SADY = { sk: ZNACKY_SK };

/** Obrázky sady pri danom pixelRatio, s menom `sk.rail.signal`. */
export function obrazky(krajina, pomer) {
  return Object.entries(SADY[krajina]()).map(([meno, z]) => {
    const strana = z.strana || 22;
    const entry = { pixelRatio: pomer };
    if (z.obsah) {
      entry.content = z.obsah.map((v) => Math.round(v * pomer));
      entry.figures = z.cifry;
    }
    return { name: `${krajina}.${meno}`, image: nakresli(strana, strana, z.kresba, pomer), entry };
  });
}

export function zapis(krajina, zaklad) {
  for (const [pripona, pomer] of [["", 1], ["@2x", 2]]) {
    const boxy = obrazky(krajina, pomer).map((o) => ({ ...o, width: o.image.width, height: o.image.height }));
    const atlas = packShelves(boxy, 256 * pomer);
    const data = Buffer.alloc(atlas.width * atlas.height * 4);
    const index = {};
    for (const b of boxy) {
      for (let y = 0; y < b.height; y++) {
        data.set(b.image.data.subarray(y * b.width * 4, (y + 1) * b.width * 4),
          ((b.y + y) * atlas.width + b.x) * 4);
      }
      index[b.name] = { x: b.x, y: b.y, width: b.width, height: b.height, ...b.entry };
    }
    writeFileSync(`${zaklad}${pripona}.png`, encodePng({ width: atlas.width, height: atlas.height, data }));
    writeFileSync(`${zaklad}${pripona}.json`, JSON.stringify(index, null, 1) + "\n");
  }
}

const citaj = (meno) => JSON.parse(readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "data", meno), "utf8"));

/** ISO kód krajiny regiónu, malými písmenami; kraj ho berie od krajiny, výsek podľa polohy. */
export function krajinaRegionu(kluc, regiony = citaj("regions.json"), vyseky = citaj("areas.json")) {
  const holy = kluc.replace(/_test[\d.]+km2$/, "");
  const r = regiony[holy];
  if (r) return (r.iso || (regiony[r.country] || {}).iso || "").toLowerCase();
  const box = (vyseky[holy] || {}).bbox;
  if (!box) return "";
  const [x, y] = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  const krajina = Object.values(regiony).find(({ iso, bbox: b }) =>
    iso && b && x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]);
  return (krajina?.iso || "").toLowerCase();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = Object.fromEntries(process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=")];
  }));
  if (!args.region || !args.out) {
    console.error("Použitie: node workers/rail/signs.mjs --region=<kľúč> --out=<základ>");
    process.exit(2);
  }
  const krajina = krajinaRegionu(args.region);
  if (!SADY[krajina]) {
    console.log(`Krajina „${krajina || "?"}" vlastné značky nemá – appka kreslí predvolené.`);
    process.exit(0);
  }
  zapis(krajina, args.out);
  console.log(`Značky ${krajina} → ${args.out}.json/.png (+@2x)`);
}
