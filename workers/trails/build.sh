#!/usr/bin/env bash
# Značené trasy z OSM relácií → `{región}-trails.pmtiles`.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 kB.
#
# Predfilter preto, že index polôh uzlov nad celým Slovenskom (~380 MB) by
# zobral niekoľko GB pamäte; `osmium tags-filter` nechá len relácie trás a ich
# členov a až nad tým beží `routes.py`.
#
# Prázdny výsledok nie je chyba: malý testovací štvorec nemusí mať ani jednu
# značenú trasu.
#
# Podiel na veľkosti stránky berie z `BUDGET_TRAILS_PCT`.

set -euo pipefail
mkdir -p _site/tiles data
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
# pyosmium je v Ubuntu ako balík; keď tam nie je (iný obraz
# runnera), doinštaluje sa z PyPI. Verzia 3 aj 4 majú `SimpleHandler`,
# ktorý workers/trails/routes.py používa.
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'

# ---- 1. predfilter ----
# Celé Slovensko je ~380 MB a index polôh uzlov nad ním by zobral
# niekoľko GB pamäte. `tags-filter` nechá len relácie trás a ich
# členov (cesty aj s uzlami), čo je zlomok veľkosti.
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/trails.osm.pbf \
  data/region.osm.pbf \
  r/route=hiking,foot,walking,bicycle,mtb,ski,nordic,skitour,horse,via_ferrata
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/trails.osm.pbf | cut -f1)"

# ---- 2. relácie → línie s pruhmi ----
python3 workers/trails/routes.py \
  --pbf=data/trails.osm.pbf \
  --out=data/trails.geojson \
  --stats=steps-out/trail-stats.txt
# shellcheck disable=SC1091
. steps-out/trail-stats.txt
printf '%s\t%s\t%s\t%s\n' "55" "Značené trasy z OSM" "$(( $(date +%s) - T_F ))" \
  "${routes:-0} trás, ${features:-0} úsekov, ${multi:-0} ciest s viac trasami, ${marked:-0} so značkou" \
  >> steps-out/trails.tsv

if [ "${features:-0}" -eq 0 ]; then
  echo "::warning::V tomto území nie je ani jedna značená trasa – mapa pôjde bez nich."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 3. dlaždice ----
TZ_="$OPT_TRAILS_MAXZOOM"
case "$TZ_" in ''|*[!0-9]*) TZ_=14 ;; esac
if [ "$TZ_" -gt 16 ]; then TZ_=16; fi

# Ten istý orez na región ako pri mape (workers/lib/region-clip.sh) – trasy
# nesmú siahať ďalej než mapa pod nimi.
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/trails/trails.yml \
  "${CLIP[@]}" \
  --output="_site/tiles/${REGION_KEY}-trails.pmtiles" \
  --maxzoom="$TZ_" --render_maxzoom="$TZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

OUT="_site/tiles/${REGION_KEY}-trails.pmtiles"
MB=$(( $(stat -c%s "$OUT") / 1048576 ))

# Poistka na rozpočet stránky. Trasy sú malé (jednotky MB), ale keby
# niekedy neboli, nech sa to ozve tu a nie až v `deploy`.
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TBUDGET_MB=$(( LIMIT_MB * BUDGET_TRAILS_PCT / 100 ))
if [ "$MB" -gt "$TBUDGET_MB" ]; then
  echo "::warning::Trasy majú ${MB} MB, čo je nad podielom ${TBUDGET_MB} MB z rozpočtu stránky. Zníž trails_maxzoom alebo zdvihni BUDGET_TRAILS_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$TZ_" >> "$GITHUB_OUTPUT"
echo "count=${routes:-0}" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "56" "Značené trasy → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $TZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/trails.tsv
