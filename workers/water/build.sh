#!/usr/bin/env bash
# Vodstvo z OSM → `{región}-water.pmtiles`.
#
# ČO TO JE A PREČO: rozpis je v hlavičke `workers/water/water.yml`. Krátko –
# voda v mape je rozdelená do troch vrstiev OpenMapTiles (`water`, `waterway`,
# `water_name`), meno je v inej vrstve než geometria a potoky vypadávajú podľa
# zoomu. Tu je všetko vodné v jednom archíve a meno na tom istom prvku.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map-region.yml` má strop 128 kB a nad ním ho
# GitHub ticho neprijme (stráži „Kontrola · lint workflowov").
#
# PREDFILTER MUSÍ DOŤAHOVAŤ ČLENOV RELÁCIÍ: veľké jazerá a priehrady sú
# multipolygóny, ktorých členovia `natural=water` nemajú. Bez nich by po
# Domaši v dlaždiciach ticho neostalo nič. `osmium tags-filter` to robí SÁM
# a vypína sa to až `-R`/`--omit-referenced` – preto tu žiadny taký prepínač
# nie je. (`-r` neexistuje, osmium na ňom skončí s „unrecognised option".)
#
# Podiel na veľkosti stránky berie z `BUDGET_WATER_PCT` (env workflowu).

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# ---- 1. predfilter: len voda ----
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/water.osm.pbf \
  data/region.osm.pbf --expressions=workers/water/filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/water.osm.pbf)
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/water.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "65" "Predfilter vodstva" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/water.tsv

# Prázdny výsledok nie je chyba – 4 km² rýchleho testu môže padnúť na hrebeň
# bez jediného potoka. Že vrstva v mape nie je, povie `obsah.json`.
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jeden tok ani vodná plocha – balík \`vodstvo\` sa nevyrobí."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. dlaždice ----
WZ_="$OPT_WATER_MAXZOOM"
case "$WZ_" in ''|*[!0-9]*) WZ_=14 ;; esac
if [ "$WZ_" -gt 16 ]; then WZ_=16; fi

# Poistka proti tichej strate: čo má v schéme `min_zoom` nad maxzoomom,
# Planetiler zahodí BEZ SLOVA. Tá istá poistka ako v jobe `transport`.
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/water/water.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$WZ_" ]; then
  echo "::error::workers/water/water.yml má bloky s min_zoom až ${TOPZ}, ale dlaždice idú po z${WZ_} – tie sa do nich vôbec nedostanú (pri jarkoch a odvodňovacích kanáloch je to celá poľnohospodárska krajina). Zdvihni water_maxzoom na ${TOPZ}, alebo tým blokom zníž min_zoom."
  exit 1
fi

# Ten istý orez na región ako pri mape (workers/lib/region-clip.sh) – voda
# nesmie siahať ďalej než mapa pod ňou.
mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")

T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-water.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/water/water.yml \
  "${CLIP[@]}" \
  --output="$OUT" \
  --maxzoom="$WZ_" --render_maxzoom="$WZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
WBUDGET_MB=$(( LIMIT_MB * BUDGET_WATER_PCT / 100 ))
if [ "$MB" -gt "$WBUDGET_MB" ]; then
  echo "::warning::Vodstvo má ${MB} MB, čo je nad podielom ${WBUDGET_MB} MB z rozpočtu stránky. Zníž water_maxzoom alebo zdvihni BUDGET_WATER_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$WZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "66" "Vodstvo → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $WZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/water.tsv
