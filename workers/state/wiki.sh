#!/usr/bin/env bash
# Relay leg of “Wiki state”: “Build wiki” over every region of a country.
# From the environment: COUNTRY CONTINUATION REF REPO GH_TOKEN REBUILD
set -euo pipefail

SELF="${SELF:-wiki-state.yml}"
REGION_WF="wiki.yml"
REGION_NAME="Map · Build wiki"
TITLE="Articles · ${COUNTRY:-?}"
DESCRIPTION="Each region runs its own **$REGION_NAME**, one region after another."

hand_over() {
  gh workflow run "$SELF" --repo "$REPO" --ref "$REF" \
    -f country="$COUNTRY" \
    -f rebuild="${REBUILD:-false}" \
    -f continuation="$1"
}

start_region() {
  gh workflow run "$REGION_WF" --repo "$REPO" --ref "$REF" \
    -f region="$1" \
    -f rebuild="${REBUILD:-false}"
}

# shellcheck source=workers/state/relay-core.sh
. workers/state/relay-core.sh
relay_main
