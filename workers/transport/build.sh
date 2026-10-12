#!/usr/bin/env bash
# OSM roads → `{region}-transport.pmtiles` (`transport.yml`), what cars don't fit →
# `{region}-paths.pmtiles` (`paths.yml`); two packages, downloadable alone.
# The style draws only road restrictions from them; both share `BUDGET_TRANSPORT_PCT`.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

T_F=$(date +%s)
osmium tags-filter --overwrite -o data/transport.osm.pbf \
  data/region.osm.pbf --expressions=workers/transport/filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/transport.osm.pbf)
echo "Prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/transport.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "61" "Transport network prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/transport.tsv

# empty isn't an error for a small test; `contents.json` says the package is absent
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has no road, path, ferry or aerialway – neither \`roads\` nor \`paths\` is made."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

TZ_="$OPT_TRANSPORT_MAXZOOM"
case "$TZ_" in ''|*[!0-9]*) TZ_=14 ;; esac
if [ "$TZ_" -gt 16 ]; then TZ_=16; fi

# Planetiler silently drops `min_zoom` above maxzoom
TOPZ=$(cat workers/transport/transport.yml workers/transport/paths.yml \
       | grep -oE 'min_zoom: [0-9]+' | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$TZ_" ]; then
  echo "::error::workers/transport/transport.yml or paths.yml has blocks with min_zoom up to ${TOPZ}, but tiles go to z${TZ_} – those never get in (for \`service\` roads that is every driveway). Raise transport_maxzoom to ${TOPZ}, or lower min_zoom of those blocks."
  exit 1
fi

# the map's own region cut
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-transport.pmtiles"
PATHS_OUT="_site/tiles/${REGION_KEY}-paths.pmtiles"
for pair in "transport:$OUT" "paths:$PATHS_OUT"; do
  java -Xmx4g -jar planetiler.jar generate-custom \
    --schema="workers/transport/${pair%%:*}.yml" \
    "${CLIP[@]}" \
    --output="${pair#*:}" \
    --maxzoom="$TZ_" --render_maxzoom="$TZ_" \
    --simplify_tolerance_at_max_zoom=0 \
    --min_feature_size_at_max_zoom=0 \
    --force
  # the region ends in the tiles, not in the style
  workers/lib/clip-tiles.sh "${pair#*:}"
done

# signs ride with the roads and in the base map; without them both still draw
T_RS=$(date +%s)
workers/transport/roadsigns.sh "$TZ_" "${CLIP[@]}" || {
  echo "::warning::Road signs weren't made – roads go without them."
  rm -f _site/tiles/"${REGION_KEY}"-roadsigns*
}
ROADSIGNS=false
[ -f "_site/tiles/${REGION_KEY}-roadsigns.pmtiles" ] && ROADSIGNS=true
printf '%s\t%s\t%s\t%s\n' "62.5" "Road signs → PMTiles and sprite" "$(( $(date +%s) - T_RS ))" \
  "$ROADSIGNS" >> steps-out/transport.tsv

MB=$(( $(stat -c%s "$OUT") / 1048576 ))
PATHS_MB=$(( $(stat -c%s "$PATHS_OUT") / 1048576 ))

# `deploy` checks the total again; the largest own-schema layer says its excess here
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TBUDGET_MB=$(( LIMIT_MB * BUDGET_TRANSPORT_PCT / 100 ))
if [ $(( MB + PATHS_MB )) -gt "$TBUDGET_MB" ]; then
  echo "::warning::Roads and paths take $(( MB + PATHS_MB )) MB, above their ${TBUDGET_MB} MB share of the page budget. Lower transport_maxzoom or raise BUDGET_TRANSPORT_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$TZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
echo "paths_enabled=true" >> "$GITHUB_OUTPUT"
echo "roadsigns_enabled=$ROADSIGNS" >> "$GITHUB_OUTPUT"
echo "paths_size_mb=$PATHS_MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT" "$PATHS_OUT"
printf '%s\t%s\t%s\t%s\n' "62" "Roads and paths → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $TZ_, roads $(du -h "$OUT" | cut -f1), paths $(du -h "$PATHS_OUT" | cut -f1)" \
  >> steps-out/transport.tsv
