#!/usr/bin/env bash
# Relay core shared by the country batches (`relay.sh` builds every region,
# `regenerate.sh` regenerates one layer, `wiki.sh` builds articles).
#
# A region takes up to three hours and a job six, so each run is one short leg
# that dispatches the next run of the same workflow; a chain has no cap.
#
# The baton is the input `continuation`, four fields split by `|`:
#
#   <run id>:<region>|<regions still to go>|<done>|<leg number>
#
# An empty baton = the first leg. A failed region doesn't stop the chain, the
# last leg fails on it. A cancelled region stops the batch green.
#
# The caller provides: COUNTRY REPO (optionally REF SELF REGION_WF SUMMARY),
# TITLE and DESCRIPTION, functions `hand_over` and `start_region`, then calls
# `relay_main`.
set -euo pipefail

COUNTRY="${COUNTRY:?country missing}"
REPO="${REPO:?repository missing}"
CONTINUATION="${CONTINUATION:-}"
REF="${REF:-master}"
REGION_WF="${REGION_WF:?region workflow missing}"
# the region workflow's name as the form shows it – for the "run it by hand" line
REGION_NAME="${REGION_NAME:-$REGION_WF}"
SUMMARY="${SUMMARY:-${GITHUB_STEP_SUMMARY:-/dev/null}}"
SERVER="${GITHUB_SERVER_URL:-https://github.com}"

# five hours of waiting leave one of the job's six for dispatching the next leg
WAIT_MAX_S="${WAIT_MAX_S:-18000}"    # 5 h
POLL_S="${POLL_S:-60}"
# guard against an endless chain; three legs per region is the worst case
LEGS_PER_REGION=3

log() { echo "$@"; }
summary() { echo "$@" >> "$SUMMARY"; }

# an interruptible sleep: a foreground `sleep` would run the trap a minute late
pause() {
  sleep "$1" &
  wait "$!" 2>/dev/null || true
}

# a cancelled batch cancels the region it waited for; best effort
on_cancel() {
  trap - INT TERM
  if [ -n "${RUNNING_ID:-}" ]; then
    log "The batch run was cancelled – cancelling the region run ${RUNNING_REGION:-?} ($RUNNING_ID) too."
    gh run cancel "$RUNNING_ID" --repo "$REPO" 2>/dev/null || \
      log "::warning::Region run $RUNNING_ID couldn't be cancelled – cancel it by hand, or it runs to the end."
  fi
  exit 130
}
trap on_cancel INT TERM

run_link() { echo "$SERVER/$REPO/actions/runs/$1"; }

# GitHub ended the run with jobs that never got a runner, and none of ours failed
never_started() {
  gh run view "$1" --repo "$REPO" --json attempt,jobs --jq \
    '.attempt == 1
     and ([.jobs[] | select(.conclusion == "failure")] | length) == 0
     and ([.jobs[] | select(.status != "completed")] | length) > 0' 2>/dev/null || true
}

# the whole picture in every leg, rebuilt from the baton
FAILED=0
write_summary() {
  summary "## $TITLE"
  summary ""
  summary "Relay leg **$LEG**. $DESCRIPTION"
  summary ""
  summary "| region | state |"
  summary "| --- | --- |"
  FAILED=0
  local region h line rest result hid
  for region in $(echo "$ALL" | tr ',' ' '); do
    line=""
    for h in $(echo "$DONE" | tr ',' ' '); do
      [ "${h%%:*}" = "$region" ] || continue
      rest="${h#*:}"; result="${rest%%:*}"; hid="${rest#*:}"
      if [ "$result" = "success" ]; then
        line="| \`$region\` | ✅ done ([run]($(run_link "$hid"))) |"
      else
        line="| \`$region\` | ❌ $result ([run]($(run_link "$hid"))) |"
        FAILED=$(( FAILED + 1 ))
      fi
    done
    if [ -z "$line" ] && [ "$region" = "$RUNNING_REGION" ]; then
      line="| \`$region\` | ⏳ running ([run]($(run_link "$RUNNING_ID"))) |"
    fi
    summary "${line:-"| \`$region\` | · waiting |"}"
  done
  summary ""
}

relay_main() {
  # unpack the baton
  IFS='|' read -r RUNNING_FIELD REMAINING DONE LEG <<< "$CONTINUATION"
  RUNNING_FIELD="${RUNNING_FIELD:-}"; REMAINING="${REMAINING:-}"
  DONE="${DONE:-}";                   LEG="${LEG:-0}"
  RUNNING_ID="${RUNNING_FIELD%%:*}"
  RUNNING_REGION="${RUNNING_FIELD#*:}"
  [ "$RUNNING_FIELD" = "$RUNNING_ID" ] && RUNNING_REGION=""

  ALL="$(python3 workers/state/queue.py --regions="$COUNTRY" | paste -sd, -)"
  if [ -z "$CONTINUATION" ]; then
    # first leg: regions from the registry, so a new one is never silently missing
    REMAINING="$ALL"
    log "Batch for country $COUNTRY: $REMAINING"
  fi
  LEG=$(( LEG + 1 ))
  REGION_COUNT="$(echo "$ALL" | tr ',' '\n' | grep -c .)"
  LEGS_MAX=$(( REGION_COUNT * LEGS_PER_REGION + 2 ))
  if [ "$LEG" -gt "$LEGS_MAX" ]; then
    echo "::error::The relay is $LEG legs in, more than $LEGS_MAX for $REGION_COUNT regions – the chain isn't shrinking and I won't start another leg. See the baton: continuation=$CONTINUATION"
    exit 1
  fi
  log "Leg $LEG of at most $LEGS_MAX. Running “${RUNNING_REGION:-(none)}” ($RUNNING_ID), remaining “${REMAINING:-(none)}”."

  # 1. wait for the running region
  if [ -n "$RUNNING_ID" ]; then
    local start state result
    start=$(date +%s)
    state=""
    while :; do
      state="$(gh run view "$RUNNING_ID" --repo "$REPO" --json status,conclusion \
                --jq '.status + " " + (.conclusion // "")' 2>/dev/null || true)"
      case "$state" in
        "completed failure")
          if [ "$(never_started "$RUNNING_ID")" = "true" ]; then
            log "::warning::Region $RUNNING_REGION (run $RUNNING_ID) failed with jobs GitHub never started – running it once more."
            if gh run rerun "$RUNNING_ID" --repo "$REPO"; then
              pause "$POLL_S"
              continue
            fi
            log "::warning::Run $RUNNING_ID couldn't be started again – it counts as failed."
          fi
          break ;;
        completed*) break ;;
        "") log "::warning::Run $RUNNING_ID can't be read (API outage?) – still trying." ;;
      esac
      if [ $(( $(date +%s) - start )) -ge "$WAIT_MAX_S" ]; then
        # the region outlasts this job – hand the same baton on
        log "Region $RUNNING_REGION runs longer than $((WAIT_MAX_S / 3600)) h – handing the relay on."
        hand_over "$RUNNING_FIELD|$REMAINING|$DONE|$LEG"
        write_summary
        summary "Region **$RUNNING_REGION** still runs after $((WAIT_MAX_S / 3600)) h – the next leg waits for it."
        exit 0
      fi
      pause "$POLL_S"
    done
    result="${state#completed }"
    result="${result:-unknown}"
    log "Region $RUNNING_REGION (run $RUNNING_ID) finished: $result"
    DONE="${DONE:+$DONE,}$RUNNING_REGION:$result:$RUNNING_ID"
    # a cancelled region stops the batch – the only way a person can tell it
    if [ "$result" = "cancelled" ]; then
      REMAINING_BEFORE="$REMAINING"
      RUNNING_ID=""; RUNNING_REGION=""; RUNNING_FIELD=""; REMAINING=""
      write_summary
      summary "**Batch stopped.** The region run was cancelled, so no further region"
      summary "starts and the relay chain ends here."
      if [ -n "$REMAINING_BEFORE" ]; then
        # GitHub cancels runs on its own too, so leave a baton to continue with
        summary ""
        summary "Not built: \`$REMAINING_BEFORE\`. Continue with the same batch and"
        summary "the baton \`|$REMAINING_BEFORE|$DONE|0\` in the field \`continuation\`."
      fi
      log "The region was cancelled – the batch ends. Not built: ${REMAINING_BEFORE:-(none)}"
      return 0
    fi
    if [ "$result" != "success" ]; then
      log "::warning::Region $RUNNING_REGION finished as $result. The batch goes on with the next region – the last leg fails on it, so the batch never ends green with a hole in the map."
    fi
    RUNNING_ID=""; RUNNING_REGION=""; RUNNING_FIELD=""
  fi

  # 2. start the next region
  NEW_BATON=""
  if [ -n "$REMAINING" ]; then
    local region rest before id
    region="${REMAINING%%,*}"
    rest="${REMAINING#*,}"
    [ "$rest" = "$REMAINING" ] && rest=""
    log "Starting region $region …"
    # `workflow_dispatch` returns no id (204), so the run is found by its time
    before="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    start_region "$region"
    id=""
    for _ in $(seq 1 30); do
      sleep 5
      id="$(gh run list --repo "$REPO" --workflow "$REGION_WF" \
              --event workflow_dispatch --branch "$REF" --limit 20 \
              --json databaseId,createdAt \
              --jq "[.[] | select(.createdAt >= \"$before\")] | sort_by(.createdAt) | last | .databaseId" \
            2>/dev/null || true)"
      [ -n "$id" ] && [ "$id" != "null" ] && break
      id=""
    done
    if [ -z "$id" ]; then
      # two regions at once would fight over cache and catalog, so waiting is a must
      echo "::error::I started region $region, but its run didn't show in the $REGION_WF runs within two minutes. Without its id there's no waiting for it, so the chain ends here – start the remaining regions ($region,$rest) with the batch again."
      exit 1
    fi
    log "Region $region runs as $id ($(run_link "$id"))"
    # set before handing over, so the `trap` knows which region to cancel
    RUNNING_ID="$id"; RUNNING_REGION="$region"; REMAINING="$rest"
    NEW_BATON="$id:$region|$rest|$DONE|$LEG"
    hand_over "$NEW_BATON"
  fi

  write_summary

  if [ -n "$NEW_BATON" ]; then
    summary "The next relay leg is started; baton: \`$NEW_BATON\`"
    exit 0
  fi

  # end of the chain
  summary "**The batch is done.**"
  if [ "$FAILED" -gt 0 ]; then
    echo "::error::The batch for $COUNTRY finished, but $FAILED region(s) failed – the country's map has a hole. The list is in the summary; run the failed regions again one by one with “$REGION_NAME”."
    exit 1
  fi
  log "The batch for $COUNTRY is done – every region passed."
}
