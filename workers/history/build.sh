#!/usr/bin/env bash
# Army and history from OSM → `{region}-history.pmtiles`; themes and zooms in `history.yml`.
# Training areas and castles are multipolygons, so the prefilter pulls members (`tags-filter` does unless `-R`).
# Its share of the page size comes from `BUDGET_HISTORY_PCT`.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

T_F=$(date +%s)
osmium tags-filter --overwrite -o data/history.osm.pbf \
  data/region.osm.pbf --expressions=workers/history/filter.txt

# castles and training areas ride in as border members far away; a z8 tile would hold them
workers/lib/region-cut.sh data/history.osm.pbf "$REGION_BBOX"

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/history.osm.pbf)
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/history.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "71" "Army and history prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/history.tsv

# empty isn't an error for a small test; `contents.json` says the layer is absent
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has nothing military, historic, mined, embanked, abandoned or disused – the \`history\` package isn't made."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

WZ_="$OPT_HISTORY_MAXZOOM"
case "$WZ_" in ''|*[!0-9]*) WZ_=14 ;; esac
if [ "$WZ_" -gt 16 ]; then WZ_=16; fi

# Planetiler silently drops `min_zoom` above maxzoom
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/history/history.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$WZ_" ]; then
  echo "::error::workers/history/history.yml has blocks with min_zoom up to ${TOPZ}, but tiles go to z${WZ_} – those never get in (the densest themes). Raise history_maxzoom to ${TOPZ}, or lower min_zoom of those blocks."
  exit 1
fi

# the map's own region cut
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

# names in the app's languages, as the base map has them
workers/lib/name-languages.sh workers/history/history.yml data/history.yml

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-history.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=data/history.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$WZ_" --render_maxzoom="$WZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force
# the region ends in the tiles, not in the style
workers/lib/clip-tiles.sh "$OUT"

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
WBUDGET_MB=$(( LIMIT_MB * BUDGET_HISTORY_PCT / 100 ))
if [ "$MB" -gt "$WBUDGET_MB" ]; then
  echo "::warning::Army and history take ${MB} MB, above its ${WBUDGET_MB} MB share of the page budget. Lower history_maxzoom or raise BUDGET_HISTORY_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$WZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "72" "Army and history → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $WZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/history.tsv
