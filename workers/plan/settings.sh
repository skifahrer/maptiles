#!/usr/bin/env bash
# Job `settings` – the run's first job: what the run goes with, before anything is computed.
# Its own job, so it isn't buried under the 380 MB PBF download of `plan`.
set -euo pipefail

OUT="$RUNNER_TEMP/settings.md"
: > "$OUT"

python3 workers/plan/summary-inputs.py \
  --inputs="$INPUTS_JSON" \
  --workflow=.github/workflows/build-map-region.yml \
  --with-env >> "$OUT"

# without `--out`: this job only shows, `options.py` still fails on an unknown key
python3 workers/plan/options.py \
  --options="$OPT_OPTIONS" \
  --rebuild="$OPT_REBUILD" \
  --contour-source="$OPT_CONTOUR_SOURCE" \
  --rock-source="$OPT_ROCK_SOURCE" \
  --shading-source="$OPT_SHADING_SOURCE" \
  --test="$OPT_TEST" \
  --publish-pages="$OPT_PUBLISH_PAGES" \
  --summary="$OUT"

# summary is read on a phone, the log can be grepped
cat "$OUT" >> "$GITHUB_STEP_SUMMARY"
cat "$OUT"
