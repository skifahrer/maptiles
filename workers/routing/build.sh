#!/usr/bin/env bash
# A region's routing network → `{region}-routing.pmtiles` (in the map and in `roads`).
# Tags travel, not costs (`docs/navigation.md` §10, format in `docs/routing-tiles.md`).
# An empty result isn't an error: a small test square may have no road.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'
python3 -c 'import pmtiles' 2>/dev/null \
  || python3 -m pip install --quiet --break-system-packages pmtiles

# classes come from the tag dictionary, not a second list here
T_F=$(date +%s)
python3 workers/routing/tags.py --filter > data/routing-filter.txt
osmium tags-filter --overwrite -o data/routing.osm.pbf \
  data/region.osm.pbf --expressions=data/routing-filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/routing.osm.pbf)
echo "Routing prefilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/routing.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "20" "Routing network prefilter" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/routing.tsv

if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::This area has no road one could take – no routing network is made."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# a height every 5 m along the road; Sonny 20 m is the fallback where DMR is missing
DEM_SOURCE="${ROUTING_DEM_SOURCE:-dmr5}"
DEM_FALLBACK="${ROUTING_DEM_FALLBACK:-sonny}"
PROFILE_STEP="${ROUTING_PROFILE_STEP_M:-5}"

# on the run page, since a log warning gets missed
no_heights() {
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  cat >> "$GITHUB_STEP_SUMMARY" <<TEXT
### Routing: archive without heights
\`${REGION_KEY}\` goes with \`height: false\` – bicycle and walker cost as if the
region were flat, and the route shows a dash instead of the climb.

To fix: **Data · DMR 5.0** (5 m, store \`dem-dmr5-v2\`) or **Data · elevation
models**, source \`sonny\` (20 m, all of Slovakia), then build the region again.
TEXT
}

from_fallback() {
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  cat >> "$GITHUB_STEP_SUMMARY" <<TEXT
### Routing: profile from a coarser model
\`${REGION_KEY}\` has not a single \`dmr5\` tile in the store, so edge profiles come
from \`${DEM_FALLBACK}\`. The step stays ${PROFILE_STEP} m, but four samples in a row
then share one model cell – the climb is smoothed, not measured.

To fix: **Data · DMR 5.0**, \`tiles: true\` over this region's degrees, then build
the region again.
TEXT
}

# returns 0 when the source downloaded
try_dem() {
  local source="$1"
  set +e
  workers/dem/fetch.sh "$DEM_BBOX" "dem/$source" steps-out/routing.tsv "$source"
  local rc=$?
  set -e
  [ "$rc" -eq 0 ] && [ -s "dem/$source/all.vrt" ]
}

DEM=()
if [ -n "${DEM_BBOX:-}" ]; then
  sudo apt-get install -y -qq gdal-bin
  python3 -c 'import numpy' 2>/dev/null \
    || python3 -m pip install --quiet --break-system-packages numpy
  if try_dem "$DEM_SOURCE"; then
    DEM=(--dem="dem/$DEM_SOURCE/all.vrt" --profile-step="$PROFILE_STEP")
  elif [ "$DEM_FALLBACK" != "$DEM_SOURCE" ] && try_dem "$DEM_FALLBACK"; then
    echo "::warning::$DEM_SOURCE isn't in the store for this region – the profile comes from $DEM_FALLBACK."
    from_fallback
    DEM=(--dem="dem/$DEM_FALLBACK/all.vrt" --profile-step="$PROFILE_STEP")
  else
    echo "::warning::The region's elevation model ($DEM_SOURCE nor $DEM_FALLBACK) didn't download – the archive goes without heights."
    no_heights
  fi
else
  echo "::warning::The region has no elevation model bbox (DEM_BBOX) – the archive goes without heights."
  no_heights
fi

# the node order over the WHOLE area (`order.sh`); without it `tiles.py` says so
ORDER=()
if [ -s data/routing-order.json ]; then
  ORDER=(--order=data/routing-order.json)
fi

COUNTRY="${ROUTING_COUNTRY:-}"
if [ -z "$COUNTRY" ]; then
  echo "::warning::The region has no ISO country code (\`iso\` in workers/data/regions.json), so archive edges say nothing of their country and the vignette has nothing to stand on."
fi

T_A=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-routing.pmtiles"
python3 workers/routing/tiles.py \
  --pbf=data/routing.osm.pbf \
  --out="$OUT" \
  --region-key="$REGION_KEY" \
  --name="$REGION_NAME" \
  --country="$COUNTRY" \
  "${ORDER[@]}" "${DEM[@]}"

if [ ! -s "$OUT" ]; then
  echo "::warning::No routing archive came out – nothing in the area one could take."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# the lint's own check – there over the lookup, here over the archive
python3 workers/lint/routing-tiles.py "$OUT"

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
RBUDGET_MB=$(( LIMIT_MB * BUDGET_ROUTING_PCT / 100 ))
if [ "$MB" -gt "$RBUDGET_MB" ]; then
  echo "::warning::The routing network takes ${MB} MB, above its ${RBUDGET_MB} MB share of the page budget. The lever is the tag dictionary (workers/data/routing-tags.json) – what isn't in it doesn't travel."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "21" "Routing network → PMTiles" "$(( $(date +%s) - T_A ))" \
  "$(du -h "$OUT" | cut -f1)" >> steps-out/routing.tsv
