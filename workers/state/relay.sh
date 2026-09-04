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
#   reuse_layers  dopĺňa sa do `options` ako `true`, keď si ho tam človek
#                 nenapísal sám. Rozpis hneď nižšie.
# Všetko ostatné sa podáva ďalej nezmenené – a podáva sa CELÉ a zakaždým,
# lebo články štafety sú samostatné behy a beh bez nich by postavil inú mapu.
# Stráži to `workers/lint/state.py`.
#
# ── PREČO DÁVKA NEPOČÍTA VRSTVY, KTORÉ UŽ RAZ VZNIKLI ─────────────────────
# Vrstevnice, skaly a tieňovanie sú hodiny na kraj a krajov je osem – z dňa,
# ktorý dávka trvá, je to väčšina. A pritom sa medzi dvomi dávkami zmení
# málokedy niečo, čo by ich zmenilo: doplnený sklad výškového modelu a opravený
# skript inde v pipeline zahodili cache oboch (bol v kľúči ich otlačok), takže
# druhá dávka počítala to isté odznova. Preto sa každému kraju podáva
# `reuse_layers=true`: vrstva, ktorá s TÝMI ISTÝMI nastaveniami už existuje,
# sa vezme hotová a job, ktorý to spraví, to hlási `::notice::`-om.
#
# KTO CHCE PREPOČET, POVIE TO – a má na to dve páky, obe v tomto formulári:
# `rebuild` (zahodí záznam tej vrstvy a spočíta ju nanovo) alebo
# `options: reuse_layers=false` (celá dávka prísne, ako jeden kraj). Preto sa
# hodnota dopĺňa len vtedy, keď o `reuse_layers` v `options` nie je ani slovo –
# napísané prebíja doplnené.
#
# Hodnoty z prostredia (viď `.github/workflows/build-map-state.yml`):
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
