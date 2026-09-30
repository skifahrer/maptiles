#!/usr/bin/env bash
# ROCKS: the steepest parts of the terrain → data/rock.gpkg.
#
# Sourced by `workers/contours-rocks/build.sh` – the second half of the same
# computation, sharing its variables (`ROCK_SLOPE`, `ROCK_DEM_USED`, `RR`).
# `set -euo pipefail` is whatever `build.sh` set.

# shellcheck source=workers/lib/store-area.sh
. workers/lib/store-area.sh

# the computation is in `rock-areas.py`, in chunks: a region's bbox at 2 m has 3 billion cells
T_ROCK=$(date +%s)
ROCK_SLOPE="$ROCK_SLOPE_IN"
case "$ROCK_SLOPE" in ''|*[!0-9]*) ROCK_SLOPE=50 ;; esac
ROCK_CLIFF=$(( ROCK_SLOPE + ROCK_CLIFF_PLUS ))
# `auto` = rock-areas.py picks the grid from the cut-out's area and the DEM cell
RR="$ROCK_RES_IN"
case "$RR" in
  auto|'') RR=auto ;;
  *[!0-9.]*) RR="$ROCK_RES" ;;
esac

make_empty_rock() { make_empty_gpkg data/rock.gpkg rock POLYGON; }

if [ "$OPT_ROCKS" = 'true' ]; then
  ROCK_READY=""
  ROCK_SRC="computed"

  # rocks from hillshading tiles: the `shading-rocks` job made them, only downloaded here
  if [ "$OPT_ROCK_SOURCE" = 'shading' ]; then
    IMG_ASSET="$OPT_ROCK_IMG_ASSET"
    echo "::group::Rocks from hillshading – $AREA_NAME, store $ROCK_IMG_STORE"
    if [ -z "$IMG_ASSET" ]; then
      # newest by upload time, not name: thresholds in the name would win alphabetically
      IMG_ASSET=$(python3 workers/drive/store.py --latest \
        --store="$ROCK_IMG_STORE" --prefix="rockimg-$(store_area "$AREA_KEY")-" \
        --suffix=".gpkg.zst" 2>/dev/null || true)
    fi
    if [ -z "$IMG_ASSET" ]; then
      echo "::endgroup::"
      echo "::error::Store $ROCK_IMG_STORE has no file for cut-out '$AREA_KEY' (rockimg-$(store_area "$AREA_KEY")-*.gpkg.zst). See the job \"Rocks from hillshading\" in this run – it should have made them; if it failed, it says why. Or pick an elevation model for rock_source (sonny / dmr35 / dmr5 / ugkk)."
      exit 1
    fi
    rm -rf /tmp/rockimg && mkdir -p /tmp/rockimg
    if ! python3 workers/drive/store.py --get --store="$ROCK_IMG_STORE" \
           --name="$IMG_ASSET" --dir=/tmp/rockimg; then
      echo "::endgroup::"
      echo "::error::File $IMG_ASSET couldn't be downloaded from store $ROCK_IMG_STORE."
      exit 1
    fi
    echo "  taking: $IMG_ASSET ($(du -h "/tmp/rockimg/$IMG_ASSET" | cut -f1))"
    unzstd -q -f -o data/rock.gpkg "/tmp/rockimg/$IMG_ASSET"
    ROCK_READY=1
    ROCK_SRC="store $ROCK_IMG_STORE ($IMG_ASSET)"
    # not clipped to the region bbox: the asset was made for exactly this cut-out
    echo "::endgroup::"
  fi

  # finished rocks for these settings are in the store; the name carries cut-out and overlap
  ROCK_BORDER_M=$(python3 -c "import sys; sys.path.insert(0, 'workers/plan'); import area; print(int(area.BORDER_BUFFER_M))")
  ROCK_ASSET="rock-${REGION_KEY}-$(store_area "$AREA_KEY")-${ROCK_DEM_USED:-none}-s${ROCK_SLOPE}-g${RR}-${ROCK_ALGO}-o${ROCK_BORDER_M}.gpkg.zst"
  # a test run keeps the whole-region key, so it must not touch the store
  ROCK_STORE_OK=1
  if [ "${OPT_TEST_KM2:-0}" != '0' ]; then
    ROCK_STORE_OK=""
    echo "Quick test (${OPT_TEST_KM2} km²): rocks are neither saved to nor taken from store $ROCK_STORE – a real run would take them for the whole cut-out."
  fi
  if [ -n "$ROCK_READY" ]; then
    : # rocks are here (from hillshading) – no DEM is read for them
  elif [ -z "$ROCK_STORE_OK" ]; then
    : # a test run – computed anew and kept nowhere
  elif [ "$OPT_ROCKS_REBUILD" = 'true' ]; then
    echo "rocks_rebuild=yes – dropping the stored version and computing anew."
    python3 workers/drive/store.py --rm --store="$ROCK_STORE" \
      --name="$ROCK_ASSET" || true
  elif python3 workers/drive/store.py --get --store="$ROCK_STORE" \
         --name="$ROCK_ASSET" --dir=/tmp >/dev/null 2>&1; then
    unzstd -q -f -o data/rock.gpkg "/tmp/$ROCK_ASSET" && ROCK_READY=1
    [ -n "$ROCK_READY" ] && ROCK_SRC="store $ROCK_STORE" \
      && echo "Rocks from store $ROCK_STORE ✓ ($ROCK_ASSET)"
  fi

  if [ -z "$ROCK_READY" ]; then
    echo "::group::Rocks from model $ROCK_DEM_USED – $AREA_NAME, slope ≥ ${ROCK_SLOPE}° (cliffs from ${ROCK_CLIFF}°), grid ${RR}, rounding ${ROCK_SMOOTH}×"
    # rocks are a bonus, a failure mustn't fail the build – except exit 2, "can't be computed"
    # 1. where heights are read from: `dmr5` straight from Drive, others local tiles
    SRC_ARGS=(--dem "$ROCK_VRT")
    [ "$ROCK_DEM_USED" = 'dmr5' ] && SRC_ARGS=(--drive --dem-cell-m 1)

    # a test run and a rebuild must not touch the store
    STORE_ARGS=()
    [ "${OPT_TEST_KM2:-0}" != '0' ] && STORE_ARGS+=(--no-store)
    [ "$OPT_ROCKS_REBUILD" = 'true' ] && STORE_ARGS+=(--rebuild)

    # 2. the grid, picked by `slope-chunks.py` before it computes
    set +e
    RES=$(python3 workers/contours-rocks/slope-chunks.py --bbox="$AREA_BBOX" --res="$RR" \
      "${SRC_ARGS[@]}" --budget-min="$ROCK_BUDGET_MIN" \
      --chunk-cells="$ROCK_CHUNK_CELLS" --print-res)
    RC=$?
    set -e
    if [ "$RC" -ne 0 ] || [ -z "$RES" ]; then
      echo "::error::No grid could be picked for the rocks."
      exit 1
    fi

    # 3. slope in chunks (the store survives a cancelled run)
    set +e
    python3 workers/contours-rocks/slope-chunks.py --bbox="$AREA_BBOX" --res="$RES" \
      "${SRC_ARGS[@]}" "${STORE_ARGS[@]}" \
      --out="$SLOPE_DIR" --jobs="${SLOPE_JOBS:-6}" \
      --store="${SLOPE_STORE:-dem-slope}" \
      --stats=contours-out/slope-stats.txt
    RC=$?
    set -e
    if [ "$RC" -ne 0 ]; then
      echo "::error::Slope in chunks failed – rocks can't be computed."
      exit 1
    fi
    SLOPE_VRT=$(sed -n 's/^vrt=//p' contours-out/slope-stats.txt)

    # 4. vectorising in one pass over the whole mosaic
    set +e
    python3 workers/contours-rocks/rock-areas.py --slope-vrt="$SLOPE_VRT" --bbox="$AREA_BBOX" \
      --res="$RES" --vec-res="${ROCK_VEC_RES:-auto}" \
      --slope="$ROCK_SLOPE" --cliff="$ROCK_CLIFF" \
      --dem="$ROCK_VRT" \
      --min-area=-1 --simplify="$ROCK_SIMPLIFY" \
      --solid="${OPT_ROCK_SOLID:-1}" \
      --fill-holes="${OPT_ROCK_FILL_HOLES:-0}" \
      --smooth="$ROCK_SMOOTH" --maxzoom="$OPT_ROCK_MAXZOOM" \
      --stats=contours-out/rock-stats.txt \
      --budget-min="$ROCK_BUDGET_MIN" \
      --block-px="${ROCK_BLOCK_PX:-4096}" \
      --max-rss-gb="$ROCK_MAX_RSS_GB" --heartbeat="$ROCK_HEARTBEAT_S" \
      --out=data/rock.gpkg
    RC=$?
    set -e
    if [ "$RC" -eq 2 ]; then
      echo "::endgroup::"
      echo "::error::The rock computation couldn't finish – the request is beyond the runner (see the messages above: memory or chunk count). Adjust rock_res or area and run again."
      exit 1
    fi
    if [ "$RC" -eq 0 ] && [ -z "$ROCK_STORE_OK" ]; then
      ls -lh data/rock.gpkg
      echo "Not saved to store $ROCK_STORE – it is a quick test."
    elif [ "$RC" -eq 0 ]; then
      ls -lh data/rock.gpkg
      # store them for next time; a failed save mustn't fail the run
      zstd -q -19 -T0 -f -o "/tmp/$ROCK_ASSET" data/rock.gpkg
      python3 workers/drive/store.py --put --store="$ROCK_STORE" \
          --file="/tmp/$ROCK_ASSET" \
          --note="Vector rocks from the elevation model's slope – the name carries region, cut-out, model and settings (slope threshold, outline grid)" \
        && echo "Saved to store $ROCK_STORE as $ROCK_ASSET" \
        || echo "::warning::Rocks couldn't be saved to store $ROCK_STORE – next time they will be computed again."
    else
      echo "::warning::No rock areas were made (the reason is in the message above) – the layer will be empty. Such a run goes neither to the cache nor the map, so the next one tries again."
      make_empty_rock
      # without it the cache keeps it as a finished layer
      echo "$RC" > contours-out/rock-failed.txt
    fi
    echo "::endgroup::"
  fi

  # store and computation go by bbox; the map gets only what lies in the region
  if [ -s data/region.geojson ]; then
    ogr2ogr -f GPKG work/rock-region.gpkg data/rock.gpkg rock -nln rock \
      -clipsrc data/region.geojson -explodecollections -nlt POLYGON \
      -lco GEOMETRY_NAME=geom
    mv work/rock-region.gpkg data/rock.gpkg
    echo "Rocks clipped to the region (data/region.geojson)."
  else
    echo "::warning::No region polygon (data/region.geojson) – rocks cover the whole bbox, outside the region too."
  fi

  # the stats go to contours-out so the cache carries them for the summary
  ROCK_N=$(ogrinfo -so data/rock.gpkg rock 2>/dev/null \
    | awk -F': ' '/^Feature Count/ {print $2}')
  # rocks from hillshading have neither slope nor grid
  if [ "$OPT_ROCK_SOURCE" = 'shading' ]; then
    ROCK_HOW="dark areas in the hillshading"
  else
    ROCK_HOW="$ROCK_DEM_USED, slope ≥ ${ROCK_SLOPE}°, grid ${RR} m"
  fi
  printf '%s\t%s\t%s\t%s\n' "40" "Rock areas" "$(( $(date +%s) - T_ROCK ))" \
    "${ROCK_N:-0} areas, $AREA_NAME, ${ROCK_HOW} ($ROCK_SRC)" \
    >> steps-out/contours.tsv
  # rocks from the store: the script didn't run and nobody wrote the stats
  if [ ! -s contours-out/rock-stats.txt ]; then
    # no `min_area_m2`: rock-areas.py computes it; the summary copes without
    if [ "$OPT_ROCK_SOURCE" = 'shading' ]; then
      { echo "source=shading"; echo "count=${ROCK_N:-0}"
        printf "asset='%s'\n" "$ROCK_SRC"
      } > contours-out/rock-stats.txt
    else
      { echo "source=dem"; echo "count=${ROCK_N:-0}"; echo "grid_m=$RR"
        echo "slope_deg=$ROCK_SLOPE"; echo "cliff_deg=$ROCK_CLIFF"
      } > contours-out/rock-stats.txt
    fi
  fi
  # which model the rocks are from, for the summary; empty with hillshading
  printf "rock_dem='%s'\n" "$ROCK_DEM_USED" >> contours-out/rock-stats.txt
  # zero areas from a failure and from flat land look the same in the summary
  if [ -s contours-out/rock-failed.txt ]; then
    echo "failed=1" >> contours-out/rock-stats.txt
  fi
  # quoted: the summary sources the file and the name has a space
  { printf "area_key='%s'\n" "$AREA_KEY"
    printf "area_name='%s'\n" "$AREA_NAME"
    printf "area_bbox='%s'\n" "$AREA_BBOX"; } >> contours-out/rock-stats.txt
else
  make_empty_rock
  echo "Rocks: off (empty layer)."
fi
