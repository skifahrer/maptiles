import {
  THEMES,
  buildStyle,
  normalizeOverrides,
  hasOverrides,
  emptyOverrides,
  selectedIconSource,
  CLICKABLE_LAYERS,
  MAX_DISPLAY_Z,
  MAX_TILE_Z,
  TERRAIN_MIN_Z,
  DEFAULT_DEM_TILES,
  DEFAULT_DEM_MAXZOOM,
  DEFAULT_DEM_SOURCE,
  DEM_SOURCES,
  TRAIL_TYPES,
  MAP_TYPES,
  DEFAULT_MAP_TYPE,
  mapTypeDef,
  normalizeMapType
} from "./themes.js";
import { initDevMode, loadOverrides, saveOverrides } from "./devmode.js";
import { parsePatternName, renderPattern } from "./patterns.js";
import { ICON_SOURCES, DEFAULT_ICON_SOURCE, customIconSources } from "./icon-sources.js";

// Základná URL stránky (funguje na GitHub Pages aj lokálne).
const baseUrl = new URL(".", location.href).href.replace(/\/$/, "");

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const $ = (id) => document.getElementById(id);
const themeSelect = $("theme");
const mapTypeSelect = $("maptype");
const regionSelect = $("region");
const contoursCheck = $("contours");
const rocksCheck = $("rocks");
const trailsCheck = $("trails");
const featuresCheck = $("features");
const roadsCheck = $("roads");
const boundariesCheck = $("boundaries");
const waterCheck = $("water");
const terrainCheck = $("terrain");
const hillshadeCheck = $("hillshade");
const devCheck = $("devmode");
const metaEl = $("meta");
const zoomEl = $("zoom");
const warnEl = $("warn");
const panelEl = $("panel");
const toggleEl = $("toggle");
const devEl = $("dev");

for (const [key, t] of Object.entries(THEMES)) {
  themeSelect.add(new Option(t.label, key));
}

// Typ mapy hovorí, **čo** mapa ukazuje (téma len to, ako to vyzerá).
for (const t of MAP_TYPES) {
  mapTypeSelect.add(new Option(t.label, t.id));
}
mapTypeSelect.value = (() => {
  try {
    return normalizeMapType(localStorage.getItem("fricomaps.maptype"));
  } catch {
    return DEFAULT_MAP_TYPE;
  }
})();

/**
 * Región z adresy (`#map=15/49.17/20.11&region=zilinsky`), alebo null.
 *
 * Neznámy kľúč sa ignoruje, nech starý odkaz otvorí mapu a nie prázdnu stránku.
 */
function regionFromHash(manifest) {
  const raw = location.hash.replace(/^#/, "");
  for (const part of raw.split("&")) {
    const [k, v] = part.split("=");
    if (k === "region" && v && manifest.regions[v]) return v;
  }
  return null;
}

/** Poloha z adresy (`#map=15/49.17/20.11`) ako `{zoom, lat, lon}`, alebo null. */
function posFromHash() {
  const raw = location.hash.replace(/^#/, "");
  for (const part of raw.split("&")) {
    const [k, v] = part.split("=");
    if (k !== "map" || !v) continue;
    const [zoom, lat, lon] = v.split("/").map(Number);
    if ([zoom, lat, lon].every(Number.isFinite)) return { zoom, lat, lon };
  }
  return null;
}

/** Vyhodí z adresy `map=…`; ostatné parametre (`region=…`) nechá. */
function dropPosFromHash() {
  const rest = location.hash
    .replace(/^#/, "")
    .split("&")
    .filter((p) => p && p.split("=")[0] !== "map");
  history.replaceState(
    null,
    "",
    location.pathname + location.search + (rest.length ? `#${rest.join("&")}` : "")
  );
}

// ---------- zbalené ovládanie ----------
function setPanel(open) {
  panelEl.hidden = !open;
  toggleEl.setAttribute("aria-expanded", String(open));
  toggleEl.textContent = open ? "✕" : "⚙";
  try {
    localStorage.setItem("fricomaps.panel", open ? "1" : "0");
  } catch {
    /* súkromný režim – stav si jednoducho nezapamätáme */
  }
}
toggleEl.addEventListener("click", () => setPanel(panelEl.hidden));
setPanel(localStorage.getItem?.("fricomaps.panel") === "1");

function showError(detail) {
  $("error").style.display = "block";
  $("error-detail").textContent = detail || "";
}

/**
 * Chyby pri načítaní dlaždíc, spritu alebo glyfov sa inak prejavia len ako
 * prázdna (biela) mapa – preto ich zbierame a zobrazíme v paneli.
 */
const seenWarnings = new Set();
function warn(message) {
  if (seenWarnings.has(message)) return;
  seenWarnings.add(message);
  warnEl.style.display = "block";
  toggleEl.classList.add("has-warning");
  const li = document.createElement("li");
  li.textContent = message;
  warnEl.querySelector("ul").appendChild(li);
  console.warn("[FricoMaps]", message);
}

async function loadJson(url, { optional = false } = {}) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    if (!optional) throw new Error(`${url}: ${err.message}`);
    warn(`Nepodarilo sa načítať ${url} (${err.message})`);
    return null;
  }
}

/** Druhy značených trás – ľudsky, do popupu (zoznam je v themes.js). */
const TRAIL_LABELS = Object.fromEntries(TRAIL_TYPES.map((t) => [t.id, t.short]));

let map;
let dev = null;
/** Úpravy štýlu z developer módu (prehliadač > zdroják > žiadne). */
let overrides = emptyOverrides();
/** Posledný vygenerovaný štýl – developer mode z neho číta zoznam vrstiev. */
let currentStyle = null;
/**
 * Nasadené sady ikoniek. Pipeline vyrobí SDF sprite z každého zdroja, takže
 * sa dajú v developer móde prepínať naživo bez ďalšieho buildu.
 */
let iconSets = [];

/**
 * Hranice stiahnutých regiónov (`region.geojson`) podľa kľúča regiónu.
 *
 * Za hranicou mapa končí – dlaždice sú orezané len po celých dlaždiciach
 * a vodstvo kreslí Planetiler na celom obdĺžniku bboxu. Štýl sa skladá nanovo
 * pri každom prepnutí témy, preto sa súbory držia tu.
 */
const regionOutlines = {};

/** Sada, ktorú má štýl použiť (z úprav, inak prvá dostupná). */
function currentIconSet() {
  const id = selectedIconSource(overrides);
  return iconSets.find((s) => s.id === id) || iconSets[0] || null;
}

function styleFor(manifest) {
  const region = manifest.regions[regionSelect.value];
  const tileZ = region.maxzoom || manifest.maxzoom || MAX_TILE_Z;
  const demTiles = manifest.dem === null ? null : manifest.dem || DEFAULT_DEM_TILES;
  const set = currentIconSet();

  return buildStyle({
    theme: themeSelect.value,
    mapType: mapTypeSelect.value,
    tilesUrl: `pmtiles://${baseUrl}/${region.pmtiles}`,
    spriteUrl: set ? set.spriteUrl : `${baseUrl}/sprites/osm-liberty`,
    glyphsUrl:
      manifest.glyphs || "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
    icons: set ? set.icons : [],
    iconSet: set ? set.id : DEFAULT_ICON_SOURCE,
    sdfIcons: set ? set.sdf : false,
    fonts: manifest.fonts,
    maxzoom: tileZ,
    contoursUrl:
      region.contours && contoursCheck.checked
        ? `pmtiles://${baseUrl}/${region.contours}`
        : null,
    contoursMaxzoom: region.contours_maxzoom || 14,
    // Skaly majú vlastný .pmtiles s vlastným maxzoomom – v mape sú vidieť
    // do maximálneho zoomu (nad `maxzoom` sa dlaždice naťahujú overzoomom).
    rocksUrl:
      region.rocks && rocksCheck.checked
        ? `pmtiles://${baseUrl}/${region.rocks}`
        : null,
    rocksMaxzoom: region.rocks_maxzoom || 16,
    trailsUrl:
      region.trails && trailsCheck.checked
        ? `pmtiles://${baseUrl}/${region.trails}`
        : null,
    trailsMaxzoom: region.trails_maxzoom || 14,
    // Krajinné prvky (línie a plochy), ktoré schéma OpenMapTiles nemá –
    // vlastný .pmtiles (násypy, múry, vedenia, prieseky, zjazdovky).
    featuresUrl:
      region.features && featuresCheck.checked
        ? `pmtiles://${baseUrl}/${region.features}`
        : null,
    featuresMaxzoom: region.features_maxzoom || 15,
    // Body v krajine (pramene, jaskyne, rozhľadne, …) – DRUHÝ výstup toho
    // istého jobu ako krajinné prvky vyššie (workers/features/points.yml),
    // vlastný .pmtiles. V paneli je to TEN ISTÝ prepínač „Krajinné prvky":
    // pred rozdelením do vlastného súboru boli body súčasťou tej istej
    // vrstvy a nikto v aplikácii nečakal preň druhé zaškrtávacie políčko.
    pointsUrl:
      region.points && featuresCheck.checked
        ? `pmtiles://${baseUrl}/${region.points}`
        : null,
    pointsMaxzoom: region.points_maxzoom || 15,
    // DOPRAVNÁ SIEŤ (workers/transport/transport.yml) – balík `cesty`. Štýl
    // z nej kreslí len OBMEDZENIA NA CESTE (výška podjazdov a tunelov, šírka,
    // hmotnosť, maximálna rýchlosť); čiary ciest sú v základnej mape, takže
    // prepínač v paneli sa aj ďalej volá „Obmedzenia na ceste" – to je to,
    // čo sa ním zapína.
    transportUrl:
      region.transport && roadsCheck.checked
        ? `pmtiles://${baseUrl}/${region.transport}`
        : null,
    transportMaxzoom: region.transport_maxzoom || 14,
    // NÁZVY ÚZEMÍ (balík `hranice`) a NÁZVY VÔD (balík `vodstvo`). Obe vrstvy
    // existujú kvôli menu: `boundary` OpenMapTiles je čiara bez mena územia
    // a meno vody leží mimo jej geometrie.
    boundariesUrl:
      region.boundaries && boundariesCheck.checked
        ? `pmtiles://${baseUrl}/${region.boundaries}`
        : null,
    boundariesMaxzoom: region.boundaries_maxzoom || 12,
    waterUrl:
      region.water && waterCheck.checked
        ? `pmtiles://${baseUrl}/${region.water}`
        : null,
    waterMaxzoom: region.water_maxzoom || 14,
    demSource: region.dem_source || DEFAULT_DEM_SOURCE,
    demTiles,
    // Tieňovanie má vo formulári pipeline vlastný výber modelu, takže
    // výškové dlaždice môžu byť z iného než vrstevnice. Manifest to nesie
    // hore pri `dem`, lebo dlaždice sú spoločné pre všetky regióny.
    demTilesSource: manifest.dem_source || region.dem_source || DEFAULT_DEM_SOURCE,
    demMaxzoom: manifest.dem_maxzoom || DEFAULT_DEM_MAXZOOM,
    // Pri rýchlom teste je tieňovanie len na testovacom štvorci, kým mapa je
    // celý región – bez tejto hranice by MapLibre pýtal dlaždice po celom kraji.
    demBounds: region.test_bbox || null,
    regionOutline: regionOutlines[regionSelect.value] || null,
    overrides,
    name: `FricoMaps – ${region.name}`
  });
}

// Kam mapu otvoriť. Bežne na celý región – ale pri rýchlom teste (switch
// `test`) sú vrstevnice, skaly a tieňovanie len na štvorci s pár km², kým
// mapa je celý kraj. Bez tohto by sa výsledok testu hľadal očami niekde
// v štyroch tisícoch km²; s ním je mapa hneď tam, kde sa niečo počítalo.
function initialBounds(region) {
  const [w, s, e, n] = region.test_bbox || region.bbox;
  return [[w, s], [e, n]];
}

/** Kam sa mapa smie posunúť: presne po hranicu stiahnutého regiónu.
 *
 * Bez toho sa dá odscrollovať kamkoľvek, a mimo regiónu nie je nič – mapa
 * vyzerá ako prázdna sivá plocha.
 *
 * Berie sa vždy celý `bbox`, nie `test_bbox`: rýchly test zmenšuje len terénne
 * vrstvy, kým mapa ostáva celý kraj.
 *
 * MapLibre z `maxBounds` odvodí aj dolný strop zoomu.
 */
function regionMaxBounds(region) {
  const [w, s, e, n] = region.bbox;
  return [[w, s], [e, n]];
}

function applyStyle(manifest) {
  const region = manifest.regions[regionSelect.value];
  const themeKey = themeSelect.value;
  const tileZ = region.maxzoom || manifest.maxzoom || MAX_TILE_Z;

  const style = styleFor(manifest);
  currentStyle = style;

  document.body.classList.toggle("dark", themeKey === "tmava");
  hillshadeCheck.checked = overrides.hillshade === true;

  const kind = mapTypeDef(mapTypeSelect.value);

  metaEl.innerHTML =
    `Región: <b>${region.name}</b><br>` +
    // Rýchly test počíta vrstevnice, skaly a tieňovanie len na štvorci; mapa
    // je pritom celý región. Bez tejto vety vyzerá kraj bez skál ako pokazený
    // build – pritom sú skaly na tých dvoch kilometroch, kde sa čakali.
    (region.test_km2
      ? `<b>Rýchly test:</b> vrstevnice, skaly a tieňovanie len na ` +
        `${region.test_km2} km² zo stredu výrezu – zvyšok mapy je celý región<br>`
      : "") +
    `Mapa: <b>${kind.label}</b> – ${kind.note}<br>` +
    `Dlaždice do z${tileZ}, zobrazenie do z${MAX_DISPLAY_Z} (overzoom)<br>` +
    (region.contours
      ? `Vrstevnice po ${region.contour_interval || 10} m, od z${TERRAIN_MIN_Z}<br>`
      : "") +
    (region.rocks
      ? `Skalné plochy od z${TERRAIN_MIN_Z} do z${region.rocks_maxzoom || 16}` +
        (region.rock_slope ? `, od ${region.rock_slope}°` : "") +
        (region.rock_source ? ` (${region.rock_source})` : "") +
        "<br>"
      : "") +
    (region.contours || region.rocks
      ? `Výšky: ${
          (DEM_SOURCES[region.dem_source] || DEM_SOURCES[DEFAULT_DEM_SOURCE]).label
        }<br>`
      : "") +
    (region.trails
      ? `Značené trasy: ${region.trail_count || "?"} ` +
        `(pásiky vedľa cesty, farba podľa značky)<br>`
      : "") +
    (region.features
      ? `Krajinné prvky do z${region.features_maxzoom || 15} ` +
        `(násypy, múry, vedenia, pramene, zjazdovky)<br>`
      : "") +
    (hasOverrides(overrides) ? "Štýl s vlastnými úpravami (developer mode)<br>" : "") +
    `Vygenerované: ${new Date(manifest.built_at).toLocaleString("sk-SK")}<br>` +
    `© OpenStreetMap prispievatelia`;

  if (!map) {
    const [w, s, e, n] = region.bbox;
    // Poloha z adresy má prednosť pred bboxom regiónu – ale len keď v tom
    // regióne naozaj leží. Hash z minulej návštevy alebo starý odkaz môže
    // mieriť do iného kraja a MapLibre by mapu otvoril nad prázdnom –
    // vyzeralo by to, že build nič nevyrobil, pritom sú dlaždice o sto
    // kilometrov vedľa. Hash sa preto zahodí a rozhodne bbox. Musí to byť
    // PRED vytvorením mapy: `hash: "map"` si adresu prečíta hneď pri štarte.
    const pos = posFromHash();
    if (pos && (pos.lon < w || pos.lon > e || pos.lat < s || pos.lat > n)) {
      dropPosFromHash();
    }
    map = new maplibregl.Map({
      container: "map",
      style,
      bounds: initialBounds(region),
      fitBoundsOptions: { padding: 20 },
      maxBounds: regionMaxBounds(region),
      maxZoom: MAX_DISPLAY_Z,
      maxPitch: 75,
      // Poloha v adrese: `#map=15/49.17/20.11`. Dve veci naraz – dá sa poslať
      // odkaz na konkrétne miesto (to robí pipeline pri testovacom výreze)
      // a F5 nehodí mapu späť na celý región. Menovaný tvar `map=`, a nie
      // holý `#15/49.17/20.11`, aby v hashi ostalo miesto aj na `&region=`.
      hash: "map",
      attributionControl: { compact: true }
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
    map.addControl(
      new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true
      }),
      "top-right"
    );

    // Vzory plôch a čiar sú generované – názov obrázka je zároveň jeho
    // predpis, takže sa dokreslí presne vtedy, keď ho štýl použije.
    // (Pipeline tie isté obrázky dopečie do spritu pre iOS.)
    map.on("styleimagemissing", (ev) => {
      if (map.hasImage(ev.id)) return;
      // VLASTNÁ IKONA sa nesie priamo v úpravách ako PNG v `data:` adrese –
      // v sprite je až po builde, ale v prehliadači má byť vidieť HNEĎ, inak
      // by sa nedala vybrať a pozrieť. Toto je to isté miesto, kde sa
      // dokresľujú vzory: „štýl si pýta obrázok, ktorý v sprite nie je".
      const vlastna = (overrides.customIcons || []).find((i) => i.name === ev.id);
      if (vlastna) {
        const img = new Image();
        img.onload = () => {
          if (!map.hasImage(ev.id)) {
            map.addImage(ev.id, img, { pixelRatio: vlastna.pixelRatio || 1 });
          }
        };
        img.onerror = () => warn(`Vlastnú ikonu "${ev.id}" sa nepodarilo načítať.`);
        img.src = vlastna.png;
        return;
      }
      const spec = parsePatternName(ev.id);
      if (!spec) return;
      map.addImage(ev.id, renderPattern(spec, 2), { pixelRatio: 2 });
    });

    map.on("error", (ev) => {
      const err = ev?.error;
      const url = err?.url || ev?.sourceId || "";
      warn(`${err?.message || "neznáma chyba"}${url ? ` – ${url}` : ""}`);
    });

    const updateZoom = () => {
      const z = map.getZoom();
      zoomEl.textContent =
        `zoom ${z.toFixed(1)}` + (z > tileZ ? ` · overzoom z${tileZ}` : "");
    };
    map.on("zoom", updateZoom);
    map.on("load", updateZoom);
    map.on("style.load", applyTerrain);

    // Klik na POI / vrchol / letisko / trasu zobrazí popup s detailom.
    // Kým je v developer móde otvorený inšpektor prvkov, klik patrí jemu –
    // vypíše všetko, čo je pod kurzorom, nielen jeden vybraný prvok.
    map.on("click", (ev) => {
      if (dev?.isPicking?.()) return;
      const layers = CLICKABLE_LAYERS.filter((id) => map.getLayer(id));
      const [f] = map.queryRenderedFeatures(ev.point, { layers });
      if (!f) return;
      const p = f.properties;
      // Po jednej ceste vedie aj päť trás – popup povie, do ktorej sa trafil.
      if (f.layer.id.startsWith("trail-")) {
        const title = [p.ref, p.name].filter(Boolean).join(" ") || "(bez názvu)";
        const detail = [TRAIL_LABELS[p.route] || p.route, p.colour, p.network]
          .filter(Boolean)
          .join(" · ");
        new maplibregl.Popup()
          .setLngLat(ev.lngLat)
          .setHTML(
            `<b>${title}</b><br><small>${detail}</small>` +
              (p.rel
                ? `<br><small><a href="https://www.openstreetmap.org/relation/${p.rel}"` +
                  ` target="_blank" rel="noopener">trasa v OSM</a></small>`
                : "")
          )
          .addTo(map);
        return;
      }
      // `ref` je záloha za meno: plánovaná diaľnica meno väčšinou nemá, ale
      // `D3` je presne to, čo od nej človek chce vedieť. Bez tejto zálohy by
      // popup na nej hlásil „(bez názvu)“, hoci označenie v dátach je.
      const title = p["name:sk"] || p.name || p.ref || "(bez názvu)";
      // `difficulty` je pri zjazdovkách to hlavné – modrá alebo čierna je
      // odpoveď na to, prečo si tam človek klikol.
      const detail = [p.subclass, p.class, p.difficulty].filter(Boolean).join(" · ");
      const ele = p.ele ? `<br><small>${p.ele} m n. m.</small>` : "";
      new maplibregl.Popup()
        .setLngLat(ev.lngLat)
        .setHTML(`<b>${title}</b><br><small>${detail}</small>${ele}`)
        .addTo(map);
    });
    map.on("mousemove", (ev) => {
      const layers = CLICKABLE_LAYERS.filter((id) => map.getLayer(id));
      const hit = layers.length && map.queryRenderedFeatures(ev.point, { layers }).length;
      map.getCanvas().style.cursor = hit ? "pointer" : "";
    });
  } else {
    // `diff: true` (default) prekreslí len to, čo sa naozaj zmenilo – vďaka
    // tomu je ladenie farieb v developer móde plynulé.
    map.setStyle(style);
  }
}

/** 3D terén používa ten istý raster-dem zdroj ako tieňovanie reliéfu.
 *
 * Prevýšenie sa berie zo štýlu, keď ho tam pipeline dala – inak by sa 3D na
 * webe a v mape pre iOS raz rozišlo.
 */
function terrainExaggeration() {
  const zo_stylu = map?.getStyle?.()?.terrain?.exaggeration;
  return Number.isFinite(zo_stylu) ? zo_stylu : 1.3;
}

function applyTerrain() {
  if (!map) return;
  const on = terrainCheck.checked && map.getSource("dem");
  map.setTerrain(on ? { source: "dem", exaggeration: terrainExaggeration() } : null);
}

// ---------- developer mode ----------
function setDevMode(on, manifest) {
  devEl.hidden = !on;
  devCheck.checked = on;
  try {
    localStorage.setItem("fricomaps.dev", on ? "1" : "0");
  } catch {
    /* súkromný režim */
  }
  if (!on || dev) return;

  dev = initDevMode({
    root: devEl,
    getStyle: () => currentStyle,
    getTheme: () => themeSelect.value,
    // Prepínač tmavá/svetlá priamo v paneli (rozpis pri `renderThemeToggle`
    // v devmode.js) – ide cez ten istý výber, aký má gombík ⚙, takže sa
    // znova spustí jeho `change` (prekreslenie mapy aj `dev.refresh()`)
    // a obe miesta ostanú vždy zhodné.
    setTheme: (key) => {
      if (themeSelect.value === key) return;
      themeSelect.value = key;
      themeSelect.dispatchEvent(new Event("change"));
    },
    getMapType: () => mapTypeSelect.value,
    getMap: () => map,
    getIconSets: () => iconSets,
    onChange: (next) => {
      overrides = next;
      applyStyle(manifest);
    }
  });
  devEl.addEventListener("dev-close", () => setDevMode(false, manifest));
}

async function main() {
  let manifest;
  try {
    manifest = await loadJson(`${baseUrl}/tiles/manifest.json`);
  } catch (err) {
    showError(String(err));
    return;
  }

  // Hranica stiahnutého regiónu. `optional` naschvál: keď súbor nie je (starší
  // build), mapa sa má načítať aj bez nej – len bude siahať za región, a to
  // `loadJson` napíše do konzoly.
  for (const [key, r] of Object.entries(manifest.regions)) {
    if (!r.outline) continue;
    const data = await loadJson(`${baseUrl}/${r.outline}`, { optional: true });
    if (data) regionOutlines[key] = data;
  }

  // Sady ikoniek. Z indexu každej sa berie zoznam mien (aby štýl neodkazoval
  // na ikonu, ktorá v sprite nie je) aj to, či je sprite SDF – vtedy sa dajú
  // ikonám nastaviť farby.
  const declared = manifest.icon_sources?.length
    ? manifest.icon_sources
    : [{ id: DEFAULT_ICON_SOURCE, sprite: manifest.sprite || "sprites/osm-liberty" }];
  for (const entry of declared) {
    const meta = ICON_SOURCES.find((s) => s.id === entry.id) || {};
    const url = /^https?:/.test(entry.sprite) ? entry.sprite : `${baseUrl}/${entry.sprite}`;
    const index = await loadJson(`${url}.json`, { optional: true });
    if (!index) continue;
    const names = Object.keys(index);
    iconSets.push({
      ...meta,
      id: entry.id,
      label: meta.label || entry.id,
      spriteUrl: url,
      index,
      icons: names,
      count: names.length,
      sdf: Object.values(index).some((e) => e && e.sdf)
    });
  }
  if (!iconSets.length) warn("Nenašla sa žiadna sada ikoniek – mapa bude bez ikon.");

  // Úpravy štýlu: čo je uložené v prehliadači má prednosť, inak sa vezme to,
  // čo je zapečené v zdrojáku (workflow „Mapa · úpravy štýlu").
  const stored = loadOverrides();
  if (hasOverrides(stored)) {
    overrides = stored;
  } else {
    const committed = await loadJson(`${baseUrl}/style-overrides.json`, { optional: true });
    if (committed) {
      const { overrides: clean, problems } = normalizeOverrides(committed);
      overrides = clean;
      for (const p of problems) warn(`style-overrides.json: ${p}`);
    }
  }

  // Vlastné sady ikoniek z úprav. Pipeline ich sťahuje a prerába na SDF
  // rovnako ako tie z repozitára, ale v prehliadači sa dá práve pridaná sada
  // pozrieť hneď – načíta sa priamo z jej adresy. Kým ju build nespracuje,
  // je to CUDZÍ sprite: ikony majú svoje pôvodné farby a nedajú sa prefarbiť.
  for (const set of customIconSources(overrides)) {
    if (iconSets.some((s2) => s2.id === set.id)) continue;
    const index = await loadJson(`${set.sprite}.json`, { optional: true });
    if (!index) {
      warn(`Vlastnú sadu ikoniek "${set.id}" sa nepodarilo načítať z ${set.sprite}.json`);
      continue;
    }
    const names = Object.keys(index);
    iconSets.push({
      ...set,
      spriteUrl: set.sprite,
      index,
      icons: names,
      count: names.length,
      sdf: Object.values(index).some((e) => e && e.sdf)
    });
  }

  for (const [key, r] of Object.entries(manifest.regions)) {
    regionSelect.add(new Option(r.name, key));
  }
  // Región sa dá zadať v adrese (`#map=…&region=zilinsky`). Pipeline taký
  // odkaz vypisuje do súhrnu behu pri testovacom výreze – bez toho by odkaz
  // otvoril správne súradnice, ale predvolený región, čiže inú mapu.
  regionSelect.value = regionFromHash(manifest) || manifest.default_region;

  const syncControls = () => {
    const region = manifest.regions[regionSelect.value];
    $("row-contours").hidden = !region.contours;
    $("row-rocks").hidden = !region.rocks;
    $("row-trails").hidden = !region.trails;
    $("row-features").hidden = !region.features;
    $("row-roads").hidden = !region.transport;
    $("row-boundaries").hidden = !region.boundaries;
    $("row-water").hidden = !region.water;
    $("row-terrain").hidden = manifest.dem === null;
    $("row-hillshade").hidden = manifest.dem === null;
  };
  syncControls();

  themeSelect.addEventListener("change", () => {
    applyStyle(manifest);
    dev?.refresh();
  });
  mapTypeSelect.addEventListener("change", () => {
    try {
      localStorage.setItem("fricomaps.maptype", mapTypeSelect.value);
    } catch {
      /* súkromný režim – typ mapy sa jednoducho nezapamätá */
    }
    applyStyle(manifest);
    // Developer mode ladí vždy tú mapu, ktorá je na obrazovke – zoznam vrstiev
    // aj rozsah úprav sa preto musia prekresliť.
    dev?.refresh();
  });
  contoursCheck.addEventListener("change", () => {
    applyStyle(manifest);
    dev?.refresh();
  });
  rocksCheck.addEventListener("change", () => {
    applyStyle(manifest);
    dev?.refresh();
  });
  featuresCheck.addEventListener("change", () => {
    applyStyle(manifest);
  });
  roadsCheck.addEventListener("change", () => {
    applyStyle(manifest);
  });
  boundariesCheck.addEventListener("change", () => {
    applyStyle(manifest);
  });
  waterCheck.addEventListener("change", () => {
    applyStyle(manifest);
  });
  trailsCheck.addEventListener("change", () => {
    applyStyle(manifest);
    dev?.refresh();
  });
  terrainCheck.addEventListener("change", applyTerrain);
  // Tieňovanie reliéfu je súčasť štýlu (nie len prepínač viewra), aby sa
  // rovnaké nastavenie zapieklo aj do statického štýlu pre iOS.
  hillshadeCheck.addEventListener("change", () => {
    const next = { ...overrides, hillshade: hillshadeCheck.checked };
    if (dev) {
      // Developer mode si drží vlastnú kópiu – nech o zmene vie a uloží ju.
      dev.setOverrides(next);
    } else {
      overrides = next;
      saveOverrides(overrides);
      applyStyle(manifest);
    }
  });
  regionSelect.addEventListener("change", () => {
    syncControls();
    applyStyle(manifest);
    const region = manifest.regions[regionSelect.value];
    // Staré hranice sa musia najprv PUSTIŤ: nový región je inde a `fitBounds`
    // by sa doň nemal ako dostať – MapLibre by cieľ orezal na to, čo dovoľuje
    // ešte stále nastavený bbox predošlého kraja.
    map.setMaxBounds(null);
    map.fitBounds(initialBounds(region), { padding: 20 });
    map.setMaxBounds(regionMaxBounds(region));
  });
  devCheck.addEventListener("change", () =>
    setDevMode(devCheck.checked, manifest)
  );

  applyStyle(manifest);

  // Developer mode sa zapína prepínačom v paneli alebo cez ?dev=1.
  const wantDev =
    new URLSearchParams(location.search).get("dev") === "1" ||
    localStorage.getItem?.("fricomaps.dev") === "1";
  if (wantDev) setDevMode(true, manifest);

  // Viewer nabehol – strážca štartu v `index.html` už nemá čo hlásiť. Je to
  // až tu, na konci `main()`: skôr by príznak povedal „nabehol" o niečom, čo
  // sa ešte môže zlomiť.
  window.__viewerBooted = true;
}

main();
