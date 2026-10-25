#!/usr/bin/env bash
# The range's OSM data: its country's osm.fr export, cut to the range's box.
# `-S types=…`: protected areas are `type=boundary`, which `smart` leaves incomplete.
set -euo pipefail
mkdir -p data

if [ -s data/region.osm.pbf ]; then
  echo "PBF from cache ✓ ($(du -h data/region.osm.pbf | cut -f1))"
  exit 0
fi
command -v osmium >/dev/null \
  || { sudo apt-get update -qq && sudo apt-get install -y -qq osmium-tool; }

curl -fL --retry 3 --retry-delay 5 -o data/country.osm.pbf "$OSMFR_URL"
osmium extract --overwrite -s smart -S types=multipolygon,boundary \
  -b "$MOUNTAIN_BBOX" -o data/region.osm.pbf data/country.osm.pbf
rm -f data/country.osm.pbf
echo "$(du -h data/region.osm.pbf | cut -f1) of OSM over $MOUNTAIN_BBOX"
