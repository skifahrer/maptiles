#!/usr/bin/env bash
# Úsek štafety „Wiki state": „Build wiki" nad každým krajom krajiny.
# Z prostredia: COUNTRY POKRACOVANIE REF REPO GH_TOKEN REBUILD
set -euo pipefail

SELF="${SELF:-wiki-state.yml}"
REGION_WF="wiki.yml"
REGION_MENO="Mapa · Build wiki"
TITUL="Články · ${COUNTRY:-?}"
POPIS="Nad krajom beží vlastný **$REGION_MENO**, kraje idú jeden po druhom."

odovzdaj() {
  gh workflow run "$SELF" --repo "$REPO" --ref "$REF" \
    -f country="$COUNTRY" \
    -f rebuild="${REBUILD:-false}" \
    -f pokracovanie="$1"
}

spusti_kraj() {
  gh workflow run "$REGION_WF" --repo "$REPO" --ref "$REF" \
    -f region="$1" \
    -f rebuild="${REBUILD:-false}"
}

# shellcheck source=workers/state/estafeta.sh
. workers/state/estafeta.sh
estafeta_hlavna
