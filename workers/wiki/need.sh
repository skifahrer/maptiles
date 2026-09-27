#!/usr/bin/env bash
# Treba články stiahnuť? Nie, keď ich región má v cache aj balík v katalógu.
#
# Volá to build mapy: články sa neobnovujú pri každom builde, na to je
# `rebuild: clanky`. Chýbajúca cache alebo balík = sťahuje sa.
#
# Z prostredia: REGION_KEY COUNTRY LANGS FMT RUN_ID; píše `skip` do GITHUB_OUTPUT.
set -euo pipefail

PREFIX=$(REGION="$REGION_KEY" workers/wiki/key.sh | sed -n 's/^prefix=//p')
KEY=$(REGION="$REGION_KEY" workers/wiki/key.sh | sed -n 's/^key=//p')

# balík regiónu v katalógu – kraj pod `regions`, krajina na vrchu
V_KATALOGU=$(jq -r --arg r "$REGION_KEY" '
  any(.[] | objects; (.regions[$r].maps.wikipedia? // null) != null)
  or ((.[$r].maps.wikipedia? // null) != null)' maps.json)

LOOKUP="${RUNNER_TEMP:-/tmp}/wiki-lookup"
: > "$LOOKUP"
GITHUB_OUTPUT="$LOOKUP" python3 workers/drive/cache.py --lookup \
  --key="$KEY" --restore-keys="$PREFIX"
V_CACHE=$(sed -n 's/^cache-matched-key=//p' "$LOOKUP")

if [ "$V_KATALOGU" = true ] && [ -n "$V_CACHE" ]; then
  echo "::notice::Články regiónu $REGION_KEY sú v cache ($V_CACHE) aj v" \
       "katalógu – nesťahujú sa. Nanovo: \`rebuild: clanky\`."
  echo "skip=true" >> "$GITHUB_OUTPUT"
else
  echo "Články regiónu $REGION_KEY: katalóg=$V_KATALOGU," \
       "cache=${V_CACHE:-žiadna} – sťahujú sa."
  echo "skip=false" >> "$GITHUB_OUTPUT"
fi
