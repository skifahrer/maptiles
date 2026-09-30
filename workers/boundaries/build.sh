#!/usr/bin/env bash
# Area borders and names from OSM → `{region}-boundaries.pmtiles`; see `boundaries.yml`.
# The prefilter must pull relation members – `tags-filter` does unless `-R`, so none here.
# Its share of the page size comes from `BUDGET_BOUNDARIES_PCT`.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

T_F=$(date +%s)
osmium tags-filter --overwrite -o data/boundaries.osm.pbf \
  data/region.osm.pbf --expressions=workers/boundaries/filter.txt

# the state border relation comes whole from `plan/pbf.sh`, so cut it to the region
workers/lib/region-cut.sh data/boundaries.osm.pbf "$REGION_BBOX"

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/boundaries.osm.pbf)
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/boundaries.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "63" "Border prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/boundaries.tsv

# empty isn't an error for a small test; `contents.json` says the layer is absent
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has no administrative border or settlement – the \`boundaries\` package isn't made."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

BZ_="$OPT_BOUNDARIES_MAXZOOM"
case "$BZ_" in ''|*[!0-9]*) BZ_=12 ;; esac
if [ "$BZ_" -gt 16 ]; then BZ_=16; fi

# Planetiler silently drops `min_zoom` above maxzoom
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/boundaries/boundaries.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$BZ_" ]; then
  echo "::error::workers/boundaries/boundaries.yml has blocks with min_zoom up to ${TOPZ}, but tiles go to z${BZ_} – those never get in (villages and hamlets are most settlements). Raise boundaries_maxzoom to ${TOPZ}, or lower min_zoom of those blocks."
  exit 1
fi

# the whole state border relation needs the region cut too; districts nest, so none splits
T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-boundaries.pmtiles"
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/boundaries/boundaries.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$BZ_" --render_maxzoom="$BZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
BBUDGET_MB=$(( LIMIT_MB * BUDGET_BOUNDARIES_PCT / 100 ))
if [ "$MB" -gt "$BBUDGET_MB" ]; then
  echo "::warning::Borders take ${MB} MB, above their ${BBUDGET_MB} MB share of the page budget. Lower boundaries_maxzoom or raise BUDGET_BOUNDARIES_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$BZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "64" "Borders → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $BZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/boundaries.tsv
