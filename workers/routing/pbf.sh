#!/usr/bin/env bash
# PBF for the routing graph – download and merge what the area lookup names, cutting nothing
# (an edge missing its other end is a dead end). Not `plan/pbf.sh`, which cuts a region.
#
# In:  AREA (key in routing-areas.json), OSMFR_BASE
# Out: data/routing.osm.pbf and `pbf_mb` to GITHUB_OUTPUT

set -euo pipefail
mkdir -p data steps-out
T=$(date +%s)

: "${AREA:?give AREA – a key from workers/data/routing-areas.json}"
BASE="${OSMFR_BASE:-https://download.openstreetmap.fr/extracts}"

mapfile -t PBFS < <(python3 - "$AREA" <<'PY'
import json, os, sys
here = os.path.join("workers", "data", "routing-areas.json")
areas = (json.load(open(here, encoding="utf-8")).get("areas") or {})
area = areas.get(sys.argv[1])
if not area:
    sys.exit(f"::error::Area `{sys.argv[1]}` isn't in workers/data/"
             f"routing-areas.json. Known: {', '.join(sorted(areas))}.")
for p in area["pbf"]:
    print(p)
PY
)
echo "Area \`$AREA\`: ${#PBFS[@]} extract(s) – ${PBFS[*]}"

# hundreds of MB to GBs: the plan before the slow part
echo "::group::Downloading PBF"
i=0
FILES=()
for p in "${PBFS[@]}"; do
  i=$(( i + 1 ))
  out="data/$(basename "$p").osm.pbf"
  echo "[$i/${#PBFS[@]}] $BASE/$p-latest.osm.pbf"
  # a foreign server's short outage must not fail an hours-long build
  curl -fSL --retry 5 --retry-delay 10 --retry-all-errors --connect-timeout 60 \
    -o "$out" "$BASE/$p-latest.osm.pbf"
  echo "    $(du -h "$out" | cut -f1)"
  FILES+=("$out")
done
echo "::endgroup::"

if [ "${#FILES[@]}" -eq 1 ]; then
  mv "${FILES[0]}" data/routing.osm.pbf
else
  # `merge`, not `cat`: border nodes are unified by id, or the graph splits in two
  echo "::group::Merging ${#FILES[@]} extracts (osmium merge)"
  osmium merge --overwrite -o data/routing.osm.pbf "${FILES[@]}"
  echo "::endgroup::"
  rm -f "${FILES[@]}"
fi

MB=$(( $(stat -c%s data/routing.osm.pbf) / 1048576 ))
echo "PBF for the graph: ${MB} MB"
echo "pbf_mb=$MB" >> "$GITHUB_OUTPUT"
printf '%s\t%s\t%s\t%s\n' "10" "PBF for the routing graph" "$(( $(date +%s) - T ))" \
  "${#PBFS[@]} extract(s), ${MB} MB" >> steps-out/routing.tsv
