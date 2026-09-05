#!/usr/bin/env node
/**
 * Prevezme úpravy štýlu z developer módu a uloží ich do
 * `poc/web/style-overrides.json`, odkiaľ ich použije web aj generátor
 * statických štýlov pre iOS.
 *
 * Vstup je JSON zo súboru, stdin alebo z inputu workflowu. Pred zápisom ho
 * prečistí tá istá `normalizeOverrides`, akú používa prehliadač, takže sa do
 * repa nedostane neznáma farba ani vlastnosť, ktorú štýl nevie prepísať.
 *
 *   node workers/styles/overrides.mjs --file=overrides.json [--check]
 *   node workers/styles/overrides.mjs --stdin < overrides.json
 *   node workers/styles/overrides.mjs --reset
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  normalizeOverrides,
  emptyOverrides,
  hasOverrides,
  THEMES,
  PALETTE_LABELS,
  DEFAULT_ICON_SOURCE,
  TRAIL_GAP_DEFAULTS,
  TRAIL_GAP_ZOOM,
  TRAIL_MARK_DEFAULTS,
  TRAIL_MARK_ZOOM,
  isRelative,
  mapTypeDef
} from "../../poc/web/themes.js";

// `import.meta.url` je `workers/styles`, takže koreň repozitára je o DVE
// úrovne vyššie. Kým bol tento súbor priamo vo `workers/`, stačila jedna –
// a po presune z toho bolo `workers/poc/web/…` (viď beh 31413580102).
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const TARGET = join(root, "poc", "web", "style-overrides.json");

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  })
);

function readInput() {
  if (args.reset) return emptyOverrides();
  if (args.file) return JSON.parse(readFileSync(args.file, "utf8"));
  if (args.stdin) return JSON.parse(readFileSync(0, "utf8"));
  console.error(
    "Chýba vstup: --file=<json>, --stdin alebo --reset (pozri hlavičku súboru)"
  );
  process.exit(2);
}

let raw;
try {
  raw = readInput();
} catch (err) {
  console.error(`::error::Vstup sa nepodarilo prečítať ako JSON: ${err.message}`);
  process.exit(1);
}

const { overrides, problems } = normalizeOverrides(raw);

for (const p of problems) console.log(`::warning::${p}`);

// ---------- prehľad, čo sa vlastne mení ----------
const summary = [];
if (overrides.hillshade) summary.push("  tieňovanie reliéfu: zapnuté");
if (overrides.icons && overrides.icons !== DEFAULT_ICON_SOURCE) {
  summary.push(`  sada ikoniek: ${overrides.icons}`);
}
for (const [theme, colors] of Object.entries(overrides.palette)) {
  const names = Object.keys(colors)
    .map((k) => PALETTE_LABELS[k] || k)
    .join(", ");
  summary.push(`  téma ${THEMES[theme].label}: ${Object.keys(colors).length} farieb (${names})`);
}
// PORADIE KRESLENIA. Nie je to úprava vrstvy (tá o svojich susedoch nevie),
// ale zoznam presunov – v súhrne preto vlastný riadok, nech je vidieť, že sa
// mapa nemení len farbou, ale aj tým, čo je nad čím.
if (overrides.order.length) {
  summary.push(
    `  poradie kreslenia: ` +
      overrides.order
        .map((m) => `${m.id} → ${m.before ? `pod ${m.before}` : "navrch"}`)
        .join(", ")
  );
}
const hidden = Object.entries(overrides.layers).filter(([, o]) => o.visible === false);
const recolored = Object.entries(overrides.layers).filter(([, o]) => o.paint);
// TMAVÝ VARIANT (rozpis pri `applyLayerOverrides` v themes.js). Vlastný
// riadok, hoci sedí v tých istých vrstvách ako `recolored`: bez neho by beh
// ukázal len počet prefarbených vrstiev a nebolo by vidieť, ktoré z nich majú
// pre tému „tmava" inú farbu než zvyšné tri.
const darkened = Object.entries(overrides.layers).filter(
  ([, o]) => (o.paintDark && Object.keys(o.paintDark).length) || o.outline?.colorDark
);
const rezoomed = Object.entries(overrides.layers).filter(
  ([, o]) => o.minzoom != null || o.maxzoom != null
);
const patterned = Object.entries(overrides.layers).filter(([, o]) => o.pattern);
const outlined = Object.entries(overrides.layers).filter(([, o]) => o.outline);
// RELATÍVNE ÚPRAVY („nechaj krivku zo štýlu, len ju preškáluj"). V súhrne majú
// vlastný riadok, hoci sedia v `paint` ako farby: sú to jediné úpravy, ktoré
// menia hodnotu podľa toho, čo v štýle práve JE – takže „prefarbené vrstvy: 3"
// by o nich nepovedalo to podstatné, totiž o koľko.
const relPopis = (v) =>
  [v.scale != null ? `${v.scale}×` : null, v.add != null ? `${v.add > 0 ? "+" : ""}${v.add}` : null]
    .filter(Boolean).join(" a ");
const skalovane = Object.entries(overrides.layers).flatMap(([id, o]) => [
  ...Object.entries(o.paint || {}).filter(([, v]) => isRelative(v))
    .map(([prop, v]) => `${id} ${prop} ${relPopis(v)}`),
  ...Object.entries(o.layout || {}).filter(([, v]) => isRelative(v))
    .map(([prop, v]) => `${id} ${prop} ${relPopis(v)}`),
  ...(isRelative(o.outline?.width) ? [`${id} okraj ${relPopis(o.outline.width)}`] : [])
]);
// ROZLÍŠENIE PODĽA ATRIBÚTU OSM. Nie je to prefarbenie ani okraj – je to
// VRSTVA NAVYŠE a k nej zúžený filter predlohy, teda zmena v tom, čo sa vôbec
// kreslí. V súhrne preto musí byť vidieť aj to, čím sa delí.
const rozlisene = Object.entries(overrides.layers).flatMap(([id, o]) =>
  (o.variants || []).map((v) => `${id}: ${v.attr} = ${v.values.join(", ")}`));
const dashed = Object.entries(overrides.layers).filter(([, o]) => o.dash);
const reiconed = Object.entries(overrides.layers).filter(([, o]) => o.icon);
if (hidden.length) summary.push(`  skryté vrstvy: ${hidden.map(([id]) => id).join(", ")}`);
if (recolored.length) summary.push(`  prefarbené vrstvy: ${recolored.length}`);
if (darkened.length) {
  summary.push(`  z toho s vlastnou farbou pre tmavú tému: ${darkened.map(([id]) => id).join(", ")}`);
}
if (rezoomed.length) summary.push(`  zmenený rozsah zoomu: ${rezoomed.length}`);
if (patterned.length) {
  summary.push(
    // Vzor môže byť KRESLENÝ (`id`) alebo VLASTNÝ OBRÁZOK (`image`) – bez
    // toho druhého by v súhrne stálo „→ undefined" práve pri tom, čo build
    // musí dopiecť do spritu.
    `  vzory: ${patterned
      .map(([id, o]) => `${id} → ${o.pattern.image || o.pattern.id}`)
      .join(", ")}`
  );
}
if (outlined.length) summary.push(`  okraje: ${outlined.map(([id]) => id).join(", ")}`);
if (skalovane.length) summary.push(`  preškálované podľa štýlu: ${skalovane.join(", ")}`);
if (rozlisene.length) summary.push(`  rozlíšenie podľa OSM: ${rozlisene.join(" · ")}`);
if (dashed.length) {
  summary.push(`  prerušenie čiar: ${dashed.map(([id, o]) => `${id} → ${o.dash}`).join(", ")}`);
}
if (reiconed.length) {
  summary.push(`  ikony: ${reiconed.map(([id, o]) => `${id} → ${o.icon}`).join(", ")}`);
}
if (overrides.poi.hidden.length) {
  summary.push(`  skryté POI triedy: ${overrides.poi.hidden.join(", ")}`);
}
// Ikony kategórií. Sú v `poi` vedľa skrytých tried, ale je to iná otázka –
// a keby v súhrne chýbali, nebolo by z behu vidieť, že sa mapa kreslí inými
// značkami (vrátane vlastných obrázkov, ktoré sa musia dopiecť do spritu).
const poiIcons = Object.entries(overrides.poi.icons || {});
if (poiIcons.length) {
  summary.push(
    `  ikony POI kategórií: ` +
      poiIcons.map(([cls, name]) => `${cls} → ${name || "žiadna"}`).join(", ")
  );
}

// Značené trasy. Nie sú to úpravy jednej vrstvy (jeden druh trasy má v štýle
// tri), tak majú v súhrne vlastný riadok – inak by z neho zmizli.
const gaps = Object.entries(overrides.trails?.gap || {});
if (gaps.length) {
  summary.push(
    `  odstup trás od cesty (px pri z${TRAIL_GAP_ZOOM}): ` +
      gaps.map(([k, v]) => `${k} ${v} (pôvodne ${TRAIL_GAP_DEFAULTS[k]})`).join(", ")
  );
}
for (const [id, def] of Object.entries(overrides.trails?.types || {})) {
  const parts = [];
  if (def.dash) parts.push(`čiara ${def.dash}`);
  if (def.icon != null) parts.push(`ikona ${def.icon || "žiadna"}`);
  if (def.mark != null) parts.push(`značka ${def.mark || "žiadna"}`);
  summary.push(`  trasa ${id}: ${parts.join(" · ")}`);
}
const marks = Object.entries(overrides.trails?.marks || {});
if (marks.length) {
  summary.push(
    `  značky trás (pri z${TRAIL_MARK_ZOOM}): ` +
      marks.map(([k, v]) => `${k} ${v} (pôvodne ${TRAIL_MARK_DEFAULTS[k]})`).join(", ")
  );
}
for (const [id, def] of Object.entries(overrides.shields || {})) {
  summary.push(`  štítok ${id}: tvar ${def.shape}`);
}

// Vlastné sady ikoniek a vlastné ikony. Sady sťahuje `workers/assets/icons.sh`
// spolu s tými z repozitára, ikony sa dopekajú do každého spritu
// (`workers/assets/custom-icons.mjs`) – oboje teda ovplyvní BUILD, nie len
// prehliadač, a v súhrne to má byť vidieť.
if (overrides.iconSets?.length) {
  summary.push(
    `  vlastné sady ikoniek: ` +
      overrides.iconSets.map((s2) => `${s2.id} (${s2.sprite})`).join(", ")
  );
}
if (overrides.customIcons?.length) {
  const kB = Math.round(
    overrides.customIcons.reduce((n, i) => n + i.png.length, 0) / 1024
  );
  summary.push(
    `  vlastné ikony (${kB} kB): ` +
      overrides.customIcons.map((i) => i.name).join(", ")
  );
}

// Vlastnosti z `layout` (veľkosť ikony, rozostup po čiare, veľkosť písma)
// sú v `layers` ako všetko ostatné, ale v súhrne by inak zmizli medzi
// „prefarbenými vrstvami" – a pritom sa nimi ladia práve značky trás.
const rozlozene = Object.entries(overrides.layers).filter(([, o]) => o.layout);
if (rozlozene.length) {
  summary.push(
    `  veľkosti a rozostupy: ` +
      rozlozene
        .map(([id, o]) => `${id} (${Object.keys(o.layout).join(", ")})`)
        .join(", ")
  );
}

// Úpravy, ktoré platia len pre jeden typ mapy. Všetko vyššie je spoločné –
// tu je vidieť, čo si ktorá mapa robí po svojom.
for (const [typeId, m] of Object.entries(overrides.maps)) {
  const parts = [];
  const own = Object.entries(m.layers || {});
  const off = own.filter(([, o]) => o.visible === false).map(([id]) => id);
  const on = own.filter(([, o]) => o.visible === true).map(([id]) => id);
  const zoomed = own.filter(([, o]) => o.minzoom != null || o.maxzoom != null);
  const styled = own.filter(([, o]) => o.paint || o.dash || o.pattern || o.outline || o.icon);
  const darkenedOwn = own.filter(
    ([, o]) => (o.paintDark && Object.keys(o.paintDark).length) || o.outline?.colorDark
  );
  if (off.length) parts.push(`skryté: ${off.join(", ")}`);
  if (on.length) parts.push(`zapnuté navyše: ${on.join(", ")}`);
  if (zoomed.length) parts.push(`zoom: ${zoomed.length}`);
  if (styled.length) parts.push(`štýl: ${styled.length}`);
  if (darkenedOwn.length) {
    parts.push(`z toho pre tmavú tému: ${darkenedOwn.map(([id]) => id).join(", ")}`);
  }
  if (m.poi?.hidden?.length) parts.push(`skryté POI: ${m.poi.hidden.join(", ")}`);
  if (parts.length) {
    summary.push(`  mapa ${mapTypeDef(typeId).label}: ${parts.join(" · ")}`);
  }
}

console.log(
  hasOverrides(overrides)
    ? `Úpravy štýlu:\n${summary.join("\n")}`
    : "Žiadne úpravy – štýl zostane pôvodný."
);

if (args.check) {
  console.log("Kontrola prebehla, súbor sa nezapisuje (--check).");
  process.exit(0);
}

const payload = {
  version: 2,
  updated_at: new Date().toISOString(),
  icons: overrides.icons,
  hillshade: overrides.hillshade,
  palette: overrides.palette,
  layers: overrides.layers,
  order: overrides.order,
  poi: overrides.poi,
  // ZNAČENÉ TRASY A ŠTÍTKY CIEST. Kým tu neboli, developer mode ich vedel
  // nastaviť aj uložiť, ale do repozitára z nich nedošlo NIČ – `payload` ich
  // proste nevypisoval a `normalizeOverrides` pri ďalšom načítaní nemal čo
  // čítať. Nespadlo pri tom nič: súbor bol platný, len v ňom odstup pásikov,
  // vzor čiary, ikona ani značka nikdy neboli. Stráži to
  // `workers/lint/overrides.mjs`.
  trails: overrides.trails,
  shields: overrides.shields,
  iconSets: overrides.iconSets,
  customIcons: overrides.customIcons,
  // Úpravy pre jednotlivé typy máp (turistická, lyžiarska, cestná, …).
  maps: overrides.maps
};
writeFileSync(TARGET, `${JSON.stringify(payload, null, 2)}\n`);
console.log(`✓ zapísané do ${TARGET}`);
