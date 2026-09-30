#!/usr/bin/env bash
# Glyphs (fonts) onto Pages ourselves, so the map doesn't depend on a foreign service.
# Without the bundle the style falls back to `fonts.openmaptiles.org`. `GLYPHS_ZIP` comes from env.

set -euo pipefail

# ranges for every app language (`TILE_LANGUAGES`); a missing one shows empty boxes.
#     0-2559       Latin, Latin-1, Ext-A/B, diacritics, Greek, Cyrillic, Arabic, Devanagari
#     7424-9215    phonetics, Latin Ext. Additional, Greek Ext., punctuation, currency
#     11264-11519  Latin Extended-C
#     42752-43007  Latin Extended-D, tone modifiers
#     64256-65279  Arabic presentation forms MapLibre shapes Arabic with
# CJK is drawn by MapLibre with the system font; `all` turns the cut off.
GLYPHS_KEEP_RANGES="${GLYPHS_KEEP_RANGES:-0-2559,7424-9215,11264-11519,42752-43007,64256-65279}"

mkdir -p _site/fonts
if [ -n "$(ls -A _site/fonts 2>/dev/null)" ]; then
  echo "Glyphs from cache ✓"
elif curl -fL --retry 4 --retry-delay 5 -o /tmp/glyphs.zip "$GLYPHS_ZIP"; then
  unzip -q /tmp/glyphs.zip -d /tmp/glyphs

  # a fontstack is a folder with 0-255.pbf; names vary: exact → any Noto Sans → all
  mapfile -t stacks < <(find /tmp/glyphs -name '0-255.pbf' -printf '%h\n' | sort -u)
  echo "The bundle has ${#stacks[@]} fontstacks."

  copy_matching() { # $1 = grep -E pattern on the folder name
    local copied=0 d
    for d in "${stacks[@]}"; do
      if printf '%s' "$(basename "$d")" | grep -qiE "$1"; then
        cp -r "$d" _site/fonts/ && copied=$(( copied + 1 ))
      fi
    done
    [ "$copied" -gt 0 ]
  }

  copy_matching '^Noto Sans (Regular|Bold|Italic)$' \
    || copy_matching 'noto.?sans' \
    || cp -r "${stacks[@]}" _site/fonts/ 2>/dev/null \
    || true
else
  echo "::warning::The glyph bundle couldn't be downloaded."
fi

# runs over cached glyphs too, so a narrower range list trims an older cache
if [ "$GLYPHS_KEEP_RANGES" = 'all' ] || [ "$GLYPHS_KEEP_RANGES" = 'vsetko' ]; then
  echo "GLYPHS_KEEP_RANGES=all – ranges are NOT cut, the bundle keeps the whole of unicode."
elif [ -n "$(ls -A _site/fonts 2>/dev/null)" ]; then
  declare -A OK=()
  IFS=',' read -ra PARTS <<<"$GLYPHS_KEEP_RANGES"
  for c in "${PARTS[@]}"; do
    lo="${c%%-*}"; hi="${c##*-}"
    case "$lo$hi" in ''|*[!0-9]*)
      echo "::error::\`$c\` in GLYPHS_KEEP_RANGES isn't a range of the form \`from-to\` (character numbers, e.g. \`0-2047\`)."
      exit 1 ;;
    esac
    # files are 256-character blocks named by their first character
    for b in $(seq $(( lo / 256 )) $(( hi / 256 ))); do OK["$b"]=1; done
  done

  # checked before deleting: the glyph cache save runs on `always()`
  if [ -z "${OK[0]:-}" ]; then
    echo "::error::GLYPHS_KEEP_RANGES=\`$GLYPHS_KEEP_RANGES\` has no range from 0 (basic Latin and digits) – the map would have no labels. Nothing was deleted."
    exit 1
  fi

  mapfile -t PBF < <(find _site/fonts -name '*.pbf' | sort)
  kept=0; deleted=0; before=0; after=0
  for p in "${PBF[@]}"; do
    size=$(stat -c%s "$p"); before=$(( before + size ))
    f="${p##*/}"; lo="${f%%-*}"
    # an unknown file name is kept: deleting the unknown is worse than a few kB
    case "$lo" in ''|*[!0-9]*) after=$(( after + size )); kept=$(( kept + 1 )); continue ;; esac
    if [ -n "${OK[$(( lo / 256 ))]:-}" ]; then
      after=$(( after + size )); kept=$(( kept + 1 ))
    else
      rm -f "$p"; deleted=$(( deleted + 1 ))
    fi
  done
  echo "Glyphs cut to ranges $GLYPHS_KEEP_RANGES: $kept files kept" \
       "($(( after / 1024 )) kB), $deleted deleted ($(( (before - after) / 1048576 )) MB saved)."

  # `0-255.pbf` carries every fallback label and `deploy/check.sh` asks for it
  for d in _site/fonts/*/; do
    [ -d "$d" ] || continue
    if [ ! -s "${d}0-255.pbf" ]; then
      echo "::error::After the cut ${d}0-255.pbf is missing – the map would have no labels. Check GLYPHS_KEEP_RANGES (it must contain a range from 0)."
      exit 1
    fi
  done
fi

if [ -z "$(ls -A _site/fonts 2>/dev/null)" ]; then
  echo "::warning::No local glyphs – the style uses fonts.openmaptiles.org (if it goes down, the map has no labels)."
else
  du -sh _site/fonts
  ls _site/fonts
fi
