#!/usr/bin/env bash
# Krajinné prvky mimo schémy OpenMapTiles → DVA `.pmtiles`:
#   `{región}-features.pmtiles`   línie a plochy (workers/features/features.yml)
#   `{región}-points.pmtiles`     body (workers/features/points.yml)
#
# PREČO DVA SÚBORY Z JEDNÉHO JOBU: appka ponúka na stiahnutie „línie z OSM"
# a „body z OSM" ako dva rôzne balíky (`workers/deploy/publish-map.py`,
# balíky `cesty` a `body`) – rozpis prečo je v hlavičke `points.yml`. Vstup
# aj predfilter sú pre oba súbory ROVNAKÉ, líši sa len schéma, ktorú nad ním
# beží Planetiler – druhý beh je preto len pár riadkov navyše, nie druhý job.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map-region.yml` má strop 128 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# Zoznam tagov je vo `workers/features/filter.txt` vedľa oboch schém, nech sa
# všetky tri menia na jednom mieste. Bez predfiltra by Planetiler čítal celé
# Slovensko druhýkrát (a s bodmi zvlášť trikrát).
#
# POISTKA PROTI TICHEJ STRATE: čo má v schéme `min_zoom` nad maxzoomom,
# Planetiler zahodí bez slova – tak sa to najprv porovná a povie nahlas.
#
# Podiel na veľkosti stránky berie z `BUDGET_FEATURES_PCT` (env workflowu) –
# body sú doň započítané, nemajú vlastný podiel (rozpis pri poistke nižšie).

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
# ani jeden násyp. Mapa vtedy pôjde bez oboch vrstiev (línie aj body sú
# z toho istého predfiltra – prázdny vstup znamená prázdne oboje).
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jeden krajinný prvok – mapa pôjde bez nich."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  echo "points_enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. dlaždice ----
FZ="$OPT_FEATURES_MAXZOOM"
case "$FZ" in ''|*[!0-9]*) FZ=15 ;; esac
if [ "$FZ" -gt 16 ]; then FZ=16; fi

# Poistka proti tichej strate: čo má v schéme `min_zoom` nad
# maxzoomom, Planetiler zahodí bez slova. Body zdieľajú maxzoom s líniami
# a plochami (vlastný by bol štvrtý prepínač pre vrstvu, ktorá je jednotky
# MB) – poistka preto porovná OBE schémy proti tomu istému `$FZ`.
TOPZ=$(grep -hoE 'min_zoom: [0-9]+' \
       workers/features/features.yml workers/features/points.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$FZ" ]; then
  echo "::warning::workers/features/features.yml alebo points.yml má triedy s min_zoom až ${TOPZ}, ale dlaždice idú po z${FZ} – tie sa do nich vôbec nedostanú. Zdvihni features_maxzoom na ${TOPZ}, alebo tým triedam zníž min_zoom."
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

# ---- 3. body, DRUHÝ beh nad tým istým PBF ----
# Vlastný súbor kvôli balíku na stiahnutie (rozpis v hlavičke `points.yml`) –
# nie vlastná otázka o zoome či rozpočte, tie zdieľa s líniami a plochami
# vyššie.
POUT="_site/tiles/${REGION_KEY}-points.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/features/points.yml \
  "${CLIP[@]}" \
  --output="$POUT" \
  --maxzoom="$FZ" --render_maxzoom="$FZ" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

# Prázdne body nie sú chyba – testovací štvorec nemusí mať ani jeden prameň.
# Mapa vtedy pôjde bez tejto vrstvy, presne ako pri iných voliteľných
# vrstvách (rovnaké pravidlo ako pri predfiltri vyššie). Na rozdiel od PBF
# vyššie sa tu meria VÝSTUP Planetileru (`.pmtiles` má vlastnú hlavičku
# a adresár aj bez jedinej dlaždice, rádovo kilobajt) – práve preto, že
# spoločný predfilter môže mať cesty a plochy, a ani jeden bod.
PBYTES=$(stat -c%s "$POUT")
if [ "$PBYTES" -lt 1000 ]; then
  echo "::warning::V tomto území nie je ani jeden bodový krajinný prvok (prameň, jaskyňa, rozhľadňa, …) – mapa pôjde bez nich."
  # Súbor sa ZMAŽE, nenechá sa prázdny v `_site/tiles/` – inak by ho
  # `workers/deploy/subory.py` (`body_subory`, náhradné hľadanie podľa mena,
  # keď manifest kľúč nemá) zobralo do balíka `body`, hoci vrstva je
  # vypnutá. Rovnaké pravidlo ako pri iných voliteľných vrstvách: čo nie je,
  # sa v `_site` netvári, že je.
  rm -f "$POUT"
  echo "points_enabled=false" >> "$GITHUB_OUTPUT"
  PMB=0
else
  echo "points_enabled=true" >> "$GITHUB_OUTPUT"
  PMB=$(( PBYTES / 1048576 ))
  ls -lh "$POUT"
fi
echo "points_size_mb=$PMB" >> "$GITHUB_OUTPUT"

# Poistka na rozpočet stránky. `deploy` overí súčet ešte raz, ale
# keď je nad podielom práve táto vrstva, má sa to povedať tu. Body sú v tom
# istom podiele ako línie a plochy (vlastný `BUDGET_POINTS_PCT` by bol
# štvrtý prepínač pre vrstvu, ktorá váži jednotky MB).
LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
FBUDGET_MB=$(( LIMIT_MB * BUDGET_FEATURES_PCT / 100 ))
TOTAL_MB=$(( MB + PMB ))
if [ "$TOTAL_MB" -gt "$FBUDGET_MB" ]; then
  echo "::warning::Krajinné prvky (línie, plochy a body) majú spolu ${TOTAL_MB} MB, čo je nad podielom ${FBUDGET_MB} MB z rozpočtu stránky. Zníž features_maxzoom alebo zdvihni BUDGET_FEATURES_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$FZ" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
# `$POUT` už nemusí existovať (zmazaný vyššie, keď v území nie je ani jeden
# bod) – "žiadne" je vtedy pravdivejšia hláška než chyba `du` na chýbajúcom súbore.
BODY_SIZE=$([ -s "$POUT" ] && du -h "$POUT" | cut -f1 || echo "žiadne")
printf '%s\t%s\t%s\t%s\n' "58" "Krajinné prvky → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $FZ, línie+plochy $(du -h "$OUT" | cut -f1), body $BODY_SIZE" \
  >> steps-out/features.tsv
