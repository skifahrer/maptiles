#!/usr/bin/env bash
# Glyfy (fonty) k sebe na Pages, nech mapa nezávisí od cudzej služby.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map.yml` má strop 128 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# Keď sa balík nestiahne, mapa pôjde ďalej a štýl siahne na
# `fonts.openmaptiles.org` – lepšie než beh bez mapy. Presné mená adresárov
# v balíku sa môžu líšiť, preto sa fontstacky vyberajú postupne: presne to, čo
# štýl chce → čokoľvek „Noto Sans" → všetko.
#
# `GLYPHS_ZIP` si berie z env workflowu.

set -euo pipefail

# ROZSAHY ZNAKOV, KTORÉ V BALÍKU OSTANÚ.
#
# Fontstack je 256 súborov po 256 znakoch, teda CELÝ unicode – vrátane CJK,
# arabčiny, hebrejčiny, thajčiny a emoji. `cp -r` nižšie berie adresár celý,
# takže tri stacky (Regular, Bold, Italic) sú 99,7 MB na disku a 61,2 MB
# v ZIPe. Fonty sú v každom regióne tie isté, takže to bola KONŠTANTA
# v každom balíku mapy: pri `bratislavsky.zip` (130,9 MB) 47 % toho, čo si
# appka stiahne. Po orezaní na rozsahy nižšie ostane 51 súborov, 1,7 MB
# v ZIPe – teda o 59,5 MB menej v KAŽDOM balíku mapy.
#
# ČO SA NECHÁVA A PREČO. Mapa sa tiluje s `--languages=sk,en`
# (`workers/tiles/build.sh`), takže do dlaždíc idú `name`, `name:sk`
# a `name:en`. Nechávajú sa preto:
#
#     0-2047       latinka, Latin-1, Latin Ext-A (č ď ľ ň š ť ž ĺ ŕ ô),
#                  Ext-B, diakritika, gréčtina, cyrilika
#     7424-9215    fonetika, Latin Extended Additional, Greek Extended,
#                  interpunkcia (– — „ " …), meny, ⅓ ½ №, × ÷ ≈, technické
#     11264-11519  Latin Extended-C
#     42752-43007  Latin Extended-D, modifikátory tónu
#
# Je to o dosť viac, než mapa Slovenska naozaj potrebuje (samotná latinka
# s interpunkciou je 1,1 MB), a to je zámer: rozdiel medzi „bezpečne" a
# „na tesno" je 0,6 MB, kým chýbajúci rozsah znamená na mape prázdne
# štvorčeky a nikto nepovie prečo.
#
# KEBY PRIBUDOL REGIÓN, KTORÝ PÍŠE INÝM PÍSMOM, je to jedna premenná – a keď
# sa nastaví na `vsetko`, neoreže sa nič. (Prázdna hodnota to nevypne:
# `${VAR:-...}` ju nahradí predvoleným zoznamom, takže „vypnuté" musí byť
# slovo, nie prázdno.) Mapa sveta si rozsahy nehádže takto
# natvrdo, ale MERIA z mien v podkladoch (`workers/world/glyphs.py`); tam sa
# to dá, lebo mená štátov sú v jednom geojsone. Pri kraji sú mená
# roztrúsené v PBF a v dlaždiciach, ktoré v tomto jobe ešte nie sú.
GLYPHS_KEEP_RANGES="${GLYPHS_KEEP_RANGES:-0-2047,7424-9215,11264-11519,42752-43007}"

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

# OREZ ROZSAHOV. Beží aj nad glyfmi z cache: keď sa zoznam rozsahov zmení,
# starý (širší) obsah cache sa má orezať tiež. Je to `rm` nad súbormi, ktoré
# už na disku sú, takže opakovanie nič nestojí a nič nepokazí.
if [ "$GLYPHS_KEEP_RANGES" = 'vsetko' ]; then
  echo "GLYPHS_KEEP_RANGES=vsetko – rozsahy sa NEOREŽÚ, v balíku ostane celý unicode."
elif [ -n "$(ls -A _site/fonts 2>/dev/null)" ]; then
  declare -A OK=()
  IFS=',' read -ra CASTI <<<"$GLYPHS_KEEP_RANGES"
  for c in "${CASTI[@]}"; do
    lo="${c%%-*}"; hi="${c##*-}"
    case "$lo$hi" in ''|*[!0-9]*)
      echo "::error::\`$c\` v GLYPHS_KEEP_RANGES nie je rozsah v tvare \`od-do\` (čísla znakov, napr. \`0-2047\`)."
      exit 1 ;;
    esac
    # `seq`, nie `for (( ))`: rozsahy sú 256-znakové bloky a súbory sa volajú
    # podľa prvého znaku bloku, takže `<od>/256` až `<do>/256` je presne
    # zoznam blokov, ktoré rozsah pokrýva.
    for b in $(seq $(( lo / 256 )) $(( hi / 256 ))); do OK["$b"]=1; done
  done

  # NAJPRV SA OVERÍ ZOZNAM, AŽ POTOM SA MAŽE. Rozsah od 0 je základná latinka
  # a číslice – bez neho by mapa bola bez nápisov. Keby sa kontrolovalo až po
  # mazaní, ostal by po spadnutom behu okresaný `_site/fonts` a krok „Cache
  # glyfov a spritov (save)" beží pri `always()`, takže by tú skazu ULOŽIL do
  # cache a ďalšie behy by si ju ťahali späť.
  if [ -z "${OK[0]:-}" ]; then
    echo "::error::GLYPHS_KEEP_RANGES=\`$GLYPHS_KEEP_RANGES\` neobsahuje rozsah od 0 (základná latinka a číslice) – mapa by bola bez nápisov. Nič sa nezmazalo."
    exit 1
  fi

  mapfile -t PBF < <(find _site/fonts -name '*.pbf' | sort)
  ostalo=0; zmazane=0; pred=0; po=0
  for p in "${PBF[@]}"; do
    velkost=$(stat -c%s "$p"); pred=$(( pred + velkost ))
    f="${p##*/}"; lo="${f%%-*}"
    # Súbor, ktorý sa nevolá `<od>-<do>.pbf`, sa NEMAŽE: neviem, čo je,
    # a zmazať neznáme je horšie než nechať pár kB navyše.
    case "$lo" in ''|*[!0-9]*) po=$(( po + velkost )); ostalo=$(( ostalo + 1 )); continue ;; esac
    if [ -n "${OK[$(( lo / 256 ))]:-}" ]; then
      po=$(( po + velkost )); ostalo=$(( ostalo + 1 ))
    else
      rm -f "$p"; zmazane=$(( zmazane + 1 ))
    fi
  done
  echo "Glyfy orezané na rozsahy $GLYPHS_KEEP_RANGES: ostalo $ostalo súborov" \
       "($(( po / 1024 )) kB), zmazaných $zmazane ($(( (pred - po) / 1048576 )) MB ušetrených)."

  # POISTKA. `0-255.pbf` je základná latinka a číslice, teda to, čím sa dá
  # napísať čokoľvek náhradné – a je to jediný súbor, ktorý si pýta aj
  # `workers/deploy/check.sh`. Keby ho orez zhltol, mapa by bola bez nápisov
  # a prišlo by sa na to až na telefóne.
  for d in _site/fonts/*/; do
    [ -d "$d" ] || continue
    if [ ! -s "${d}0-255.pbf" ]; then
      echo "::error::Po orezaní chýba ${d}0-255.pbf – to by bola mapa bez nápisov. Skontroluj GLYPHS_KEEP_RANGES (musí obsahovať rozsah od 0)."
      exit 1
    fi
  done
fi

if [ -z "$(ls -A _site/fonts 2>/dev/null)" ]; then
  echo "::warning::Lokálne glyfy nie sú k dispozícii – štýl použije fonts.openmaptiles.org (ak služba vypadne, mapa bude bez nápisov)."
else
  du -sh _site/fonts
  ls _site/fonts
fi
