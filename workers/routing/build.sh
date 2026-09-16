#!/usr/bin/env bash
# Smerovacia sieť kraja → `{región}-routing.pmtiles` (v mape aj v `cesty`).
#
# Rozpis formátu je v `docs/routing-tiles.md`, dôvod v `docs/navigation.md` §10.
# Krátko: do telefónu ide TAG, nie cena – profil používateľa sa do
# predpočítaného grafu zapiecť nedá.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 kB.
#
# Prázdny výsledok nie je chyba: malý testovací štvorec nemusí mať ani jednu
# cestu.

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'
python3 -c 'import pmtiles' 2>/dev/null \
  || python3 -m pip install --quiet --break-system-packages pmtiles

# ---- 1. predfilter ----
# Zoznam tried je v slovníku značiek; druhý zoznam tu by sa rozišiel a rozišiel
# by sa ticho – trieda by z archívu vypadla a profil by ju ponúkal ďalej.
T_F=$(date +%s)
python3 workers/routing/tags.py --filter > data/routing-filter.txt
osmium tags-filter --overwrite -o data/routing.osm.pbf \
  data/region.osm.pbf --expressions=data/routing-filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/routing.osm.pbf)
echo "Predfilter smerovania: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/routing.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "20" "Predfilter smerovacej siete" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/routing.tsv

if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jedna cesta, po ktorej by sa dalo ísť – smerovacia sieť sa nevyrobí."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. výšky uzlov ----
# Sonny 20 m: výška sa berie na križovatke, a medzi dvomi križovatkami tvar
# cesty nenesie žiadnu – jemnejší model by tú chybu nezmenšil, len by stiahol
# rádovo viac bajtov. Iný je vec `ROUTING_DEM_SOURCE`.
DEM_SOURCE="${ROUTING_DEM_SOURCE:-sonny}"

# Warning v logu prehliadne každý: kraje sa už dvakrát prestavali a `vyska`
# zostala `false`. Toto je na stránke behu, kde sa výsledok číta.
bez_vysok() {
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  cat >> "$GITHUB_STEP_SUMMARY" <<TEXT
### Navigácia: archív bez výšok uzlov
\`${REGION_KEY}\` ide s \`vyska: false\` – bicykel a chodec sa v ňom rátajú, ako
keby bol kraj rovina, a trasa hlási namiesto stúpania pomlčku.

Model si build dopĺňa sám (job **Doplniť výškový model**) – keď archív aj tak
ide bez výšok, odpoveď je v logu toho jobu.
TEXT
}

DEM=()
if [ -n "${DEM_BBOX:-}" ]; then
  sudo apt-get install -y -qq gdal-bin
  python3 -c 'import numpy' 2>/dev/null \
    || python3 -m pip install --quiet --break-system-packages numpy
  set +e
  workers/dem/fetch.sh "$DEM_BBOX" "dem/$DEM_SOURCE" steps-out/routing.tsv "$DEM_SOURCE"
  DRC=$?
  set -e
  if [ "$DRC" -eq 0 ] && [ -s "dem/$DEM_SOURCE/all.vrt" ]; then
    DEM=(--dem="dem/$DEM_SOURCE/all.vrt")
  else
    echo "::warning::Výškový model kraja ($DEM_SOURCE) sa nestiahol (kód $DRC) – archív ide bez výšok uzlov."
    bez_vysok
  fi
else
  echo "::warning::Kraj nemá bbox výškového modelu (DEM_BBOX) – archív ide bez výšok uzlov."
  bez_vysok
fi

# ---- 3. archív ----
# Poradie uzlov sa počíta nad CELÝM stavaným územím (`order.sh`, z cache na
# Drive alebo dopočítané) a leží tu. Keď tu nie je, archív ide bez neho
# a `tiles.py` to povie.
PORADIE=()
if [ -s data/routing-order.json ]; then
  PORADIE=(--poradie=data/routing-order.json)
fi

KRAJINA="${ROUTING_COUNTRY:-}"
if [ -z "$KRAJINA" ]; then
  echo "::warning::Kraj nemá ISO kód krajiny (\`iso\` v workers/data/regions.json), takže hrany v archíve o svojej krajine nepovedia nič a diaľničná známka nemá na čom stáť."
fi

T_A=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-routing.pmtiles"
python3 workers/routing/tiles.py \
  --pbf=data/routing.osm.pbf \
  --out="$OUT" \
  --region-key="$REGION_KEY" \
  --name="$REGION_NAME" \
  --krajina="$KRAJINA" \
  "${PORADIE[@]}" "${DEM[@]}"

if [ ! -s "$OUT" ]; then
  echo "::warning::Archív so smerovaním nevznikol – v území nie je nič, po čom by sa dalo ísť."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# tá istá kontrola, aká beží v lintoch – tam nad číselníkom, tu nad archívom
python3 workers/lint/routing-tiles.py "$OUT"

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
RBUDGET_MB=$(( LIMIT_MB * BUDGET_ROUTING_PCT / 100 ))
if [ "$MB" -gt "$RBUDGET_MB" ]; then
  echo "::warning::Smerovacia sieť má ${MB} MB, čo je nad podielom ${RBUDGET_MB} MB z rozpočtu stránky. Páka je slovník značiek (workers/data/routing-tags.json) – čo v ňom nie je, sa nevezie."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "21" "Smerovacia sieť → PMTiles" "$(( $(date +%s) - T_A ))" \
  "$(du -h "$OUT" | cut -f1)" >> steps-out/routing.tsv
