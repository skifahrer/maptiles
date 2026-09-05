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
 *   --transport  … dopravná sieť; štýl z nej kreslí obmedzenia na ceste
 *                  (výška podjazdov a tunelov, šírka,
 *                  hmotnosť, maximálna rýchlosť), ktoré vrstva
 *                  `transportation` OpenMapTiles nenesie vôbec
 *   --boundaries … hranice území; štýl z nich kreslí NÁZVY území – vrstva
 *                  `boundary` OpenMapTiles je čiara bez mena
 *   --water      … vodstvo; meno je tam na geometrii, takže odtiaľ idú názvy
 *                  vôd namiesto `water_name` OpenMapTiles
 *   --features   … krajinné prvky (línie a plochy), ktoré schéma OpenMapTiles
 *                  nemá – násypy, múry, vedenia, zjazdovky (vlastný .pmtiles)
 *   --points     … body v krajine – pramene, jaskyne, rozhľadne, pamiatky
 *                  (workers/features/points.yml, DRUHÝ výstup toho istého
 *                  jobu ako --features, vlastný .pmtiles)
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

// číselníky sú v susednom `workers/data/`, koreň o dve úrovne vyššie
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
// vrstevnice sú voliteľné – štýl ich zapne, len ak pipeline vyrobila .pmtiles
const contoursMaxzoom = Number(args["contours-maxzoom"] || 14);
const hasContours = args.contours === "true" || args.contours === "1";
// skaly majú vlastný .pmtiles a vlastný maxzoom
const rocksMaxzoom = Number(args["rocks-maxzoom"] || 16);
const hasRocks = args.rocks === "true" || args.rocks === "1";
// značené trasy – rovnako voliteľné a v samostatnom .pmtiles
const trailsMaxzoom = Number(args["trails-maxzoom"] || 14);
const hasTrails = args.trails === "true" || args.trails === "1";
// krajinné prvky – to isté
const featuresMaxzoom = Number(args["features-maxzoom"] || 15);
const hasFeatures = args.features === "true" || args.features === "1";
// body v krajine: druhý výstup toho istého jobu, preto vlastný .pmtiles,
// ale rovnaký maxzoom
const pointsMaxzoom = Number(args["points-maxzoom"] || featuresMaxzoom);
const hasPoints = args.points === "true" || args.points === "1";
// obmedzenia na ceste – opäť vlastný .pmtiles a voliteľné
const transportMaxzoom = Number(args["transport-maxzoom"] || 14);
const hasTransport = args.transport === "true" || args.transport === "1";
// hranice a vodstvo – vlastné .pmtiles, z ktorých štýl kreslí názvy území a vôd
const boundariesMaxzoom = Number(args["boundaries-maxzoom"] || 12);
const hasBoundaries = args.boundaries === "true" || args.boundaries === "1";
const waterMaxzoom = Number(args["water-maxzoom"] || 14);
const hasWater = args.water === "true" || args.water === "1";
// zdroj výšok ovplyvňuje atribúciu vrstevníc a skál
const demSource = DEM_SOURCES[args["dem-source"]]
  ? args["dem-source"]
  : DEFAULT_DEM_SOURCE;
// tieňovanie má vlastný výber modelu, takže dlaždice môžu byť z iného než
// vrstevnice – atribúcia sa berie zvlášť
const demTilesSource = DEM_SOURCES[args["dem-tiles-source"]]
  ? args["dem-tiles-source"]
  : demSource;
// tieňovanie sa dá vypnúť (`--dem-tiles=none`)
const demTiles =
  args["dem-tiles"] === "none" ? null : args["dem-tiles"] || DEFAULT_DEM_TILES;
const demMaxzoom = Number(args["dem-maxzoom"] || DEFAULT_DEM_MAXZOOM);
// 3D terén sa zapína, keď máme vlastné výškové dlaždice. Na verejné AWS
// Terrain Tiles sa nezapína: sú globálne a hrubé, z hôr by boli mydlové kopce.
// Doteraz si 3D zapínal len web za behu, takže iOS dostával plochú mapu, hoci
// dlaždice v štýle boli.
const ownDemTiles = Boolean(demTiles) && demTiles !== DEFAULT_DEM_TILES;
const terrain3dArg = String(args["terrain-3d"] ?? "auto").toLowerCase();
const terrain3d = ["0", "false", "nie", "ziadne", "vypnute"].includes(terrain3dArg)
  ? false
  // `auto` aj `1` znamenajú „zapni, ak máme z čoho"; bez vlastných dlaždíc
  // sa 3D nezapne ani na výslovnú žiadosť
  : ownDemTiles;
const terrainExaggeration = Number(
  args["terrain-exaggeration"] || DEFAULT_TERRAIN_EXAGGERATION
);
// kde vlastné výškové dlaždice vôbec sú – rýchly test ich počíta len na
// štvorci, takže by klient inak pýtal tieňovanie po celom kraji a dostal 404
const demBounds = args["dem-bounds"]
  ? args["dem-bounds"].split(",").map(Number)
  : null;
if (demBounds && (demBounds.length !== 4 || demBounds.some((n) => !Number.isFinite(n)))) {
  console.error("--dem-bounds musí byť W,S,E,N (štyri čísla)");
  process.exit(1);
}

// hranica regiónu sa vkladá do štýlu, nie ako URL: aplikácia si mapu stiahne
// a offline musí prepísať adresy; zabudnutý odkaz na `region.geojson` by sa
// neprejavil pádom – mapa by len zase siahala za región. Dáta majú jednotky kB.
//
// Do štýlu ide zástupný reťazec a hotový JSON sa zaň vymení až nakoniec:
// `JSON.stringify(…, null, 2)` rozsype každú súradnicu na vlastný riadok
// (z 8,9 kB je 54 kB a v 25 štýloch 1,3 MB samého odsadenia).
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
// región nemusí byť v regions.json (custom z osm.fr) – vtedy meno z `--name`
const regionName = regions[region]?.name || args.name || region;

// sada ikoniek: ktorú použiť, hovoria úpravy z developer módu; keď jej sprite
// chýba, vezme sa prvá dostupná
const spritesDir = args["sprites-dir"] || "";
let iconSetId = null;
let spriteJsonPath = args.sprite || "";

// zo sprite indexu sa berie aj to, či je sprite SDF – tomu sa dá nastaviť
// farba, takže štýl pridá `icon-color`
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

// úpravy z developer módu; súbor je voliteľný
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

// sadu ikoniek určujú úpravy; sprite k nej musí byť nasadený
iconSetId = selectedIconSource(overrides);
if (spritesDir) {
  // náhradníci, keď vybraná sada nie je nasadená; vlastné sady z úprav sú
  // medzi nimi tiež
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

// fontstacky: na Pages ležia glyfy v `_site/fonts/<Fontstack>/<range>.pbf`.
// Keď žiadne nie sú, spadne sa na verejnú službu.
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

// sprite, na ktorý sa odkazuje výsledný štýl (bez prípony)
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

// každá farba témy musí byť v niektorej skupine palety, inak by sa v developer
// móde nedala nájsť
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
      pointsUrl: hasPoints
        ? `pmtiles://${baseUrl}/tiles/${region}-points.pmtiles`
        : null,
      pointsMaxzoom,
      transportUrl: hasTransport
        ? `pmtiles://${baseUrl}/tiles/${region}-transport.pmtiles`
        : null,
      transportMaxzoom,
      boundariesUrl: hasBoundaries
        ? `pmtiles://${baseUrl}/tiles/${region}-boundaries.pmtiles`
        : null,
      boundariesMaxzoom,
      waterUrl: hasWater
        ? `pmtiles://${baseUrl}/tiles/${region}-water.pmtiles`
        : null,
      waterMaxzoom,
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
    // staré meno bez typu mapy ostáva – odkazuje naň iOS aj smoke test
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
  `Body v krajine: ${hasPoints ? `áno (do z${pointsMaxzoom})` : "nie"}, ` +
  `Dopravná sieť (obmedzenia na ceste): ${hasTransport ? `áno (do z${transportMaxzoom})` : "nie"}, ` +
  `Názvy území: ${hasBoundaries ? `áno (do z${boundariesMaxzoom})` : "nie"}, ` +
  `Názvy vôd: ${hasWater ? `áno (do z${waterMaxzoom})` : "nie"}, ` +
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
