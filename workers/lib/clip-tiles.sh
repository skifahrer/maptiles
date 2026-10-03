#!/usr/bin/env bash
# Cut finished vector .pmtiles to the region polygon.
set -euo pipefail

REGION="${REGION_GEOJSON:-data/region.geojson}"
python3 -c 'import pmtiles, mapbox_vector_tile, shapely' 2>/dev/null \
  || python3 -m pip install --quiet --break-system-packages pmtiles mapbox-vector-tile shapely \
  || python3 -m pip install --quiet pmtiles mapbox-vector-tile shapely

for ARCHIVE in "$@"; do
  [ -s "$ARCHIVE" ] || continue
  python3 workers/lib/clip-tiles.py "$ARCHIVE" --region="$REGION"
done
