#!/usr/bin/env node
/**
 * 3D terén: sľub o výškovom modeli musí platiť až do štýlu. Volá to
 * `Kontrola · lint workflowov`.
 *
 * ČO STRÁŽI A PREČO. Výškový model (balík `tienovanie`, terrarium dlaždice
 * z `workers/terrain/`) má dve použitia: tieňovanie reliéfu a 3D terén. To
 * druhé je JEDINÝ RIADOK v štýle – `terrain: { source, exaggeration }` –
 * a všetko na ňom je ticho:
 *
 *   - keď `terrain` v štýle NIE JE, klient nakreslí plochú mapu. Nikto
 *     nepovie nič; dlaždice sú stiahnuté, len ich nemá čo vyzdvihnúť. Presne
 *     to sa dialo na iOS, kým si 3D zapínal len web za behu
 *     (`map.setTerrain` v `poc/web/app.js`).
 *   - keď `terrain` v štýle JE, ale ukazuje na zdroj, ktorý v ňom nie je,
 *     MapLibre odmietne CELÝ štýl a mapa sa nevykreslí vôbec.
 *   - keď je zdroj iného typu než `raster-dem`, číta sa z neho výška z RGB
 *     bežnej dlaždice – terén je z toho poskladaný z náhodných hodnôt.
 *
 * ŠTYRI VECI:
 *   1. bez výškových dlaždíc nesmie `terrain` v štýle byť (ukazoval by na nič),
 *   2. s dlaždicami a `terrain3d` musí byť – a musí ukazovať na existujúci
 *      zdroj typu `raster-dem`,
 *   3. prevýšenie musí byť kladné konečné číslo (0 je plochá mapa so zapnutým
 *      3D, čo je najtichšia podoba vypnutého 3D),
 *   4. vypnuté 3D nesmie zobrať tieňovanie: zdroj `dem` a vrstva `hillshade`
 *      ostávajú, lebo sú to tie isté dlaždice a druhé použitie.
 *
 * A JEDNA VEC MIMO ŠTÝLU: `workers/deploy/site.sh` musí písať do manifestu
 * `terrain_3d` podľa HOTOVÉHO štýlu, nie podľa prepínača. Prepínač je `auto`
 * („zapni, ak máme z čoho"), takže sám o výsledku nehovorí – a dve odpovede
 * na jednu otázku sa raz rozídu (pravidlo 1). Appka podľa toho poľa ponúka
 * vrstvu „3D terén", takže rozídenie znamená ponuku, ktorá nič neurobí.
 *
 * Použitie:
 *   node workers/lint/terrain3d.mjs
 */
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { THEMES, buildStyle } from "../../poc/web/themes.js";
import { MAP_TYPE_IDS } from "../../poc/web/map-types.js";

const KOREN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** Vlastné dlaždice z `workers/terrain/pack.py` – jeden `.pmtiles`. */
const VLASTNE_DLAZDICE = "pmtiles://https://x/tiles/region-terrain.pmtiles";

const problems = [];
let checks = 0;

function styl(opts) {
  return buildStyle({
    tilesUrl: "https://x/tiles.pmtiles",
    spriteUrl: "https://x/sprite",
    glyphsUrl: "https://x/fonts/{fontstack}/{range}.pbf",
    ...opts
  });
}

for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    const kde = `${theme}/${mapType}`;

    // 1. bez dlaždíc žiadne 3D
    checks += 1;
    const bezDlazdic = styl({ theme, mapType, demTiles: null, terrain3d: true });
    if (bezDlazdic.terrain) {
      problems.push(
        `${kde}: štýl bez výškových dlaždíc nesie \`terrain\` – ` +
          "ukazuje na zdroj, ktorý v ňom nie je, a MapLibre odmietne celý štýl."
      );
    }

    // 2. s dlaždicami a zapnutým 3D musí byť, a musí ukazovať na raster-dem
    checks += 1;
    const s3d = styl({
      theme,
      mapType,
      demTiles: VLASTNE_DLAZDICE,
      hillshade: true,
      terrain3d: true
    });
    if (!s3d.terrain) {
      problems.push(
        `${kde}: výškové dlaždice v štýle sú a \`terrain3d\` je zapnuté, ale ` +
          "štýl `terrain` nenesie – klient z neho nakreslí plochú mapu a nikto " +
          "nepovie nič."
      );
    } else {
      const id = s3d.terrain.source;
      const zdroj = (s3d.sources || {})[id];
      if (!zdroj) {
        problems.push(`${kde}: \`terrain.source\` = "${id}", taký zdroj v štýle nie je.`);
      } else if (zdroj.type !== "raster-dem") {
        problems.push(
          `${kde}: \`terrain\` ukazuje na zdroj "${id}" typu "${zdroj.type}" – ` +
            "výška sa dá čítať len z `raster-dem`."
        );
      }

      // 3. prevýšenie
      const exag = s3d.terrain.exaggeration;
      if (!Number.isFinite(exag) || exag <= 0) {
        problems.push(
          `${kde}: prevýšenie 3D terénu je ${JSON.stringify(exag)} – ` +
            "plochá mapa so zapnutým 3D je najtichšia podoba vypnutého 3D."
        );
      }
    }

    // 4. vypnuté 3D nesmie zobrať tieňovanie
    checks += 1;
    const bez3d = styl({
      theme,
      mapType,
      demTiles: VLASTNE_DLAZDICE,
      hillshade: true,
      terrain3d: false
    });
    if (bez3d.terrain) {
      problems.push(`${kde}: \`terrain3d\` je vypnuté, ale štýl \`terrain\` nesie.`);
    }
    if (!(bez3d.sources || {}).dem) {
      problems.push(
        `${kde}: vypnuté 3D zobralo aj zdroj \`dem\` – sú to tie isté dlaždice ` +
          "a tieňovanie je ich druhé použitie."
      );
    }
    if (!(bez3d.layers || []).some((l) => l.type === "hillshade")) {
      problems.push(`${kde}: vypnuté 3D zobralo aj vrstvu \`hillshade\`.`);
    }
  }
}

// 5. manifest hovorí o 3D podľa hotového štýlu, nie podľa prepínača
checks += 1;
const site = fs.readFileSync(path.join(KOREN, "workers/deploy/site.sh"), "utf8");
if (!site.includes("terrain_3d:")) {
  problems.push(
    "workers/deploy/site.sh: manifest nenesie `terrain_3d` – appka nemá odkiaľ " +
      "vedieť, ktorý región má 3D, a musela by si rozoberať štýl."
  );
} else if (!/_site\/styles/.test(site.slice(0, site.indexOf("terrain_3d:")))) {
  problems.push(
    "workers/deploy/site.sh: `terrain_3d` sa neberie z hotového štýlu v " +
      "`_site/styles`. Prepínač je `auto` („zapni, ak máme z čoho\"), takže sám " +
      "o výsledku nehovorí – dve odpovede na jednu otázku sa raz rozídu."
  );
}

// 6. beh mapy prepínač vôbec podáva ďalej
checks += 1;
const workflow = fs.readFileSync(
  path.join(KOREN, ".github/workflows/build-map-region.yml"),
  "utf8"
);
if (!workflow.includes("--terrain-3d=")) {
  problems.push(
    ".github/workflows/build-map-region.yml: `workers/styles/build.mjs` nedostáva " +
      "`--terrain-3d`, takže voľba z formulára do štýlu nedôjde."
  );
}

console.log(`kontrol: ${checks}`);
if (problems.length) {
  for (const p of problems) console.log(`::error::${p}`);
  console.log(`3D terén: ${problems.length} problémov`);
  process.exit(1);
}
console.log("3D terén: v poriadku");
