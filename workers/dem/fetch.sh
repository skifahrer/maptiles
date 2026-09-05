#!/usr/bin/env bash
# Stiahne DEM dlaždice pre bbox zo skladu na Drive a zlepí ich do jedného VRT.
#
# Potrebujú to dva joby (vrstevnice/skaly aj tieňovanie), tak je to jeden
# skript. Sklad je priečinok na Drive (`workers/drive/store.py`).
#
# `sonny`, `dmr35` a `dmr5` na celý región sa líšia len menom skladu – dlaždice
# majú tú istú schému mien (`N49E019.tif`).
#
# Ktorý sklad a ktoré súbory, rozhoduje `workers/dem/target.py`: tú istú otázku
# si kladie aj `check-dem` a musia si odpovedať rovnako.
#
# Použitie:
#   workers/dem/fetch.sh <bbox W,S,E,N> <adresár> [tsv] [zdroj] [kľúč výrezu]
#
# Kľúč výrezu prepína podobu DMR 5.0: vrstevnice a skaly ho podávajú,
# tieňovanie nie. Kto zmení niektoré z tých volaní, musí zmeniť aj tabuľku
# vrstiev v `check-dem`.
#
# Výstup: `<adresár>/tiles/N49E019.tif …` a `<adresár>/all.vrt`.
# Očakáva prihlásenie na Drive v prostredí.
set -euo pipefail

BBOX="$1"
DIR="${2:-dem}"
STEPS_TSV="${3:-}"
SOURCE="${4:-sonny}"
AREA_KEY="${5:-cely}"
T0=$(date +%s)
# sklad je v susednom priečinku, `target.py` vedľa tohto skriptu
HERE="$(dirname "$0")"
WORKERS="$(dirname "$HERE")"
STORE_PY="$WORKERS/drive/store.py"

# čo sa má stiahnuť, povie ten istý zdroj pravdy ako pre `check-dem`
TARGET=$(python3 "$HERE/target.py" \
  --source="$SOURCE" --area-key="$AREA_KEY" --bbox="$BBOX")
get() { printf '%s\n' "$TARGET" | sed -n "s/^$1=//p" | head -1; }
FORM=$(get form)
SRC_STORE=$(get store)
SRC_LABEL=$(get label)

# DMR 5.0 má dve podoby a rozhoduje medzi nimi rozsah, nie druhý výber vo
# formulári: výrez je plné 1 m v `dem-ugkk`, celý región 5 m dlaždice
# v `dem-dmr5-v2`. Dôvod je veľkosť – 1° dlaždica má pri 1 m ~48 GB a runner
# má voľných ~60 GB, takže je to obmedzenie stroja a nie voľba.
if [ "$FORM" = "area" ]; then
  mkdir -p "$DIR"
  UASSET=$(get assets)
  if ! python3 "$STORE_PY" --get --store="$SRC_STORE" --name="$UASSET" \
        --dir="$DIR" --skip-local; then
    # kód 3 = „pre tento výrez to nemáme", nie „všetko je zle" – volajúci sa
    # podľa neho vie rozhodnúť (spadnúť, alebo hrubší model)
    echo "::warning::V sklade $SRC_STORE nie je $UASSET – DMR 5.0 pre tento výrez ešte nikto nevyrobil. Spusti workflow 'Dáta · DMR 5.0' s area: $AREA_KEY."
    exit 3
  fi
  gdalbuildvrt -q "$DIR/all.vrt" "$DIR/$UASSET"
  SIZE=$(du -h "$DIR/$UASSET" | cut -f1)
  echo "$SRC_LABEL zo skladu: $UASSET, $SIZE"
  gdalinfo "$DIR/$UASSET" | grep -E "Pixel Size|Size is" || true
  if [ -n "$STEPS_TSV" ]; then
    printf '%s\t%s\t%s\t%s\n' 20 "DEM (DMR 5.0, výrez)" "$(( $(date +%s) - T0 ))" \
      "$UASSET zo skladu, $SIZE" >> "$STEPS_TSV"
  fi
  exit 0
fi

# stiahnuté dlaždice majú vlastný podadresár: medzivýsledky sú tiež .tif
mkdir -p "$DIR/tiles"

# dlaždice sú 1°×1°, pomenované podľa juhozápadného rohu (konvencia SRTM)
get assets | tr ' ' '\n' | sed '/^$/d' > "$DIR/list.txt"
WANT=$(wc -l < "$DIR/list.txt")
echo "DEM dlaždíc pre bbox: $WANT"

# jedno volanie na všetky dlaždice, nie jedno na každú. `--missing-ok`, lebo
# bbox je obdĺžnik, ale produkt pokrýva krajinu – rohové bunky v ňom nikdy
# nebudú. `--skip-local`: čo už je v cache behu, sa neťahá znova.
set +e
python3 "$STORE_PY" --get --store="$SRC_STORE" --dir="$DIR/tiles" \
  --name="$(tr '\n' ' ' < "$DIR/list.txt")" --missing-ok --skip-local
SRC=$?
set -e

shopt -s nullglob
tifs=("$DIR"/tiles/*.tif)
have=${#tifs[@]}

if [ "$have" -eq 0 ]; then
  # kód 3 = „tento model nemáme", nie „všetko je zle". Pri Sonnym sa už nie je
  # kam vrátiť, tak je to tvrdá chyba – inak by sa volajúci s fallbackom zacyklil.
  echo "::warning::V sklade $SRC_STORE nie je pre toto územie ani jedna dlaždica (kód $SRC)."
  echo "Zálohu z Copernicusu zámerne nepoužívame (je to model povrchu so stromami, nie terén)."
  if [ "$SOURCE" = "dmr5" ]; then
    # dlaždicovú podobu dopĺňa job `mirror-dmr5-tiles`; keď tu aj tak nič nie
    # je, ten job buď nebežal, alebo spadol
    echo "Doplniť ich mal job 'Doplniť DMR 5.0 (dlaždice)' – pozri jeho log."
    echo "Ručne: workflow 'Dáta · DMR 5.0', area: $(python3 "$HERE/target.py" --source=dmr5 --bbox="$BBOX" | sed -n 's/^degrees=//p'), tiles: true, mriežka 5 m."
  else
    echo "Spusti workflow 'Dáta · výškové modely' so zdrojom, ktorý toto územie pokrýva."
  fi
  [ "$SOURCE" = "sonny" ] && exit 1
  exit 3
fi
if [ "$have" -lt "$WANT" ]; then
  # bbox je obdĺžnik, produkt pokrýva krajinu – rohové bunky za hranicou v ňom
  # byť nemusia. Radšej diera, ktorú vidno, než výplň z modelu povrchu.
  echo "::warning::V sklade $SRC_STORE nie je $(( WANT - have )) z $WANT dlaždíc – tam vrstevnice, skaly ani tieňovanie nebudú. Ak to územie má mať terén, spusti 'Dáta · výškové modely' s priečinkom, ktorý ho pokrýva."
fi
echo "$SRC_LABEL: $have z $WANT dlaždíc zo skladu $SRC_STORE ✓"

# ---------- pokrýva to územie? ----------
# Počet súborov na tú otázku neodpovedá: dlaždica je sľub o celom stupni, ale
# v sklade ležali tri s pár set metrami dát (presah prevodu do WGS84 pod menom
# celého stupňa) a `gdal_contour` prešiel po mozaike so 48 % kraja.
# Odteraz sa meria rozsah dlaždíc, nie ich počet.
COV="$DIR/coverage.txt"
set +e
# `--data-pct`: dlaždica so správnym rozsahom, ale takmer bez výšok, sa ohlási.
# Prah 2 % je zámerne nízko – ide o „takmer prázdna".
python3 "$HERE/coverage.py" --bbox="$BBOX" --dir="$DIR/tiles" \
  --min-pct="${DEM_MIN_COVER_PCT:-95}" \
  --data-pct="${DEM_MIN_DATA_PCT:-2}" --out="$COV"
COV_RC=$?
set -e
LIARS=$(sed -n 's/^liars=//p' "$COV" 2>/dev/null || true)
COV_PCT=$(sed -n 's/^covered_pct=//p' "$COV" 2>/dev/null || true)
COV_MISS=$(sed -n 's/^missing=//p' "$COV" 2>/dev/null || true)
COV_EMPTY=$(sed -n 's/^empty=//p' "$COV" 2>/dev/null || true)

# prázdny stupeň sa do pokrytia počíta (prečítaný je), ale je to jediné miesto,
# kde sa dá vopred prečítať, že tam terén nebude
if [ -n "$COV_EMPTY" ]; then
  echo "V mozaike sú prázdne stupne (prečítané, terén v nich nie je): $COV_EMPTY"
  echo "  Ak niektorý z nich terén MÁ, je to chyba – zmaž ho zo skladu $SRC_STORE a spusti build znova."
fi

# sklad sa vylieči sám: nepoctivú dlaždicu nestačí preskočiť – kým leží
# v sklade, kontrola v ďalšom behu opäť usúdi, že model má. Je to zrkadlo,
# dá sa vyrobiť znova.
for f in $LIARS; do
  echo "::warning::Dlaždica $f v sklade $SRC_STORE nesplnila, čo sľubuje jej meno (dôvod je vo výpise pokrytia vyššie: buď nepokrýva celý svoj stupeň, alebo je to prázdna dlaždica od kontroly, ktorej už neveríme). Mažem ju zo skladu – ďalší beh ju doplní celú (job 'Doplniť DMR 5.0 (dlaždice)')."
  python3 "$STORE_PY" --rm --store="$SRC_STORE" --name="$f" \
    || echo "  (zo skladu sa ju nepodarilo zmazať – zmaž ju na Drive ručne)"
  rm -f "$DIR/tiles/$f"
done
if [ -n "$LIARS" ]; then
  tifs=("$DIR"/tiles/*.tif)
  have=${#tifs[@]}
fi

if [ "$COV_RC" -ne 0 ]; then
  # dosť dlaždíc, málo územia – pre volajúceho to isté ako kód 3. Pri Sonnym
  # sa nie je kam vrátiť, tak ostáva varovanie a mapa s dierou, ktorú vidno.
  echo "Pokrytie územia $BBOX: ${COV_PCT:-0} % (chce sa aspoň ${DEM_MIN_COVER_PCT:-95} %)"
  if [ "$SOURCE" = "sonny" ]; then
    echo "::warning::Mozaika zo Sonnyho pokrýva len ${COV_PCT:-0} % územia – chýbajú stupne: ${COV_MISS:-?}. Vo zvyšku nebude terén."
  else
    echo "::error::Mozaika $SRC_LABEL pokrýva len ${COV_PCT:-0} % územia (chýbajúce stupne: ${COV_MISS:-?}), takže vrstevnice, skaly ani tieňovanie by v zvyšku regiónu neboli – a mapa by vyzerala hotovo. Keď sa vyššie mazali nepoctivé dlaždice, stačí spustiť build znova: chýbajúce si doplní sám. Inak ich doplň ručne (workflow 'Dáta · DMR 5.0', area: $(python3 "$HERE/target.py" --source="$SOURCE" --bbox="$BBOX" | sed -n 's/^degrees=//p'), tiles: true, mriežka 5 m) alebo zvoľ zdroj, ktorý celé územie pokrýva."
    exit 3
  fi
fi
if [ "$have" -eq 0 ]; then
  echo "::error::Po vyradení nepoctivých dlaždíc neostala ani jedna – doplň model a spusti build znova."
  exit 3
fi

# `-resolution highest`: dlaždice môžu mať rôznu mriežku (20m model má
# obdĺžnikové pixely)
gdalbuildvrt -q -resolution highest "$DIR/all.vrt" "${tifs[@]}"
echo "DEM dlaždíc k dispozícii: ${#tifs[@]} → $DIR/all.vrt"

if [ -n "$STEPS_TSV" ]; then
  # prvé pole je poradie v súhrne – joby bežia súbežne
  printf '%s\t%s\t%s\t%s\n' 20 "DEM dlaždice ($SRC_LABEL)" "$(( $(date +%s) - T0 ))" \
    "$have z $WANT dlaždíc, $(du -sh "$DIR/tiles" | cut -f1)" >> "$STEPS_TSV"
fi
