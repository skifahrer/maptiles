#!/usr/bin/env bash
# Hillshading and 3D terrain: terrarium PNG or WebP tiles from the chosen elevation model.
#
# Cheapest first: the run's cache → the Drive store → computing.
#
# The asset name carries source, maxzoom and encoding shape
# (`terrain-<key>-<model>-z<maxzoom>-v<version>.pmtiles`), so a fix shows on a
# region already computed.
#
# Usage:
#   REGION_KEY=presovsky_kraj DEM_BBOX=20,49,21,50 SHADING_SOURCE=sonny \
#   TERRAIN_MAXZOOM=13 TERRAIN_STORE=dem-terrain GDRIVE_CREDENTIALS=… \
#   workers/terrain/build.sh
set -euo pipefail
: "${REGION_KEY:?region key}"
T_TER=$(date +%s)
TSRC="computed"
FELL_BACK=false
TZ="${TERRAIN_MAXZOOM:-}"
case "$TZ" in ''|*[!0-9]*) TZ=13 ;; esac
# a layer from the DEM, so it goes on `dem_bbox` – a square in a test
BBOX="${DEM_BBOX:?bbox for the DEM}"
TDEM="${SHADING_SOURCE:?hillshading source}"
# the hillshading budget: a share of the site budget, so fitting is decided up front
LIMIT_MB="${SIZE_LIMIT_MB:-900}"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TPCT="${BUDGET_TERRAIN_PCT:-12}"
case "$TPCT" in ''|*[!0-9]*) TPCT=12 ;; esac
TBUDGET_MB=$(( LIMIT_MB * TPCT / 100 ))
REBUILD="${TERRAIN_REBUILD:-false}"
FMT="${TERRAIN_FORMAT:-png}"
case "$FMT" in png|webp) ;; *) FMT=png ;; esac
BITS="${TERRAIN_FRAC_BITS:-auto}"
case "$BITS" in ''|*[!0-9]*) BITS=auto ;; esac

# the real maxzoom is known only after computing (the size cap may lower it),
# so the name is a function; the encoding shape is written once
ENC_VER=v7
# empty for the defaults, so assets already stored stay found
ENC_OPT=""
[ "$BITS" != auto ] && ENC_OPT="${ENC_OPT}-b${BITS}"
[ "$FMT" != png ] && ENC_OPT="${ENC_OPT}-${FMT}"
# the overlap with the neighbouring region changes the tiles, so it is in the name too
BORDER_M=$(python3 -c "import sys; sys.path.insert(0, 'workers/plan'); import area; print(int(area.BORDER_BUFFER_M))")
asset_name() { echo "terrain-${REGION_KEY}-${TDEM}-z${1}-${ENC_VER}${ENC_OPT}-o${BORDER_M}.pmtiles"; }

# done = a finished archive lies here; half a PNG tree is a non-empty folder too
have_tiles() { [ -s terrain-out/terrain.pmtiles ]; }

if [ "$REBUILD" = 'true' ]; then
  echo "terrain_rebuild=yes – tiles are computed anew."
  rm -rf terrain-out
elif have_tiles; then
  echo "Terrain tiles are in the run's cache ✓"
  TSRC="cache"
else
  # the highest stored zoom not above the wished one: a capped run stored exactly that
  HAVE_Z=$(python3 workers/drive/store.py --names --store="$TERRAIN_STORE" \
      2>/dev/null \
    | sed -n "s/^terrain-${REGION_KEY}-${TDEM}-z\([0-9]\+\)-${ENC_VER}${ENC_OPT}-o${BORDER_M}\.pmtiles$/\1/p" \
    | awk -v want="$TZ" '$1 <= want' | sort -n | tail -1)
  if [ -n "$HAVE_Z" ] && python3 workers/drive/store.py --get \
       --store="$TERRAIN_STORE" --name="$(asset_name "$HAVE_Z")" --dir=/tmp; then
    # `.pmtiles` isn't unpacked – it is the same file that goes to Pages
    mkdir -p terrain-out
    cp "/tmp/$(asset_name "$HAVE_Z")" terrain-out/terrain.pmtiles
    echo "$HAVE_Z" > terrain-out/maxzoom.txt
    echo "Terrain tiles downloaded from store $TERRAIN_STORE ✓ (z$HAVE_Z)"
    TSRC="store $TERRAIN_STORE"
  fi
fi

if ! have_tiles; then
  # its own job = its own DEM: contours run in parallel
  sudo apt-get update -qq
  sudo apt-get install -y -qq gdal-bin zstd
  python3 -m pip install --quiet numpy
  [ "$FMT" = webp ] && python3 -m pip install --quiet pillow
  # no cut-out key is passed, so `dmr5` means the 5 m tiles; code 3 = "no model here"
  set +e
  workers/dem/fetch.sh "$BBOX" "dem/$TDEM" steps-out/terrain.tsv "$TDEM"
  TRC=$?
  set -e
  if [ "$TRC" -eq 3 ]; then
    if [ "${OPT_UGKK_FALLBACK:-true}" != 'true' ]; then
      echo "::error::Model $TDEM for hillshading isn't available and ugkk_fallback is off. Fill it, turn the fallback on, or pick another shading_source."
      exit 1
    fi
    echo "::warning::Model $TDEM for hillshading isn't available – hillshading is computed from Sonny (20 m). The map will be there, with coarser relief, and the attribution will say Sonny."
    TDEM=sonny
    FELL_BACK=true
    # the file name carries the source (`asset_name` uses `TDEM`), so it fixes itself
    workers/dem/fetch.sh "$BBOX" "dem/$TDEM" steps-out/terrain.tsv "$TDEM"
  elif [ "$TRC" -ne 0 ]; then
    exit "$TRC"
  fi
  echo "::group::Terrain tiles to z$TZ from model $TDEM, $FMT, fraction bits $BITS (cap ${TBUDGET_MB} MB)"
  # `--poly` stops shading at the region's edge; without a polygon the whole bbox
  python3 workers/terrain/tiles.py --dem="dem/$TDEM/all.vrt" --bbox="$BBOX" \
    --poly=data/region.geojson \
    --minzoom=5 --maxzoom="$TZ" --budget-mb="$TBUDGET_MB" --out=terrain-png \
    --format="$FMT" --max-frac-bits="$([ "$BITS" = auto ] && echo -1 || echo "$BITS")"
  # `tiles.py` writes the maxzoom made – the size cap may have lowered it
  TZ=$(cat terrain-png/maxzoom.txt)
  # the PNG tree is only a step: one `.pmtiles` goes out (see `pack.py`)
  python3 -m pip install --quiet pmtiles
  mkdir -p terrain-out
  # `--clip-bbox`: the header says the run's area, not whole tiles (11.25° at z5)
  python3 workers/terrain/pack.py --in=terrain-png \
    --out=terrain-out/terrain.pmtiles --name="$REGION_KEY" --source="$TDEM" \
    --clip-bbox="$BBOX"
  echo "$TZ" > terrain-out/maxzoom.txt
  # tens of thousands of files for a region
  rm -rf terrain-png
  echo "::endgroup::"

  # store it so next time it isn't computed again; a failed save mustn't fail the run
  ASSET=$(asset_name "$TZ")
  cp terrain-out/terrain.pmtiles "/tmp/$ASSET"
  python3 workers/drive/store.py --put --store="$TERRAIN_STORE" \
      --file="/tmp/$ASSET" \
      --note="Terrarium PNG/WebP tiles from the elevation model as raster .pmtiles – one file per region, model and maxzoom (Build map)" \
    && echo "Saved to store $TERRAIN_STORE as $ASSET" \
    || echo "::warning::Terrain tiles couldn't be saved to store $TERRAIN_STORE – next time they will be computed again."
fi

TZ=$(cat terrain-out/maxzoom.txt 2>/dev/null || echo "$TZ")
# among the other `.pmtiles`: to the client the same thing as the map, only raster
mkdir -p _site/tiles
cp terrain-out/terrain.pmtiles "_site/tiles/${REGION_KEY}-terrain.pmtiles"
echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$TZ" >> "$GITHUB_OUTPUT"
# hillshading has its own choice, so this may differ from the contours' model
echo "dem_source=$TDEM" >> "$GITHUB_OUTPUT"
# after falling back to Sonny, the original model's cache key mustn't get these tiles
echo "fell_back=$FELL_BACK" >> "$GITHUB_OUTPUT"
TER_MB=$(du -sm "_site/tiles/${REGION_KEY}-terrain.pmtiles" | cut -f1)
echo "Terrain tiles: raster .pmtiles ($FMT, fraction bits $BITS) to z$TZ from model $TDEM, ${TER_MB} MB"
printf '%s\t%s\t%s\t%s\n' "60" "Hillshading and 3D terrain" "$(( $(date +%s) - T_TER ))" \
  "raster .pmtiles ($FMT, bits $BITS) to z$TZ from $TDEM, ${TER_MB} MB ($TSRC)" \
  >> steps-out/terrain.tsv
