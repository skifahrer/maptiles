#!/usr/bin/env bash
# Contours and rock areas from elevation models → contours-out/contours.pmtiles.
#
# Values from the form and the plan come through the environment (see the step
# "Contours and rocks from the DEM"), plus the workflow's `env:` and Drive sign-in.

set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq gdal-bin libsqlite3-mod-spatialite zstd
python3 -m pip install --quiet numpy
# `work/` holds intermediates (gigabytes) outside the cached `dem/`; `slope-chunks/`
# keeps slope parts so a cancelled run doesn't lose an hour of Drive reading
SLOPE_DIR="${SLOPE_DIR:-slope-chunks}"
mkdir -p dem data work contours-out "$SLOPE_DIR"

BBOX="$REGION_BBOX"
IFS=, read -r W S E N <<< "$BBOX"

# cut to the region polygon: the data's edge is a wall to `gdaldem slope`, false rocks
CUT=()
if [ -s data/region.geojson ]; then
  CUT=(-cutline data/region.geojson)
  echo "Region clip: data/region.geojson (nodata outside the region)"
else
  echo "::warning::No region polygon (data/region.geojson) – the whole region bbox is computed, outside the region too. Beyond Slovakia DMR 5.0 is empty and the data's edge makes false rocks."
fi
INTERVAL="$CONTOUR_INTERVAL"
case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=10 ;; esac

# the plan resolved the cut-out (`workers/plan/area.py`)
AREA_KEY="$AREA_KEY_IN"
AREA_NAME="$AREA_NAME_IN"
AREA_BBOX="$AREA_BBOX_IN"
if [ "$AREA_KEY" != "whole" ]; then
  echo "::warning::Contours and rocks are computed ONLY on the cut-out \"$AREA_NAME\" ($AREA_BBOX, ${AREA_KM2} km²). The rest of the region gets none of them – this run is for testing, not deploying. For the whole region pick \"whole_region\" for the \"area\" input."
  IFS=, read -r W S E N <<< "$AREA_BBOX"
fi

# two jobs, one script: both halves stand on the same cut-out, DEM and budget
ONLY="${ONLY:-all}"
case "$ONLY" in
  contours) OPT_ROCK_DEM=""; OPT_ROCKS=false ;;
  rocks)    OPT_CONTOUR_LINES=false ;;
  all)      ;;
  *) echo "::error::ONLY must be 'contours', 'rocks' or 'all' (got '$ONLY')."; exit 1 ;;
esac
echo "This half: $ONLY"

# contours and rocks have their own source choice, so two models may be here;
# tiled models are fetched for the whole region, ÚGKK by cut-out
fetch_dem() { # $1 = source → DEM_VRT, DEM_GOT (what was REALLY used)
  local src="$1" fbbox rc
  if [ -s "dem/$src/all.vrt" ]; then
    DEM_VRT="dem/$src/all.vrt"; DEM_GOT="$src"
    echo "DEM $src: the mosaic is here ✓"
    return 0
  fi
  # DMR 5.0 for a cut-out is one COG for exactly that cut-out
  if [ "$src" = 'dmr5' ] && [ "$AREA_KEY_IN" != 'whole' ]; then
    fbbox="$AREA_BBOX"
  else
    fbbox="$BBOX"
  fi
  set +e
  workers/dem/fetch.sh "$fbbox" "dem/$src" steps-out/contours.tsv \
    "$src" "$AREA_KEY_IN"
  rc=$?
  set -e
  if [ "$rc" -eq 3 ]; then
    # no such model for this area; never silent – `dem-source.txt` says what was used
    local how
    if [ "$src" = 'dmr5' ] && [ "$AREA_KEY_IN" != 'whole' ]; then
      how="workflow 'Data · DMR 5.0' with area: $AREA_KEY_IN"
    elif [ "$src" = 'dmr5' ]; then
      how="workflow 'Data · DMR 5.0' with area: whole_country"
    else
      how="workflow 'Data · elevation models' with source $src"
    fi
    if [ "$OPT_UGKK_FALLBACK" != 'true' ]; then
      echo "::error::Model $src isn't available for this area and ugkk_fallback is off. Fill it ($how), turn the fallback on, or pick another source."
      exit 1
    fi
    echo "::warning::Model $src isn't available for this area – computing from Sonny (20 m). The map will be there, with a coarser model. $how fills it."
    fetch_dem sonny
    return 0
  elif [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  DEM_VRT="dem/$src/all.vrt"; DEM_GOT="$src"
}

# raster size and cell count tell minutes from an hour, before the first gdalwarp
dem_info() { # $1 = label, $2 = mosaic
  echo "── Input DEM: $1 ──────────────────────────────"
  gdalinfo "$2" 2>/dev/null \
    | grep -E "^Size is|^Pixel Size|^Upper Left|^Lower Right" || true
  python3 - "$W" "$S" "$E" "$N" "$2" <<'PY'
import json, math, subprocess, sys
w, s, e, n = map(float, sys.argv[1:5])
try:
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", sys.argv[5]],
        capture_output=True, text=True, check=True).stdout)
    gt = info["geoTransform"]
    dx, dy = abs(gt[1]), abs(gt[5])
    cells = ((e - w) / dx) * ((n - s) / dy)
    lat = (s + n) / 2
    print(f"  cut-out      {e-w:.3f}° × {n-s:.3f}°  "
          f"(~{(e-w)*111.32*math.cos(math.radians(lat)):.0f} × "
          f"{(n-s)*110.54:.0f} km)")
    print(f"  DEM cell     {dx*111320*math.cos(math.radians(lat)):.0f} × "
          f"{dy*110540:.0f} m")
    print(f"  cells        {cells/1e6:.1f} M")
except Exception as exc:
    print(f"  (size unknown: {exc})")
PY
  echo "─────────────────────────────────────────────────────"
}

# `opt_rock_dem` is empty when rocks come from hillshading or are off
CONTOUR_SRC="$OPT_CONTOUR_SOURCE"
ROCK_DEM="$OPT_ROCK_DEM"
CONTOUR_VRT=""; CONTOUR_DEM=""
ROCK_VRT=""; ROCK_DEM_USED=""

if [ "$OPT_CONTOUR_LINES" = 'true' ]; then
  fetch_dem "$CONTOUR_SRC"
  CONTOUR_VRT="$DEM_VRT"; CONTOUR_DEM="$DEM_GOT"
  dem_info "contours ($CONTOUR_DEM)" "$CONTOUR_VRT"
fi
if [ -n "$ROCK_DEM" ]; then
  # DMR 5.0 isn't downloaded whole for rocks: the slope reads it from Drive in chunks
  if [ "$ROCK_DEM" = 'dmr5' ]; then
    ROCK_VRT=""; ROCK_DEM_USED=dmr5
    echo "Rock DEM (dmr5): read from Drive in chunks, not downloaded whole"
  else
    fetch_dem "$ROCK_DEM"
    ROCK_VRT="$DEM_VRT"; ROCK_DEM_USED="$DEM_GOT"
    [ "$ROCK_VRT" = "$CONTOUR_VRT" ] \
      || dem_info "rocks ($ROCK_DEM_USED)" "$ROCK_VRT"
  fi
fi

T_CONT=$(date +%s)

make_empty_gpkg() { # $1 = file, $2 = layer, $3 = geometry type
  # the schema always refers to both layers, so the file must exist when a layer is off
  echo '{"type":"FeatureCollection","features":[]}' > work/empty.geojson
  ogr2ogr -f GPKG "$1" work/empty.geojson -nln "$2" -overwrite \
    -nlt "$3" -a_srs EPSG:4326 -lco GEOMETRY_NAME=geom
}

if [ "$OPT_CONTOUR_LINES" != 'true' ]; then
  echo "Contours: off (contour_source: none) – empty layer."
  make_empty_gpkg data/contours.gpkg contours LINESTRING
else
  SMOOTH="$OPT_CONTOUR_SMOOTHING"
  case "$SMOOTH" in ''|*[!0-9.]*) SMOOTH=0 ;; esac
  if [ "${SMOOTH%%.*}" -gt 0 ] 2>/dev/null; then
    RES=$(python3 -c "print(f'{$SMOOTH / 3600:.8f}')")
    echo "DEM coarsening: ${SMOOTH}″ (grid $RES°)"
    python3 workers/lib/watch.py --label="DEM clip" --watch-file=work/clip.tif \
      -- gdalwarp -overwrite -te "$W" "$S" "$E" "$N" "${CUT[@]}" \
         -tr "$RES" "$RES" -r average "$CONTOUR_VRT" work/clip.tif
  else
    echo "DEM coarsening: off – contours are traced at full resolution."
    python3 workers/lib/watch.py --label="DEM clip" --watch-file=work/clip.tif \
      -- gdalwarp -overwrite -te "$W" "$S" "$E" "$N" "${CUT[@]}" \
         "$CONTOUR_VRT" work/clip.tif
  fi

  # smoothing the DEM itself removes the jaggedness: LiDAR micro-relief crinkles the line.
  # The window is in metres (a coarse model gets one cell, nothing), `0` turns it off;
  # a mean by two gdalwarps is cheaper and safer than a gigabyte raster in numpy.
  CONTOUR_RASTER=work/clip.tif
  LOWPASS_M="${CONTOUR_DEM_LOWPASS:-2}"
  case "$LOWPASS_M" in ''|*[!0-9.]*) LOWPASS_M=2 ;; esac
  set +e
  LP_OUT=$(python3 - "$LOWPASS_M" <<'PY'
import json, subprocess, sys
want_m = float(sys.argv[1])
info = json.loads(subprocess.run(["gdalinfo", "-json", "work/clip.tif"],
                                 capture_output=True, text=True,
                                 check=True).stdout)
gt = info["geoTransform"]
cell_deg = min(abs(gt[1]), abs(gt[5]))
cell_m = cell_deg * 110540          # a degree of latitude, as for the tolerance below
# an odd multiple of the cell (`2r+1`); r = 0 means the model is too coarse for micro-relief
r = int(round(want_m / cell_m / 2)) if cell_m > 0 else 0
print(f"{2 * r + 1} {cell_deg:.10f} {cell_m:.2f}")
PY
)
  LP_RC=$?
  set -e
  if [ "$LP_RC" -ne 0 ] || [ -z "$LP_OUT" ]; then
    echo "::warning::The DEM smoothing window can't be computed – contours are traced from the unsmoothed model."
  else
    read -r LP_WIN LP_CELL_DEG LP_CELL_M <<< "$LP_OUT"
    if [ "$LP_WIN" -le 1 ]; then
      echo "DEM smoothing: off – the model cell is ${LP_CELL_M} m, more than the ${LOWPASS_M} m window (no micro-relief in it)."
    else
      LP_COARSE=$(python3 -c "print(f'{$LP_CELL_DEG * $LP_WIN:.10f}')")
      echo "DEM smoothing: a ${LP_WIN}×${LP_WIN} cell window (~$(python3 -c "print(f'{$LP_CELL_M * $LP_WIN:.1f}')") m) – mean, then back to the original grid"
      python3 workers/lib/watch.py --label="DEM smoothing (mean)" \
        --watch-file=work/lp.tif \
        -- gdalwarp -overwrite -r average -tr "$LP_COARSE" "$LP_COARSE" \
           work/clip.tif work/lp.tif
      python3 workers/lib/watch.py --label="DEM smoothing (back to the grid)" \
        --watch-file=work/clip-smooth.tif \
        -- gdalwarp -overwrite -r cubicspline -te "$W" "$S" "$E" "$N" \
           -tr "$LP_CELL_DEG" "$LP_CELL_DEG" work/lp.tif work/clip-smooth.tif
      rm -f work/lp.tif
      CONTOUR_RASTER=work/clip-smooth.tif
      # the original clip has gigabytes – the difference to "no space left on device"
      rm -f work/clip.tif
    fi
  fi

  # through watch.py: gdal_contour over a region runs tens of minutes in silence
  python3 workers/lib/watch.py --label="contours" --watch-file=work/raw.gpkg \
    -- gdal_contour -a ele -i "$INTERVAL" -f GPKG -nln contours \
       "$CONTOUR_RASTER" work/raw.gpkg

  # `level` from the interval: every tenth is major, every fifth mid
  MAJOR=$(( INTERVAL * 10 ))
  MID=$(( INTERVAL * 5 ))
  echo "Contours: ${INTERVAL} m interval from model $CONTOUR_DEM, every ${MAJOR} m major and ${MID} m mid"

  # simplify, then round: stairs first, or each stair gets rounded on its own.
  # Tolerance in degrees; negative = quarters of a DEM cell, `0` = off, positive = metres.
  C_SIMPLIFY="${CONTOUR_SIMPLIFY:--1}"
  # two numbers: the tolerance in degrees (for ogr2ogr) and in metres (for the log)
  set +e
  SIMPL_OUT=$(python3 - "$C_SIMPLIFY" "$CONTOUR_RASTER" <<'PY'
import json, subprocess, sys
want, raster = float(sys.argv[1]), sys.argv[2]
# the longer degree, of latitude: the worst case both ways
m_per_deg = 110540
if want == 0:
    deg = 0.0
elif want > 0:
    deg = want / m_per_deg          # given in metres
else:
    # the raster really traced – `clip.tif` is gone once smoothed
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", raster],
        capture_output=True, text=True, check=True).stdout)
    gt = info["geoTransform"]
    # -1 = a quarter cell, -2 = half, -4 = whole; over half the line leaves the terrain
    deg = min(abs(gt[1]), abs(gt[5])) * (-want) / 4
print(f"{deg:.10f} {deg * m_per_deg:.2f}")
PY
)
  SIMPL_RC=$?
  set -e
  SIMPL_ARGS=()
  if [ "$SIMPL_RC" -ne 0 ] || [ -z "$SIMPL_OUT" ]; then
    # cosmetics don't fail the run, but it must say why the stairs stayed
    echo "::warning::The contour simplification tolerance can't be computed – going without (stairs along cell edges stay)."
  else
    read -r SIMPL_DEG SIMPL_M <<< "$SIMPL_OUT"
    # bash has no decimals, so zero is compared as the `%.10f` string
    if [ "$SIMPL_DEG" = "0.0000000000" ]; then
      echo "Contour simplification: off (CONTOUR_SIMPLIFY=0)."
    else
      SIMPL_ARGS=(-simplify "$SIMPL_DEG")
      echo "Contour simplification: ${SIMPL_DEG}° (~${SIMPL_M} m)"
    fi
  fi

  python3 workers/lib/watch.py --label="sorting contours" \
    --watch-file=work/level.gpkg \
    -- ogr2ogr -f GPKG work/level.gpkg work/raw.gpkg -nln contours \
    "${SIMPL_ARGS[@]}" \
    -dialect SQLITE -sql "SELECT *, CASE
         WHEN CAST(ele AS INTEGER) % $MAJOR = 0 THEN 'major'
         WHEN CAST(ele AS INTEGER) % $MID  = 0 THEN 'mid'
         ELSE 'minor' END AS level
       FROM contours WHERE ele IS NOT NULL"

  # rounding by the limit curve (quadratic B-spline); the number is the chord sag
  # in quarters of the tile grid step, `0` turns it off
  C_SMOOTH="${CONTOUR_SMOOTH:-2}"
  case "$C_SMOOTH" in ''|*[!0-9]*) C_SMOOTH=2 ;; esac
  if [ "$C_SMOOTH" -gt 0 ]; then
    echo "Contour rounding: limit curve, sag ${C_SMOOTH}/4 of the z${OPT_CONTOUR_MAXZOOM} grid step"
    if ! python3 workers/contours-rocks/smooth-shapes.py --in=work/level.gpkg \
           --out=data/contours.gpkg --layer=contours \
           --maxzoom="$OPT_CONTOUR_MAXZOOM" --sag="$C_SMOOTH"; then
      # cosmetics over finished contours mustn't lose them, but it must be heard
      echo "::warning::Contour rounding failed – they go jagged, as before."
      cp work/level.gpkg data/contours.gpkg
    fi
  else
    echo "Contour rounding: off (contour_smooth=0)."
    cp work/level.gpkg data/contours.gpkg
  fi
  ls -lh data/contours.gpkg
  printf '%s\t%s\t%s\t%s\n' "30" "Contours (gdal_contour)" "$(( $(date +%s) - T_CONT ))" \
    "${INTERVAL} m interval from $CONTOUR_DEM, $(du -h data/contours.gpkg | cut -f1)" \
    >> steps-out/contours.tsv
fi

# the second half is sourced, not run: both halves share variables (`ROCK_SLOPE`, `ROCK_DEM_USED`, `RR`)
# shellcheck source=workers/contours-rocks/rocks.sh
. workers/contours-rocks/rocks.sh

CZ="$OPT_CONTOUR_MAXZOOM"
case "$CZ" in ''|*[!0-9]*) CZ=14 ;; esac
if [ "$CZ" -gt 16 ]; then CZ=16; fi

# rocks have their own .pmtiles and maxzoom: areas only where steep fit up to z16,
# Planetiler's hard cap; overzoom does the rest
RZ="$OPT_ROCK_MAXZOOM"
case "$RZ" in ''|*[!0-9]*) RZ=16 ;; esac
if [ "$RZ" -gt 16 ]; then RZ=16; fi

# contours, rocks and the map share the site budget
LIMIT_MB="$OPT_SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
CBUDGET_MB=$(( LIMIT_MB * BUDGET_CONTOURS_PCT / 100 ))
RBUDGET_MB=$(( LIMIT_MB * BUDGET_ROCKS_PCT / 100 ))

# leaves `PM_Z` (zoom used) and `PM_MB` behind
. workers/lib/pmtiles-budget.sh

T_PM=$(date +%s)
# only this job's half: an empty `.pmtiles` would overwrite the other job's in deploy
if [ "$ONLY" != 'rocks' ]; then
  # the eighth argument caps how high it may go with room left: `contour_maxzoom` is a wish and a floor
  pmtiles_in_budget workers/contours-rocks/contours.yml contours-out/contours.pmtiles \
    "$CZ" "$CBUDGET_MB" 10 "Contours" \
    "raise contour_interval (e.g. 20 m) or turn them off for this area." 16
  CZ="$PM_Z"
fi

if [ "$ONLY" != 'contours' ]; then
  pmtiles_in_budget workers/contours-rocks/rocks.yml contours-out/rocks.pmtiles \
    "$RZ" "$RBUDGET_MB" 12 "Rocks" \
    "raise rock_min_area or shrink the cut-out."
  RZ="$PM_Z"
  echo "$RZ" > contours-out/rock-maxzoom.txt
fi

# the cache keeps the maxzoom used, the height source (attribution) and slope threshold (manifest)
echo "$CZ" > contours-out/maxzoom.txt
# attribution: the contours' model, the rocks' when contours are off
DEM_FOR_STYLE="$CONTOUR_DEM"
[ -n "$DEM_FOR_STYLE" ] || DEM_FOR_STYLE="$ROCK_DEM_USED"
echo "$DEM_FOR_STYLE" > contours-out/dem-source.txt
# the slope threshold means something only for rocks from a DEM
if [ "$OPT_ROCKS" = 'true' ] \
   && [ "$OPT_ROCK_SOURCE" != 'shading' ]; then
  echo "$ROCK_SLOPE" > contours-out/rock-slope.txt
else
  echo "off" > contours-out/rock-slope.txt
fi
if [ "$OPT_ROCKS" = 'true' ]; then
  echo "$OPT_ROCK_SOURCE" > contours-out/rock-source.txt
else
  echo "off" > contours-out/rock-source.txt
fi
ls -lh contours-out/
# measured: only this job's half, or the summary reports a layer that didn't run
MEASURE=""
if [ "$ONLY" != 'rocks' ]; then
  MEASURE="contours z$CZ ($(du -h contours-out/contours.pmtiles | cut -f1))"
fi
if [ "$ONLY" != 'contours' ]; then
  [ -n "$MEASURE" ] && MEASURE="$MEASURE, "
  MEASURE="${MEASURE}rocks z$RZ ($(du -h contours-out/rocks.pmtiles | cut -f1))"
fi
printf '%s\t%s\t%s\t%s\n' "50" "Contours and rocks → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "$MEASURE" >> steps-out/contours.tsv
