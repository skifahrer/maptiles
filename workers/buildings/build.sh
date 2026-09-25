#!/usr/bin/env bash
# Sídla z OSM → `{región}-buildings.pmtiles` – každá budova s výmerou a menom.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 kB.
# Podiel na veľkosti stránky berie z `BUDGET_BUILDINGS_PCT`.

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
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/buildings.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "73" "Predfilter sídiel" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/buildings.tsv

# prázdny výrez nie je chyba – rýchly test môže padnúť do lesa
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jedna budova – balík \`sidla\` sa nevyrobí."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

BZ_="$OPT_BUILDINGS_MAXZOOM"
case "$BZ_" in ''|*[!0-9]*) BZ_=14 ;; esac
if [ "$BZ_" -gt 16 ]; then BZ_=16; fi

# planetiler zahodí bez slova, čo má min_zoom nad maxzoomom
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/buildings/buildings.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$BZ_" ]; then
  echo "::error::workers/buildings/buildings.yml má bloky s min_zoom až ${TOPZ}, ale dlaždice idú po z${BZ_}. Zdvihni buildings_maxzoom na ${TOPZ}, alebo tým blokom zníž min_zoom."
  exit 1
fi

T_A=$(date +%s)
python3 workers/buildings/areas.py --pbf=data/buildings.osm.pbf \
  --out=data/buildings-area.osm.pbf
printf '%s\t%s\t%s\t%s\n' "74" "Výmera budov" "$(( $(date +%s) - T_A ))" "" \
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
  echo "::warning::Sídla majú ${MB} MB, čo je nad podielom ${BBUDGET_MB} MB z rozpočtu stránky. Zníž buildings_maxzoom alebo zdvihni BUDGET_BUILDINGS_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$BZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "75" "Sídla → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $BZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/buildings.tsv
