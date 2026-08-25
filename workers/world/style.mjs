#!/usr/bin/env node
/**
 * MapLibre štýl k mape sveta – jeden súbor na farebnú tému.
 *
 * PREČO VLASTNÝ GENERÁTOR A NIE `workers/styles/build.mjs`. Ten skladá štýl
 * nad schémou OpenMapTiles (`transportation`, `landcover`, `poi`, …) plus nad
 * našimi vrstvami vrstevníc, skál, trás a prvkov – dokopy stovky vrstiev,
 * z ktorých mapa sveta nemá ANI JEDNU. Mapa sveta má štyri vlastné
 * (`workers/world/world.yml`), takže by to nebolo „to isté s vypnutými
 * vrstvami", ale druhá vetva v tom istom súbore. Farby sú spoločné: berú sa
 * z `poc/web/themes.js`, aby svet a mapa kraja vyzerali ako jedna aplikácia.
 *
 * ODKAZY SÚ PREDVOLENE RELATÍVNE (`pmtiles://tiles/svet.pmtiles`). Táto mapa
 * sa nenasadzuje na Pages – ide na Drive ako `.zip` a `.aar`, ktorý si človek
 * (alebo appka) rozbalí k sebe, a tam žiadna adresa nie je. Keď ju niekto
 * chce hosťovať, `--base-url=` z nich spraví absolútne.
 *
 * ZOOMY MUSIA SEDIEŤ SO SCHÉMOU. `minzoom` vrstvy štýlu hovorí, čo sa KRESLÍ,
 * `min_zoom` v `world.yml`, čo sa VYROBÍ – a keď sa rozídu, mapa má buď dieru,
 * alebo platí za dlaždice, ktoré nikto nevykreslí. Je to ten istý pár čísel,
 * aký pri vrstevniciach stráži `workers/lint/zoom-floor.py`; tu ho stráži
 * `workers/lint/world.py`.
 *
 * Použitie:
 *   node workers/world/style.mjs --out=_site/styles --maxzoom=6
 *   node workers/world/style.mjs --out=_site/styles --base-url=https://…/svet
 */
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { THEMES } from "../../poc/web/themes.js";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=")];
  })
);

const outDir = args.out || "_site/styles";
const region = args.region || "svet";
const maxzoom = Number(args.maxzoom || 6);

// PODOBA MAPY (`plna` / `basic`). Číselník je ten istý, z ktorého si build
// skladá schému pre Planetiler – `workers/data/world-variants.json`. Štýl
// z neho potrebuje jedinú vec: ktoré vrstvy schémy v tej podobe existujú.
// Kresliť vrstvu, ktorá v dlaždiciach nie je, by MapLibre nezhodilo a nikto
// by nepovedal nič (presne to stráži `workers/lint/world.py` pri menách).
const _HERE = dirname(fileURLToPath(import.meta.url));
const VARIANTY = JSON.parse(
  readFileSync(join(_HERE, "..", "data", "world-variants.json"), "utf8")
);
const variant = args.variant || "plna";
if (!VARIANTY[variant] || variant.startsWith("_")) {
  console.error(
    `::error::Podobu mapy sveta „${variant}" nepoznám. Sú: ` +
      Object.keys(VARIANTY).filter((k) => !k.startsWith("_")).join(", ")
  );
  process.exit(1);
}
const VRSTVY = new Set(VARIANTY[variant].layers);
// Prázdny `--base-url` = relatívne odkazy (balík na disku). S ním sa z nich
// stanú absolútne (mapa hosťovaná na URL).
const base = (args["base-url"] || "").replace(/\/$/, "");
const url = (cesta) => (base ? `${base}/${cesta}` : cesta);
// GLYFY V BALÍKU NIE SÚ. Boli – odkaz sem mieril relatívne, vedľa dlaždíc –
// a `publish-map.py` ich preto ako jedinému balíku nechával. Odkedy si tri
// orezané stacky nesie v sebe appka (`skifahrer/rikimaps`, `GlyphStore`)
// a `glyphs` si pri načítaní prepíše na ne, je kópia v balíku mŕtva váha
// a pri strope 15 MB na podobu `basic` to nie je zanedbateľná váha.
//
// Adresa tu ostáva preto, aby mal ODKIAĽ BRAŤ ten, kto nie je appka: rozbalený
// balík vo webovom vieweri. Je to tá istá verejná služba, na ktorú siaha
// `workers/deploy/site.sh` aj `workers/styles/build.mjs`, keď lokálne glyfy
// nie sú – mapa s cudzími nápismi je lepšia než mapa bez nápisov.
const glyphs = args.glyphs || "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf";

// Tie isté fontstacky, aké kopíruje `workers/assets/glyphs.sh` (hľadá presne
// `Noto Sans Regular` / `Bold` / `Italic`).
const REG = ["Noto Sans Regular"];
const BOLD = ["Noto Sans Bold"];

const ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap ' +
  'prispievatelia</a> · <a href="https://download.geofabrik.de/">Geofabrik</a>' +
  ' · <a href="https://www.naturalearthdata.com/">Natural Earth</a>';

/**
 * Od ktorého zoomu sa čo kreslí. Sú to TIE ISTÉ čísla, aké má `min_zoom`
 * v `workers/world/world.yml` – nižšie by mapa mala dieru, vyššie by sa
 * platili dlaždice, ktoré nikto nevykreslí. Porovnáva ich
 * `workers/lint/world.py`.
 */
const OD = {
  water: 0,
  lakeMinor: 5,
  boundary: 0,
  boundaryDisputed: 2,
  place: 1,
  download: { continent: 0, country: 2, subregion: 5 },
  downloadLabel: { continent: 2, country: 3, subregion: 5 }
};

/** Do ktorého zoomu má úroveň regiónov zmysel – nižšia sa vypne, keď nastúpi
 * podrobnejšia. Bez toho by na sebe ležali tri obrysy toho istého územia
 * (výsek je vnútri štátu a ten vnútri svetadielu) a mapa by bola sieť. */
const DO = { continent: OD.download.country, country: OD.download.subregion };

const UROVNE = ["continent", "country", "subregion"];

function styl(temaId) {
  const c = THEMES[temaId];
  const layers = [
    // Pevnina je PODKLAD, nie polygón: mapa sveta nekreslí plochy štátov,
    // takže všetko, čo nie je voda, je táto farba.
    {
      id: "background",
      type: "background",
      paint: { "background-color": c.background }
    },
    // Moria, oceány a jazerá. Vrstva je čisto plošná (popisky sú vlastné
    // vrstvy), takže `fill` nemá čo pustiť do earcutu okrem plôch.
    {
      id: "water",
      type: "fill",
      source: "svet",
      "source-layer": "water",
      minzoom: OD.water,
      paint: { "fill-color": c.water }
    },
    {
      id: "water-outline",
      type: "line",
      source: "svet",
      "source-layer": "water",
      minzoom: 3,
      paint: { "line-color": c.waterOutline, "line-width": 0.6 }
    }
  ];

  // ---------- regióny sťahovania ----------
  // Kvôli nim je táto mapa: ukazujú, na aké kusy je OSM rozdelené a ktorý si
  // stiahnuť. Každá úroveň má vlastnú vrstvu, aby sa dala vypnúť tam, kde
  // nastúpi podrobnejšia (viď `DO`).
  for (const uroven of UROVNE) {
    const od = OD.download[uroven];
    const doZoomu = DO[uroven];
    const rozsah = { minzoom: od, ...(doZoomu ? { maxzoom: doZoomu } : {}) };
    layers.push({
      id: `download-${uroven}`,
      type: "fill",
      source: "svet",
      "source-layer": "download",
      ...rozsah,
      filter: ["==", ["get", "level"], uroven],
      paint: { "fill-color": c.boundaryLocal, "fill-opacity": 0.08 }
    });
    layers.push({
      id: `download-${uroven}-line`,
      type: "line",
      source: "svet",
      "source-layer": "download",
      ...rozsah,
      filter: ["==", ["get", "level"], uroven],
      paint: {
        "line-color": c.boundaryLocal,
        "line-width": uroven === "subregion" ? 0.8 : 1.4
      }
    });
  }

  // ---------- hranice štátov ----------
  layers.push({
    id: "boundary",
    type: "line",
    source: "svet",
    "source-layer": "boundary",
    minzoom: OD.boundary,
    filter: ["==", ["get", "kind"], "country"],
    paint: {
      "line-color": c.boundary,
      "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 6, 1.6]
    }
  });
  layers.push({
    // Sporná hranica prerušovane – mapa nemá tvrdiť, že je istá.
    id: "boundary-disputed",
    type: "line",
    source: "svet",
    "source-layer": "boundary",
    minzoom: OD.boundaryDisputed,
    filter: ["==", ["get", "kind"], "disputed"],
    paint: {
      "line-color": c.boundary,
      "line-width": 0.8,
      "line-dasharray": [2, 2],
      "line-opacity": 0.7
    }
  });

  // ---------- popisky ----------
  layers.push({
    id: "place-country",
    type: "symbol",
    source: "svet",
    "source-layer": "place",
    minzoom: OD.place,
    layout: {
      "text-field": ["coalesce", ["get", "name"], ["get", "name_en"]],
      "text-font": BOLD,
      "text-size": ["match", ["get", "rank"], "major", 14, "mid", 12, 11],
      "text-max-width": 7,
      "text-padding": 4
    },
    paint: {
      "text-color": c.placeText,
      "text-halo-color": c.textHalo,
      "text-halo-width": 1.4
    }
  });
  for (const uroven of UROVNE) {
    const doZoomu = DO[uroven];
    layers.push({
      id: `download-label-${uroven}`,
      type: "symbol",
      source: "svet",
      "source-layer": "download_label",
      minzoom: OD.downloadLabel[uroven],
      ...(doZoomu ? { maxzoom: doZoomu } : {}),
      filter: ["==", ["get", "level"], uroven],
      layout: {
        "text-field": ["get", "name"],
        "text-font": REG,
        "text-size": uroven === "subregion" ? 10 : 11,
        "text-max-width": 8,
        "text-padding": 6
      },
      paint: {
        "text-color": c.placeText,
        "text-halo-color": c.textHalo,
        "text-halo-width": 1.2,
        "text-opacity": 0.9
      }
    });
  }

  // ČO PODOBA NEMÁ, SA NEKRESLÍ. Filtruje sa tu, na konci a podľa
  // `source-layer`, a nie `if`-mi po celom súbore: pribudnúť môže vrstva
  // aj podoba a takto sa nedá zabudnúť na jedno z tých dvoch miest.
  // `background` zdroj nemá a ostáva vždy – je to farba pevniny.
  const podla = layers.filter(
    (l) => !l["source-layer"] || VRSTVY.has(l["source-layer"])
  );

  return {
    version: 8,
    name: `FricoMaps svet – ${c.label}`,
    // Kto štýl otvorí, má vedieť, čo v tej mape je a čo v nej NIE JE.
    metadata: {
      "fricomaps:kind": "svet",
      "fricomaps:variant": variant,
      "fricomaps:description":
        `Základná mapa sveta (${VARIANTY[variant].label}). Cesty, sídla ani `
        + "terén v nej nie sú – je to podklad pod výber, ktorý kus si stiahnuť.",
      "fricomaps:theme": temaId
    },
    glyphs,
    sources: {
      svet: {
        type: "vector",
        url: `pmtiles://${url(`tiles/${region}.pmtiles`)}`,
        attribution: ATTRIBUTION,
        minzoom: 0,
        maxzoom
      }
    },
    layers: podla
  };
}

mkdirSync(outDir, { recursive: true });
const napisane = [];
for (const temaId of Object.keys(THEMES)) {
  const cesta = join(outDir, `${region}-${temaId}.json`);
  writeFileSync(cesta, JSON.stringify(styl(temaId), null, 2) + "\n");
  napisane.push(cesta);
}
console.log(`Štýly mapy sveta – podoba ${variant} (${napisane.length}): `
  + napisane.join(", "));
console.log(`  dlaždice: pmtiles://${url(`tiles/${region}.pmtiles`)}`);
console.log(`  glyfy:    ${glyphs}`);
