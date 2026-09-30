#!/usr/bin/env bash
# Download DEM tiles for a bbox from the Drive store and glue them into one VRT.
#
# `workers/dem/target.py` decides which store and files – `check-dem` asks it
# the same question and both must agree.
#
# Usage:
#   workers/dem/fetch.sh <bbox W,S,E,N> <directory> [tsv] [source] [cut-out key]
#
# The cut-out key switches the DMR 5.0 shape: contours and rocks pass it,
# hillshading doesn't; change those calls and `check-dem`'s layer table with them.
# Output: `<directory>/tiles/N49E019.tif …` and `<directory>/all.vrt`.
set -euo pipefail

BBOX="$1"
DIR="${2:-dem}"
STEPS_TSV="${3:-}"
SOURCE="${4:-sonny}"
AREA_KEY="${5:-whole}"
T0=$(date +%s)
HERE="$(dirname "$0")"
WORKERS="$(dirname "$HERE")"
STORE_PY="$WORKERS/drive/store.py"

TARGET=$(python3 "$HERE/target.py" \
  --source="$SOURCE" --area-key="$AREA_KEY" --bbox="$BBOX")
get() { printf '%s\n' "$TARGET" | sed -n "s/^$1=//p" | head -1; }
FORM=$(get form)
SRC_STORE=$(get store)
SRC_LABEL=$(get label)

# DMR 5.0 has two shapes decided by extent: a cut-out is full 1 m in `dem-ugkk`,
# a whole region 5 m tiles – a 1° tile at 1 m is ~48 GB, the runner has ~60 GB
if [ "$FORM" = "area" ]; then
  mkdir -p "$DIR"
  UASSET=$(get assets)
  if ! python3 "$STORE_PY" --get --store="$SRC_STORE" --name="$UASSET" \
        --dir="$DIR" --skip-local; then
    # code 3 = "not for this cut-out", so the caller can fall back
    echo "::warning::Store $SRC_STORE has no $UASSET – nobody has made DMR 5.0 for this cut-out yet. Run the workflow 'Data · DMR 5.0' with area: $AREA_KEY."
    exit 3
  fi
  gdalbuildvrt -q "$DIR/all.vrt" "$DIR/$UASSET"
  SIZE=$(du -h "$DIR/$UASSET" | cut -f1)
  echo "$SRC_LABEL from the store: $UASSET, $SIZE"
  gdalinfo "$DIR/$UASSET" | grep -E "Pixel Size|Size is" || true
  if [ -n "$STEPS_TSV" ]; then
    printf '%s\t%s\t%s\t%s\n' 20 "DEM (DMR 5.0, cut-out)" "$(( $(date +%s) - T0 ))" \
      "$UASSET from the store, $SIZE" >> "$STEPS_TSV"
  fi
  exit 0
fi

# downloaded tiles get their own subdirectory: intermediates are .tif too
mkdir -p "$DIR/tiles"

# 1°×1° tiles named by the south-west corner (the SRTM convention)
get assets | tr ' ' '\n' | sed '/^$/d' > "$DIR/list.txt"
WANT=$(wc -l < "$DIR/list.txt")
echo "DEM tiles for the bbox: $WANT"

# one call for all tiles; `--missing-ok` because the bbox's corners lie outside the country
set +e
python3 "$STORE_PY" --get --store="$SRC_STORE" --dir="$DIR/tiles" \
  --name="$(tr '\n' ' ' < "$DIR/list.txt")" --missing-ok --skip-local
SRC=$?
set -e

shopt -s nullglob
tifs=("$DIR"/tiles/*.tif)
have=${#tifs[@]}

if [ "$have" -eq 0 ]; then
  # code 3 = "no such model"; with Sonny there is nowhere to go back, a hard error
  echo "::warning::Store $SRC_STORE has not a single tile for this area (code $SRC)."
  echo "The Copernicus fallback is left out on purpose (a surface model with trees, not terrain)."
  if [ "$SOURCE" = "dmr5" ]; then
    echo "The job 'Refill DMR 5.0 (tiles)' should have filled them – see its log."
    echo "By hand: workflow 'Data · DMR 5.0', area: $(python3 "$HERE/target.py" --source=dmr5 --bbox="$BBOX" | sed -n 's/^degrees=//p'), tiles: true, grid 5 m."
  else
    echo "Run the workflow 'Data · elevation models' with a source covering this area."
  fi
  [ "$SOURCE" = "sonny" ] && exit 1
  exit 3
fi
if [ "$have" -lt "$WANT" ]; then
  # a visible hole beats filling from a surface model
  echo "::warning::Store $SRC_STORE lacks $(( WANT - have )) of $WANT tiles – no contours, rocks or hillshading there. If that area should have terrain, run 'Data · elevation models' with a folder covering it."
fi
echo "$SRC_LABEL: $have of $WANT tiles from store $SRC_STORE ✓"

# does it cover the area? a file count can't tell: tiles with a few hundred metres
# of data under a whole degree's name let gdal_contour through at 48 % of a region
COV="$DIR/coverage.txt"
set +e
# `--data-pct`: a tile with the right extent but almost no heights is reported
python3 "$HERE/coverage.py" --bbox="$BBOX" --dir="$DIR/tiles" \
  --min-pct="${DEM_MIN_COVER_PCT:-95}" \
  --data-pct="${DEM_MIN_DATA_PCT:-2}" --out="$COV"
COV_RC=$?
set -e
LIARS=$(sed -n 's/^liars=//p' "$COV" 2>/dev/null || true)
COV_PCT=$(sed -n 's/^covered_pct=//p' "$COV" 2>/dev/null || true)
COV_MISS=$(sed -n 's/^missing=//p' "$COV" 2>/dev/null || true)
COV_EMPTY=$(sed -n 's/^empty=//p' "$COV" 2>/dev/null || true)

# an empty degree counts as covered (it was read), but here it can be told up front
if [ -n "$COV_EMPTY" ]; then
  echo "The mosaic has empty degrees (read, no terrain in them): $COV_EMPTY"
  echo "  If one of them DOES have terrain, that is a bug – delete it from store $SRC_STORE and run the build again."
fi

# the store heals itself: while a dishonest tile lies there, the next check trusts it
for f in $LIARS; do
  echo "::warning::Tile $f in store $SRC_STORE didn't keep what its name promises (the reason is in the coverage listing above: it doesn't cover its whole degree, or it is an empty tile from a check we no longer trust). Deleting it from the store – the next run refills it whole (job 'Refill DMR 5.0 (tiles)')."
  python3 "$STORE_PY" --rm --store="$SRC_STORE" --name="$f" \
    || echo "  (couldn't delete it from the store – delete it on Drive by hand)"
  rm -f "$DIR/tiles/$f"
done
if [ -n "$LIARS" ]; then
  tifs=("$DIR"/tiles/*.tif)
  have=${#tifs[@]}
fi

if [ "$COV_RC" -ne 0 ]; then
  # enough tiles, too little area – for the caller the same as code 3; Sonny has no fallback
  echo "Area coverage $BBOX: ${COV_PCT:-0} % (at least ${DEM_MIN_COVER_PCT:-95} % wanted)"
  if [ "$SOURCE" = "sonny" ]; then
    echo "::warning::The Sonny mosaic covers only ${COV_PCT:-0} % of the area – missing degrees: ${COV_MISS:-?}. No terrain in the rest."
  else
    echo "::error::The $SRC_LABEL mosaic covers only ${COV_PCT:-0} % of the area (missing degrees: ${COV_MISS:-?}), so contours, rocks and hillshading would be missing in the rest of the region – and the map would look finished. If dishonest tiles were deleted above, just run the build again: it refills the missing ones. Otherwise refill them by hand (workflow 'Data · DMR 5.0', area: $(python3 "$HERE/target.py" --source="$SOURCE" --bbox="$BBOX" | sed -n 's/^degrees=//p'), tiles: true, grid 5 m) or pick a source covering the whole area."
    exit 3
  fi
fi
if [ "$have" -eq 0 ]; then
  echo "::error::No tile is left after dropping the dishonest ones – refill the model and run the build again."
  exit 3
fi

# `-resolution highest`: tiles may differ in grid (the 20 m model has rectangular pixels)
gdalbuildvrt -q -resolution highest "$DIR/all.vrt" "${tifs[@]}"
echo "DEM tiles available: ${#tifs[@]} → $DIR/all.vrt"

if [ -n "$STEPS_TSV" ]; then
  # the first field orders the summary – jobs run in parallel
  printf '%s\t%s\t%s\t%s\n' 20 "DEM tiles ($SRC_LABEL)" "$(( $(date +%s) - T0 ))" \
    "$have of $WANT tiles, $(du -sh "$DIR/tiles" | cut -f1)" >> "$STEPS_TSV"
fi
