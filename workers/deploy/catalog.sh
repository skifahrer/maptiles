#!/usr/bin/env bash
# Commit a changed `maps.json` – the last step of a build.
#
# Several jobs of one run write the catalog, so the parent is the fresh branch
# and `catalog-merge.py` adds only what this run changed against its base.
# A rejected push by a repository rule fails the run; a race retries.
#
# From the environment: MAPS_JSON (which file), BRANCH (where to push), RUN_URL.
set -uo pipefail

MAPS_JSON="${MAPS_JSON:-maps.json}"
BRANCH="${BRANCH:-master}"
TRIES=4

if [ ! -f "$MAPS_JSON" ]; then
  echo "::warning::$MAPS_JSON doesn't exist – nothing to commit."
  exit 0
fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# what this run wrote, and what it started from (kept by `catalog.py`)
MINE="$(mktemp)"
THEIRS="$(mktemp)"
BASE="$MAPS_JSON.base"
cp "$MAPS_JSON" "$MINE"
trap 'rm -f "$MINE" "$THEIRS"' EXIT
if [ ! -f "$BASE" ]; then
  echo "::warning::$BASE is missing – the commit carries the whole file, so another job's write from this run may be lost."
fi

# branch + my change; without a base or a file in the branch, my write
merge_with_branch() {
  cp "$MINE" "$MAPS_JSON"
  [ -f "$BASE" ] || return 0
  git show "FETCH_HEAD:$MAPS_JSON" >"$THEIRS" 2>/dev/null || return 0
  python3 workers/deploy/catalog-merge.py --base="$BASE" --mine="$MINE" \
    --theirs="$THEIRS" --out="$MAPS_JSON" || cp "$MINE" "$MAPS_JSON"
}

# a branch rule's rejection is no race: the next build wouldn't pass either
push_output=""
rejected_for_good() {
  printf '%s' "$push_output" | grep -qE 'GH013|repository rule violations|protected branch|pre-receive hook declined'
}

for i in $(seq 1 "$TRIES"); do
  # parent is the fresh branch; `--mixed` leaves the working tree alone
  if git fetch --quiet --depth=1 origin "$BRANCH" 2>/dev/null; then
    merge_with_branch
    git reset --mixed --quiet FETCH_HEAD 2>/dev/null \
      || echo "::warning::The index couldn't be moved to $BRANCH."
    echo "Commit parent: fresh $BRANCH ($(git rev-parse --short FETCH_HEAD))"
  else
    echo "::warning::Branch $BRANCH couldn't be fetched – committing on the SHA this run started from. Another job's catalog write since then is lost."
  fi

  # a new file is a change too: `git diff` says nothing about untracked files
  if git ls-files --error-unmatch -- "$MAPS_JSON" >/dev/null 2>&1; then
    if git diff --quiet -- "$MAPS_JSON"; then
      echo "$MAPS_JSON didn't change (the same map with the same links) – no commit."
      exit 0
    fi
  else
    echo "$MAPS_JSON isn't in the repository yet – creating it."
  fi

  git add "$MAPS_JSON"
  git commit -q -m "Map catalog: $(git diff --cached --shortstat -- "$MAPS_JSON" | tr -s ' ')" \
    -m "Written by build ${RUN_URL:-(no link)} after uploading the packages to Drive." \
    || { echo "::warning::The commit failed – the next build writes the catalog."; exit 0; }

  if push_output=$(git push origin "HEAD:$BRANCH" 2>&1); then
    printf '%s\n' "$push_output"
    echo "$MAPS_JSON is in branch $BRANCH ✓"
    exit 0
  fi
  printf '%s\n' "$push_output"
  if rejected_for_good; then
    echo "::error::$MAPS_JSON can't be written to branch $BRANCH – a repository rule rejected the push, not a race of two runs. The next build WON'T write it either: packages on Drive keep being overwritten while the catalog stays as it is now. Give the bot a way into $BRANCH (a ruleset bypass or a push through a pull request) and run the build again."
    exit 1
  fi
  if [ "$i" -eq "$TRIES" ]; then break; fi
  WAIT=$(( 2 ** i ))
  echo "Push to $BRANCH failed ($i of $TRIES) – merging with the fresh branch and retrying in ${WAIT} s."
  sleep "$WAIT"
done
echo "::warning::$MAPS_JSON couldn't be pushed to $BRANCH in $TRIES tries. The map is on Drive; the next build writes the catalog."
exit 0
