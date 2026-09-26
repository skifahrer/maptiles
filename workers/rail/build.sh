#!/usr/bin/env bash
# Železnice a lanovky z OSM → `{región}-rail.pmtiles` a `{región}-rail-routing.pmtiles`.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 kB.
# Podiel na veľkosti stránky berie z `BUDGET_RAIL_PCT`.

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
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/rail.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "67" "Predfilter železníc a lanoviek" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/rail.tsv

# prázdny výrez nie je chyba – trať ani lanovka byť nemusí
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jedna koľaj ani lanovka – balík \`zeleznice\` sa nevyrobí."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

RZ_="$OPT_RAIL_MAXZOOM"
case "$RZ_" in ''|*[!0-9]*) RZ_=15 ;; esac
if [ "$RZ_" -gt 16 ]; then RZ_=16; fi

# planetiler zahodí bez slova, čo má min_zoom nad maxzoomom
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/rail/rail.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$RZ_" ]; then
  echo "::error::workers/rail/rail.yml má bloky s min_zoom až ${TOPZ}, ale dlaždice idú po z${RZ_}. Zdvihni rail_maxzoom na ${TOPZ}, alebo tým blokom zníž min_zoom."
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
printf '%s\t%s\t%s\t%s\n' "68" "Železnice a lanovky → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $RZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/rail.tsv

# značky krajiny idú s mapou, appka ich nekreslí sama
node workers/rail/signs.mjs --region="$REGION_KEY" --out="_site/tiles/${REGION_KEY}-signs"

# koľajová sieť na navigáciu – ten istý formát ako cestná, vlastný slovník
T_R=$(date +%s)
ROUT="_site/tiles/${REGION_KEY}-rail-routing.pmtiles"
python3 workers/routing/tiles.py --pbf=data/rail.osm.pbf --out="$ROUT" \
  --region-key="$REGION_KEY" --name="${REGION_NAME:-$REGION_KEY}" \
  --slovnik=workers/data/rail-routing-tags.json --profil-krok=0
ROUTING=false
if [ -s "$ROUT" ]; then
  ROUTING=true
  printf '%s\t%s\t%s\t%s\n' "69" "Koľajová sieť na navigáciu" "$(( $(date +%s) - T_R ))" \
    "$(du -h "$ROUT" | cut -f1)" >> steps-out/rail.tsv
fi

MB=$(( ($(stat -c%s "$OUT") + $( [ -s "$ROUT" ] && stat -c%s "$ROUT" || echo 0 )) / 1048576 ))
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
RBUDGET_MB=$(( LIMIT_MB * BUDGET_RAIL_PCT / 100 ))
if [ "$MB" -gt "$RBUDGET_MB" ]; then
  echo "::warning::Železnice majú ${MB} MB, čo je nad podielom ${RBUDGET_MB} MB z rozpočtu stránky. Zníž rail_maxzoom alebo zdvihni BUDGET_RAIL_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$RZ_" >> "$GITHUB_OUTPUT"
echo "routing=$ROUTING" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh _site/tiles/"${REGION_KEY}"-rail*.pmtiles
