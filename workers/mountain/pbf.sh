#!/usr/bin/env bash
# The range's OSM data: each extract it names (`OSM_URLS`), cut to its box, then merged.
# `-S types=…`: protected areas are `type=boundary`, which `smart` leaves incomplete.
set -euo pipefail
mkdir -p data

if [ -s data/region.osm.pbf ]; then
  echo "PBF from cache ✓ ($(du -h data/region.osm.pbf | cut -f1))"
  exit 0
fi
command -v osmium >/dev/null \
  || { sudo apt-get update -qq && sudo apt-get install -y -qq osmium-tool; }

# osm.fr first, as every build; Geofabrik spells the same extracts the same way
mirror() { printf '%s' "$1" | sed 's#^https://download.openstreetmap.fr/extracts/#https://download.geofabrik.de/#'; }

cuts=()
i=0
for url in $OSM_URLS; do
  i=$((i + 1))
  if ! curl -fL --retry 3 --retry-delay 5 -o data/extract.osm.pbf "$url"; then
    echo "::warning::$url didn't download – trying $(mirror "$url")"
    curl -fL --retry 3 --retry-delay 5 -o data/extract.osm.pbf "$(mirror "$url")"
  fi
  osmium extract --overwrite -s smart -S types=multipolygon,boundary \
    -b "$MOUNTAIN_BBOX" -o "data/cut-$i.osm.pbf" data/extract.osm.pbf
  rm -f data/extract.osm.pbf
  echo "$(du -h "data/cut-$i.osm.pbf" | cut -f1) from $url"
  cuts+=("data/cut-$i.osm.pbf")
done

# a way on the border is in both extracts; merge keeps one copy of each object
if [ "${#cuts[@]}" -eq 1 ]; then
  mv "${cuts[0]}" data/region.osm.pbf
else
  osmium merge --overwrite -o data/region.osm.pbf "${cuts[@]}"
  rm -f "${cuts[@]}"
fi
echo "$(du -h data/region.osm.pbf | cut -f1) of OSM over $MOUNTAIN_BBOX"
