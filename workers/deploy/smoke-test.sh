#!/usr/bin/env bash
# Smoke test of the deployed map: the files are on the web and readable the way
# the map reads them. PMTiles is read by Range requests, so 206 is checked, not 200.
#
#   BASE=https://user.github.io/repo REGION=presovsky_kraj SPRITE=osm-liberty \
#   workers/deploy/smoke-test.sh
set -uo pipefail

BASE="${BASE:?address of the deployed site}"
BASE="${BASE%/}"
REGION="${REGION:?region key (plan.outputs.key)}"
SPRITE="${SPRITE:?sprite name (assets.outputs.name)}"
PAGES_BUILD_TYPE="${PAGES_BUILD_TYPE:-}"

fail=0

check() { # $1 = URL, $2 = expected code, $3 = label, $4 = extra curl args
  local code=000 attempt
  for attempt in 1 2 3 4 5; do
    # shellcheck disable=SC2086  # $4 are curl arguments split on purpose
    code=$(curl -s -o /dev/null -w '%{http_code}' ${4:-} "$1" || echo 000)
    [ "$code" = "$2" ] && break
    sleep $(( attempt * 5 ))
  done
  if [ "$code" = "$2" ]; then
    echo "  ✓ $3 ($code)"
  else
    echo "::error::$3 returned HTTP $code (expected $2) – $1"
    fail=1
  fi
}

# first wait until Pages serves this deploy (`built_at`), or checks see the old one
SITE_DIR="${SITE_DIR:-_site}"
WANT=$(jq -r '.built_at // empty' "$SITE_DIR/tiles/manifest.json" 2>/dev/null)
if [ -n "$WANT" ]; then
  echo "Waiting for Pages to serve this deploy (built_at=$WANT)"
  live=""
  for attempt in $(seq 1 30); do
    live=$(curl -s "$BASE/tiles/manifest.json" | jq -r '.built_at // empty' 2>/dev/null)
    [ "$live" = "$WANT" ] && break
    [ $(( attempt % 3 )) -eq 0 ] && \
      echo "  … $(( attempt * 10 )) s, the web still has built_at=${live:-none}"
    sleep 10
  done
  if [ "$live" = "$WANT" ]; then
    echo "  ✓ Pages serve this deploy"
  else
    echo "::error::Pages don't serve this deploy even after five minutes (the web has built_at=${live:-none}, expected $WANT). The checks below would test old files, so they don't run – see the deploy state in Settings → Pages."
    exit 1
  fi
else
  echo "::warning::$SITE_DIR/tiles/manifest.json is missing, so there is no waiting for the deploy to switch – the checks below may test old files."
fi

echo "Checking $BASE"
check "$BASE/tiles/manifest.json" 200 "manifest.json"
check "$BASE/sprites/$SPRITE.json" 200 "sprite index"
check "$BASE/sprites/$SPRITE.png" 200 "sprite bitmap"
# a phone asks for the retina variant and without it draws no icons
check "$BASE/sprites/$SPRITE@2x.json" 200 "sprite index @2x (retina, phones)"
check "$BASE/sprites/$SPRITE@2x.png" 200 "sprite bitmap @2x (retina, phones)"
check "$BASE/styles/$REGION-svetla.json" 200 "style.json"
# every map type has a style per theme; one besides the default is checked
check "$BASE/styles/$REGION-cestna-svetla.json" 200 "style.json (road map)"
check "$BASE/style-overrides.json" 200 "style overrides from developer mode"
# the region outline, when the manifest says the run made one
OUTLINE=$(jq -r '.regions[.default_region].outline // empty' \
  "$SITE_DIR/tiles/manifest.json" 2>/dev/null || true)
if [ -n "$OUTLINE" ]; then
  check "$BASE/$OUTLINE" 200 "downloaded region outline"
fi

GLYPHS=$(curl -s "$BASE/tiles/manifest.json" | jq -r '.glyphs')
case "$GLYPHS" in
  "$BASE"*) check "$BASE/fonts/Noto%20Sans%20Regular/0-255.pbf" 200 "glyphs" ;;
  *) echo "  ℹ glyphs are external: $GLYPHS" ;;
esac

# base tiles always; an empty variable = the layer wasn't built
check "$BASE/tiles/$REGION.pmtiles" 206 "pmtiles (Range request)" "-H Range:bytes=0-1023"
for pair in "${CONTOURS:-}:contours:contours" \
            "${ROCKS:-}:rocks:rocks" \
            "${TRAILS:-}:trails:waymarked trails" \
            "${FEATURES:-}:features:landscape features" \
            "${POINTS:-}:points:points of interest" \
            "${BOUNDARIES:-}:boundaries:boundaries" \
            "${WATER:-}:water:water" \
            "${RAIL:-}:rail:railways" \
            "${HISTORY:-}:history:army and history" \
            "${BUILDINGS:-}:buildings:settlements"; do
  IFS=: read -r on src label <<<"$pair"
  [ "$on" = 'true' ] || continue
  check "$BASE/tiles/$REGION-$src.pmtiles" 206 "$label (Range request)" \
        "-H Range:bytes=0-1023"
done

# the site root must be the map; Jekyll makes a README page without `id="map"`.
# Downloaded to a file first: `curl | grep -q` races into EPIPE under `pipefail`.
ROOT_HTML=$(mktemp)
trap 'rm -f "$ROOT_HTML"' EXIT
CODE=000
for attempt in 1 2 3 4 5; do
  CODE=$(curl -sL -o "$ROOT_HTML" -w '%{http_code}' "$BASE/" || echo 000)
  [ "$CODE" = 200 ] && grep -q 'id="map"' "$ROOT_HTML" && break
  sleep $(( attempt * 5 ))
done

if grep -q 'id="map"' "$ROOT_HTML"; then
  echo "  ✓ the site root is the map"
elif [ "$PAGES_BUILD_TYPE" != 'workflow' ]; then
  # the cause is known from the first step, fixable only in repository settings
  echo "::warning::$BASE/ holds the README, not the map: the Pages source is a branch (build_type=$PAGES_BUILD_TYPE), so the built-in Jekyll builder overwrote it. Settings → Pages → Source: 'GitHub Actions'."
else
  echo "::error::$BASE/ is not the map (no \`id=\"map\"\` in the HTML), though the Pages source is Actions. Last answer: HTTP $CODE, $(wc -c < "$ROOT_HTML") B. First line: $(head -c 120 "$ROOT_HTML" | tr -d '\n')"
  fail=1
fi

exit $fail
