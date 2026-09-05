#!/usr/bin/env bash
# Tieňovanie a 3D terén: terrarium PNG dlaždice z vybraného výškového modelu.
#
# Poradie je „najlacnejšie najprv": cache behu → sklad na Drive → prepočet.
#
# Meno assetu nesie zdroj, maxzoom aj podobu kódovania
# (`terrain-<kľúč>-<model>-z<maxzoom>-v<verzia>.pmtiles`): tieňovanie zo
# Sonnyho a z DMR 3.5 nie je to isté a `v6` dopĺňa výšku za hranicou kraja
# okolím, kým `v5` ju tam zrovnával na rovinu (zvislá stena po obvode).
# Bez tej prípony by sa oprava na už spočítanom regióne neprejavila.
#
# Použitie:
#   REGION_KEY=presovsky_kraj DEM_BBOX=20,49,21,50 SHADING_SOURCE=sonny \
#   TERRAIN_MAXZOOM=13 TERRAIN_STORE=dem-terrain GDRIVE_CREDENTIALS=… \
#   workers/terrain/build.sh
set -euo pipefail
: "${REGION_KEY:?kľúč regiónu}"
T_TER=$(date +%s)
TSRC="výpočet"
FELL_BACK=false
TZ="${TERRAIN_MAXZOOM:-}"
case "$TZ" in ''|*[!0-9]*) TZ=13 ;; esac
# tieňovanie je vrstva z DEM, takže ide na `dem_bbox` – pri teste na štvorec
BBOX="${DEM_BBOX:?bbox pre DEM}"
TDEM="${SHADING_SOURCE:?zdroj tieňovania}"
# rozpočet na tieňovanie: podiel z rozpočtu stránky. Bez neho sa zmestenie
# riešilo až v kontrole pred nasadením, čiže po celej práci.
LIMIT_MB="${SIZE_LIMIT_MB:-900}"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TPCT="${BUDGET_TERRAIN_PCT:-12}"
case "$TPCT" in ''|*[!0-9]*) TPCT=12 ;; esac
TBUDGET_MB=$(( LIMIT_MB * TPCT / 100 ))
REBUILD="${TERRAIN_REBUILD:-false}"

# meno assetu nesie zdroj aj maxzoom; skutočný maxzoom je známy až po výpočte
# (strop veľkosti ho môže zraziť), tak sa meno skladá funkciou a volá dvakrát.
# Podoba kódovania je tu raz – kým bola napísaná dvakrát, hľadalo sa v sklade
# niečo iné, než sa doň ukladalo.
ENC_VER=v6
# a nesie aj prekryv so susedným krajom: nafúknutie polygónu mení obsah aj
# rozsah dlaždíc. Kým to číslo v mene nebolo, sklad vrátil dlaždice spočítané
# podľa pôvodnej tesnej hranice – mapa pokračovala za hranicu, reliéf pod ňou nie.
BORDER_M=$(python3 -c "import sys; sys.path.insert(0, 'workers/plan'); import area; print(int(area.BORDER_BUFFER_M))")
asset_name() { echo "terrain-${REGION_KEY}-${TDEM}-z${1}-${ENC_VER}-o${BORDER_M}.pmtiles"; }

# hotové = leží tu hotový archív; polovica stromu PNG je tiež neprázdny priečinok
have_tiles() { [ -s terrain-out/terrain.pmtiles ]; }

if [ "$REBUILD" = 'true' ]; then
  echo "terrain_rebuild=áno – dlaždice sa počítajú nanovo."
  rm -rf terrain-out
elif have_tiles; then
  echo "Výškové dlaždice sú v cache behu ✓"
  TSRC="cache"
else
  # skús sklad – uložené dlaždice sú lacnejšie než prepočet. Hľadá sa najvyšší
  # uložený zoom, ktorý nie je vyšší než želaný: keď minulý beh narazil na strop
  # a uložil z13, je to presne to, čo by sa znova vypočítalo.
  HAVE_Z=$(python3 workers/drive/store.py --names --store="$TERRAIN_STORE" \
      2>/dev/null \
    | sed -n "s/^terrain-${REGION_KEY}-${TDEM}-z\([0-9]\+\)-${ENC_VER}-o${BORDER_M}\.pmtiles$/\1/p" \
    | awk -v want="$TZ" '$1 <= want' | sort -n | tail -1)
  if [ -n "$HAVE_Z" ] && python3 workers/drive/store.py --get \
       --store="$TERRAIN_STORE" --name="$(asset_name "$HAVE_Z")" --dir=/tmp; then
    # `.pmtiles` sa nerozbaľuje – je to ten istý súbor, ktorý ide na Pages
    mkdir -p terrain-out
    cp "/tmp/$(asset_name "$HAVE_Z")" terrain-out/terrain.pmtiles
    echo "$HAVE_Z" > terrain-out/maxzoom.txt
    echo "Výškové dlaždice stiahnuté zo skladu $TERRAIN_STORE ✓ (z$HAVE_Z)"
    TSRC="sklad $TERRAIN_STORE"
  fi
fi

if ! have_tiles; then
  # vlastný job = vlastný DEM: vrstevnice bežia súbežne, tak sa oň nedá oprieť
  sudo apt-get update -qq
  sudo apt-get install -y -qq gdal-bin zstd
  python3 -m pip install --quiet numpy
  # model z výberu `shading_source`, do podpriečinka podľa zdroja. Kľúč výrezu
  # sa nepodáva, tak `dmr5` vyjde na dlaždicovú 5 m verziu.
  # Kód 3 = „ten model pre toto územie nemáme" – rovnaký fallback ako pri
  # vrstevniciach, riadený tým istým prepínačom.
  set +e
  workers/dem/fetch.sh "$BBOX" "dem/$TDEM" steps-out/terrain.tsv "$TDEM"
  TRC=$?
  set -e
  if [ "$TRC" -eq 3 ]; then
    if [ "${OPT_UGKK_FALLBACK:-true}" != 'true' ]; then
      echo "::error::Model $TDEM pre tieňovanie nie je k dispozícii a ugkk_fallback je vypnutý. Naplň ho, zapni fallback, alebo vyber iný shading_source."
      exit 1
    fi
    echo "::warning::Model $TDEM pre tieňovanie nie je k dispozícii – tieňovanie sa počíta zo Sonnyho (20 m). Mapa bude, len s hrubším reliéfom, a atribúcia bude hovoriť Sonny."
    TDEM=sonny
    FELL_BACK=true
    # meno súboru nesie zdroj (`asset_name` ho skladá z `TDEM`), takže sa
    # prepísaním modelu opraví samo
    workers/dem/fetch.sh "$BBOX" "dem/$TDEM" steps-out/terrain.tsv "$TDEM"
  elif [ "$TRC" -ne 0 ]; then
    exit "$TRC"
  fi
  echo "::group::Výškové dlaždice do z$TZ z modelu $TDEM (strop ${TBUDGET_MB} MB)"
  # `--poly`: dlaždice mimo kraja sa nekreslia, za hranicou sa výška dopĺňa
  # okolím a dlaždica bez pixela kraja sa nezapíše – tieňovanie sa tak zastaví
  # na hranici regiónu. Keď polygón nie je, `tiles.py` to povie a kreslí celý
  # bbox: vrstva teda nikdy nezmizne, len je väčšia.
  python3 workers/terrain/tiles.py --dem="dem/$TDEM/all.vrt" --bbox="$BBOX" \
    --poly=data/region.geojson \
    --minzoom=5 --maxzoom="$TZ" --budget-mb="$TBUDGET_MB" --out=terrain-png
  # vyrobený maxzoom píše `tiles.py` – strop veľkosti mohol želaný zraziť
  TZ=$(cat terrain-png/maxzoom.txt)
  # strom PNG je len medzikrok: von ide jeden `.pmtiles` (viď `pack.py`)
  python3 -m pip install --quiet pmtiles
  mkdir -p terrain-out
  # `--clip-bbox`: hlavička má povedať územie behu, nie zjednotenie celých
  # dlaždíc – tá na z5 má 11,25°
  python3 workers/terrain/pack.py --in=terrain-png \
    --out=terrain-out/terrain.pmtiles --name="$REGION_KEY" --source="$TDEM" \
    --clip-bbox="$BBOX"
  echo "$TZ" > terrain-out/maxzoom.txt
  # strom PNG sa maže hneď: pri kraji sú to desaťtisíce súborov
  rm -rf terrain-png
  echo "::endgroup::"

  # ulož do skladu, nech ich nabudúce netreba počítať znova; zlyhanie uloženia
  # nesmie zhodiť beh. Do skladu ide ten istý súbor, ktorý sa nasadí.
  ASSET=$(asset_name "$TZ")
  cp terrain-out/terrain.pmtiles "/tmp/$ASSET"
  python3 workers/drive/store.py --put --store="$TERRAIN_STORE" \
      --file="/tmp/$ASSET" \
      --note="Terrarium PNG dlaždice z výškového modelu ako raster .pmtiles – jeden súbor na región, model a maxzoom (Build map)" \
    && echo "Uložené do skladu $TERRAIN_STORE ako $ASSET" \
    || echo "::warning::Výškové dlaždice sa nepodarilo uložiť do skladu $TERRAIN_STORE – nabudúce sa budú počítať znova."
fi

TZ=$(cat terrain-out/maxzoom.txt 2>/dev/null || echo "$TZ")
# ide medzi ostatné `.pmtiles`: pre klienta je to tá istá vec ako mapa, len raster
mkdir -p _site/tiles
cp terrain-out/terrain.pmtiles "_site/tiles/${REGION_KEY}-terrain.pmtiles"
echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$TZ" >> "$GITHUB_OUTPUT"
# model ide do atribúcie výškových dlaždíc; tieňovanie má vlastný výber, tak
# to nemusí byť ten istý model ako pri vrstevniciach
echo "dem_source=$TDEM" >> "$GITHUB_OUTPUT"
# keď sa spadlo na Sonnyho, dlaždice sa nesmú uložiť pod kľúč cache pôvodného
# modelu – do skladu môžu, tam meno súboru už hovorí pravdu
echo "fell_back=$FELL_BACK" >> "$GITHUB_OUTPUT"
TER_MB=$(du -sm "_site/tiles/${REGION_KEY}-terrain.pmtiles" | cut -f1)
echo "Výškové dlaždice: raster .pmtiles do z$TZ z modelu $TDEM, ${TER_MB} MB"
printf '%s\t%s\t%s\t%s\n' "60" "Tieňovanie a 3D terén" "$(( $(date +%s) - T_TER ))" \
  "raster .pmtiles do z$TZ z $TDEM, ${TER_MB} MB ($TSRC)" \
  >> steps-out/terrain.tsv
