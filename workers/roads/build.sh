#!/usr/bin/env bash
# Obmedzenia na ceste z OSM → `{región}-roads.pmtiles`.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map.yml` má strop 128 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# DVA PRIECHODY FILTROM, a nie jeden. `osmium tags-filter` vie len ALEBO, kým
# schéma chce A: „cesta, ktorá má obmedzenie". Jeden priechod nad kľúčmi
# z `filter.txt` by pustil aj obmedzenia mimo ciest (`maxheight` má aj rieka
# pod mostom, `maxspeed` aj železnica) a jeden priechod nad `w/highway` by
# nechal všetky cesty, teda takmer celé PBF. Sú preto za sebou: najprv cesty,
# potom z nich tie s obmedzením. Merané časy sú v logu behu.
#
# Podiel na veľkosti stránky berie z `BUDGET_ROADS_PCT` (env workflowu).

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# ---- 1. predfilter, prvý priechod: len cesty ----
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/roads-hw.osm.pbf \
  data/region.osm.pbf w/highway

# ---- 2. predfilter, druhý priechod: z ciest tie s obmedzením ----
osmium tags-filter --overwrite -o data/roads.osm.pbf \
  data/roads-hw.osm.pbf --expressions=workers/roads/filter.txt
rm -f data/roads-hw.osm.pbf

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/roads.osm.pbf)
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/roads.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "59" "Predfilter obmedzení na ceste" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/roads.tsv

# Prázdny výsledok nie je chyba – 4 km² rýchleho testu nemusí mať ani jeden
# podjazd. Mapa vtedy pôjde bez tejto vrstvy a štýl ju nepridá.
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jedna cesta s obmedzením (výška, šírka, hmotnosť, rýchlosť) – mapa pôjde bez tejto vrstvy."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 3. dlaždice ----
RZ="$OPT_ROADS_MAXZOOM"
case "$RZ" in ''|*[!0-9]*) RZ=15 ;; esac
if [ "$RZ" -gt 16 ]; then RZ=16; fi

# Poistka proti tichej strate: čo má v schéme `min_zoom` nad maxzoomom,
# Planetiler zahodí BEZ SLOVA. Tá istá poistka ako v jobe `features`.
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/roads/roads.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$RZ" ]; then
  echo "::error::workers/roads/roads.yml má bloky s min_zoom až ${TOPZ}, ale dlaždice idú po z${RZ} – tie sa do nich vôbec nedostanú. Zdvihni roads_maxzoom na ${TOPZ}, alebo tým blokom zníž min_zoom."
  exit 1
fi

# Ten istý orez na región ako pri mape (workers/lib/region-clip.sh) –
# obmedzenia nesmú siahať ďalej než mapa pod nimi.
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-roads.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/roads/roads.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$RZ" --render_maxzoom="$RZ" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

# Poistka na rozpočet stránky. `deploy` overí súčet ešte raz, ale keď je nad
# podielom práve táto vrstva, má sa to povedať tu.
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
RBUDGET_MB=$(( LIMIT_MB * BUDGET_ROADS_PCT / 100 ))
if [ "$MB" -gt "$RBUDGET_MB" ]; then
  echo "::warning::Obmedzenia na ceste majú ${MB} MB, čo je nad podielom ${RBUDGET_MB} MB z rozpočtu stránky. Zníž roads_maxzoom alebo zdvihni BUDGET_ROADS_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$RZ" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "60" "Obmedzenia na ceste → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $RZ, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/roads.tsv
