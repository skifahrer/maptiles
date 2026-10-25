#!/usr/bin/env bash
# `AERIAL_<SEASON>_ENABLED` for each season whose photos are in `_site`, as `names.layers` reads.
set -euo pipefail
for season in summer winter; do
  if [ -f "_site/tiles/${REGION_KEY}-aerial_${season}.pmtiles" ]; then
    echo "AERIAL_${season^^}_ENABLED=true"
  fi
done
