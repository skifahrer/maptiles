#!/usr/bin/env bash
# `<LAYER>_ENABLED` for each season's photos in `_site`, as `names.layers` reads.
set -euo pipefail
for season in summer winter; do
  if [ -f "_site/tiles/${REGION_KEY}-aerial_${season}.pmtiles" ]; then
    # `tr`, not `${season^^}`: the macOS runner's bash is 3.2
    echo "AERIAL_$(printf '%s' "$season" | tr '[:lower:]' '[:upper:]')_ENABLED=true"
  fi
done
