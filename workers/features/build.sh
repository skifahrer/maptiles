#!/usr/bin/env bash
# Landscape features outside OpenMapTiles → `{region}-features.pmtiles` (lines, areas)
# and `{region}-points.pmtiles` (points): two packages in the app, one prefilter.
# Points share the `BUDGET_FEATURES_PCT` share of the page size.

set -euo pipefail
mkdir -p _site/tiles data
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# tags in `filter.txt` beside the schemas; without it Planetiler reads the whole country again
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/features.osm.pbf \
  data/region.osm.pbf --expressions=workers/features/filter.txt
BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/features.osm.pbf)
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/features.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "57" "Landscape feature prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/features.tsv

# an empty result isn't an error; both layers come from this prefilter
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has no landscape feature – the map goes without them."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  echo "points_enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

FZ="$OPT_FEATURES_MAXZOOM"
case "$FZ" in ''|*[!0-9]*) FZ=15 ;; esac
if [ "$FZ" -gt 16 ]; then FZ=16; fi

# Planetiler silently drops `min_zoom` above maxzoom; points share `$FZ`, so check both
TOPZ=$(grep -hoE 'min_zoom: [0-9]+' \
       workers/features/features.yml workers/features/points.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$FZ" ]; then
  echo "::warning::workers/features/features.yml or points.yml has classes with min_zoom up to ${TOPZ}, but tiles go to z${FZ} – those never get in. Raise features_maxzoom to ${TOPZ}, or lower min_zoom of those classes."
fi

# the map's own region cut
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-features.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/features/features.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$FZ" --render_maxzoom="$FZ" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

# points: a second pass over the same PBF, its own file for its own package
POUT="_site/tiles/${REGION_KEY}-points.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/features/points.yml \
  "${CLIP[@]}" \
  --output="$POUT" \
  --maxzoom="$FZ" --render_maxzoom="$FZ" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

# the OUTPUT is measured: the shared prefilter may hold lines and not one point
PBYTES=$(stat -c%s "$POUT")
if [ "$PBYTES" -lt 1000 ]; then
  echo "::warning::This area has no point feature (spring, cave, lookout tower, …) – the map goes without them."
  # deleted, or `workers/deploy/files.py` would find it by name for the `points` package
  rm -f "$POUT"
  echo "points_enabled=false" >> "$GITHUB_OUTPUT"
  PMB=0
else
  echo "points_enabled=true" >> "$GITHUB_OUTPUT"
  PMB=$(( PBYTES / 1048576 ))
  ls -lh "$POUT"
fi
echo "points_size_mb=$PMB" >> "$GITHUB_OUTPUT"

# `deploy` checks the total again, but this layer's excess is said here
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
FBUDGET_MB=$(( LIMIT_MB * BUDGET_FEATURES_PCT / 100 ))
TOTAL_MB=$(( MB + PMB ))
if [ "$TOTAL_MB" -gt "$FBUDGET_MB" ]; then
  echo "::warning::Landscape features (lines, areas and points) take ${TOTAL_MB} MB together, above their ${FBUDGET_MB} MB share of the page budget. Lower features_maxzoom or raise BUDGET_FEATURES_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$FZ" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
# `$POUT` may be gone (deleted above)
POINTS_SIZE=$([ -s "$POUT" ] && du -h "$POUT" | cut -f1 || echo "none")
printf '%s\t%s\t%s\t%s\n' "58" "Landscape features → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $FZ, lines+areas $(du -h "$OUT" | cut -f1), points $POINTS_SIZE" \
  >> steps-out/features.tsv
