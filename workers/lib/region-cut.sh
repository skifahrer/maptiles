#!/usr/bin/env bash
# Drop from the PBF what lies wholly outside the region, so it can't get into a tile.
# By rectangle: a feature on the border itself has nodes right on the polygon line.
#
#   workers/lib/region-cut.sh data/water.osm.pbf "$REGION_BBOX"
set -euo pipefail

PBF="${1:?PBF to cut}"
BBOX="${2:-}"
POLY="${3:-data/region.poly}"

# the tiles' region; its warnings belong to the tiles' own call
mapfile -t CLIP < <(workers/lib/region-clip.sh "$BBOX" "$POLY" 2>/dev/null)

BOX=""
for A in "${CLIP[@]}"; do
  case "$A" in
    --bounds=*)  BOX="${A#--bounds=}" ;;
    # `+0`: as text "9.5" is greater than "16.8"
    --polygon=*) BOX=$(awk 'NF==2 && $1+0==$1 && $2+0==$2 {
                              lon = $1 + 0; lat = $2 + 0
                              if (k++ == 0) { w = e = lon; s = n = lat }
                              if (lon < w) w = lon; if (lon > e) e = lon
                              if (lat < s) s = lat; if (lat > n) n = lat
                            } END { if (k) printf "%.6f,%.6f,%.6f,%.6f", w, s, e, n }' \
                       "${A#--polygon=}") ;;
  esac
done

if [ -z "$BOX" ]; then
  echo "::warning::No region to cut the PBF by (neither polygon nor bbox), so it keeps what lies hundreds of kilometres beyond the region – visible on the lowest zooms." >&2
  exit 0
fi

BEFORE=$(stat -c%s "$PBF")
osmium extract --overwrite -s smart -b "$BOX" -o "${PBF%.osm.pbf}-cut.osm.pbf" "$PBF"
mv "${PBF%.osm.pbf}-cut.osm.pbf" "$PBF"
echo "Cut to region ($BOX): $(( BEFORE / 1048576 )) MB → $(( $(stat -c%s "$PBF") / 1048576 )) MB" >&2
