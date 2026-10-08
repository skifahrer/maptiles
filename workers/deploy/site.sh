#!/usr/bin/env bash
# Viewer + `manifest.json` into `_site/` – the last step before Pages.
#
# The manifest is the one file saying what this build holds; a layer that
# wasn't on is absent, not empty ("there, just empty" is another claim).
set -euo pipefail
# all of `poc/web/`, not a list that drifts from the folder (workers/lint/viewer.py)
cp poc/web/*.js poc/web/*.json poc/web/index.html _site/

# the outline is optional; `if`, not a test chain, or `set -e` trips on the last `&&`
OUTLINE="${REGION_OUTLINE:-}"
if [ -n "$OUTLINE" ] && [ ! -s "_site/$OUTLINE" ]; then
  echo "::warning::The region outline (_site/$OUTLINE) wasn't made – the map goes without it and reaches beyond the region."
  OUTLINE=""
fi

BASE="${BASE_URL%/}"
if [ -d _site/fonts ] && [ -n "$(ls -A _site/fonts)" ]; then
  GLYPHS="$BASE/fonts/{fontstack}/{range}.pbf"
else
  GLYPHS="https://fonts.openmaptiles.org/{fontstack}/{range}.pbf"
fi

# icon sets for the switch, only those really built – a missing sprite is an empty switch
ICON_SOURCES=$(node -e "
  Promise.all([
    import('./poc/web/icon-sources.js'),
    import('./poc/web/themes.js'),
    import('node:fs')
  ]).then(([ic, th, fs]) => {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync('poc/web/style-overrides.json', 'utf8')); } catch {}
    const ok = (process.env.ICONS_AVAILABLE || '').split(/\\s+/).filter(Boolean);
    const every = ic.allIconSources(th.normalizeOverrides(raw).overrides);
    console.log(JSON.stringify(every.filter((s) => ok.includes(s.id))
      .map((s) => ({ id: s.id, label: s.label, sprite: 'sprites/' + s.id,
                     license: s.license, source: s.source, suffix: s.suffix, note: s.note }))));
  });
")

# 3D terrain? the finished style answers, not the switch; the app offers "3D terrain" by it
TERRAIN_3D=false
TERRAIN_EXAG=0
if [ -d _site/styles ]; then
  # several styles (map type × theme), any one will do
  read -r TERRAIN_3D TERRAIN_EXAG <<<"$(jq -rs '
    [.[] | .terrain // empty]
    | if length > 0
      then "true \((.[0].exaggeration) // 1)"
      else "false 0" end' _site/styles/*.json 2>/dev/null || echo "false 0")"
  case "$TERRAIN_3D" in true|false) ;; *) TERRAIN_3D=false; TERRAIN_EXAG=0 ;; esac
fi
echo "3D terrain in the style: $TERRAIN_3D (exaggeration $TERRAIN_EXAG×)"

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
  --argjson rail "${RAIL_ENABLED:-false}" \
  --argjson railmaxzoom "${RAIL_MAXZOOM:-15}" \
  --argjson history "${HISTORY_ENABLED:-false}" \
  --argjson histmaxzoom "${HISTORY_MAXZOOM:-14}" \
  --argjson railrouting "${RAIL_ROUTING:-false}" \
  --argjson buildings "${BUILDINGS_ENABLED:-false}" \
  --argjson bldmaxzoom "${BUILDINGS_MAXZOOM:-14}" \
  --argjson railsigns "$(find _site/tiles -maxdepth 1 -name "${REGION_KEY}-signs*" 2>/dev/null | sed 's|^_site/||' | sort | jq -R . | jq -s .)" \
  --argjson transport "$TRANSPORT_ENABLED" \
  --argjson trmaxzoom "$TRANSPORT_MAXZOOM" \
  --argjson routing "$ROUTING_ENABLED" \
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
    # height tiles are shared, so their model sits at `dem`, maybe not the one of the contours
    dem_source: $demtilessource,
    # exaggeration from the style, so the client never invents another
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
      # quick test: terrain only on this square, the viewer opens on it
      + (if $testkm2 > 0 and $testbbox != "" then {
        test_km2: $testkm2,
        test_bbox: ($testbbox | split(",") | map(tonumber))
      } else {} end)
      + (if $contours then {
        contours: ("tiles/" + $region + "-contours.pmtiles"),
        contours_maxzoom: $cmaxzoom,
        contour_interval: $cinterval
      } else {} end)
      # rocks have their own archive and maxzoom – contours can be off
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
      # landscape features OpenMapTiles lacks – their own archive
      + (if $features then {
        features: ("tiles/" + $region + "-features.pmtiles"),
        features_maxzoom: $fmaxzoom
      } else {} end)
      # points: second output of the same job, so the same maxzoom
      + (if $points then {
        points: ("tiles/" + $region + "-points.pmtiles"),
        points_maxzoom: $fmaxzoom
      } else {} end)
      # without `boundaries_maxzoom` a client asks past the cap and names vanish
      + (if $boundaries then {
        boundaries: ("tiles/" + $region + "-boundaries.pmtiles"),
        boundaries_maxzoom: $bmaxzoom
      } else {} end)
      # the same reason for `water_maxzoom`
      + (if $water then {
        water: ("tiles/" + $region + "-water.pmtiles"),
        water_maxzoom: $wmaxzoom
      } else {} end)
      + (if $rail then {
        rail: ("tiles/" + $region + "-rail.pmtiles"),
        rail_maxzoom: $railmaxzoom
      } else {} end)
      # track network for train routing
      + (if $rail and $railrouting then {
        rail_routing: ("tiles/" + $region + "-rail-routing.pmtiles")
      } else {} end)
      + (if $history then {
        history: ("tiles/" + $region + "-history.pmtiles"),
        history_maxzoom: $histmaxzoom
      } else {} end)
      + (if $buildings then {
        buildings: ("tiles/" + $region + "-buildings.pmtiles"),
        buildings_maxzoom: $bldmaxzoom
      } else {} end)
      # rail and road signs of the country – a sprite the app reads itself
      + (if $railsigns != [] then { rail_signs: $railsigns } else {} end)
      # the manifest lists what the map holds (files.py packs by it), not what the style asks
      + (if $transport then {
        transport: ("tiles/" + $region + "-transport.pmtiles"),
        transport_maxzoom: $trmaxzoom
      } else {} end)
      # routing network; `routing_zoom` is fixed z9, but a client has no other way to know the grid
      + (if $routing then {
        routing: ("tiles/" + $region + "-routing.pmtiles"),
        routing_zoom: 9
      } else {} end)
      # tiles are cut per whole tile, so the viewer masks beyond the outline
      + (if $outline != "" then { outline: $outline } else {} end))
    }
  }' > _site/tiles/manifest.json
cat _site/tiles/manifest.json
