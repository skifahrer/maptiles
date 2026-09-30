#!/usr/bin/env bash
# Finished contours and rocks from `contours-out/` into `_site/`, plus outputs for the style.
#
# Two jobs (`contours` and `rocks`) share this step. Values come from what was
# really made (`contours-out/*.txt`): maxzoom may have dropped for size and the
# model may have fallen back to Sonny.

set -euo pipefail
mkdir -p _site/tiles
KEY="$REGION_KEY"

# which half: `build.sh` got the same `ONLY`, so a missing other half isn't a fault
ONLY="${ONLY:-all}"
case "$ONLY" in
  contours|rocks|all) ;;
  *) echo "::error::ONLY must be 'contours', 'rocks' or 'all' (got '$ONLY')."; exit 1 ;;
esac
# what this job should have made; nobody expects a layer that is off
WANT_CONTOURS=false; [ "$ONLY" != 'rocks' ] && [ "$OPT_CONTOUR_LINES" = 'true' ] && WANT_CONTOURS=true
WANT_ROCKS=false;    [ "$ONLY" != 'contours' ] && [ "$OPT_ROCKS" = 'true' ] && WANT_ROCKS=true

# rocks: their own .pmtiles and maxzoom, deployable without contours (and back)
RPM=contours-out/rocks.pmtiles
RZ=$(cat contours-out/rock-maxzoom.txt 2>/dev/null || echo '')
case "$RZ" in ''|*[!0-9]*) RZ="$OPT_ROCK_MAXZOOM" ;; esac
case "$RZ" in ''|*[!0-9]*) RZ=16 ;; esac
if [ "$RZ" -gt 16 ]; then RZ=16; fi
# an empty layer from a failure can't be told on the map from a region without rocks
FAILED=false
if [ -s contours-out/rock-failed.txt ]; then
  FAILED=true
fi
if [ "$OPT_ROCKS" = 'true' ] && [ "$FAILED" != 'true' ] && [ -s "$RPM" ]; then
  cp "$RPM" "_site/tiles/$KEY-rocks.pmtiles"
  echo "rocks_enabled=true" >> "$GITHUB_OUTPUT"
  echo "Rocks to z$RZ, $(du -h "$RPM" | cut -f1)"
else
  echo "rocks_enabled=false" >> "$GITHUB_OUTPUT"
  if [ "$FAILED" = 'true' ]; then
    echo "::warning::The rock computation failed – the map and the \`contours-rocks\` package go with contours only. The reason is in the Rocks job's log; the next run computes them again."
  elif [ "$WANT_ROCKS" = 'true' ]; then
    echo "::warning::No rocks were made – the map goes without them."
  fi
fi
echo "rocks_maxzoom=$RZ" >> "$GITHUB_OUTPUT"

# contours
SRC=contours-out/contours.pmtiles
if [ -s "$SRC" ]; then
  cp "$SRC" "_site/tiles/$KEY-contours.pmtiles"
  # maxzoom from what was really made (it may have dropped for size)
  CZ=$(cat contours-out/maxzoom.txt 2>/dev/null || echo '')
  case "$CZ" in ''|*[!0-9]*) CZ="$OPT_CONTOUR_MAXZOOM" ;; esac
  case "$CZ" in ''|*[!0-9]*) CZ=14 ;; esac
  if [ "$CZ" -gt 16 ]; then CZ=16; fi
  # `enabled` is about contours, not the file: with `none` the .pmtiles is there, empty
  if [ "$OPT_CONTOUR_LINES" = 'true' ]; then
    echo "enabled=true" >> "$GITHUB_OUTPUT"
  else
    echo "enabled=false" >> "$GITHUB_OUTPUT"
  fi
  echo "maxzoom=$CZ" >> "$GITHUB_OUTPUT"
else
  CZ=''
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  [ "$WANT_CONTOURS" = 'true' ] \
    && echo "::warning::No contours were made – the map goes without them."
fi

# for both halves: written always, deploy builds the manifest from them
DEM_USED=$(cat contours-out/dem-source.txt 2>/dev/null || echo '')
# keys must match `dem-sources.json`, or the attribution names another model
case "$DEM_USED" in sonny|dmr35|dmr5) ;; *) DEM_USED=sonny ;; esac
RSLOPE=$(cat contours-out/rock-slope.txt 2>/dev/null || echo off)
RSRC=$(cat contours-out/rock-source.txt 2>/dev/null || echo off)
case "$RSRC" in sonny|dmr35|dmr5|shading) ;; tienovanie) RSRC=shading ;; *) RSRC=off ;; esac
echo "dem_source=$DEM_USED" >> "$GITHUB_OUTPUT"
echo "rock_slope=$RSLOPE" >> "$GITHUB_OUTPUT"
echo "rock_source=$RSRC" >> "$GITHUB_OUTPUT"
# the size of the layer this job really made
MEASURED="$SRC"; [ "$ONLY" = 'rocks' ] && MEASURED="$RPM"
if [ -s "$MEASURED" ]; then
  echo "size_mb=$(( $(stat -c%s "$MEASURED") / 1048576 ))" >> "$GITHUB_OUTPUT"
else
  echo "size_mb=0" >> "$GITHUB_OUTPUT"
fi
[ -n "$CZ" ] && echo "Contours to z$CZ, heights: $DEM_USED, rocks: $RSLOPE"
ls -lh _site/tiles/
# a cache hit skipped the computation – the summary gets a line anyway
if [ "$CACHE_HIT" = 'true' ]; then
  case "$ONLY" in
    rocks) LABEL="rocks from the cache (nothing computed), maxzoom $RZ" ;;
    *)     LABEL="contours from the cache (nothing computed), maxzoom ${CZ:-?}" ;;
  esac
  [ -s "$MEASURED" ] && LABEL="$LABEL, $(du -h "$MEASURED" | cut -f1)"
  printf '%s\t%s\t%s\t%s\n' "50" "Contours and rocks" "0" "$LABEL" \
    >> steps-out/contours.tsv
fi
