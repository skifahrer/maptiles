#!/usr/bin/env bash
# Vyhľadávací index z OSM (názvy miest, hôr, chát, trás) → `_site/search-index.db`.
#
# Číta sa priamo z PBF bez Planetilera: názvy sú prvotné, súradnice presné
# a trvá to minúty.
#
# Prázdny index nie je chyba – malý testovací štvorec nemusí mať čo indexovať;
# povie sa to na stdout.

set -euo pipefail
mkdir -p _site/tiles data
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# ---- 1. predfilter ----
# Zoznam tagov je vo workers/search/filter.txt vedľa schémy, nech
# sa obe menia na jednom mieste. Bez neho by sa celý región čítal;
# po ňom ostane zlomok orientovaný len na hľadateľné prvky.
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/search.osm.pbf \
  data/region.osm.pbf --expressions=workers/search/filter.txt
BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/search.osm.pbf)
echo "Predfilter hľadania: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/search.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "56" "Predfilter hľadania" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/search.tsv

# Prázdny výsledok nie je chyba – malý testovací štvorec nemusí mať
# ani jeden hľadateľný prvok. Index vtedy pôjde bez položiek.
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jeden hľadateľný prvok – mapa pôjde bez indexu."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. index ----
T_I=$(date +%s)
OUT="data/search-index.db"

# Osm-id field name – odkiaľ ho bereme:
# Z spike 04-01 vieme, že Planetiler emituje id cez `value: '${ feature.id }'`
# Do indexu to ide ako `osm_id` a typ ako `osm_type`.
OSM_ID_FIELD="${OSM_ID_FIELD:-osm_id}"

python3 workers/search/build-index.py \
  --pbf=data/search.osm.pbf \
  --out="$OUT" \
  --region-key="$REGION_KEY" \
  --osm-id-field="$OSM_ID_FIELD"

if [ ! -f "$OUT" ]; then
  echo "::error::Vyhľadávacieho indexu sa nepodarilo vytvoriť."
  exit 1
fi

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

# Počítačom sa reťazce počítajú ako byť v poriadku.
# Overenie si bere sqlite3 – čo by sme tu skúšali, ked to vedľa zastaví.
ROW_COUNT=$(sqlite3 "$OUT" "SELECT count(*) FROM search_fts;" 2>/dev/null || echo "0")

if [ "$ROW_COUNT" -eq 0 ]; then
  echo "::warning::Index sa vytvoril, ale ostane prázdny – v území nie sú prvky na hľadanie."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
echo "row_count=$ROW_COUNT" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "57" "Vyhľadávací index → SQLite" "$(( $(date +%s) - T_I ))" \
  "$ROW_COUNT položiek, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/search.tsv

# ---- 3. presun do _site ----
# publish-map.py balí všetko v _site do mapa kusa. Search index sem patrí.
mkdir -p _site/tiles
mv "$OUT" _site/tiles/
echo "Index presunutý do _site/tiles/search-index.db"
