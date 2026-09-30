#!/usr/bin/env bash
# SDF sprites from icon sets → `_site/sprites/` (sources in `poc/web/icon-sources.js`).
# A set that fails to download doesn't fail the build; only none at all does.
# `set -uo pipefail` without `-e`: skipping missing sets relies on it.

set -uo pipefail
T_SPR=$(date +%s)
mkdir -p _site/sprites /tmp/icons

# find, not ls: `ls pattern*` without a match exits 2 and `pipefail` fails the step
CACHED_SPRITES=$(find _site/sprites -maxdepth 1 -name '*.json' | wc -l)

# custom sets from developer mode are in the list too
node -e "
  Promise.all([
    import('./poc/web/icon-sources.js'),
    import('./poc/web/themes.js'),
    import('node:fs')
  ]).then(([ic, th, fs]) => {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync('poc/web/style-overrides.json', 'utf8')); } catch {}
    for (const s of ic.allIconSources(th.normalizeOverrides(raw).overrides)) {
      console.log(s.id + ' ' + s.sprite);
    }
  });
" > /tmp/icons/list.txt
cat /tmp/icons/list.txt

ok=""
while read -r id url; do
  [ -n "$id" ] || continue
  if [ "$CACHED_SPRITES" -gt 0 ] && [ -s "_site/sprites/$id.json" ]; then
    echo "── $id (from cache)"
    ok="$ok $id"
    continue
  fi
  echo "── $id"
  got=1
  for ext in .json .png; do
    curl -fL --retry 4 --retry-delay 5 -o "/tmp/icons/$id$ext" "$url$ext" || got=0
  done
  # @2x is optional – without it the map is only softer on retina
  for ext in '@2x.json' '@2x.png'; do
    curl -fL --retry 2 --retry-delay 3 -o "/tmp/icons/$id$ext" "$url$ext" \
      || rm -f "/tmp/icons/$id$ext"
  done
  if [ "$got" != 1 ]; then
    echo "::warning::Icon set $id couldn't be downloaded – skipping."
    continue
  fi
  if node workers/assets/sprite.mjs --in="/tmp/icons/$id" --out="_site/sprites/$id"; then
    # our own images; each missing one degrades the map, so warnings only
    node workers/assets/shields.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Road shields couldn't be baked into set $id – road numbers will have no base."
    node workers/assets/route-shields.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Network shields couldn't be baked into set $id – road numbers get the classic shield."
    node workers/assets/marks.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Trail marks couldn't be baked into set $id – trails get the kind icon, not the mark."
    node workers/assets/arrows.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::One-way arrows couldn't be baked into set $id – one-way roads will have no arrows."
    node workers/assets/custom-icons.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Custom icons couldn't be baked into set $id – layers using them stay without an icon."
    ok="$ok $id"
  else
    echo "::warning::Icon set $id couldn't be converted to SDF – skipping."
  fi
done < /tmp/icons/list.txt

if [ -z "$ok" ]; then
  echo "::error::Not a single icon set could be prepared – the map would have no icons."
  exit 1
fi

# developer-mode overrides pick the style's set
WANT=$(node -e "
  Promise.all([import('./poc/web/themes.js'), import('node:fs')]).then(([m, fs]) => {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync('poc/web/style-overrides.json', 'utf8')); } catch {}
    console.log(m.selectedIconSource(m.normalizeOverrides(raw).overrides));
  });
")
if [ ! -s "_site/sprites/$WANT.json" ]; then
  WANT=$(printf '%s' "$ok" | awk '{print $1}')
  echo "::warning::The chosen icon set isn't available – using $WANT."
fi
echo "name=$WANT" >> "$GITHUB_OUTPUT"
echo "available=$(printf '%s' "$ok" | xargs)" >> "$GITHUB_OUTPUT"
echo "Deployed sets:$ok, the style uses $WANT"
printf '%s\t%s\t%s\t%s\n' "80" "Icons (SDF sprites)" "$(( $(date +%s) - T_SPR ))" \
  "sets:$ok, the style uses $WANT$([ "$CACHED_SPRITES" -gt 0 ] && echo ' (from cache)')" \
  >> steps-out/assets.tsv
