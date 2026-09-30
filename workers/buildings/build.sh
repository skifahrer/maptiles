#!/usr/bin/env bash
# Settlements from OSM → `{region}-buildings.pmtiles` – every building with area and name.
# Its share of the page size comes from `BUDGET_BUILDINGS_PCT`.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'

T_F=$(date +%s)
osmium tags-filter --overwrite -o data/buildings.osm.pbf \
  data/region.osm.pbf --expressions=workers/buildings/filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/buildings.osm.pbf)
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/buildings.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "73" "Settlement prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/buildings.tsv

# an empty cutout isn't an error – a quick test may land in a forest
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has no building – the \`settlements\` package isn't made."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

BZ_="$OPT_BUILDINGS_MAXZOOM"
case "$BZ_" in ''|*[!0-9]*) BZ_=14 ;; esac
if [ "$BZ_" -gt 16 ]; then BZ_=16; fi

# planetiler silently drops what has min_zoom above maxzoom
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/buildings/buildings.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$BZ_" ]; then
  echo "::error::workers/buildings/buildings.yml has blocks with min_zoom up to ${TOPZ}, but tiles go to z${BZ_}. Raise buildings_maxzoom to ${TOPZ}, or lower min_zoom of those blocks."
  exit 1
fi

T_A=$(date +%s)
python3 workers/buildings/areas.py --pbf=data/buildings.osm.pbf \
  --out=data/buildings-area.osm.pbf
printf '%s\t%s\t%s\t%s\n' "74" "Building areas" "$(( $(date +%s) - T_A ))" "" \
  >> steps-out/buildings.tsv

mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-buildings.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/buildings/buildings.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$BZ_" --render_maxzoom="$BZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
BBUDGET_MB=$(( LIMIT_MB * BUDGET_BUILDINGS_PCT / 100 ))
if [ "$MB" -gt "$BBUDGET_MB" ]; then
  echo "::warning::Settlements take ${MB} MB, above their ${BBUDGET_MB} MB share of the page budget. Lower buildings_maxzoom or raise BUDGET_BUILDINGS_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$BZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "75" "Settlements → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $BZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/buildings.tsv
