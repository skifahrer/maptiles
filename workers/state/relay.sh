#!/usr/bin/env bash
# Jeden úsek štafety dávky „Build map state": počkaj na kraj, ktorý beží,
# spusti ďalší a odovzdaj štafetu sám sebe.
#
# Samotná štafeta je vo `workers/state/estafeta.sh` – to isté jadro, aké
# používa „Regenerate state". Tu ostáva len to, čím sa táto dávka líši.
#
# Čím sa dávka líši od jedného kraja:
#   area          natvrdo `cely_region` – vyberať jedno pohorie pre osem
#                 krajov nedáva zmysel
#   publish_pages natvrdo vypnuté – na Pages je jedna mapa a osem behov by ju
#                 osemkrát prepísalo
#   reuse_layers  dopĺňa sa ako `true`, keď si ho tam človek nenapísal sám
#
# Všetko ostatné sa podáva ďalej nezmenené, celé a zakaždým – články štafety sú
# samostatné behy. Stráži to `workers/lint/state.py`.
#
# Prečo dávka nepočíta vrstvy, ktoré už raz vznikli: vrstevnice, skaly
# a tieňovanie sú hodiny na kraj a krajov je osem, čiže väčšina toho dňa. Medzi
# dvomi dávkami sa pritom málokedy zmení niečo, čo by ich zmenilo. Kto chce
# prepočet, povie to – `rebuild` alebo `options: reuse_layers=false`; napísané
# prebíja doplnené.
#
# Z prostredia (viď `.github/workflows/build-map-state.yml`):
#   COUNTRY POKRACOVANIE REF SELF REGION_WF REPO SUMMARY GH_TOKEN
#   CONTOUR_SOURCE ROCK_SOURCE SHADING_SOURCE ROCK_SLOPE REBUILD TEST OPTIONS
set -euo pipefail

SELF="${SELF:-build-map-state.yml}"
REGION_WF="${REGION_WF:-build-map-region.yml}"
REGION_MENO="Mapa · Build map region"

# `options` pre beh kraja: to, čo si zadal, plus hotové vrstvy, keď si o nich
# nepovedal nič (rozpis v hlavičke). Ďalšiemu článku štafety sa podáva PÔVODNÉ
# `OPTIONS` – kolík má niesť to, čo je vo formulári, a doplnenie si každý
# článok spraví sám a rovnako.
OPTIONS_KRAJ="${OPTIONS:-}"
case "$OPTIONS_KRAJ" in
  *reuse_layers=*) echo "options nesie vlastné reuse_layers – nechávam ho tak." ;;
  *) OPTIONS_KRAJ="reuse_layers=true${OPTIONS_KRAJ:+ $OPTIONS_KRAJ}" ;;
esac
echo "Kraj dostane options: $OPTIONS_KRAJ"

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
    -f options="$OPTIONS_KRAJ"
}

# shellcheck source=workers/state/estafeta.sh
. workers/state/estafeta.sh
estafeta_hlavna
