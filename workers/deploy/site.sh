#!/usr/bin/env bash
# Viewer + `manifest.json` do `_site/` – posledný krok pred nasadením na Pages.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map.yml` má strop 500 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov"). Tento blok bol jeho druhý najväčší
# (109 riadkov, z toho 30 riadkov `jq --arg`).
#
# ČO JE MANIFEST. Jediný súbor, z ktorého viewer (web aj iOS) zistí, čo v tomto
# builde vôbec je: ktoré vrstvy vznikli, po aký zoom siahajú, z akého výškového
# modelu sú a kde ležia ich `.pmtiles`. Vrstva, ktorá v behu nebola zapnutá
# (alebo jej job spadol), v manifeste jednoducho NIE JE a viewer ju nekreslí –
# preto sú všetky položky regiónu podmienené (`if $trails then … else {} end`)
# a nie vypĺňané prázdnymi hodnotami. Prázdna hodnota by znamenala „vrstva je,
# len je prázdna", a to je iné tvrdenie.
set -euo pipefail
# CELÝ `poc/web/`, nie vymenovaný zoznam. Zoznam tu bol a rozišiel sa
# s priečinkom v ten deň, keď pribudol `layer-style.js`: súbor je
# v repozitári, do `_site` ho nikto neskopíroval a `devmode.js` si ho
# importuje. Modulový graf tým padol celý – prehliadač nenačíta `app.js`,
# mapa sa vôbec nevykreslí a NIKTO nič nepovie: build je zelený, `_site`
# prejde kontrolou (tá pozerá na štýly a dlaždice, nie na moduly) aj smoke
# test. Priečinok je celý viewer a nič iné, takže „skopíruj ho" je jediná
# odpoveď, ktorá sa nemá ako rozísť s tým, čo si viewer naozaj pýta
# (pravidlo 1). Stráži to `workers/lint/viewer.py`.
cp poc/web/*.js poc/web/*.json poc/web/index.html _site/

# Hranica regiónu (`_site/region.geojson`) je voliteľná: keď sa v `plan`
# nestiahol polygón, mapa ide bez nej – a v manifeste vtedy nesmie byť.
# (`set -e`: `[ … ] && …` na konci by pri prázdnej hodnote zhodilo skript,
# preto `if` a nie reťazec testov.)
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

# Zoznam sád ikoniek pre prepínač vo vieweri. Berie sa z toho istého
# `icon-sources.js`, z ktorého ich sťahoval job `assets` – zoznam mien tu nemá
# byť napísaný druhýkrát. Filtruje sa na tie, čo naozaj vznikli
# (`ICONS_AVAILABLE`): stiahnutie sady z cudzieho servera môže zlyhať
# a chýbajúci sprite by vo vieweri bol prázdny prepínač.
# Vlastné sady z úprav developer módu (`overrides.iconSets`) sú v tom
# zozname tiež: pipeline ich sťahuje a prerába rovnako, takže by bolo zvláštne,
# keby sa dali pridať, ale viewer by o nich nevedel.
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
  --argjson roads "$ROADS_ENABLED" \
  --argjson rdmaxzoom "$ROADS_MAXZOOM" \
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
    # Model, z ktorého sú výškové dlaždice. Je hore pri `dem`
    # a nie pri regióne, lebo dlaždice sú tiež spoločné – a nemusí
    # to byť ten istý model ako pri vrstevniciach (`dem_source`
    # v regióne), odkedy má tieňovanie vlastný výber.
    dem_source: $demtilessource,
    regions: {
      ($region): ({
        name: $name,
        bbox: ($bbox | split(",") | map(tonumber)),
        pmtiles: ("tiles/" + $region + ".pmtiles"),
        maxzoom: $maxzoom,
        size_mb: $size_mb
      }
      # Rýchly test (switch `test`): mapa je celý región, ale
      # vrstevnice, skaly a tieňovanie sú len na tomto štvorci.
      # Viewer sa naň otvorí a napíše to do panelu – bez toho by
      # sa pár km² skál v kraji hľadalo očami.
      + (if $testkm2 > 0 and $testbbox != "" then {
        test_km2: $testkm2,
        test_bbox: ($testbbox | split(",") | map(tonumber))
      } else {} end)
      + (if $contours then {
        contours: ("tiles/" + $region + "-contours.pmtiles"),
        contours_maxzoom: $cmaxzoom,
        contour_interval: $cinterval
      } else {} end)
      # Skaly majú vlastný .pmtiles a vlastný maxzoom, takže sú
      # v manifeste vlastnou položkou – vrstevnice sa dajú vypnúť
      # a skaly nechať.
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
      # Krajinné prvky, ktoré schéma OpenMapTiles nemá – vlastný
      # .pmtiles, takže aj vlastná položka a vlastný prepínač.
      + (if $features then {
        features: ("tiles/" + $region + "-features.pmtiles"),
        features_maxzoom: $fmaxzoom
      } else {} end)
      # Obmedzenia na ceste – vlastný .pmtiles, takže vlastná položka
      # a vlastný prepínač. `roads_maxzoom` tu MUSÍ byť: kto ho nenájde,
      # dosadí `maxzoom` mapy (16) a nad skutočným stropom pýta neexistujúce
      # dlaždice – štítky s výškou ticho zmiznú a vyzerá to ako pokazené
      # ťuknutie do mapy, nie ako chýbajúce dáta.
      + (if $roads then {
        roads: ("tiles/" + $region + "-roads.pmtiles"),
        roads_maxzoom: $rdmaxzoom
      } else {} end)
      # Hranica stiahnutého regiónu. Viewer podľa nej prekryje všetko za
      # regiónom – dlaždice sú orezané len po celých dlaždiciach, takže bez
      # nej mapa presahuje. Keď súbor nevznikol, položka NIE JE (a nie je
      # prázdna): „hranica je, len prázdna" je iné tvrdenie než „nie je".
      + (if $outline != "" then { outline: $outline } else {} end))
    }
  }' > _site/tiles/manifest.json
cat _site/tiles/manifest.json
