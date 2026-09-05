#!/usr/bin/env bash
# Viewer + `manifest.json` do `_site/` – posledný krok pred nasadením na Pages.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 kB.
#
# Manifest je jediný súbor, z ktorého viewer zistí, čo v tomto builde je:
# ktoré vrstvy vznikli, po aký zoom siahajú, z akého modelu sú a kde ležia.
# Vrstva, ktorá nebola zapnutá, v ňom nie je – preto sú položky podmienené
# a nie vypĺňané prázdnymi hodnotami („je, len prázdna" je iné tvrdenie).
set -euo pipefail
# celý `poc/web/`, nie vymenovaný zoznam: ten sa raz rozišiel s priečinkom
# (`layer-style.js`) a modulový graf padol celý – mapa sa nevykreslila a build
# bol zelený. Stráži to workers/lint/viewer.py.
cp poc/web/*.js poc/web/*.json poc/web/index.html _site/

# hranica regiónu je voliteľná – keď sa polygón nestiahol, v manifeste nesmie
# byť. (`if`, nie reťazec testov: `set -e` by na poslednom `&&` spadol.)
OUTLINE="${REGION_OUTLINE:-}"
if [ -n "$OUTLINE" ] && [ ! -s "_site/$OUTLINE" ]; then
  echo "::warning::Hranica regiónu (_site/$OUTLINE) nevznikla – mapa pôjde bez nej a bude siahať aj za región."
  OUTLINE=""
fi

BASE="${BASE_URL%/}"
if [ -d _site/fonts ] && [ -n "$(ls -A _site/fonts)" ]; then
  GLYPHS="$BASE/fonts/{fontstack}/{range}.pbf"
else
  GLYPHS="https://fonts.openmaptiles.org/{fontstack}/{range}.pbf"
fi

# zoznam sád ikoniek pre prepínač; z toho istého `icon-sources.js`, z ktorého
# ich sťahoval job `assets`. Filtruje sa na tie, čo naozaj vznikli – chýbajúci
# sprite by bol vo vieweri prázdny prepínač. Vlastné sady z úprav sú v ňom tiež.
ICON_SOURCES=$(node -e "
  Promise.all([
    import('./poc/web/icon-sources.js'),
    import('./poc/web/themes.js'),
    import('node:fs')
  ]).then(([ic, th, fs]) => {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync('poc/web/style-overrides.json', 'utf8')); } catch {}
    const ok = (process.env.ICONS_AVAILABLE || '').split(/\\s+/).filter(Boolean);
    const vsetky = ic.allIconSources(th.normalizeOverrides(raw).overrides);
    console.log(JSON.stringify(vsetky.filter((s) => ok.includes(s.id))
      .map((s) => ({ id: s.id, label: s.label, sprite: 'sprites/' + s.id,
                     license: s.license, source: s.source, suffix: s.suffix, note: s.note }))));
  });
")

# je v tejto mape 3D terén? Odpovedá hotový štýl, nie prepínač: `auto`
# znamená „zapni, ak máme vlastné výškové dlaždice". Appka podľa toho poľa
# ponúka vrstvu „3D terén".
TERRAIN_3D=false
TERRAIN_EXAG=0
if [ -d _site/styles ]; then
  # `-s` a `map`: štýlov je viac (typ mapy × téma) a stačí ktorýkoľvek
  read -r TERRAIN_3D TERRAIN_EXAG <<<"$(jq -rs '
    [.[] | .terrain // empty]
    | if length > 0
      then "true \((.[0].exaggeration) // 1)"
      else "false 0" end' _site/styles/*.json 2>/dev/null || echo "false 0")"
  case "$TERRAIN_3D" in true|false) ;; *) TERRAIN_3D=false; TERRAIN_EXAG=0 ;; esac
fi
echo "3D terén v štýle: $TERRAIN_3D (prevýšenie $TERRAIN_EXAG×)"

jq -n \
  --arg region "$REGION_KEY" \
  --arg outline "$OUTLINE" \
  --arg name "$REGION_NAME" \
  --arg bbox "$REGION_BBOX" \
  --arg built "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg glyphs "$GLYPHS" \
  --arg sprite "$BASE/sprites/$ICONS_NAME" \
  --arg icons "$ICONS_NAME" \
  --argjson icon_sources "$ICON_SOURCES" \
  --argjson maxzoom "$TILES_MAXZOOM" \
  --argjson size_mb "$TILES_SIZE_MB" \
  --argjson trails "$TRAILS_ENABLED" \
  --argjson tmaxzoom "$TRAILS_MAXZOOM" \
  --argjson tcount "$TRAILS_COUNT" \
  --argjson features "$FEATURES_ENABLED" \
  --argjson fmaxzoom "$FEATURES_MAXZOOM" \
  --argjson points "$POINTS_ENABLED" \
  --argjson boundaries "$BOUNDARIES_ENABLED" \
  --argjson bmaxzoom "$BOUNDARIES_MAXZOOM" \
  --argjson water "$WATER_ENABLED" \
  --argjson wmaxzoom "$WATER_MAXZOOM" \
  --argjson transport "$TRANSPORT_ENABLED" \
  --argjson trmaxzoom "$TRANSPORT_MAXZOOM" \
  --argjson contours "$CONTOURS_ENABLED" \
  --argjson cmaxzoom "$CONTOURS_MAXZOOM" \
  --argjson rocks "$ROCKS_ENABLED" \
  --argjson rmaxzoom "$ROCKS_MAXZOOM" \
  --argjson cinterval "$CONTOUR_INTERVAL" \
  --argjson testkm2 "$TEST_KM2" \
  --arg testbbox "$TEST_BBOX" \
  --arg demsource "$CONTOURS_DEM_SOURCE" \
  --arg dem "$DEM_URL" \
  --argjson demmaxzoom "$DEM_MAXZOOM" \
  --arg demtilessource "$DEM_TILES_SOURCE" \
  --argjson terrain3d "$TERRAIN_3D" \
  --argjson terrainexag "$TERRAIN_EXAG" \
  --arg rockslope "$ROCK_SLOPE" \
  --arg rocksource "$ROCK_SOURCE" \
  '{
    default_region: $region,
    built_at: $built,
    maxzoom: $maxzoom,
    glyphs: $glyphs,
    sprite: $sprite,
    icon_sources: $icon_sources,
    default_icons: $icons,
    dem: $dem,
    dem_maxzoom: $demmaxzoom,
    # model výškových dlaždíc je hore pri `dem`, lebo dlaždice sú spoločné –
    # a nemusí to byť ten istý model ako pri vrstevniciach
    dem_source: $demtilessource,
    # 3D terén je hore pri `dem` z toho istého dôvodu; prevýšenie je zo štýlu,
    # nech si ho klient nemusí vymyslieť inak než pipeline
    terrain_3d: $terrain3d,
    terrain_exaggeration: $terrainexag,
    regions: {
      ($region): ({
        name: $name,
        bbox: ($bbox | split(",") | map(tonumber)),
        pmtiles: ("tiles/" + $region + ".pmtiles"),
        maxzoom: $maxzoom,
        size_mb: $size_mb
      }
      # rýchly test: mapa je celý región, ale vrstevnice, skaly a tieňovanie
      # len na tomto štvorci – viewer sa naň otvorí
      + (if $testkm2 > 0 and $testbbox != "" then {
        test_km2: $testkm2,
        test_bbox: ($testbbox | split(",") | map(tonumber))
      } else {} end)
      + (if $contours then {
        contours: ("tiles/" + $region + "-contours.pmtiles"),
        contours_maxzoom: $cmaxzoom,
        contour_interval: $cinterval
      } else {} end)
      # skaly majú vlastný .pmtiles aj maxzoom – vrstevnice sa dajú vypnúť
      # a skaly nechať
      + (if $rocks then {
        rocks: ("tiles/" + $region + "-rocks.pmtiles"),
        rocks_maxzoom: $rmaxzoom
      } else {} end)
      + (if $contours or $rocks then { dem_source: $demsource } else {} end)
      + (if $rockslope == "off" then {} else { rock_slope: ($rockslope | tonumber) } end)
      + (if $rocksource == "off" then {} else { rock_source: $rocksource } end)
      + (if $trails then {
        trails: ("tiles/" + $region + "-trails.pmtiles"),
        trails_maxzoom: $tmaxzoom,
        trail_count: $tcount
      } else {} end)
      # krajinné prvky, ktoré schéma OpenMapTiles nemá – vlastný .pmtiles
      + (if $features then {
        features: ("tiles/" + $region + "-features.pmtiles"),
        features_maxzoom: $fmaxzoom
      } else {} end)
      # body v krajine: druhý výstup toho istého jobu, preto vlastná položka,
      # ale ten istý maxzoom
      + (if $points then {
        points: ("tiles/" + $region + "-points.pmtiles"),
        points_maxzoom: $fmaxzoom
      } else {} end)
      # hranice území. `boundaries_maxzoom` tu musí byť: kto ho nenájde,
      # dosadí `maxzoom` mapy a nad skutočným stropom pýta neexistujúce
      # dlaždice – mená obcí ticho zmiznú
      + (if $boundaries then {
        boundaries: ("tiles/" + $region + "-boundaries.pmtiles"),
        boundaries_maxzoom: $bmaxzoom
      } else {} end)
      # vodstvo – ten istý dôvod pre `water_maxzoom` ako o riadok vyššie
      + (if $water then {
        water: ("tiles/" + $region + "-water.pmtiles"),
        water_maxzoom: $wmaxzoom
      } else {} end)
      # celá dopravná sieť. V manifeste je, hoci z nej štýl kreslí len
      # obmedzenia na ceste: manifest je zoznam toho, čo v mape je (číta ho
      # `subory.py` pri skladaní balíkov aj katalóg), nie toho, čo pýta štýl.
      # Bez nej by sa balík `cesty` skladal podľa mien súborov v `_site`.
      + (if $transport then {
        transport: ("tiles/" + $region + "-transport.pmtiles"),
        transport_maxzoom: $trmaxzoom
      } else {} end)
      # hranica regiónu – viewer ňou prekryje všetko za regiónom, lebo
      # dlaždice sú orezané len po celých dlaždiciach
      + (if $outline != "" then { outline: $outline } else {} end))
    }
  }' > _site/tiles/manifest.json
cat _site/tiles/manifest.json
