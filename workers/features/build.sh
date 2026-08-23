#!/usr/bin/env bash
# Krajinné prvky mimo schémy OpenMapTiles → `{región}-features.pmtiles`.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map.yml` má strop 500 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# Zoznam tagov je vo `workers/features/filter.txt` vedľa schémy
# `workers/features/features.yml`, nech sa obe menia na jednom mieste. Bez predfiltra by
# Planetiler čítal celé Slovensko druhýkrát.
#
# POISTKA PROTI TICHEJ STRATE: čo má v schéme `min_zoom` nad maxzoomom,
# Planetiler zahodí bez slova – tak sa to najprv porovná a povie nahlas.
#
# Podiel na veľkosti stránky berie z `BUDGET_FEATURES_PCT` (env workflowu).

set -euo pipefail
mkdir -p _site/tiles data
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# ---- 1. predfilter ----
# Zoznam tagov je vo workers/features/filter.txt vedľa schémy, nech
# sa obe menia na jednom mieste. Bez neho by Planetiler čítal celé
# Slovensko druhýkrát; po ňom ostane zlomok.
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/features.osm.pbf \
  data/region.osm.pbf --expressions=workers/features/filter.txt
BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/features.osm.pbf)
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/features.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "57" "Predfilter krajinných prvkov" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/features.tsv

# Prázdny výsledok nie je chyba – malý testovací štvorec nemusí mať
# ani jeden násyp. Mapa vtedy pôjde bez tejto vrstvy.
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jeden krajinný prvok – mapa pôjde bez nich."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. dlaždice ----
FZ="$OPT_FEATURES_MAXZOOM"
case "$FZ" in ''|*[!0-9]*) FZ=15 ;; esac
if [ "$FZ" -gt 16 ]; then FZ=16; fi

# Poistka proti tichej strate: čo má v schéme `min_zoom` nad
# maxzoomom, Planetiler zahodí bez slova. Viď workers/features/features.yml.
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/features/features.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$FZ" ]; then
  echo "::warning::workers/features/features.yml má triedy s min_zoom až ${TOPZ}, ale dlaždice idú po z${FZ} – tie sa do nich vôbec nedostanú. Zdvihni features_maxzoom na ${TOPZ}, alebo tým triedam zníž min_zoom."
fi

# Ten istý orez na región ako pri mape (workers/lib/region-clip.sh) – prvky
# nesmú siahať ďalej než mapa pod nimi.
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

# Poistka na rozpočet stránky. `deploy` overí súčet ešte raz, ale
# keď je nad podielom práve táto vrstva, má sa to povedať tu.
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
FBUDGET_MB=$(( LIMIT_MB * BUDGET_FEATURES_PCT / 100 ))
if [ "$MB" -gt "$FBUDGET_MB" ]; then
  echo "::warning::Krajinné prvky majú ${MB} MB, čo je nad podielom ${FBUDGET_MB} MB z rozpočtu stránky. Zníž features_maxzoom alebo zdvihni BUDGET_FEATURES_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$FZ" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "58" "Krajinné prvky → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $FZ, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/features.tsv
