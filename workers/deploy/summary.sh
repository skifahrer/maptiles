#!/usr/bin/env bash
# The "Build map" run summary for the Summary tab: what ran, how long, in what detail.
#
# Every job kept its lines in its `steps-*` artifact; `deploy` merges them and
# sorts by order number, not time – jobs run in parallel. Values come through
# the environment (see the step "Build summary"): R_* job results, SRC_*/USED_*
# layer sources, SIZE_LIMIT_MB, PAGE_URL, PUBLISH_PAGES, PAGES_BUILD_TYPE,
# REGION_KEY, TEST_*, INPUTS_JSON. Plus `gh` and GITHUB_* from the runner.

set -uo pipefail
S="$GITHUB_STEP_SUMMARY"
hms() { printf '%d:%02d:%02d' $(( $1 / 3600 )) $(( $1 % 3600 / 60 )) $(( $1 % 60 )); }

# the total is the workflow's time, not this job's – jobs run in parallel
STARTED=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  -q .run_started_at 2>/dev/null || echo '')
if [ -n "$STARTED" ]; then
  TOTAL=$(( $(date +%s) - $(date -d "$STARTED" +%s) ))
else
  TOTAL=0
fi

{
  echo "# ${REGION_NAME}"
  echo
  echo "Whole run: **$(hms "$TOTAL")** (jobs ran in parallel, the sum below is larger)"
  echo
  echo "| job | result |"
  echo "|---|---|"
  echo "| Plan | ${R_PLAN} |"
  echo "| Contours and rocks | ${R_CONTOURS} |"
  echo "| Rocks from hillshading | ${R_SHADING_ROCKS} |"
  echo "| Marked trails | ${R_TRAILS} |"
  echo "| Landscape features | ${R_FEATURES:-–} |"
  echo "| Hillshading and 3D terrain | ${R_TERRAIN} |"
  echo "| Map tiles | ${R_TILES} |"
  echo "| Icons and fonts | ${R_ASSETS} |"
  echo
  echo "## What ran"
  echo
  echo "| step | duration | result |"
  echo "|---|--:|---|"
} >> "$S"

if [ -d steps-out ] && [ -n "$(find steps-out -name '*.tsv' 2>/dev/null)" ]; then
  # the first field only sorts
  cat steps-out/*.tsv | sort -n | while IFS=$'\t' read -r _ord name secs detail; do
    [ -n "$name" ] || continue
    printf '| %s | %s | %s |\n' "$name" "$(hms "${secs:-0}")" "$detail" >> "$S"
  done
else
  echo "| — | — | no job got to its first measured step |" >> "$S"
fi

# rock detail: rock-areas.py writes the numbers, the contours job packed them
if [ -s steps-out/rock-stats.txt ]; then
  # shellcheck disable=SC1091
  . steps-out/rock-stats.txt
fi

# rocks from hillshading have no slope, grid or DEM cell – a table of their own
if [ "${source:-dem}" = "shading" ]; then
  {
    echo
    echo "## Rock areas – from hillshading tiles"
    echo
    echo "| property | value |"
    echo "|---|---|"
    echo "| area | ${area_name:-whole region}${area_bbox:+ (\`$area_bbox\`)} |"
    echo "| separate areas | ${count:-?} |"
    echo "| source | ${asset:-store dem-rocks-img} |"
    echo
    # downloaded, or computed by the sub-pipeline in this run – two different sentences
    if [ "${R_SHADING_ROCKS:-skipped}" = 'success' ]; then
      echo "These rocks were **computed by this run** – the job *Rocks from hillshading*,"
      echo "which the build called itself. It finds them as dark areas in the"
      echo "hillshade JPG tiles from freemap.sk (not from the elevation model's"
      echo "slope) and saved the finished polygons to the store"
      echo "\`dem-rocks-img\`. Detailed numbers (thresholds, zoom, tile count)"
      echo "are in its part of this run."
    else
      echo "These rocks were **not computed** in this run. The workflow"
      echo "*Data · shaded rocks* found them as dark areas in the hillshade JPGs"
      echo "from freemap.sk and the build only downloaded them from \`dem-rocks-img\`."
      echo "Detailed numbers (thresholds, zoom, tile count) are in that run's summary."
    fi
    echo
    echo "> ⚠️ Hillshade is lit from one side, so **north-west** walls are dark"
    echo "> and south-east ones light. This layer systematically misses part"
    echo "> of the rocks. Rocks from the elevation model's slope"
    echo "> (\`rock_source: sonny\` / \`dmr35\` / \`dmr5\` / \`ugkk\`) don't"
    echo "> have this flaw."
  } >> "$S"
elif [ -s steps-out/rock-stats.txt ]; then
  {
    echo
    echo "## Rock areas – what detail"
    echo
    # otherwise a failure shows only as "areas: 0", which looks like flat land
    if [ "${failed:-0}" = '1' ]; then
      echo "> ❌ **The rock computation failed** – the layer is empty, it went"
      echo "> neither to the map nor the cache and the next run computes it again."
      echo "> The reason is in the *Rocks* job's log, in the message above"
      echo "> \"No rock areas were made\"."
      echo
    fi
    echo "| property | value |"
    echo "|---|---|"
    echo "| area | ${area_name:-whole region}${area_bbox:+ (\`$area_bbox\`)} |"
    echo "| elevation model | ${rock_dem:-?} |"
    echo "| separate areas | ${count:-?} |"
    echo "| outline computed on a grid of | ${grid_m:-?} m |"
    echo "| slope cells / computation time | ${cells_g:-?} G / ${took:-?} |"
    echo "| source DEM cell (${rock_dem:-?}) | ~${dem_cell_m:-?} m → **cap of real detail** |"
    echo "| smallest area kept | ${min_area_m2:-?} m² |"
    echo "| actual smallest area | ${min_m2:-?} m² |"
    echo "| mean area | ${avg_m2:-?} m² |"
    echo "| largest area | ${max_ha:-?} ha |"
    echo "| rock terrain in total | ${total_km2:-?} km² |"
    if [ "${solid:-1}" = '1' ]; then
      echo "| slope threshold | ≥ ${slope_deg:-?}° (step ${slope_step_deg:-?}°), one class |"
    else
      echo "| slope threshold | ≥ ${slope_deg:-?}° (cliffs from ${cliff_deg:-?}°, step ${slope_step_deg:-?}°) |"
    fi
    if [ "${fill_holes:-0}" = '1' ]; then
      echo "| holes | **filled** (\`rock_fill_holes=1\`) – the shape's detail is gone |"
    else
      echo "| areas with a hole (a spot under the threshold inside a rock) | ${with_holes:-0} |"
      echo "| cut out by holes | ${holes_km2:-0} km² |"
    fi
    echo "| outline simplification | ${simplify_m:-?} m |"
    echo "| corner rounding | sag ${smooth_sag:-0}/4 of the tile grid step |"
    echo
    echo "The outline is a slope isoline – an area has the shape the terrain really has."
    if [ "${fill_holes:-0}" = '1' ]; then
      echo "Holes are **filled** (\`options: rock_fill_holes=1\`), so every rock"
      echo "is a solid area without inner shape. Turning that switch off brings"
      echo "ledges and gaps back where they belong."
    else
      echo "Where a wall has a gentler spot inside (a ledge, a terrace), a **hole**"
      echo "drops out of the area and isn't filled – even with slope over the"
      echo "threshold all around. Those holes make a rock's shape readable."
    fi
    case "${area_key:-whole}" in whole) ;; *)
      echo
      echo "> ⚠️ **Contours and rocks are only on the cut-out \"${area_name}\".**"
      echo "> The rest of the region has none of them on the map – this is a run"
      echo "> for testing, not deploying. For the whole region pick"
      echo "> \`whole_region\` for the \`area\` input." ;;
    esac
    echo
    echo "> A ${grid_m:-?} m grid says how finely the outline is stepped; but the"
    echo "> source DEM has a ~${dem_cell_m:-?} m cell, so a finer grid invents no"
    echo "> new terrain detail – it only smooths and places the outline better."
    echo "> That is why \`rock_res=auto\` doesn't go below a tenth of the DEM cell:"
    echo "> refining further would cost four times the time for zero detail."
    echo
    echo "> Jaggedness is solved by rounding corners, not a coarser grid. The"
    echo "> isoline itself isn't jagged (mean bend 4.6°); simplifying the outline"
    echo "> makes it so (28.5°). So a corner is replaced by the limit curve"
    echo "> (quadratic B-spline), sampled to stray from its exact course by no"
    echo "> more than a fraction of the tile grid step – finer detail doesn't fit"
    echo "> a tile anyway."
  } >> "$S"
fi

# trail detail: trails/routes.py writes the numbers
if [ -s steps-out/trail-stats.txt ]; then
  # shellcheck disable=SC1091
  . steps-out/trail-stats.txt
  {
    echo
    echo "## Marked trails – what OSM had"
    echo
    echo "| property | value |"
    echo "|---|---|"
    echo "| route relations (\`type=route\`) | ${routes:-0} |"
    echo "| of them named | ${named:-0} |"
    echo "| ways a route follows | ${ways:-0} |"
    echo "| pieces in the tiles (way × route) | ${features:-0} |"
    echo "| ways with more than one route | ${multi:-0} (at most ${max_lanes:-0} at once) |"
    echo "| hiking / cycling / MTB | ${type_hiking:-0} / ${type_bicycle:-0} / ${type_mtb:-0} |"
    echo "| ski / horse | ${type_ski:-0} / ${type_horse:-0} |"
    echo "| long-distance (international + national) | $(( ${tier_international:-0} + ${tier_national:-0} )) |"
    echo "| marking colours | ${colours:-–} |"
    # a `miter` join can't stitch a bend over 120°, so the data splits it
    echo "| bends over 120° split | ${eased:-0} |"
    echo
    echo "A route is drawn as a coloured strip **beside** the way, each in its"
    echo "own lane – up to ${max_lanes:-1} follow one way at once and the way"
    echo "under them stays visible for what it is."
  } >> "$S"
fi

{
  echo
  echo "## Site budget"
  echo
  echo "| part | size |"
  echo "|---|--:|"
  for d in tiles terrain sprites fonts; do
    [ -d "_site/$d" ] && echo "| $d | $(du -sm "_site/$d" | cut -f1) MB |"
  done
  echo "| **total** | **$(du -sm _site 2>/dev/null | cut -f1) MB** of ${SIZE_LIMIT_MB} MB |"
  echo
  echo "## Where the terrain is from"
  echo
  echo "| layer | chosen source | really used |"
  echo "|---|---|---|"
  echo "| contours | \`${SRC_CONTOURS}\` | ${USED_CONTOURS} |"
  echo "| rocks | \`${SRC_ROCKS}\` | ${USED_ROCKS} |"
  echo "| hillshading and 3D | \`${SRC_SHADING}\` | ${USED_SHADING} |"
  echo
  echo "Chosen and used differ only when a model wasn't available"
  echo "and a fallback kicked in (e.g. 1 m ÚGKK → Sonny)."
  if [ "$SRC_ROCKS" = 'shading' ]; then
    echo
    echo "The hillshading tiles the rocks come from were downloaded in this"
    echo "run by the job *Rocks from hillshading* – they are in the artifact"
    echo "\`shading-tiles-…\` and a mosaic preview in \`preview-…\`."
  fi
  echo
} >> "$S"

# what the run was started with is left out on purpose: the `plan` job writes it first

{
  echo "**How to regenerate:** run the workflow again and pick \`contours\`,"
  echo "\`rocks\` (including the stored version in store \`dem-rocks\` and the"
  echo "half-done outlines of the sub-pipeline \`Data · shaded rocks\`),"
  echo "\`terrain\` or \`everything\` for \`rebuild\`."
  echo "The matching cache is deleted first – otherwise the old version"
  echo "would just come back."
  # the table above shows `rebuild` as in the form; a test would claim `nothing`
  if [ "${TEST_KM2:-0}" != '0' ]; then
    echo
    echo "This run didn't need it though: **a quick test always regenerates"
    echo "everything**, even with \`rebuild: nothing\` – otherwise you would tune"
    echo "a result that came back from the cache. It doesn't delete the real run's"
    echo "cache, the test square has a key of its own."
  fi
  echo
  echo "**Quick test run:** \`area\` (e.g. \`vysoke_tatry\`) computes contours"
  echo "and rocks only on the cut-out – ~40 minutes become ~2."
  echo "Faster still is the \`test\` switch (unticked by default): contours,"
  echo "rocks and hillshading are computed only on a 4 km² square in the middle"
  echo "of the cut-out and the map opens right there. **The map itself stays"
  echo "whole by the region's settings** – region, roads, trails and features."
  echo "Another size is \`options: test_km2=5\`. A test run is written to"
  echo "\`maps-test.json\`, not \`maps.json\` – a map with terrain on a few km²"
  echo "doesn't belong in the list of finished maps."
} >> "$S"

if [ "$PAGE_URL" != '' ]; then
  echo -e "\n[Open the map](${PAGE_URL})" >> "$S"
elif [ "${PUBLISH_PAGES:-true}" = 'false' ]; then
  # not an error, a choice in the form
  echo -e "\n**The map wasn't deployed to GitHub Pages** (\`publish_pages=false\`) –" \
       "it is finished only on Google Drive." >> "$S"
fi

# Pages takes its source from a branch: the next push to master overwrites the map
if [ -n "${PAGES_BUILD_TYPE:-}" ] && [ "$PAGES_BUILD_TYPE" != 'workflow' ]; then
  {
    echo
    echo "> ### ⚠️ The next merge overwrites the map on Pages"
    echo ">"
    echo "> The GitHub Pages source is set to a **branch**, not Actions"
    echo "> (\`build_type=$PAGES_BUILD_TYPE\`). So beside this workflow the"
    echo "> built-in Jekyll builder (*pages build and deployment*) runs and on"
    echo "> every push to \`master\` deploys the repository root – the README –"
    echo "> overwriting this run's map."
    echo ">"
    echo "> The map is **deployed and working now**; it disappears with the next merge."
    echo ">"
    echo "> **The fix is one-off and yours to do** (the token has no right to"
    echo "> change repository settings):"
    echo "> **Settings → Pages → Build and deployment → Source: \`GitHub Actions\`**"
  } >> "$S"
fi

# where the test cut-out is: the image went out with the site, so it has a public address
if [ "${TEST_KM2:-0}" != '0' ] && [ -n "${TEST_BBOX:-}" ]; then
  python3 workers/plan/test-map.py \
    --bbox="$TEST_BBOX" --full-bbox="${TEST_FULL_BBOX:-}" \
    --name="$REGION_NAME" \
    --layers="contours: ${SRC_CONTOURS}, rocks: ${SRC_ROCKS}, hillshading: ${SRC_SHADING}" \
    --png= --md=/tmp/where-it-is.md \
    --img-url="${PAGE_URL}where-it-is.png" \
    --pages-url="$PAGE_URL" --region="${REGION_KEY:-}" || true
  if [ -s /tmp/where-it-is.md ]; then
    { echo; cat /tmp/where-it-is.md; } >> "$S"
  else
    { echo; echo "### Test cut-out"; echo;
      echo "bbox \`${TEST_BBOX}\` (${TEST_KM2} km²) – the image couldn't be made.";
    } >> "$S"
  fi
fi

# what failed: step, duration and the last `::error::` lines; `|| true` so the summary survives
FAILED=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/jobs?per_page=100" \
  --jq '.jobs[]
        | select(.conclusion == "failure" or .conclusion == "cancelled")
        | [.id, .name, .conclusion, .started_at, .completed_at,
           ([.steps[]? | select(.conclusion == "failure" or .conclusion == "cancelled")
             | .name] | first // "—"),
           .html_url] | @tsv' 2>/dev/null || true)

if [ -n "$FAILED" ]; then
  { echo; echo "## What failed"; echo; } >> "$S"
  while IFS=$'\t' read -r jid jname jconcl jstart jend jstep jurl; do
    [ -n "${jname:-}" ] || continue
    if [ -n "${jstart:-}" ] && [ -n "${jend:-}" ]; then
      TOOK=$(( $(date -d "$jend" +%s) - $(date -d "$jstart" +%s) ))
    else
      TOOK=0
    fi
    {
      echo "### [$jname]($jurl) – $jconcl after $(hms "$TOOK")"
      echo
      echo "It stopped at the step **$jstep**."
      if [ "$jconcl" = "cancelled" ] && [ "$TOOK" -gt 3000 ]; then
        echo
        echo "> Cancelled after $(hms "$TOOK") – not a failure, a cap."
        echo "> Either the job timeout or the computation budget. Try a smaller"
        echo "> cut-out, a lower zoom or a coarser grid."
      fi
    } >> "$S"
    # the timestamp at the start of a line goes – it would break the table
    ERRORS=$(gh api "repos/$GITHUB_REPOSITORY/actions/jobs/$jid/logs" 2>/dev/null \
      | grep -a "##\[error\]" | tail -3 | sed 's/^[0-9TZ:.-]* //' || true)
    if [ -n "$ERRORS" ]; then
      { echo; echo '```'; echo "$ERRORS"; echo '```'; echo; } >> "$S"
    fi
  done <<< "$FAILED"
fi
