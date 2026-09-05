#!/usr/bin/env node
/**
 * Kontrola ŠTÍTKOV S ČÍSLOM CESTY („D1", „R1", „I/18").
 * Volá ju `Kontrola · lint workflowov`.
 *
 * TRI TICHÉ VECI – žiadna z nich nič nezhodí a všetky sa prejavia až v mape:
 *
 * 1. **Štítok, ktorý sa nemá o čo oprieť.** `SHIELD_DEFS` v `themes.js`
 *    hovorí, ktorý obrázok zo spritu si vrstva vypýta. Keď sa ten obrázok
 *    premenuje (alebo ho `poc/web/shields.js` prestane kresliť), štýl
 *    NESPADNE – `hasIcon` ho ticho nechá bez podkladu a číslo sa nakreslí len
 *    s halom. Vyzerá to ako „tak to je navrhnuté", nie ako chyba.
 *
 * 2. **Stratené rozťahovacie pásma – a SDF, ktoré sa vrátilo.** Štítok je
 *    HOTOVÝ FAREBNÝ obrázok (dva rovnako hrubé prstence sa jedným
 *    `icon-halo` spraviť nedajú), takže deväťdielne naťahovanie na ňom
 *    funguje správne a musí tam byť – bez neho je z dlhého čísla kapsula.
 *    Naopak `sdf: true` sa vrátiť NESMIE: na vzdialenostnom poli to isté
 *    naťahovanie pole rozladí a obrys pretrhne, a v mape z toho bol
 *    rozmazaný KRÍŽ (namerané 89 × 85 px proti správnym ~20 × 14 px).
 *    Ani jedno nič nezhodí. Rozpis je v hlavičke `poc/web/shields.js`.
 *
 * 3. **Štítok pod menom ulice.** MapLibre umiestňuje popisky v poradí vrstiev
 *    a kto je skôr, berie si miesto prvý. Keby `road-shield-*` skončili ZA
 *    `road-name`, na hustej sieti by čísla ciest mizli v prospech mien ulíc –
 *    a práve číslo je to, čo človek na mape hľadá.
 *
 * Použitie:
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
const chyba = (subor, text) => {
  console.log(`::error file=${subor}::${text}`);
  bad += 1;
};

// 1. každý štítok má svoj obrázok
for (const [id, , , , , shapeId] of SHIELD_DEFS) {
  if (!SHIELD_SHAPE_IDS.includes(shapeId)) {
    chyba(
      "poc/web/themes.js",
      `\`road-shield-${id}\` si pýta obrázok "${shapeId}", ktorý ` +
        `poc/web/shields.js nekreslí (kreslí: ${SHIELD_SHAPE_IDS.join(", ")}). ` +
        `Štýl kvôli tomu nespadne – číslo cesty ostane bez podkladu.`
    );
  }
}

// 1b. zaoblené je aj vnútorné pole
// Pásma vznikajú odsadením dovnútra a polomer sa pri tom zmenšuje o to isté;
// pri nule alebo menej má vnútro ostré rohy, hoci vonkajší tvar je zaoblený.
for (const shape of SHIELD_SHAPES) {
  const vnutro = shape.radius - 2 * SHIELD_RING;
  if (vnutro <= 0) {
    chyba(
      "poc/web/shields.js",
      `tvar "${shape.id}" má polomer ${shape.radius} px a prstenec ` +
        `${SHIELD_RING} px, takže vnútornému poľu ostane ${vnutro.toFixed(1)} px ` +
        `– bude mať OSTRÉ rohy, hoci vonkajší tvar je zaoblený. Zaoblené majú ` +
        `byť všetky tri tvary: polomer musí byť väčší než 2 × prstenec ` +
        `(teda nad ${(2 * SHIELD_RING).toFixed(1)} px).`
    );
  }
}

// 2. rozťahovacie pásma prežijú preskladanie spritu – na naozaj vyrobenom sprite
const dir = mkdtempSync(join(tmpdir(), "shields-lint-"));
try {
  const base = join(dir, "sprite");
  // najmenší možný sprite: jeden biely štvorček
  writeFileSync(
    `${base}.png`,
    encodePng({ width: 4, height: 4, data: Buffer.alloc(4 * 4 * 4, 255) })
  );
  writeFileSync(
    `${base}.json`,
    JSON.stringify({ test_11: { x: 0, y: 0, width: 4, height: 4, pixelRatio: 1, sdf: true } })
  );

  execFileSync("node", ["workers/assets/shields.mjs", `--sprite=${base}`], { stdio: "pipe" });
  const poStitkoch = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  const mena = [];
  for (const shape of SHIELD_SHAPES) {
    for (const [id] of SHIELD_DEFS) {
      for (const tema of Object.keys(THEMES)) mena.push(`${shape.id}-${id}-${tema}`);
    }
  }
  for (const meno of mena) {
    const e = poStitkoch[meno];
    if (!e) {
      chyba("workers/assets/shields.mjs", `štítok "${meno}" sa do spritu nedopiekol.`);
      continue;
    }
    for (const kluc of ["stretchX", "stretchY", "content"]) {
      if (!e[kluc]) {
        chyba("workers/assets/shields.mjs",
          `štítok "${meno}" nemá v indexe \`${kluc}\` – bez rozťahovacích ` +
          `pásem sa obrázok škáluje celý aj s rohmi a z dlhého čísla je kapsula.`);
      }
    }
    if (e.sdf) {
      chyba("workers/assets/shields.mjs",
        `štítok "${meno}" je označený ako \`sdf\` – naťahovanie vtedy rozladí ` +
        `vzdialenostné pole a v mape je zo štítka rozmazaný kríž. Obrázok je ` +
        `farebný, SDF tam nepatrí.`);
    }
  }

  // a to isté po preskladaní, ktoré robí dopekanie vzorov
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
  const poVzoroch = JSON.parse(readFileSync(`${base}.json`, "utf8"));
  for (const meno of mena) {
    const pred = poStitkoch[meno] || {};
    const po = poVzoroch[meno] || {};
    for (const kluc of ["stretchX", "stretchY", "content", "sdf"]) {
      if (JSON.stringify(pred[kluc]) !== JSON.stringify(po[kluc])) {
        chyba("workers/styles/patterns.mjs",
          `preskladanie spritu stratilo \`${kluc}\` štítka "${meno}" ` +
          `(${JSON.stringify(pred[kluc])} → ${JSON.stringify(po[kluc])}). ` +
          `Sprite aj štýl ostanú platné, len bude štítok pokrivený.`);
      }
    }
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

// 3. štítok je nad menom ulice
let skusok = 0;
for (const theme of Object.keys(THEMES)) {
  for (const mapType of MAP_TYPE_IDS) {
    const style = buildStyle({
      theme,
      mapType,
      tilesUrl: "pmtiles://x/t.pmtiles",
      spriteUrl: "https://x/sprite",
      glyphsUrl: "https://x/{fontstack}/{range}.pbf",
      // mená sú tvar × trieda × téma – štítok je pečený obrázok, nie SDF
      icons: SHIELD_SHAPE_IDS.flatMap((tvar) =>
        SHIELD_DEFS.flatMap(([id]) => Object.keys(THEMES).map((t) => `${tvar}-${id}-${t}`)))
    });
    const poradie = new Map(style.layers.map((l, i) => [l.id, i]));
    const meno = poradie.get("road-name");
    for (const [id] of SHIELD_DEFS) {
      const stitok = poradie.get(`road-shield-${id}`);
      skusok += 1;
      if (stitok == null) {
        chyba("poc/web/themes.js", `vrstva \`road-shield-${id}\` v štýle (${theme} × ${mapType}) nie je.`);
      } else if (meno != null && stitok > meno) {
        chyba("poc/web/themes.js",
          `\`road-shield-${id}\` je v štýle (${theme} × ${mapType}) AŽ ZA \`road-name\`. ` +
          `MapLibre umiestňuje popisky v poradí vrstiev, takže by na hustej sieti ` +
          `vyhrávalo meno ulice a číslo cesty by mizlo.`);
      }
    }
    // štítok musí obrázok použiť, keď v sprite je
    for (const [id] of SHIELD_DEFS) {
      const l = style.layers.find((x) => x.id === `road-shield-${id}`);
      if (l && !(l.layout || {})["icon-image"]) {
        chyba("poc/web/themes.js",
          `\`road-shield-${id}\` nekreslí podklad ani vtedy, keď je štítok v sprite.`);
      }
    }
  }
}

// 4. tvar prepnutý v developer móde má svoj obrázok
// V prehliadači sa mení len meno obrázka, sprite sa neprebuildováva – v sprite
// musí byť každý tvar pre každú triedu aj tému.
const upecene = new Set(
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
      icons: [...upecene],
      overrides: {
        shields: Object.fromEntries(SHIELD_DEFS.map(([id]) => [id, { shape: shape.id }]))
      }
    });
    for (const [id] of SHIELD_DEFS) {
      const l = style.layers.find((x) => x.id === `road-shield-${id}`);
      const meno = (l?.layout || {})["icon-image"];
      if (!meno) {
        chyba(
          "poc/web/themes.js",
          `štítok "${id}" po prepnutí tvaru na "${shape.id}" (${theme}) stratil podklad – ` +
            `developer mode ponúka tvar, ktorý sa do spritu nepečie.`
        );
      } else if (!upecene.has(meno)) {
        chyba(
          "workers/assets/shields.mjs",
          `štítok "${id}" si po prepnutí tvaru pýta obrázok "${meno}", ktorý sa nepečie.`
        );
      }
    }
  }
}

console.log(
  `štítky ciest: ${bad} chýb (${SHIELD_DEFS.length} tried, ${SHIELD_SHAPES.length} tvarov, ` +
    `${skusok} kontrol poradia)`
);
process.exit(bad ? 1 : 0);
