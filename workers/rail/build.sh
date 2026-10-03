#!/usr/bin/env bash
# Railways and aerialways from OSM → `{region}-rail.pmtiles` and `{region}-rail-routing.pmtiles`.
# Its share of the page size comes from `BUDGET_RAIL_PCT`.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'
python3 -c 'import pmtiles' 2>/dev/null \
  || python3 -m pip install --quiet --break-system-packages pmtiles

T_F=$(date +%s)
osmium tags-filter --overwrite -o data/rail.osm.pbf \
  data/region.osm.pbf --expressions=workers/rail/filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/rail.osm.pbf)
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/rail.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "67" "Railway and aerialway prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/rail.tsv

# an empty cutout isn't an error – there may be no track at all
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has no track and no aerialway – the \`railways\` package isn't made."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

RZ_="$OPT_RAIL_MAXZOOM"
case "$RZ_" in ''|*[!0-9]*) RZ_=15 ;; esac
if [ "$RZ_" -gt 16 ]; then RZ_=16; fi

# planetiler silently drops what has min_zoom above maxzoom
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/rail/rail.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$RZ_" ]; then
  echo "::error::workers/rail/rail.yml has blocks with min_zoom up to ${TOPZ}, but tiles go to z${RZ_}. Raise rail_maxzoom to ${TOPZ}, or lower min_zoom of those blocks."
  exit 1
fi

mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

python3 workers/rail/lines.py --pbf=data/rail.osm.pbf --out=data/rail-lines.osm.pbf

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-rail.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/rail/rail.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$RZ_" --render_maxzoom="$RZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force
# the region ends in the tiles, not in the style
workers/lib/clip-tiles.sh "$OUT"
printf '%s\t%s\t%s\t%s\n' "68" "Railways and aerialways → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $RZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/rail.tsv

# country signs ship with the map, the app doesn't draw them itself
node workers/rail/signs.mjs --region="$REGION_KEY" --out="_site/tiles/${REGION_KEY}-signs"

# track network for navigation – the road format, its own dictionary
T_R=$(date +%s)
ROUT="_site/tiles/${REGION_KEY}-rail-routing.pmtiles"
python3 workers/routing/tiles.py --pbf=data/rail.osm.pbf --out="$ROUT" \
  --region-key="$REGION_KEY" --name="${REGION_NAME:-$REGION_KEY}" \
  --dictionary=workers/data/rail-routing-tags.json --profile-step=0
ROUTING=false
if [ -s "$ROUT" ]; then
  ROUTING=true
  printf '%s\t%s\t%s\t%s\n' "69" "Track network for navigation" "$(( $(date +%s) - T_R ))" \
    "$(du -h "$ROUT" | cut -f1)" >> steps-out/rail.tsv
fi

MB=$(( ($(stat -c%s "$OUT") + $( [ -s "$ROUT" ] && stat -c%s "$ROUT" || echo 0 )) / 1048576 ))
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
RBUDGET_MB=$(( LIMIT_MB * BUDGET_RAIL_PCT / 100 ))
if [ "$MB" -gt "$RBUDGET_MB" ]; then
  echo "::warning::Railways take ${MB} MB, above their ${RBUDGET_MB} MB share of the page budget. Lower rail_maxzoom or raise BUDGET_RAIL_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$RZ_" >> "$GITHUB_OUTPUT"
echo "routing=$ROUTING" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh _site/tiles/"${REGION_KEY}"-rail*.pmtiles
