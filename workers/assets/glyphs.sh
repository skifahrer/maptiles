#!/usr/bin/env bash
# Glyfy (fonty) k sebe na Pages, nech mapa nezávisí od cudzej služby.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map.yml` má strop 500 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# Keď sa balík nestiahne, mapa pôjde ďalej a štýl siahne na
# `fonts.openmaptiles.org` – lepšie než beh bez mapy. Presné mená adresárov
# v balíku sa môžu líšiť, preto sa fontstacky vyberajú postupne: presne to, čo
# štýl chce → čokoľvek „Noto Sans" → všetko.
#
# `GLYPHS_ZIP` si berie z env workflowu.

set -euo pipefail
mkdir -p _site/fonts
if [ -n "$(ls -A _site/fonts 2>/dev/null)" ]; then
  echo "Glyfy z cache ✓"
elif curl -fL --retry 4 --retry-delay 5 -o /tmp/glyphs.zip "$GLYPHS_ZIP"; then
  unzip -q /tmp/glyphs.zip -d /tmp/glyphs

  # Fontstack = adresár, ktorý obsahuje 0-255.pbf. Presné mená
  # adresárov v balíku sa môžu líšiť, preto vyberáme postupne:
  # 1) presne to, čo štýl chce, 2) čokoľvek "Noto Sans", 3) všetko.
  mapfile -t stacks < <(find /tmp/glyphs -name '0-255.pbf' -printf '%h\n' | sort -u)
  echo "V balíku je ${#stacks[@]} fontstackov."

  copy_matching() { # $1 = grep -E vzor na názov adresára
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
  echo "::warning::Balík glyfov sa nepodarilo stiahnuť."
fi

if [ -z "$(ls -A _site/fonts 2>/dev/null)" ]; then
  echo "::warning::Lokálne glyfy nie sú k dispozícii – štýl použije fonts.openmaptiles.org (ak služba vypadne, mapa bude bez nápisov)."
else
  du -sh _site/fonts
  ls _site/fonts
fi
