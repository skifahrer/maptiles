#!/usr/bin/env bash
# Celá dopravná sieť z OSM → `{región}-transport.pmtiles`.
#
# ČO TO JE A PREČO: rozpis je v hlavičke `workers/transport/transport.yml`.
# Krátko – všetko, po čom sa dá cestovať (cesty od diaľnice po schody,
# železnice, trajekty, lanovky), v jednom archíve, ktorý sa dá stiahnuť bez
# zvyšku mapy. Je to VRSTVA NA POUŽITIE, nie druhé kreslenie: štýl si ju
# nepridáva, lebo cestnú sieť už kreslí základná mapa (rozpis pri balíku
# `linie` vo `workers/deploy/subory.py`).
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map-region.yml` má strop 128 kB a nad ním ho
# GitHub ticho neprijme (stráži „Kontrola · lint workflowov").
#
# JEDEN PRIECHOD FILTROM, nie dva ako pri obmedzeniach na ceste – dôvod je
# v hlavičke `workers/transport/filter.txt`.
#
# Podiel na veľkosti stránky berie z `BUDGET_TRANSPORT_PCT` (env workflowu).

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# ---- 1. predfilter: len to, po čom sa dá ísť ----
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/transport.osm.pbf \
  data/region.osm.pbf --expressions=workers/transport/filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/transport.osm.pbf)
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/transport.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "61" "Predfilter dopravnej siete" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/transport.tsv

# Prázdny výsledok nie je chyba – 4 km² rýchleho testu môže padnúť do lesa bez
# jedinej cesty. Mapa vtedy pôjde bez tejto vrstvy a balík `linie` bude o ňu
# ľahší; že tam nie je, povie `obsah.json` v balíku.
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jedna cesta, trať, trajekt ani lanovka – balík \`linie\` pôjde bez dopravnej siete."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. dlaždice ----
TZ_="$OPT_TRANSPORT_MAXZOOM"
case "$TZ_" in ''|*[!0-9]*) TZ_=14 ;; esac
if [ "$TZ_" -gt 16 ]; then TZ_=16; fi

# Poistka proti tichej strate: čo má v schéme `min_zoom` nad maxzoomom,
# Planetiler zahodí BEZ SLOVA. Tá istá poistka ako v joboch `features`
# a `roads`.
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/transport/transport.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$TZ_" ]; then
  echo "::error::workers/transport/transport.yml má bloky s min_zoom až ${TOPZ}, ale dlaždice idú po z${TZ_} – tie sa do nich vôbec nedostanú (pri \`service\` cestách je to každý príjazd k domu). Zdvihni transport_maxzoom na ${TOPZ}, alebo tým blokom zníž min_zoom."
  exit 1
fi

# Ten istý orez na región ako pri mape (workers/lib/region-clip.sh) – sieť
# nesmie siahať ďalej než mapa pod ňou.
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-transport.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/transport/transport.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$TZ_" --render_maxzoom="$TZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

# Poistka na rozpočet stránky. `deploy` overí súčet ešte raz, ale keď je nad
# podielom práve táto vrstva, má sa to povedať tu – je to najväčšia z vrstiev
# stavaných vlastnou schémou.
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TBUDGET_MB=$(( LIMIT_MB * BUDGET_TRANSPORT_PCT / 100 ))
if [ "$MB" -gt "$TBUDGET_MB" ]; then
  echo "::warning::Dopravná sieť má ${MB} MB, čo je nad podielom ${TBUDGET_MB} MB z rozpočtu stránky. Zníž transport_maxzoom alebo zdvihni BUDGET_TRANSPORT_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$TZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "62" "Dopravná sieť → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $TZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/transport.tsv
