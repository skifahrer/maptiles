/**
 * Štítok čísla cesty – „D1", „R1", „I/18".
 *
 * Číslo je na mape iná vec než meno cesty: meno beží pozdĺž nej a číta sa ako
 * text, číslo je značka – krátka, opakuje sa a musí byť čitateľná aj cez les
 * a vrstevnice. Preto má podklad.
 *
 * Tu je len obrázok podkladu; ktorá cesta ho dostane a akú farbu, rozhoduje
 * `SHIELD_DEFS` v `themes.js`. Rozdelené preto, že tento súbor potrebuje
 * pipeline a nemá čo vedieť o triedach OSM.
 *
 * SDF, nie hotový farebný obrázok: SDF sa dá zafarbiť aj orámovať, takže na
 * štyri témy × štyri triedy stačí jeden obrázok namiesto šestnástich a farba
 * sa dá ladiť v developer móde bez prebuildovania spritu.
 *
 * Nerozťahuje sa (žiadne `stretchX`/`stretchY`), a je to opravená chyba:
 * SDF nesie vzdialenosť v pixeloch, takže natiahnutím pásma sa pole rozladí
 * voči novej geometrii a na švíkoch hodnoty nenadviažu – v mape z toho bol
 * rozmazaný kríž namiesto štítka (89 × 85 px proti ~20 × 14 px bez nich).
 * Deväťdielne naťahovanie je robené na bežný raster, nie na vzdialenostné pole.
 *
 * Cena: `icon-text-fit` škáluje obrázok celý, takže sa s dĺžkou čísla škáluje
 * aj polomer zaoblenia – z „III/3059" je kapsula. Pravý obdĺžnik pri každej
 * dĺžke by chcel obrázok bez SDF a s farbou zapečenou pri builde, čím sa
 * farba prestane dať ladiť v developer móde.
 */

/**
 * Miesto okolo štítka pre halo (= jeho orámovanie), v pixeloch pri
 * `pixelRatio` 1. Musí byť väčšie než najväčší rozumný `icon-halo-width`,
 * inak sa rámik oreže o okraj obrázka.
 */
export const SHIELD_PAD = 1;

/**
 * Hrúbka jedného prstenca v pixeloch pri `pixelRatio` 1. Prstence sú dva
 * a rovnako hrubé, ako to má úradná značka D1/R1.
 *
 * Pásma vznikajú odsadením vonkajšieho tvaru dovnútra a polomer sa pri tom
 * zmenšuje o to isté, takže vnútro má `shape.radius - 2 * SHIELD_RING`. Keď
 * to vyjde nula alebo menej, má vnútorné pole ostré rohy pri zaoblenom
 * vonkajšku – stráži to `workers/lint/shields.mjs`.
 */
export const SHIELD_RING = 1.5;

/** Vnútorné pole s číslom (štvorec). Prstence sa pridávajú okolo neho. */
export const SHIELD_BOX = 18;

/** Dosah vzdialenostného poľa – rovnaká konvencia ako `workers/assets/sprite.mjs`. */
const SDF_RADIUS = 8;
const SDF_CUTOFF = 0.25;

/**
 * Tvary štítka. `radius` je polomer zaoblenia rohov pri `pixelRatio` 1;
 * `SHIELD_BOX / 2` je už úplný ovál.
 */
// polomer je odmeraný z úradnej značky D1/R1 (8 % výšky poľa), nie odhadnutý:
// dovtedy tu bolo 22 % a štítok pôsobil ako pilulka. Pri dlhom čísle to bolo
// horšie – `icon-text-fit` škáluje v oboch osiach, takže z „III/3059" bola
// kapsula. 8 % z 18 px = 1,44; 1,5 je najbližšie, čo má na mriežke zmysel.
export const SHIELD_SHAPES = [
  // 4,5 nie je od oka: `4,5 − 2 × 1,5 = 1,5`, takže zaoblené je aj vnútorné
  // pole (prostredný prstenec má 3). Menší vonkajší polomer by vnútro
  // zahrotil – viď rozpis pri `SHIELD_RING`.
  { id: "shield", label: "Štítok – zaoblený obdĺžnik (ako značka D1/R1)", radius: 4.5 },
  { id: "shield-round", label: "Štítok – oválny", radius: 8 }
];

export const SHIELD_SHAPE_IDS = SHIELD_SHAPES.map((s) => s.id);
export const DEFAULT_SHIELD_SHAPE = "shield";

/** Tvar podľa id; pri neznámom id vráti predvolený. */
export function shieldShape(id) {
  return SHIELD_SHAPES.find((s) => s.id === id) || SHIELD_SHAPES[0];
}

/**
 * Vzdialenosť bodu od zaobleného obdĺžnika (záporná vnútri).
 * Klasický vzorec cez „vzdialenosť od zmenšeného obdĺžnika mínus polomer".
 */
function roundedRectDistance(px, py, w, h, r) {
  const dx = Math.abs(px - w / 2) - (w / 2 - r);
  const dy = Math.abs(py - h / 2) - (h / 2 - r);
  const vx = Math.max(dx, 0);
  const vy = Math.max(dy, 0);
  return Math.sqrt(vx * vx + vy * vy) + Math.min(Math.max(dx, dy), 0) - r;
}

/**
 * Vykreslí štítok ako SDF obrázok pre sprite.
 *
 * @param {object} shape        položka zo `SHIELD_SHAPES`
 * @param {number} pixelRatio   1 alebo 2 (varianta @2x)
 * @returns {{width:number, height:number, data:Uint8Array,
 *            stretchX:number[][], stretchY:number[][], content:number[]}}
 *          `data` je RGBA (biela, SDF v alfe).
 */
/** `#rrggbb` → `[r, g, b]`. */
function rozlozFarbu(hex) {
  const h = String(hex || "#000000").replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  return [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) || 0);
}

/**
 * Vykreslí štítok ako hotový farebný obrázok (nie SDF) s tromi pásmami:
 * vonkajší prstenec vo farbe poľa, vnútorný kontrastný a pole s číslom.
 * Oba prstence sú rovnako hrubé (`SHIELD_RING`).
 *
 * Nie SDF: to vie zafarbiť tvar a dať mu jeden prstenec, dva sa ním spraviť
 * nedajú. A deväťdielne naťahovanie je robené na bežný raster – na
 * vzdialenostnom poli rozladí hodnoty a pretrhne obrys. Hotový obrázok rieši
 * oboje, takže je štítok obdĺžnik pri každej dĺžke čísla.
 *
 * Cena: farba sa pečie pri builde, takže sa pečie jeden obrázok na každú
 * dvojicu trieda × téma a v developer móde sa zmení až po prebuildovaní.
 *
 * @param {object} shape   položka zo `SHIELD_SHAPES` (polomer zaoblenia)
 * @param {object} colors  `{ field, ring }`
 * @param {number} pixelRatio
 */
export function renderShield(shape, colors, pixelRatio = 1) {
  const r = pixelRatio;
  const pad = SHIELD_PAD * r;
  const ring = SHIELD_RING * r;
  const box = SHIELD_BOX * r;
  // Pole + dva prstence na každej strane + pixel priehľadného okraja, aby
  // sa hrana pri škálovaní nemala o čo oprieť a nezačala sa opakovať.
  const size = box + 4 * ring + 2 * pad;
  const outer = size - 2 * pad;
  const radius = Math.min(shape.radius * r, outer / 2);

  const pole = rozlozFarbu(colors.field);
  const prstenec = rozlozFarbu(colors.ring);
  const data = new Uint8Array(size * size * 4);

  // Krytie pásma: 1 vnútri, 0 vonku, na hrane plynulo cez jeden pixel.
  const kryt = (dist, hranica) => Math.max(0, Math.min(1, 0.5 - (dist - hranica)));

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      // Vzdialenosť od VONKAJŠIEHO obdĺžnika; pásma sú jeho odsadenia dovnútra.
      const d = roundedRectDistance(x + 0.5 - pad, y + 0.5 - pad, outer, outer, radius);
      const aVonku = kryt(d, 0);              // celý štítok
      const aPrstenec = kryt(d, -ring);       // od vnútra vonkajšieho prstenca
      const aPole = kryt(d, -2 * ring);       // samotné pole s číslom

      // Zhora nadol: pole prekryje prstenec, prstenec prekryje vonkajší lem.
      const rr = pole[0] * aVonku * (1 - aPrstenec) + prstenec[0] * (aPrstenec - aPole) + pole[0] * aPole;
      const gg = pole[1] * aVonku * (1 - aPrstenec) + prstenec[1] * (aPrstenec - aPole) + pole[1] * aPole;
      const bb = pole[2] * aVonku * (1 - aPrstenec) + prstenec[2] * (aPrstenec - aPole) + pole[2] * aPole;

      const i = (y * size + x) * 4;
      data[i] = Math.round(Math.min(255, rr / Math.max(aVonku, 1e-6)));
      data[i + 1] = Math.round(Math.min(255, gg / Math.max(aVonku, 1e-6)));
      data[i + 2] = Math.round(Math.min(255, bb / Math.max(aVonku, 1e-6)));
      data[i + 3] = Math.round(255 * aVonku);
    }
  }

  // Naťahuje sa len ROVNÁ časť hrán – rohy nie. Na bežnom rastri to funguje
  // presne tak, ako má (na SDF nie, viď hlavičku súboru), takže štítok ostane
  // obdĺžnik aj pri dlhom čísle namiesto toho, aby sa z neho stala kapsula.
  const od = pad + radius;
  const doX = Math.max(od + 1, size - pad - radius);
  return {
    width: size,
    height: size,
    data,
    stretchX: [[od, doX]],
    stretchY: [[od, doX]],
    // Kam sa vojde text: vnútro poľa, teda za oba prstence.
    content: [pad + 2 * ring, pad + 2 * ring, size - pad - 2 * ring, size - pad - 2 * ring]
  };
}
