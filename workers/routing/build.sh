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

# ---- 2. výšky a profily ----
# DMR 5.0: archív nesie výšku každých 5 m pozdĺž cesty, takže rozlíšenie modelu
# je odteraz to, čo o stúpaní rozhoduje. Sonny 20 m je záloha, kde DMR nie je.
DEM_SOURCE="${ROUTING_DEM_SOURCE:-dmr5}"
DEM_ZALOHA="${ROUTING_DEM_FALLBACK:-sonny}"
PROFIL_KROK="${ROUTING_PROFILE_STEP_M:-5}"

# Warning v logu prehliadne každý: kraje sa už dvakrát prestavali a `vyska`
# zostala `false`. Toto je na stránke behu, kde sa výsledok číta.
bez_vysok() {
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  cat >> "$GITHUB_STEP_SUMMARY" <<TEXT
### Navigácia: archív bez výšok
\`${REGION_KEY}\` ide s \`vyska: false\` – bicykel a chodec sa v ňom rátajú, ako
keby bol kraj rovina, a trasa hlási namiesto stúpania pomlčku.

Doplniť: **Dáta · DMR 5.0** (5 m, sklad \`dem-dmr5-v2\`) alebo **Dáta · výškové
modely**, zdroj \`sonny\` (20 m, celé Slovensko), potom kraj postaviť znova.
TEXT
}

# ten istý dôvod ako `bez_vysok`: warning v logu prehliadne každý
z_zalohy() {
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
  cat >> "$GITHUB_STEP_SUMMARY" <<TEXT
### Navigácia: profil z hrubšieho modelu
\`${REGION_KEY}\` nemá v sklade \`dmr5\` ani jednu dlaždicu, tak profil hrán ide
z \`${DEM_ZALOHA}\`. Krok ostáva ${PROFIL_KROK} m, ale štyri po sebe idúce vzorky
vtedy sedia v jednej bunke modelu – stúpanie je vyhladené, nie namerané.

Doplniť: **Dáta · DMR 5.0**, \`tiles: true\` nad stupňami tohto kraja, potom
kraj postaviť znova.
TEXT
}

# vráti 0 a nastaví DEM, keď sa zdroj stiahol
skus_dem() {
  local zdroj="$1"
  set +e
  workers/dem/fetch.sh "$DEM_BBOX" "dem/$zdroj" steps-out/routing.tsv "$zdroj"
  local rc=$?
  set -e
  [ "$rc" -eq 0 ] && [ -s "dem/$zdroj/all.vrt" ]
}

DEM=()
if [ -n "${DEM_BBOX:-}" ]; then
  sudo apt-get install -y -qq gdal-bin
  python3 -c 'import numpy' 2>/dev/null \
    || python3 -m pip install --quiet --break-system-packages numpy
  if skus_dem "$DEM_SOURCE"; then
    DEM=(--dem="dem/$DEM_SOURCE/all.vrt" --profil-krok="$PROFIL_KROK")
  elif [ "$DEM_ZALOHA" != "$DEM_SOURCE" ] && skus_dem "$DEM_ZALOHA"; then
    echo "::warning::$DEM_SOURCE pre tento kraj v sklade nie je – profil ide z $DEM_ZALOHA."
    z_zalohy
    DEM=(--dem="dem/$DEM_ZALOHA/all.vrt" --profil-krok="$PROFIL_KROK")
  else
    echo "::warning::Výškový model kraja ($DEM_SOURCE ani $DEM_ZALOHA) sa nestiahol – archív ide bez výšok."
    bez_vysok
  fi
else
  echo "::warning::Kraj nemá bbox výškového modelu (DEM_BBOX) – archív ide bez výšok."
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
