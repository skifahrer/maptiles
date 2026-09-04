#!/usr/bin/env bash
# JEDEN ÚSEK ŠTAFETY dávky „Regenerate state": počkaj na kraj, ktorý beží,
# spusti nad ďalším to, čo sa má pregenerovať, a odovzdaj štafetu sám sebe.
#
# SAMOTNÁ ŠTAFETA JE VO `workers/state/estafeta.sh` – to isté jadro, aké
# používa dávka „Build map state" (`workers/state/relay.sh`). Tu ostáva len to,
# čím sa táto dávka od tamtej líši: nespúšťa nad krajom CELÝ build, ale JEDNU
# vec, a ktorú to je, hovorí formulár (`co`).
#
# ČO SA NAD KRAJOM SPUSTÍ, NEROZHODUJE TENTO SKRIPT. Číselník je vo
# `workers/state/jobs.py` – vie, ktorý workflow tú vec nad krajom spraví
# a s akými poľami. Keby to bol `case` tu, pribudnutá voľba by vo formulári
# bola a štafeta by na nej spadla; alebo, čo je horšie, spustila by niečo
# iné, než si vybral, a beh by bol zelený.
#
# ── DVE CESTY, DVE CENY ───────────────────────────────────────────────────
# Body, línie a navigácia sa počítajú z toho istého PBF ako mapa a nič iné
# z buildu nepotrebujú – idú preto cez „Mapa · Pregeneruj vrstvu kraja",
# ktorý postaví LEN tú vrstvu a na Drive prepíše LEN jej balík. Minúty.
# Vrstevnice, skaly a tieňovanie potrebujú sklad výškového modelu, jeho
# doplnenie aj kľúče cache – idú preto celým buildom kraja s `rebuild`.
# Hodiny. Rozpis, prečo to tak je, je v hlavičke `workers/state/jobs.py`.
#
# Hodnoty z prostredia (viď `.github/workflows/regenerate-state.yml`):
#   COUNTRY CO POKRACOVANIE REF SELF REPO SUMMARY GH_TOKEN
#   CONTOUR_SOURCE ROCK_SOURCE SHADING_SOURCE ROCK_SLOPE TEST OPTIONS
set -euo pipefail

CO="${CO:?chýba, čo sa má pregenerovať}"
SELF="${SELF:-regenerate-state.yml}"
# Kam sa to nad krajom posiela, hovorí číselník – nie tento skript.
REGION_WF="$(python3 workers/state/jobs.py --workflow="$CO")"
REGION_MENO="$(python3 workers/state/jobs.py --meno="$CO")"
CO_POPIS="$(python3 workers/state/jobs.py --popis="$CO")"

TITUL="Pregenerovanie · ${COUNTRY:-?} · $CO"
POPIS="Pregeneruje sa **$CO_POPIS**.
Nad krajom to robí vlastný beh **$REGION_MENO**; dávka ich spúšťa jeden po
druhom a po každom si spustí ďalší svoj beh – job má strop 6 h, dávka trvá aj
deň, a tak ju nemá čo zabiť."

# ---------- odovzdanie štafety ----------
# Ten istý workflow, ten istý formulár, iný kolík. Nastavenia sa podávajú
# CELÉ a zakaždým: reťaz je séria samostatných behov a beh, ktorý by si ich
# nepodal, by pregeneroval niečo iné – a bol by pri tom zelený.
odovzdaj() {
  local kolik="$1"
  echo "Odovzdávam štafetu: pokracovanie=$kolik"
  gh workflow run "$SELF" --repo "$REPO" --ref "$REF" \
    -f country="$COUNTRY" \
    -f co="$CO" \
    -f contour_source="${CONTOUR_SOURCE:-dmr5}" \
    -f rock_source="${ROCK_SOURCE:-dmr5}" \
    -f shading_source="${SHADING_SOURCE:-dmr5}" \
    -f rock_slope="${ROCK_SLOPE:-50}" \
    -f test="${TEST:-false}" \
    -f options="${OPTIONS:-}" \
    -f pokracovanie="$kolik"
}

# ---------- spustenie nad jedným krajom ----------
# Polia vypíše číselník (`--polia`), po riadkoch `kľúč=hodnota`. Čítajú sa
# celé riadky a nie slová: `options` je jedno pole s medzerami.
spusti_kraj() {
  local kraj="$1" riadok
  local -a args=(-f "region=$kraj")
  while IFS= read -r riadok; do
    [ -n "$riadok" ] || continue
    args+=(-f "$riadok")
  done < <(python3 workers/state/jobs.py --polia="$CO")
  gh workflow run "$REGION_WF" --repo "$REPO" --ref "$REF" "${args[@]}"
}

# shellcheck source=workers/state/estafeta.sh
. workers/state/estafeta.sh
estafeta_hlavna
