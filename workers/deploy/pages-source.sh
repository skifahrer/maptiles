#!/usr/bin/env bash
# Turn GitHub Pages on with Actions as its source – and say so when it can't.
#
# With a branch source the deploy works, but the next push to master overwrites
# the map, so this tries, reports what the API said, and goes on.
#
# In:  GH_TOKEN, GITHUB_REPOSITORY
# Out: `build_type` into GITHUB_OUTPUT – `workflow` when it takes Actions.

set -uo pipefail
BY_HAND="Set it once by hand: Settings → Pages → Build and deployment → Source: 'GitHub Actions'."
# declared up front: under `set -u` a variable made only in a branch is a silent trap
ANSWER=""

PAGES=$(gh api "repos/$GITHUB_REPOSITORY/pages" 2>/dev/null || true)

if [ -z "$PAGES" ]; then
  echo "GitHub Pages is off – turning it on with the GitHub Actions source…"
  if ANSWER=$(gh api -X POST "repos/$GITHUB_REPOSITORY/pages" \
       -f 'build_type=workflow' 2>&1); then
    echo "  ✓ on"
    PAGES=$(gh api "repos/$GITHUB_REPOSITORY/pages" 2>/dev/null || true)
  else
    echo "  The API answered: $ANSWER"
    # without Pages there is no deploying – stop here
    echo "::error::GitHub Pages is off and the token couldn't turn it on (that needs admin rights). $BY_HAND"
    exit 1
  fi
fi

BT=$(printf '%s' "$PAGES" | jq -r '.build_type // "?"')
if [ "$BT" != 'workflow' ]; then
  echo "Pages takes its source from a branch (build_type=$BT) – trying to switch to GitHub Actions…"
  if ANSWER=$(gh api -X PUT "repos/$GITHUB_REPOSITORY/pages" \
       -f 'build_type=workflow' 2>&1); then
    # verify, don't trust: a PUT may pass and the setting stay old
    BT=$(gh api "repos/$GITHUB_REPOSITORY/pages" --jq '.build_type // "?"' 2>/dev/null || echo '?')
    [ "$BT" = 'workflow' ] && echo "  ✓ switched (build_type=$BT)"
  else
    echo "  The API answered: $ANSWER"
  fi
fi

echo "build_type=$BT" >> "$GITHUB_OUTPUT"
if [ "$BT" != 'workflow' ]; then
  # a warning, not an error: the map deploys and lives until the next push to master
  echo "::warning::GitHub Pages takes its source from a branch (build_type=$BT), not from Actions, and the token couldn't switch it. The map deploys, but the next push to master overwrites it with the repository contents (you'll see the README). $BY_HAND"
else
  echo "Pages is on and takes Actions ✓ – this run's map deploys"
fi
