#!/usr/bin/env bash
# One relay leg of “Regenerate state”: over each region it starts one thing,
# the one the form names (`what`); `workers/state/jobs.py` says what that runs.
#
# From the environment (see `.github/workflows/regenerate-state.yml`):
#   COUNTRY WHAT CONTINUATION REF SELF REPO SUMMARY GH_TOKEN
#   CONTOUR_SOURCE ROCK_SOURCE SHADING_SOURCE ROCK_SLOPE TEST OPTIONS
set -euo pipefail

WHAT="${WHAT:?what to regenerate is missing}"
SELF="${SELF:-regenerate-state.yml}"
REGION_WF="$(python3 workers/state/jobs.py --workflow="$WHAT")"
REGION_NAME="$(python3 workers/state/jobs.py --name="$WHAT")"
WHAT_DESCRIPTION="$(python3 workers/state/jobs.py --describe="$WHAT")"

TITLE="Regeneration · ${COUNTRY:-?} · $WHAT"
DESCRIPTION="Regenerating **$WHAT_DESCRIPTION**.
Over each region it is a run of **$REGION_NAME**; the batch starts them one
by one and dispatches its own next run after each – a job has a 6 h cap, a
batch takes a day, so nothing can kill it."

# same workflow, same form, another baton; settings go whole every time
hand_over() {
  local baton="$1"
  echo "Handing the relay over: continuation=$baton"
  gh workflow run "$SELF" --repo "$REPO" --ref "$REF" \
    -f country="$COUNTRY" \
    -f what="$WHAT" \
    -f contour_source="${CONTOUR_SOURCE:-dmr5}" \
    -f rock_source="${ROCK_SOURCE:-dmr5}" \
    -f shading_source="${SHADING_SOURCE:-dmr5}" \
    -f rock_slope="${ROCK_SLOPE:-50}" \
    -f test="${TEST:-false}" \
    -f options="${OPTIONS:-}" \
    -f continuation="$baton"
}

# fields come from the registry line by line: `options` holds spaces
start_region() {
  local region="$1" line
  local -a args=(-f "region=$region")
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    args+=(-f "$line")
  done < <(python3 workers/state/jobs.py --fields="$WHAT")
  gh workflow run "$REGION_WF" --repo "$REPO" --ref "$REF" "${args[@]}"
}

# shellcheck source=workers/state/relay-core.sh
. workers/state/relay-core.sh
relay_main
