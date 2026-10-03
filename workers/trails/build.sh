#!/usr/bin/env bash
# Marked trails from OSM relations → `{region}-trails.pmtiles`; none is fine for a small test.
# Its share of the page size comes from `BUDGET_TRAILS_PCT`.

set -euo pipefail
mkdir -p _site/tiles data
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
# versions 3 and 4 both have the `SimpleHandler` routes.py uses
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'

# a node index over the whole country would take GBs; keep route relations and members
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/trails.osm.pbf \
  data/region.osm.pbf \
  r/route=hiking,foot,walking,bicycle,mtb,ski,nordic,skitour,horse,via_ferrata
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/trails.osm.pbf | cut -f1)"

python3 workers/trails/routes.py \
  --pbf=data/trails.osm.pbf \
  --out=data/trails.geojson \
  --stats=steps-out/trail-stats.txt
# shellcheck disable=SC1091
. steps-out/trail-stats.txt
printf '%s\t%s\t%s\t%s\n' "55" "Marked trails from OSM" "$(( $(date +%s) - T_F ))" \
  "${routes:-0} routes, ${features:-0} sections, ${multi:-0} ways with several routes, ${marked:-0} with a mark" \
  >> steps-out/trails.tsv

if [ "${features:-0}" -eq 0 ]; then
  echo "::warning::This area has no marked trail – the map goes without them."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

TZ_="$OPT_TRAILS_MAXZOOM"
case "$TZ_" in ''|*[!0-9]*) TZ_=14 ;; esac
if [ "$TZ_" -gt 16 ]; then TZ_=16; fi

# the map's own region cut, so trails don't reach beyond it
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/trails/trails.yml \
  "${CLIP[@]}" \
  --output="_site/tiles/${REGION_KEY}-trails.pmtiles" \
  --maxzoom="$TZ_" --render_maxzoom="$TZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

OUT="_site/tiles/${REGION_KEY}-trails.pmtiles"
# the region ends in the tiles, not in the style
workers/lib/clip-tiles.sh "$OUT"
MB=$(( $(stat -c%s "$OUT") / 1048576 ))

# said here rather than in `deploy`
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TBUDGET_MB=$(( LIMIT_MB * BUDGET_TRAILS_PCT / 100 ))
if [ "$MB" -gt "$TBUDGET_MB" ]; then
  echo "::warning::Trails take ${MB} MB, above their ${TBUDGET_MB} MB share of the page budget. Lower trails_maxzoom or raise BUDGET_TRAILS_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$TZ_" >> "$GITHUB_OUTPUT"
echo "count=${routes:-0}" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "56" "Marked trails → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $TZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/trails.tsv
