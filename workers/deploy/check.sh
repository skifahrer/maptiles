#!/usr/bin/env bash
# Checks the deployed site is whole: the style points at nothing missing from
# `_site`, and the total fits the budget. A missing sprite never crashes – the
# map just draws half of it.
#
#   SPRITE=osm-liberty REGION_KEY=presovsky_kraj LIMIT_MB=900 \
#   workers/deploy/check.sh
set -euo pipefail

SPRITE="${SPRITE:?sprite name (assets.outputs.name)}"
REGION_KEY="${REGION_KEY:?region key (plan.outputs.key)}"
LIMIT_MB="${LIMIT_MB:-900}"
SITE="${SITE:-_site}"

fail=0
shopt -s nullglob
styles=("$SITE"/styles/*.json)
if [ ${#styles[@]} -eq 0 ]; then
  echo "::error::$SITE/styles holds no styles"
  exit 1
fi
STYLE="${styles[0]}"
echo "Checking $STYLE"

# the sprite the style really points at
for ext in .json .png; do
  [ -s "$SITE/sprites/$SPRITE$ext" ] || { echo "::error::sprites/$SPRITE$ext is missing"; fail=1; }
done

# a phone asks for `@2x` and without it draws NO icons; its names must match 1×
for ext in @2x.json @2x.png; do
  [ -s "$SITE/sprites/$SPRITE$ext" ] \
    || { echo "::error::sprites/$SPRITE$ext is missing – a high-density display (a phone) asks for exactly this variant and without it draws NOT ONE icon"; fail=1; }
done
if [ -s "$SITE/sprites/$SPRITE@2x.json" ]; then
  MISSING=$(jq -r --slurpfile two "$SITE/sprites/$SPRITE@2x.json" \
    '[keys[] | select(. as $k | ($two[0] | has($k)) | not)] | join(", ")' \
    "$SITE/sprites/$SPRITE.json")
  if [ -n "$MISSING" ]; then
    echo "::error::sprites/$SPRITE@2x.json lacks images the 1× has: $MISSING"
    fail=1
  fi
fi

# glyphs – only when we host them; fontstack names hold spaces, hence read -r
if jq -e '.glyphs | contains("openmaptiles.org") | not' "$STYLE" >/dev/null; then
  while IFS= read -r stack; do
    if [ ! -s "$SITE/fonts/$stack/0-255.pbf" ]; then
      echo "::error::the style uses fontstack '$stack', but $SITE/fonts/$stack/0-255.pbf doesn't exist"
      fail=1
    fi
  done < <(jq -r '[.layers[].layout["text-font"] // empty] | flatten | unique | .[]' "$STYLE")
fi

# fixed icon names must be in the sprite (expression names come from the sprite index)
while IFS= read -r icon; do
  [ -n "$icon" ] || continue
  jq -e --arg i "$icon" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
    || { echo "::error::the style points at icon '$icon', which isn't in the sprite"; fail=1; }
done < <(jq -r '[.layers[].layout["icon-image"]? | strings] | unique | .[]' "$STYLE")

# trail marks are named from DATA, so a missing one is skipped silently; list from marks.js
if jq -e '[.layers[] | select(.id | endswith("-mark"))] | length > 0' "$STYLE" >/dev/null; then
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    jq -e --arg i "$img" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
      || { echo "::error::the style draws trail marks, but '$img' isn't in the sprite"; fail=1; }
  done < <(node -e "
    import('./poc/web/marks.js').then((m) => {
      for (const x of m.markImages()) console.log(x.name);
    });
  ")
fi

# one-way arrows: baked into every set, a missing one drops `road-oneway` silently
if jq -e '[.layers[] | select(.id == "road-oneway")] | length > 0' "$STYLE" >/dev/null; then
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    jq -e --arg i "$img" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
      || { echo "::error::the style draws one-way streets, but arrow '$img' isn't in the sprite"; fail=1; }
  done < <(node -e "
    import('./poc/web/arrows.js').then((m) => {
      for (const x of m.arrowImages()) console.log(x);
    });
  ")
fi

# area and line patterns must be in the sprite, or the area isn't drawn
while IFS= read -r img; do
  [ -n "$img" ] || continue
  jq -e --arg i "$img" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
    || { echo "::error::the style uses pattern '$img', which isn't in the sprite"; fail=1; }
done < <(jq -r '[.layers[].paint["fill-pattern"]?, .layers[].paint["line-pattern"]? | strings] | unique | .[]' "$STYLE")

# tiles
PM="$SITE/tiles/$REGION_KEY.pmtiles"
[ -s "$PM" ] || { echo "::error::$PM is missing"; fail=1; }

# layers the style asks for must be in `_site`, or the layer is silently missing
for pair in "contours:contours" "rocks:rocks" "trails:waymarked trails" \
            "features:landscape features" "points:points of interest" \
            "transport:the road network (and road limits)" \
            "boundaries:boundaries" "water:water" "rail:railways" "buildings:settlements"; do
  src="${pair%%:*}"; label="${pair#*:}"
  jq -e ".sources.$src" "$STYLE" >/dev/null || continue
  f="$SITE/tiles/$REGION_KEY-$src.pmtiles"
  [ -s "$f" ] || { echo "::error::the style uses $label, but $f is missing"; fail=1; }
done

# the web viewer loads the region outline from this file at run time
if jq -e '.sources.region' "$STYLE" >/dev/null; then
  [ -s "$SITE/region.geojson" ] \
    || { echo "::error::the style has a region outline, but $SITE/region.geojson is missing (made by workers/deploy/region-mask.py)"; fail=1; }
fi

# a last guard: Pages takes ~1 GB for the whole site
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TOTAL_MB=$(du -sm "$SITE" | cut -f1)
echo "Size of $SITE: ${TOTAL_MB} MB (budget ${LIMIT_MB} MB)"
du -sm "$SITE"/tiles "$SITE"/fonts "$SITE"/sprites 2>/dev/null || true
if [ "$TOTAL_MB" -gt "$LIMIT_MB" ]; then
  echo "::error::$SITE is ${TOTAL_MB} MB, the budget is ${LIMIT_MB} MB (GitHub Pages takes ~1 GB). Lower maxzoom, turn contours off, raise contour_interval or use a smaller region / crop_bbox."
  fail=1
fi
exit $fail
