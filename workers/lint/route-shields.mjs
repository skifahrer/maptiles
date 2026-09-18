#!/usr/bin/env node
/**
 * Kontrola ŠTÍTKOV PODĽA SIETE („D1", „E 75", chorvátske „A1").
 * Volá ju `Kontrola · lint workflowov`.
 *
 * Štyri tiché veci – ani jedna nič nezhodí a všetky sa prejavia až v mape:
 * sieť bez obrázka ticho spadne na klasický štítok, stratené `stretchX` spraví
 * z dlhého čísla kapsulu, `sdf: true` z neho spraví rozmazaný kríž a chýbajúca
 * záloha v `match` nechá neznámu sieť úplne bez podkladu.
 *
 *   node workers/lint/route-shields.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { buildStyle, SHIELD_DEFS, EURO_NETWORK, THEMES } from "../../poc/web/themes.js";
import {
  ROUTE_SHIELDS,
  ROUTE_SHIELD_NETWORKS,
  ROUTE_SHIELD_COLORS,
  routeShieldName,
  routeShieldRecipes
} from "../../poc/web/route-shields.js";
import { encodePng } from "../lib/png.mjs";

let bad = 0;
const chyba = (subor, text) => {
  console.log(`::error file=${subor}::${text}`);
  bad += 1;
};

// 1. každá sieť má farby, ktoré paleta pozná
for (const [network, def] of Object.entries(ROUTE_SHIELDS)) {
  for (const key of ["fill", "stroke", "text"]) {
    if (!ROUTE_SHIELD_COLORS[def[key]]) {
      chyba("poc/web/route-shields.js",
        `sieť "${network}" má \`${key}\` = "${def[key]}", ktoré paleta nepozná ` +
        `(pozná: ${Object.keys(ROUTE_SHIELD_COLORS).join(", ")}).`);
    }
  }
  if (!["rrect", "hex", "oct"].includes(def.shape)) {
    chyba("poc/web/route-shields.js",
      `sieť "${network}" má tvar "${def.shape}", ktorý sa nekreslí.`);
  }
}

// 2. obrázky sa naozaj dopečú a prežijú preskladanie spritu
const dir = mkdtempSync(join(tmpdir(), "route-shields-lint-"));
try {
  const base = join(dir, "sprite");
  writeFileSync(
    `${base}.png`,
    encodePng({ width: 4, height: 4, data: Buffer.alloc(4 * 4 * 4, 255) })
  );
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );
  execFileSync("node", ["workers/assets/route-shields.mjs", `--sprite=${base}`], { stdio: "pipe" });
  const index = JSON.parse(readFileSync(`${base}.json`, "utf8"));

  for (const network of ROUTE_SHIELD_NETWORKS) {
    const meno = routeShieldName(network);
    if (!index[meno]) {
      chyba("workers/assets/route-shields.mjs",
        `sieť "${network}" si pýta obrázok "${meno}", ktorý sa do spritu ` +
        `nedopiekol – štýl ju ticho nakreslí klasickým štítkom podľa triedy.`);
    }
  }

  for (const { name, def } of routeShieldRecipes()) {
    const e = index[name];
    if (!e) continue;
    if (e.sdf) {
      chyba("workers/assets/route-shields.mjs",
        `štítok "${name}" je označený ako \`sdf\` – obrázok je farebný, ` +
        `vzdialenostné pole tam nepatrí a v mape je z neho rozmazaný kríž.`);
    }
    // hrot šesť- a osemuholníka rovnú časť nemá, tie sa škálujú celé
    if (def.shape !== "rrect") continue;
    for (const kluc of ["stretchX", "stretchY", "content"]) {
      if (!e[kluc]) {
        chyba("workers/assets/route-shields.mjs",
          `štítok "${name}" nemá v indexe \`${kluc}\` – bez rozťahovacích ` +
          `pásem sa obrázok škáluje aj s rohmi a z dlhého čísla je kapsula.`);
      }
    }
  }

  // 3. záloha: `match` musí končiť klasickým štítkom podľa triedy
  const icons = [...Object.keys(index), "shield-motorway-svetla", "shield-primary-svetla",
                 "shield-secondary-svetla", "shield-euro-svetla"];
  const style = buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://t",
    spriteUrl: "http://s",
    glyphsUrl: "g/{fontstack}/{range}",
    icons
  });
  // posledná vetva `match`-u je záloha – tú hľadá aj aplikácia
  const zaloha = (hodnota) => {
    if (!Array.isArray(hodnota) || hodnota[0] !== "let") return null;
    const telo = hodnota[hodnota.length - 1];
    if (!Array.isArray(telo) || telo[0] !== "match") return null;
    return telo[telo.length - 1];
  };

  for (const [id, , , , , , textKey] of SHIELD_DEFS) {
    const vrstva = style.layers.find((l) => l.id === `road-shield-${id}`);
    if (!vrstva) {
      chyba("poc/web/themes.js", `vrstva "road-shield-${id}" v štýle nie je.`);
      continue;
    }
    if (zaloha(vrstva.layout["icon-image"]) !== `shield-${id}-svetla`) {
      chyba("poc/web/themes.js",
        `"road-shield-${id}" nemá na konci \`match\`-u klasický štítok ako zálohu ` +
        `– cesta v sieti, ktorú tabuľka nepozná, by ostala bez podkladu a ` +
        `aplikácia by sa nemala ako prepnúť späť.`);
    }
    if (zaloha(vrstva.paint["text-color"]) !== THEMES.svetla[textKey]) {
      chyba("poc/web/themes.js",
        `"road-shield-${id}" nemá na konci \`match\`-u farbu čísla zo štýlu ako zálohu.`);
    }
  }

  // 4. vypnuté štítky podľa siete = presne to, čo bolo predtým
  const vypnute = buildStyle({
    theme: "svetla",
    tilesUrl: "pmtiles://t",
    spriteUrl: "http://s",
    glyphsUrl: "g/{fontstack}/{range}",
    icons,
    overrides: { routeShields: false }
  });
  for (const [id] of SHIELD_DEFS) {
    const obrazok = vypnute.layers.find((l) => l.id === `road-shield-${id}`)?.layout["icon-image"];
    if (obrazok !== `shield-${id}-svetla`) {
      chyba("poc/web/themes.js",
        `s vypnutými štítkami podľa siete kreslí "road-shield-${id}" ` +
        `"${JSON.stringify(obrazok)}" namiesto klasického "shield-${id}-svetla".`);
    }
  }

  if (!ROUTE_SHIELDS[EURO_NETWORK]) {
    chyba("poc/web/route-shields.js",
      `európska cesta ("${EURO_NETWORK}") vlastný štítok nemá, hoci vrstva pre ňu je.`);
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

if (bad) {
  console.log(`::error::Štítky podľa siete: ${bad} ${bad === 1 ? "chyba" : "chýb"}.`);
  process.exit(1);
}
console.log(`✓ Štítky podľa siete: ${ROUTE_SHIELD_NETWORKS.length} sietí, ` +
  `${routeShieldRecipes().length} obrázkov, záloha na mieste.`);
