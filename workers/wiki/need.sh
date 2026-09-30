#!/usr/bin/env bash
# Do the articles need downloading? Not when the region has them cached and catalogued.
# From env: REGION_KEY COUNTRY LANGS RUN_ID; writes `skip` to GITHUB_OUTPUT.
set -euo pipefail

PREFIX=$(REGION="$REGION_KEY" workers/wiki/key.sh | sed -n 's/^prefix=//p')
KEY=$(REGION="$REGION_KEY" workers/wiki/key.sh | sed -n 's/^key=//p')

# a region sits under `regions`, a country on top
IN_CATALOG=$(jq -r --arg r "$REGION_KEY" '
  any(.[] | objects; (.regions[$r].maps.wikipedia? // null) != null)
  or ((.[$r].maps.wikipedia? // null) != null)' maps.json)

LOOKUP="${RUNNER_TEMP:-/tmp}/wiki-lookup"
: > "$LOOKUP"
GITHUB_OUTPUT="$LOOKUP" python3 workers/drive/cache.py --lookup \
  --key="$KEY" --restore-keys="$PREFIX"
IN_CACHE=$(sed -n 's/^cache-matched-key=//p' "$LOOKUP")

if [ "$IN_CATALOG" = true ] && [ -n "$IN_CACHE" ]; then
  echo "::notice::Articles of region $REGION_KEY are cached ($IN_CACHE) and" \
       "catalogued – not downloaded. Anew: \`rebuild: articles\`."
  echo "skip=true" >> "$GITHUB_OUTPUT"
else
  echo "Articles of region $REGION_KEY: catalog=$IN_CATALOG," \
       "cache=${IN_CACHE:-none} – downloading."
  echo "skip=false" >> "$GITHUB_OUTPUT"
fi
