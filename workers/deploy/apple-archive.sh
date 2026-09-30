#!/usr/bin/env bash
# The map's packages once more as Apple Archive (`.aar`), up to Drive.
#
# A job of its own on macOS, the only place with `aa`. The same contents, names
# and Drive folder as the ZIP job (`publish-map.py --format=aar`); the env must
# match that job too (`MAP_LAYERS`), or `.aar` overwrites what it said of layers.
# Plus ONLY/WIKI/SITE (which package) and BRANCH (where a fresh `maps.json` is).
set -euo pipefail

if ! command -v aa >/dev/null 2>&1; then
  echo "::error::The aa tool isn't here. Apple Archive ships with macOS 11+, so this job must run on macos-latest; .aar can't be built on Linux."
  exit 1
fi
echo "Apple Archive: $(command -v aa)"

# empty ONLY = the map's packages from `_site`, `wikipedia` = articles from WIKI,
# another name = one layer package from SITE
ONLY="${ONLY:-}"
WIKI="${WIKI:-}"
# which catalog: `catalog.py` answers, `catalog.sh` commits the same file
MAPS="$(python3 workers/deploy/catalog.py --file)"
echo "Catalog of this run: $MAPS"
ARGS=(--format=aar --maps="$MAPS" --summary="${GITHUB_STEP_SUMMARY:-/dev/null}")

if [ "$ONLY" = wikipedia ]; then
  ARGS+=(--only="$ONLY")
  if [ -z "$WIKI" ] || [ ! -f "$WIKI/index.json" ]; then
    echo "::error::ONLY=$ONLY, but there are no articles (WIKI=${WIKI:-empty}). Not going on: publish-map.py would fail on an empty package."
    exit 1
  fi
  ARGS+=(--wiki="$WIKI" --site="${SITE:-_site}")
  echo "Packing one package: $ONLY ($(du -sh "$WIKI" | cut -f1))"
elif [ -n "$ONLY" ]; then
  # one layer package from `_site` (Regenerate region layer); `files.py` says what goes in
  SITE_DIR="${SITE:-_site}"
  ARGS+=(--only="$ONLY" --site="$SITE_DIR")
  echo "Packing one package: $ONLY from $SITE_DIR ($(du -sh "$SITE_DIR" | cut -f1))"
else
  # without the manifest `.aar` is no map and the catalog entry loses bbox and zooms
  if [ ! -f _site/tiles/manifest.json ]; then
    echo "::error::_site isn't assembled – tiles/manifest.json is missing (and with it styles and viewer). The site-* pieces come here with the deploy-site artifact of the deploy job on top; see the step “Collect the assembled part of the site”. Not going on: the .aar would be no map and maps.json would lose bbox and zooms."
    exit 1
  fi
  if [ ! -d _site/styles ]; then
    echo "::error::_site has no styles folder – without styles the .aar is no map, just tiles. See the step “Collect the assembled part of the site”."
    exit 1
  fi
  # the app reads only `.aar`, and a style without a sprite draws no icon
  if [ -z "$(find _site/sprites -name '*.json' -print -quit 2>/dev/null)" ]; then
    echo "::error::_site has no sprites – the app reads .aar and without them the map draws not one icon. See the step “Collect the site pieces”."
    exit 1
  fi
  ARGS+=(--site=_site)
  echo "Assembled _site ✓ ($(find _site -type f | wc -l | tr -d ' ') files, $(du -sh _site | cut -f1))"
fi

# read the catalog from the branch, not the checkout: the job before just committed it
BRANCH="${BRANCH:-master}"
if git fetch --depth=1 origin "$BRANCH" >/dev/null 2>&1 \
   && git checkout FETCH_HEAD -- "$MAPS" 2>/dev/null; then
  echo "$MAPS: fresh from branch $BRANCH (the job before just wrote into it)"
else
  echo "$MAPS: not in branch $BRANCH – taking the checkout's."
fi

python3 workers/deploy/publish-map.py "${ARGS[@]}"
