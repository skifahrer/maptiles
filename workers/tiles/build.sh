#!/usr/bin/env bash
# PBF → `{region}.pmtiles` with Planetiler, within a size budget; a fixed share of the page,
# `deploy` checks the total. With `auto_shrink` the zoom drops and it runs again.

set -euo pipefail
T_TILES=$(date +%s)
mkdir -p _site/tiles
OUT="_site/tiles/${REGION_KEY}.pmtiles"

# above 16 Planetiler fails with "Max zoom must be <= 16"
MAXZOOM="$OPT_MAXZOOM"
case "$MAXZOOM" in ''|*[!0-9]*) MAXZOOM=16 ;; esac
if [ "$MAXZOOM" -gt 16 ]; then
  echo "::warning::Planetiler makes tiles up to zoom 16 at most (given: $MAXZOOM). Using 16 – MapLibre overzoom takes it to z20."
  MAXZOOM=16
fi
if [ "$MAXZOOM" -lt 8 ]; then MAXZOOM=8; fi

# the other layers are built in parallel jobs, so tiles get what the shares leave
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
OTHERS_MB=$(( LIMIT_MB * (BUDGET_CONTOURS_PCT + BUDGET_TERRAIN_PCT + BUDGET_TRAILS_PCT + BUDGET_FEATURES_PCT + BUDGET_TRANSPORT_PCT + BUDGET_BOUNDARIES_PCT + BUDGET_WATER_PCT + ${BUDGET_RAIL_PCT:-0} + ${BUDGET_HISTORY_PCT:-0} + ${BUDGET_BUILDINGS_PCT:-0}) / 100 + BUDGET_ASSETS_MB ))
BUDGET_MB=$(( LIMIT_MB - OTHERS_MB ))
echo "Page budget ${LIMIT_MB} MB − contours ${BUDGET_CONTOURS_PCT} % − terrain ${BUDGET_TERRAIN_PCT} % − trails ${BUDGET_TRAILS_PCT} % − landscape features ${BUDGET_FEATURES_PCT} % − transport ${BUDGET_TRANSPORT_PCT} % − boundaries ${BUDGET_BOUNDARIES_PCT} % − water ${BUDGET_WATER_PCT} % − railways ${BUDGET_RAIL_PCT:-0} % − army and history ${BUDGET_HISTORY_PCT:-0} % − settlements ${BUDGET_BUILDINGS_PCT:-0} % − icons and fonts ${BUDGET_ASSETS_MB} MB = ${BUDGET_MB} MB for tiles"

if [ "$BUDGET_MB" -lt 50 ]; then
  echo "::error::Only ${BUDGET_MB} MB are left for tiles. Raise size_limit_mb or cut the contour and terrain shares (BUDGET_*_PCT in env)."
  exit 1
fi
LIMIT=$(( BUDGET_MB * 1024 * 1024 ))

# Planetiler's ~515 MB of foreign sources in their own retried step: `http_retries`
# doesn't cover a server unreachable at the size check
DL_TRIES=3
for i in $(seq 1 "$DL_TRIES"); do
  echo "::group::Planetiler sources (attempt $i of $DL_TRIES)"
  if java -Xmx2g -jar planetiler.jar \
      --osm-path=data/region.osm.pbf \
      --download --only-download --download-dir=data/sources \
      --http_timeout=120s --http_retries=10 --http_retry_wait=10s; then
    echo "::endgroup::"
    DL_OK=1
    break
  fi
  echo "::endgroup::"
  if [ "$i" -lt "$DL_TRIES" ]; then
    echo "::warning::Planetiler sources didn't download (attempt $i of $DL_TRIES) – retrying in $(( i * 30 )) s."
    sleep $(( i * 30 ))
  fi
done
if [ -z "${DL_OK:-}" ]; then
  echo "::error::Planetiler source data (water polygons, Natural Earth, lake centerlines) couldn't be downloaded in $DL_TRIES attempts. Usually https://osmdata.openstreetmap.de is down – try the run again shortly. If it persists, give Planetiler a mirror via --water_polygons_url."
  exit 1
fi
du -sh data/sources 2>/dev/null || true

# without the cut Planetiler draws water and Natural Earth far beyond the region
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

source workers/lib/languages.sh

# Planetiler's defaults drop sub-pixel detail at max zoom; overzoom past z16 shows it
DETAIL=(--min_feature_size_at_max_zoom=0 --simplify_tolerance_at_max_zoom=0)
if [ "${OPT_MAP_SIMPLIFY:-true}" = true ]; then DETAIL=(); fi
HN_MIN="${OPT_HOUSENUMBER_MINZOOM:-16}"
case "$HN_MIN" in ''|*[!0-9]*) HN_MIN=14 ;; esac
if [ "$HN_MIN" -gt 14 ]; then python3 -m pip install --quiet pmtiles; fi

Z=$MAXZOOM
while : ; do
  echo "::group::Planetiler – maxzoom $Z"
  java -Xmx5g -jar planetiler.jar \
    --osm-path=data/region.osm.pbf \
    --output="$OUT" \
    --download --download-dir=data/sources \
    "${CLIP[@]}" \
    --minzoom=0 \
    --maxzoom="$Z" \
    --render_maxzoom="$Z" \
    "${DETAIL[@]}" \
    --transportation_z13_paths=true \
    --building_merge_z13=false \
    --languages="$TILE_LANGUAGES" \
    --http_timeout=120s --http_retries=10 --http_retry_wait=10s \
    --force
  echo "::endgroup::"
  # OpenMapTiles has no per-layer min zoom, so the low house numbers go afterwards
  if [ "$HN_MIN" -gt 14 ]; then
    python3 workers/tiles/drop-layer.py --in="$OUT" --out="$OUT" \
      --layer=housenumber --below="$HN_MIN"
  fi

  # the region ends in the tiles, not in the style
  workers/lib/clip-tiles.sh "$OUT"

  BYTES=$(stat -c%s "$OUT")
  MB=$(( BYTES / 1048576 ))
  echo "maxzoom $Z → ${MB} MB (${BUDGET_MB} MB for tiles)"

  if [ "$BYTES" -le "$LIMIT" ]; then break; fi

  if [ "$OPT_AUTO_SHRINK" != 'true' ] || [ "$Z" -le 12 ]; then
    echo "::error::Tiles take ${MB} MB but must fit ${BUDGET_MB} MB (page budget ${LIMIT_MB} MB minus the contour, terrain and icon shares). Options: lower maxzoom, pick a smaller region, use crop_bbox or cut contours via BUDGET_CONTOURS_PCT."
    exit 1
  fi

  # a zoom less is ~3.5× smaller; up to two at once, not three hour-long runs
  DROP=1
  EST=$MB
  while [ "$DROP" -lt 2 ] && [ $(( EST * 10 / 35 )) -gt "$BUDGET_MB" ]; do
    EST=$(( EST * 10 / 35 ))
    DROP=$(( DROP + 1 ))
  done
  NEXT=$(( Z - DROP ))
  if [ "$NEXT" -lt 12 ]; then NEXT=12; fi
  echo "::warning::${MB} MB is over the ${BUDGET_MB} MB budget – trying maxzoom ${NEXT}."
  Z=$NEXT
done

echo "maxzoom=$Z" >> "$GITHUB_OUTPUT"
echo "size_mb=$(( $(stat -c%s "$OUT") / 1048576 ))" >> "$GITHUB_OUTPUT"
ls -lh _site/tiles/
printf '%s\t%s\t%s\t%s\n' "70" "Map tiles (Planetiler)" "$(( $(date +%s) - T_TILES ))" \
  "maxzoom $Z, $(( $(stat -c%s "$OUT") / 1048576 )) MB, simplify ${OPT_MAP_SIMPLIFY:-true}, house numbers from z$HN_MIN" \
  >> steps-out/tiles.tsv
