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
  ROUTE_SHIELD_NETWORKS,
  routeShieldDef,
  routeShieldName,
  routeShieldRecipes
} from "../../poc/web/route-shields.js";
import { EXTRA_SHIELDS } from "../../poc/web/route-shield-defs.js";
import { outline, blankWidth, stretchable } from "../../poc/web/route-shield-shapes.js";
import { AMERICANA_NETWORKS } from "../../poc/web/route-shield-americana.js";
import { encodePng } from "../lib/png.mjs";

let bad = 0;
const chyba = (subor, text) => {
  console.log(`::error file=${subor}::${text}`);
  bad += 1;
};

// 1. každý recept sa dá nakresliť: tvar, farby a obrys, ktorý sa uzavrie
const HEX = /^#[0-9a-f]{6}$/i;
for (const { name, def } of routeShieldRecipes()) {
  for (const key of ["fill", "text"]) {
    if (!HEX.test(def[key] || "")) {
      chyba("poc/web/route-shield-americana.js",
        `štítok "${name}" má \`${key}\` = "${def[key]}", čo nie je #rrggbb ` +
        `– importér pozná len mená "white" a "black".`);
    }
  }
  if (def.stroke && !HEX.test(def.stroke)) {
    chyba("poc/web/route-shield-americana.js",
      `štítok "${name}" má \`stroke\` = "${def.stroke}", čo nie je #rrggbb.`);
  }
  const pts = outline(def, 1);
  if (!pts || pts.length < 3) {
    chyba("poc/web/route-shield-shapes.js",
      `tvar "${def.shape}" sa nekreslí – štítok "${name}" by ostal prázdny.`);
    continue;
  }
  const sirka = blankWidth(def);
  const mimo = pts.some(([x, y]) => x < -0.01 || y < -0.01 || x > sirka + 0.01);
  if (mimo) {
    chyba("poc/web/route-shield-shapes.js",
      `obrys štítka "${name}" (tvar ${def.shape}) vychádza mimo obrázka ` +
      `– v mape by bol orezaný.`);
  }
}

// 1b. každá sieť ukazuje na recept, ktorý existuje
for (const network of ROUTE_SHIELD_NETWORKS) {
  if (!routeShieldDef(network)) {
    chyba("poc/web/route-shield-defs.js",
      `sieť "${network}" nemá recept – štýl by si pýtal obrázok, ktorý nie je.`);
  }
}

// 1c. vlastné siete nie sú tiché prepísanie americkej tabuľky
for (const network of Object.keys(EXTRA_SHIELDS)) {
  if (AMERICANA_NETWORKS[network] !== undefined) {
    chyba("poc/web/route-shield-defs.js",
      `sieť "${network}" je aj v generovanej tabuľke – vlastná ju ticho prebíja. ` +
      `Buď ju z \`EXTRA_SHIELDS\` vyhoď, alebo si to obhaj poznámkou.`);
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
    // tvar s hrotom rovnú časť hrany nemá, ten sa škáluje celý
    if (!stretchable(def)) continue;
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
    if (!Array.isArray(hodnota) || hodnota[0] !== "let") return hodnota;
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

  if (!routeShieldDef(EURO_NETWORK)) {
    chyba("poc/web/route-shield-defs.js",
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
