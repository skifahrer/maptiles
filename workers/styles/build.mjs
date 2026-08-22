#!/usr/bin/env node
/**
 * Vygeneruje statické MapLibre style.json súbory pre všetky kombinácie
 * **typ mapy × farebná téma**. Tie isté štýly použije web aj iOS aplikácia
 * (MapLibre Native vie načítať style.json priamo z URL GitHub Pages).
 *
 * Súbory sú `<región>-<typ mapy>-<téma>.json`; navyše sa predvolený typ mapy
 * zapíše aj pod starým menom `<región>-<téma>.json`, aby fungovali odkazy,
 * ktoré typ mapy nepoznajú.
 *
 * Štýl sa naviaže na reálne dostupné assety:
 *   --sprite     … sprite index (JSON) – z neho sa vezme zoznam ikon, takže
 *                  nikdy neodkazujeme na ikonu, ktorá v sprite nie je;
 *                  ak je sprite SDF, štýl navyše nastaví farby ikon
 *   --fonts-dir  … adresár s glyfmi na Pages – z neho sa vyberú fontstacky
 *   --overrides  … úpravy z developer módu (poc/web/style-overrides.json)
 *   --trails     … značené trasy z OSM relácií (vlastný .pmtiles)
 *   --roads      … obmedzenia na ceste (výška podjazdov a tunelov, šírka,
 *                  hmotnosť, maximálna rýchlosť), ktoré vrstva
 *                  `transportation` OpenMapTiles nenesie vôbec
 *   --features   … krajinné prvky, ktoré schéma OpenMapTiles nemá –
 *                  násypy, múry, vedenia, pramene, zjazdovky (vlastný .pmtiles)
 *   --dem-source … model, z ktorého sú vrstevnice a skaly – ide do atribúcie
 *   --dem-tiles-source … model, z ktorého sú výškové dlaždice (tieňovanie
 *                  a 3D terén). Vo formulári je to vlastný výber, takže to
 *                  nemusí byť ten istý; prázdne = ten istý ako --dem-source
 *   --sprites-dir… adresár s nasadenými spritmi; sada sa vyberie podľa úprav
 *   --region-outline hranica stiahnutého regiónu (`_site/region.geojson`
 *                  z `workers/deploy/region-mask.py`) – za ňou štýl nekreslí
 *                  nič. Vkladá sa PRIAMO DO ŠTÝLU, nie ako URL (prečo, hovorí
 *                  komentár pri načítaní).
 *
 * Použitie:
 *   node workers/styles/build.mjs --base-url=https://user.github.io/fricomaps \
 *        --region=slovensko --maxzoom=16 --out=_site/styles \
 *        --sprite=_site/sprites/osm-liberty.json --fonts-dir=_site/fonts \
 *        --overrides=poc/web/style-overrides.json
 */
import { mkdirSync, writeFileSync, readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  THEMES,
  buildStyle,
  normalizeOverrides,
  hasOverrides,
  paletteCoverage,
  selectedIconSource,
  MAX_TILE_Z,
  DEFAULT_DEM_TILES,
  DEFAULT_DEM_MAXZOOM,
  DEFAULT_TERRAIN_EXAGGERATION,
  DEFAULT_DEM_SOURCE,
  DEM_SOURCES,
  MAP_TYPES,
  DEFAULT_MAP_TYPE
} from "../../poc/web/themes.js";
import { allIconSources } from "../../poc/web/icon-sources.js";

// Vlastný priečinok je `workers/styles`. Číselníky sú v susednom
// `workers/data/`, koreň repozitára o dve úrovne vyššie – kým bol tento
// súbor priamo vo `workers/`, bola to jedna úroveň a po presune z toho
// vyšlo `workers/styles/regions.json` (beh 31413580102).
const SELF = dirname(fileURLToPath(import.meta.url));

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=")];
  })
);

const baseUrl = (args["base-url"] || "").replace(/\/$/, "");
const region = args.region || "slovensko";
const outDir = args.out || "_site/styles";
const maxzoom = Number(args.maxzoom || MAX_TILE_Z);
// Vrstevnice sú voliteľné – štýl ich zapne, len ak pipeline vyrobila .pmtiles.
const contoursMaxzoom = Number(args["contours-maxzoom"] || 14);
const hasContours = args.contours === "true" || args.contours === "1";
// Skaly majú vlastný .pmtiles a vlastný maxzoom – viď workers/contours-rocks/rocks.yml.
const rocksMaxzoom = Number(args["rocks-maxzoom"] || 16);
const hasRocks = args.rocks === "true" || args.rocks === "1";
// Značené trasy – rovnako voliteľné a v samostatnom .pmtiles.
const trailsMaxzoom = Number(args["trails-maxzoom"] || 14);
const hasTrails = args.trails === "true" || args.trails === "1";
// Krajinné prvky – to isté: vlastný .pmtiles, vlastný maxzoom, voliteľné.
const featuresMaxzoom = Number(args["features-maxzoom"] || 15);
const hasFeatures = args.features === "true" || args.features === "1";
// Obmedzenia na ceste (výška podjazdov, šírka, hmotnosť, maximálna rýchlosť)
// – opäť vlastný .pmtiles, vlastný maxzoom a voliteľné.
const roadsMaxzoom = Number(args["roads-maxzoom"] || 15);
const hasRoads = args.roads === "true" || args.roads === "1";
// Zdroj výšok ovplyvňuje atribúciu vrstevníc a skál v štýle.
const demSource = DEM_SOURCES[args["dem-source"]]
  ? args["dem-source"]
  : DEFAULT_DEM_SOURCE;
// Tieňovanie má vo formulári vlastný výber modelu, takže výškové dlaždice
// môžu byť z iného než vrstevnice – atribúcia sa preto berie zvlášť.
const demTilesSource = DEM_SOURCES[args["dem-tiles-source"]]
  ? args["dem-tiles-source"]
  : demSource;
// Tieňovanie reliéfu sa dá vypnúť (--dem-tiles=none). Ak pipeline vyrobila
// vlastné výškové dlaždice, príde sem ich URL šablóna a max zoom.
const demTiles =
  args["dem-tiles"] === "none" ? null : args["dem-tiles"] || DEFAULT_DEM_TILES;
const demMaxzoom = Number(args["dem-maxzoom"] || DEFAULT_DEM_MAXZOOM);
// 3D TERÉN. Zapína sa vtedy, keď máme VLASTNÉ výškové dlaždice – tie sú z
// modelu vybraného v `shading_source` (predvolene DMR 5.0, mriežka 5 m, čo
// dá dlaždice do z15). Na verejné AWS Terrain Tiles sa 3D nezapína: sú
// globálne a hrubé, takže by z hôr spravili mydlové kopce.
//
// Doteraz si 3D zapínal len web za behu (`map.setTerrain` v poc/web/app.js) –
// všetko ostatné, čo tento štýl číta (iOS cez MapLibre Native), dostávalo
// plochú mapu, hoci dlaždice v štýle boli. `--terrain-3d=0` to vypne.
const ownDemTiles = Boolean(demTiles) && demTiles !== DEFAULT_DEM_TILES;
const terrain3dArg = String(args["terrain-3d"] ?? "auto").toLowerCase();
const terrain3d = ["0", "false", "nie", "ziadne", "vypnute"].includes(terrain3dArg)
  ? false
  // `auto` aj `1`/`true` znamenajú „zapni, ak máme z čoho"; bez vlastných
  // dlaždíc sa 3D nezapne ani na výslovnú žiadosť.
  : ownDemTiles;
const terrainExaggeration = Number(
  args["terrain-exaggeration"] || DEFAULT_TERRAIN_EXAGGERATION
);
// Kde vlastné výškové dlaždice vôbec sú. Rýchly test (switch `test`) ich
// počíta len na štvorci s pár km², kým mapa je celý kraj – bez tejto hranice
// by klient pýtal tieňovanie po celom kraji a dostával 404.
const demBounds = args["dem-bounds"]
  ? args["dem-bounds"].split(",").map(Number)
  : null;
if (demBounds && (demBounds.length !== 4 || demBounds.some((n) => !Number.isFinite(n)))) {
  console.error("--dem-bounds musí byť W,S,E,N (štyri čísla)");
  process.exit(1);
}

// HRANICA STIAHNUTÉHO REGIÓNU – A PREČO SA VKLADÁ DO ŠTÝLU, NIE AKO URL.
// Tento štýl číta aj aplikácia, ktorá si mapu STIAHNE a otvorí ju offline;
// všetko ostatné (dlaždice, sprite, glyfy) si pri tom musí prepísať z adresy
// Pages na svoje súbory. Odkaz na `region.geojson`, na ktorý by sa v tom
// prepise zabudlo, by sa neprejavil pádom – len by sa maska nenačítala a mapa
// by zase siahala za región, čiže presne tá tichá chyba, ktorú to má riešiť.
// Dáta majú jednotky kB (Prešovský kraj 8,9 kB), takže sa zaplatí radšej
// kópia v každom štýle.
//
// Do štýla ide najprv ZÁSTUPNÝ REŤAZEC a hotový JSON sa za neho vymení až
// nakoniec. `JSON.stringify(…, null, 2)` totiž rozsype každú súradnicu na
// vlastný riadok: z 8,9 kB dát je 54 kB a v 25 súboroch štýlov 1,3 MB navyše –
// všetko len odsadenie, ktoré v mape nikto nevidí. Vymieňa sa presný reťazec
// aj s úvodzovkami, takže sa netrafí nič iné.
const OUTLINE_TOKEN = "__frico:region-outline__";
const regionOutlinePath = args["region-outline"] || "";
let regionOutline = null;
if (regionOutlinePath) {
  if (existsSync(regionOutlinePath)) {
    regionOutline = JSON.parse(readFileSync(regionOutlinePath, "utf8"));
    const kb = (statSync(regionOutlinePath).size / 1024).toFixed(1);
    console.log(`Hranica regiónu: ${regionOutlinePath} (${kb} kB, priamo v štýle)`);
  } else {
    console.warn(
      `⚠ Hranica regiónu (${regionOutlinePath}) nenájdená – mapa pôjde bez nej a bude siahať aj za región.`
    );
  }
}

if (!baseUrl) {
  console.error("Chýba --base-url (URL GitHub Pages stránky)");
  process.exit(1);
}

const regions = JSON.parse(
  readFileSync(join(SELF, "..", "data", "regions.json"), "utf8")
);
// Región nemusí byť v regions.json (custom región z osm.fr – Európa/svet);
// vtedy sa meno berie z --name, prípadne z kľúča regiónu.
const regionName = regions[region]?.name || args.name || region;

// ---------- sada ikoniek ----------
// Ktorú sadu použiť, hovoria úpravy z developer módu; sprite k nej hľadáme
// medzi nasadenými. Ak chýba (napr. sa nestiahla), vezme sa prvá dostupná.
const spritesDir = args["sprites-dir"] || "";
let iconSetId = null;
let spriteJsonPath = args.sprite || "";

// ---------- ikony zo spritu ----------
// Zo sprite indexu sa berie nielen zoznam ikon, ale aj to, či je sprite SDF.
// SDF sprite (workers/assets/sprite.mjs) je bez koliesok pod ikonami a dá
// sa mu nastaviť farba – štýl na to potom pridá `icon-color`.
let icons = [];
let sdfIcons = false;
function readSprite(path) {
  if (!path || !existsSync(path)) return;
  try {
    const index = JSON.parse(readFileSync(path, "utf8"));
    icons = Object.keys(index);
    sdfIcons = Object.values(index).some((e) => e && e.sdf);
    console.log(
      `Sprite: ${path} – ${icons.length} ikon${sdfIcons ? " (SDF, farbiteľné)" : ""}`
    );
  } catch (err) {
    console.warn(`⚠ Sprite ${path} sa nepodarilo prečítať: ${err.message}`);
  }
}

// ---------- úpravy z developer módu ----------
// Súbor je voliteľný; ak chýba alebo je prázdny, štýl je pôvodný.
const overridesPath =
  args.overrides || join(SELF, "..", "..", "poc", "web", "style-overrides.json");
let overrides = null;
if (existsSync(overridesPath)) {
  try {
    const { overrides: clean, problems } = normalizeOverrides(
      JSON.parse(readFileSync(overridesPath, "utf8"))
    );
    for (const p of problems) console.warn(`⚠ ${overridesPath}: ${p}`);
    overrides = hasOverrides(clean) ? clean : null;
  } catch (err) {
    console.warn(`⚠ ${overridesPath} sa nepodarilo prečítať: ${err.message}`);
  }
}
console.log(
  overrides
    ? `Úpravy štýlu z developer módu: ${Object.keys(overrides.layers).length} vrstiev, ` +
        `${Object.values(overrides.palette).reduce((n, c) => n + Object.keys(c).length, 0)} farieb` +
        `${overrides.order.length ? `, ${overrides.order.length}× zmenené poradie kreslenia` : ""}`
    : "Úpravy štýlu z developer módu: žiadne"
);

// Sadu ikoniek určujú úpravy; sprite k nej musí byť nasadený.
iconSetId = selectedIconSource(overrides);
if (spritesDir) {
  // Náhradníci: keď vybraná sada nie je nasadená (stiahnutie z cudzieho
  // servera môže zlyhať), vezme sa prvá, ktorá je. Vlastné sady z úprav sú
  // medzi nimi tiež – kto si pridal vlastnú, tú aj chce.
  const candidates = [
    iconSetId,
    ...allIconSources(overrides).map((s) => s.id).filter((id) => id !== iconSetId)
  ];
  const found = candidates.find((id) => existsSync(join(spritesDir, `${id}.json`)));
  if (!found) {
    console.warn(`⚠ V ${spritesDir} nie je žiadny sprite – štýl bude bez ikon.`);
  } else {
    if (found !== iconSetId) {
      console.warn(`⚠ Sada ikoniek "${iconSetId}" nie je nasadená – používam "${found}".`);
    }
    iconSetId = found;
    spriteJsonPath = join(spritesDir, `${iconSetId}.json`);
  }
}
console.log(`Sada ikoniek: ${iconSetId}`);
readSprite(spriteJsonPath);
if (!icons.length) {
  console.warn("⚠ Sprite index nie je k dispozícii – použije sa záložný zoznam ikon.");
}

// ---------- fontstacky ----------
// Na Pages ležia glyfy v _site/fonts/<Fontstack>/<range>.pbf. Vyberieme
// reálne existujúce adresáre; ak žiadne nie sú, spadneme na verejnú službu.
const PREFERRED = {
  regular: ["Noto Sans Regular", "Open Sans Regular", "Roboto Regular"],
  bold: ["Noto Sans Bold", "Open Sans Bold", "Roboto Medium"],
  italic: ["Noto Sans Italic", "Open Sans Italic", "Noto Sans Regular"]
};

let availableStacks = [];
if (args["fonts-dir"] && existsSync(args["fonts-dir"])) {
  availableStacks = readdirSync(args["fonts-dir"]).filter(
    (d) =>
      statSync(join(args["fonts-dir"], d)).isDirectory() &&
      existsSync(join(args["fonts-dir"], d, "0-255.pbf"))
  );
}

const fonts = {};
for (const [role, candidates] of Object.entries(PREFERRED)) {
  fonts[role] =
    candidates.find((n) => availableStacks.includes(n)) ||
    availableStacks[0] ||
    candidates[0];
}

// Sprite, na ktorý sa odkazuje výsledný štýl (bez prípony).
const spriteUrl = (
  args["sprite-url"] || `${baseUrl}/sprites/${iconSetId}`
).replace(/\.json$/, "");

const glyphsUrl =
  args["glyphs-url"] ||
  (availableStacks.length
    ? `${baseUrl}/fonts/{fontstack}/{range}.pbf`
    : "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf");

if (availableStacks.length) {
  console.log(`Glyfy: lokálne (${availableStacks.length} fontstackov) → ${glyphsUrl}`);
} else {
  console.warn(`⚠ Lokálne glyfy nenájdené – používam ${glyphsUrl}`);
}
console.log(`Fonty: regular="${fonts.regular}" bold="${fonts.bold}" italic="${fonts.italic}"`);

// Každá farba témy musí byť v niektorej skupine palety, inak by sa v
// developer móde nedala nájsť ani zmeniť.
const coverage = paletteCoverage();
if (coverage.missing.length || coverage.extra.length) {
  console.error(
    `::error::PALETTE_GROUPS nesedia s témami – chýba: [${coverage.missing}], navyše: [${coverage.extra}]`
  );
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });

for (const type of MAP_TYPES) {
  for (const themeKey of Object.keys(THEMES)) {
    const style = buildStyle({
      theme: themeKey,
      mapType: type.id,
      tilesUrl: `pmtiles://${baseUrl}/tiles/${region}.pmtiles`,
      spriteUrl: spriteUrl,
      glyphsUrl,
      icons,
      fonts,
      maxzoom,
      sdfIcons,
      iconSet: iconSetId,
      overrides,
      rocksUrl: hasRocks
        ? `pmtiles://${baseUrl}/tiles/${region}-rocks.pmtiles`
        : null,
      rocksMaxzoom,
      contoursUrl: hasContours
        ? `pmtiles://${baseUrl}/tiles/${region}-contours.pmtiles`
        : null,
      contoursMaxzoom,
      trailsUrl: hasTrails
        ? `pmtiles://${baseUrl}/tiles/${region}-trails.pmtiles`
        : null,
      trailsMaxzoom,
      featuresUrl: hasFeatures
        ? `pmtiles://${baseUrl}/tiles/${region}-features.pmtiles`
        : null,
      featuresMaxzoom,
      roadsUrl: hasRoads
        ? `pmtiles://${baseUrl}/tiles/${region}-roads.pmtiles`
        : null,
      roadsMaxzoom,
      demSource,
      demTiles,
      demTilesSource,
      demMaxzoom,
      demBounds,
      regionOutline: regionOutline ? OUTLINE_TOKEN : null,
      terrain3d,
      terrainExaggeration,
      name: `FricoMaps ${regionName} – ${type.label} (${THEMES[themeKey].label})`
    });
    const json = JSON.stringify(style, null, 2).replace(
      JSON.stringify(OUTLINE_TOKEN),
      () => JSON.stringify(regionOutline)
    );
    const drawn = style.layers.filter(
      (l) => (l.layout || {}).visibility !== "none"
    ).length;

    writeFileSync(join(outDir, `${region}-${type.id}-${themeKey}.json`), json);
    // Staré meno bez typu mapy ostáva – odkazuje naň iOS aplikácia aj smoke
    // test po nasadení, a nie je dôvod ich nútiť poznať typy máp.
    if (type.id === DEFAULT_MAP_TYPE) {
      writeFileSync(join(outDir, `${region}-${themeKey}.json`), json);
    }
    console.log(
      `✓ ${region}-${type.id}-${themeKey}.json (${drawn} z ${style.layers.length} vrstiev kreslí)`
    );
  }
}

console.log(
  `Typy máp: ${MAP_TYPES.map((t) => t.label).join(", ")} ` +
    `(predvolený ${DEFAULT_MAP_TYPE} aj pod menom bez typu)`
);
console.log(
  `Značené trasy: ${hasTrails ? `áno (do z${trailsMaxzoom})` : "nie"}, ` +
  `Krajinné prvky: ${hasFeatures ? `áno (do z${featuresMaxzoom})` : "nie"}, ` +
  `Obmedzenia na ceste: ${hasRoads ? `áno (do z${roadsMaxzoom})` : "nie"}, ` +
  `Vrstevnice: ${
    hasContours ? `áno (do z${contoursMaxzoom}, výšky: ${DEM_SOURCES[demSource].label})` : "nie"
  }, ` +
  `Skaly: ${hasRocks ? `áno (do z${rocksMaxzoom})` : "nie"}, ` +
    `výškové dáta (3D terén): ${
      demTiles
        ? demTiles === DEFAULT_DEM_TILES
          ? "AWS Terrain Tiles"
          : `vlastné do z${demMaxzoom} z ${DEM_SOURCES[demTilesSource].label}`
        : "nie"
    }, ` +
    `tieňovanie reliéfu: ${overrides?.hillshade ? "zapnuté" : "vypnuté"}`,
    `3D terén: ${terrain3d ? `zapnutý (prevýšenie ${terrainExaggeration}×)` : "vypnutý"}`
);
