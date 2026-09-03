#!/usr/bin/env bash
# JEDEN ÚSEK ŠTAFETY dávky „Build map state": počkaj na kraj, ktorý beží,
# spusti ďalší a odovzdaj štafetu sám sebe.
#
# SAMOTNÁ ŠTAFETA JE VO `workers/state/estafeta.sh` – čakanie, kolík, súhrn
# aj poistka proti nekonečnej reťazi. Je to to isté, čo robí dávka
# „Regenerate state" (`workers/state/regenerate.sh`), a dve kópie by sa raz
# rozišli práve v tom, či reťaz pokračuje. Tu ostáva JEDINÉ, čím sa táto
# dávka od tamtej líši: ČO nad krajom spúšťa a s akými poľami.
#
# ── V ČOM SA DÁVKA LÍŠI OD JEDNÉHO KRAJA ──────────────────────────────────
#   area          natvrdo `cely_region`. Výrez je pohorie a vyberať jedno
#                 pohorie pre osem krajov nedáva zmysel.
#   publish_pages natvrdo VYPNUTÉ. Na Pages je JEDNA mapa, takže osem behov
#                 za sebou by stránku osemkrát prepísalo a nechalo na nej
#                 posledný kraj.
# Všetko ostatné sa podáva ďalej nezmenené – a podáva sa CELÉ a zakaždým,
# lebo články štafety sú samostatné behy a beh bez nich by postavil inú mapu.
# Stráži to `workers/lint/state.py`.
#
# Hodnoty z prostredia (viď `.github/workflows/build-map-state.yml`):
#   COUNTRY POKRACOVANIE REF SELF REGION_WF REPO SUMMARY GH_TOKEN
#   CONTOUR_SOURCE ROCK_SOURCE SHADING_SOURCE ROCK_SLOPE REBUILD TEST OPTIONS
set -euo pipefail

SELF="${SELF:-build-map-state.yml}"
REGION_WF="${REGION_WF:-build-map-region.yml}"
REGION_MENO="Mapa · Build map region"

TITUL="Dávka máp · ${COUNTRY:-?}"
POPIS="Kraj je vlastný beh **Mapa · Build map region**;
dávka ich spúšťa jeden po druhom a po každom si spustí ďalší svoj beh –
job má strop 6 h, dávka trvá aj deň, a tak ju nemá čo zabiť."

# ---------- odovzdanie štafety ----------
# Ten istý workflow, tie isté nastavenia, iný kolík. Nastavenia sa podávajú
# CELÉ a zakaždým: reťaz je séria samostatných behov a beh, ktorý by si ich
# nepodal, by postavil kraj s predvolenými hodnotami – čiže tichú inú mapu.
odovzdaj() {
  local kolik="$1"
  echo "Odovzdávam štafetu: pokracovanie=$kolik"
  gh workflow run "$SELF" --repo "$REPO" --ref "$REF" \
    -f country="$COUNTRY" \
    -f contour_source="${CONTOUR_SOURCE:-dmr5}" \
    -f rock_source="${ROCK_SOURCE:-dmr5}" \
    -f shading_source="${SHADING_SOURCE:-dmr5}" \
    -f rock_slope="${ROCK_SLOPE:-50}" \
    -f rebuild="${REBUILD:-nic}" \
    -f test="${TEST:-false}" \
    -f options="${OPTIONS:-}" \
    -f pokracovanie="$kolik"
}

# ---------- spustenie jedného kraja ----------
# `area` je natvrdo `cely_region` a `publish_pages` natvrdo vypnuté – to sú
# tie dve veci, ktorými sa dávka od jedného kraja líši (rozpis vyššie).
spusti_kraj() {
  local kraj="$1"
  gh workflow run "$REGION_WF" --repo "$REPO" --ref "$REF" \
    -f region="$kraj" \
    -f area=cely_region \
    -f test="${TEST:-false}" \
    -f contour_source="${CONTOUR_SOURCE:-dmr5}" \
    -f rock_source="${ROCK_SOURCE:-dmr5}" \
    -f shading_source="${SHADING_SOURCE:-dmr5}" \
    -f rock_slope="${ROCK_SLOPE:-50}" \
    -f rebuild="${REBUILD:-nic}" \
    -f publish_pages=false \
    -f options="${OPTIONS:-}"
}

# shellcheck source=workers/state/estafeta.sh
. workers/state/estafeta.sh
estafeta_hlavna
