#!/usr/bin/env bash
# Smoke test NASADENEJ mapy: nie „vyrobili sme súbory", ale „sú na webe
# a dajú sa prečítať tak, ako ich mapa číta".
#
# PMTiles sa číta HTTP Range requestmi, takže sa nekontroluje 200, ale **206**.
# Server, ktorý Range nevie, vráti na tú istú adresu 200 a celý súbor – mapa
# sa potom nenačíta a zo samotnej existencie súboru sa to nepozná.
#
# Použitie (hodnoty chodia z prostredia, aby sa dal skript spustiť aj ručne):
#   BASE=https://user.github.io/repo REGION=presovsky_kraj SPRITE=osm-liberty \
#   workers/deploy/smoke-test.sh
set -uo pipefail

BASE="${BASE:?adresa nasadenej stránky}"
BASE="${BASE%/}"
REGION="${REGION:?kľúč regiónu (plan.outputs.key)}"
SPRITE="${SPRITE:?meno spritu (assets.outputs.name)}"
PAGES_BUILD_TYPE="${PAGES_BUILD_TYPE:-}"

fail=0

check() { # $1 = URL, $2 = očakávaný kód, $3 = popis, $4 = extra curl args
  local code=000 attempt
  for attempt in 1 2 3 4 5; do
    # shellcheck disable=SC2086  # $4 sú zámerne rozdelené argumenty curlu
    code=$(curl -s -o /dev/null -w '%{http_code}' ${4:-} "$1" || echo 000)
    [ "$code" = "$2" ] && break
    sleep $(( attempt * 5 ))
  done
  if [ "$code" = "$2" ]; then
    echo "  ✓ $3 ($code)"
  else
    echo "::error::$3 vrátilo HTTP $code (očakávané $2) – $1"
    fail=1
  fi
}

# NAJPRV: PODÁVA UŽ PAGES TOTO NASADENIE?
#
# `deploy-pages` skončí skôr, než Pages začne novú verziu naozaj podávať, a to
# rozbíja kontroly dvomi spôsobmi naraz:
#
#   1. Falošný pád. Cesta, ktorá v predošlom nasadení NEBOLA – a meno štýlu
#      nesie kľúč regiónu, takže pri zmene regiónu je nová vždy – vracia 404,
#      kým sa nasadenie neprepne. Beh 31368710705 tak spadol na
#      `styles/presovsky-svetla.json` (predtým sa nasadzoval `presovsky_test2`),
#      hoci nasadenie bolo v poriadku: ten súbor je na webe dodnes.
#   2. Falošné zelené. Cesty, ktoré sa medzi nasadeniami NEMENIA – manifest,
#      sprity, `style-overrides.json` – vráti 200 aj to STARÉ nasadenie. Tie
#      kontroly teda môžu prejsť na včerajších súboroch a nikto sa to nedozvie.
#      V tom istom behu prešli za sekundu, kým nová cesta 75 sekúnd 404-kovala.
#
# Preto sa najprv počká, kým sa na webe objaví `built_at` z manifestu, ktorý
# tento beh práve postavil. Až potom má zmysel čokoľvek kontrolovať.
SITE_DIR="${SITE_DIR:-_site}"
WANT=$(jq -r '.built_at // empty' "$SITE_DIR/tiles/manifest.json" 2>/dev/null)
if [ -n "$WANT" ]; then
  echo "Čakám, kým Pages začne podávať toto nasadenie (built_at=$WANT)"
  live=""
  for attempt in $(seq 1 30); do
    live=$(curl -s "$BASE/tiles/manifest.json" | jq -r '.built_at // empty' 2>/dev/null)
    [ "$live" = "$WANT" ] && break
    [ $(( attempt % 3 )) -eq 0 ] && \
      echo "  … $(( attempt * 10 )) s, na webe je zatiaľ built_at=${live:-nič}"
    sleep 10
  done
  if [ "$live" = "$WANT" ]; then
    echo "  ✓ Pages podávajú toto nasadenie"
  else
    echo "::error::Pages ani po piatich minútach nepodávajú toto nasadenie (na webe built_at=${live:-nič}, čakalo sa $WANT). Kontroly nižšie by preverili staré súbory, tak sa nespúšťajú – pozri stav nasadenia v Settings → Pages."
    exit 1
  fi
else
  echo "::warning::$SITE_DIR/tiles/manifest.json nemám, tak sa nedá počkať na prepnutie nasadenia – kontroly nižšie môžu preverovať staré súbory."
fi

echo "Kontrolujem $BASE"
check "$BASE/tiles/manifest.json" 200 "manifest.json"
check "$BASE/sprites/$SPRITE.json" 200 "sprite index"
check "$BASE/sprites/$SPRITE.png" 200 "sprite bitmapa"
check "$BASE/styles/$REGION-svetla.json" 200 "style.json"
# Typy máp: každý má vlastný štýl pre každú tému; overíme jeden iný
# než predvolený, nech sa nestane, že sa nasadí len ten starý názov.
check "$BASE/styles/$REGION-cestna-svetla.json" 200 "style.json (cestná mapa)"
check "$BASE/style-overrides.json" 200 "úpravy štýlu z developer módu"
# Hranica stiahnutého regiónu. Statické štýly ju majú v sebe, viewer na webe
# si ju ťahá odtiaľto – a keď tu nie je, mapa sa načíta a len bude siahať za
# región. Či ju tento beh vôbec vyrobil, hovorí manifest (a nie ďalšia
# premenná v kroku): je to tá istá odpoveď, z ktorej ju hľadá aj viewer.
OUTLINE=$(jq -r '.regions[.default_region].outline // empty' \
  "$SITE_DIR/tiles/manifest.json" 2>/dev/null || true)
if [ -n "$OUTLINE" ]; then
  check "$BASE/$OUTLINE" 200 "hranica stiahnutého regiónu"
fi

GLYPHS=$(curl -s "$BASE/tiles/manifest.json" | jq -r '.glyphs')
case "$GLYPHS" in
  "$BASE"*) check "$BASE/fonts/Noto%20Sans%20Regular/0-255.pbf" 200 "glyfy" ;;
  *) echo "  ℹ glyfy sú externé: $GLYPHS" ;;
esac

# Základné dlaždice sú vždy; ostatné vrstvy len keď ich beh naozaj vyrobil.
# Prázdna premenná = vrstva sa nepočítala, tak sa ani nekontroluje.
check "$BASE/tiles/$REGION.pmtiles" 206 "pmtiles (Range request)" "-H Range:bytes=0-1023"
for pair in "${CONTOURS:-}:contours:vrstevnice" \
            "${ROCKS:-}:rocks:skaly" \
            "${TRAILS:-}:trails:značené trasy" \
            "${FEATURES:-}:features:krajinné prvky" \
            "${ROADS:-}:roads:obmedzenia na ceste"; do
  IFS=: read -r on src popis <<<"$pair"
  [ "$on" = 'true' ] || continue
  check "$BASE/tiles/$REGION-$src.pmtiles" 206 "$popis (Range request)" \
        "-H Range:bytes=0-1023"
done

# Na koreni stránky má byť MAPA. Všetko vyššie kontroluje súbory, ktoré
# README nemá – ale práve preto by prepísanú stránku nechytilo, keby tam
# ostali z predošlého nasadenia. Toto je tá jediná otázka, na ktorej
# návštevníkovi záleží: čo vidí, keď otvorí adresu. Jekyll z README vyrobí
# stránku bez `id="map"`.
#
# STIAHNE SA RAZ DO SÚBORU a až potom sa hľadá. `curl … | grep -q` je pasca:
# `grep -q` po PRVEJ zhode skončí a zavrie rúru, curl dopíše do zavretej rúry,
# dostane EPIPE a končí s 23 – a `set -o pipefail` hore z toho spraví nenulový
# pipeline, HOCI GREP ZHODU NAŠIEL. Je to preteky (zápis curlu proti koncu
# grepu), takže to padalo len občas a s hláškou „na koreni nie je mapa", kým
# mapa tam celý čas bola. Beh 32144952677: všetkých 13 kontrol ✓ a spadlo
# práve toto. Vyskočilo to, keď za `id="map"` pribudlo v `index.html` pár kB
# (strážca štartu): za zhodou ostávalo 2,7 kB, po zmene 5,8 kB – a čím viac
# curlu ostane dopísať, tým skôr na zavretú rúru narazí.
#
# A opakuje sa to ako všetko ostatné: jedna zaseknutá požiadavka po ÚSPEŠNOM
# nasadení nemá zhodiť build, keď je mapa na svojom mieste.
KOREN=$(mktemp)
trap 'rm -f "$KOREN"' EXIT
KOD=000
for attempt in 1 2 3 4 5; do
  KOD=$(curl -sL -o "$KOREN" -w '%{http_code}' "$BASE/" || echo 000)
  [ "$KOD" = 200 ] && grep -q 'id="map"' "$KOREN" && break
  sleep $(( attempt * 5 ))
done

if grep -q 'id="map"' "$KOREN"; then
  echo "  ✓ na koreni stránky je mapa"
elif [ "$PAGES_BUILD_TYPE" != 'workflow' ]; then
  # Príčinu poznáme z prvého kroku a opraviť sa dá len v nastaveniach
  # repozitára – červený beh by k tomu nič nepridal.
  echo "::warning::Na $BASE/ nie je mapa, ale README: zdroj Pages je vetva (build_type=$PAGES_BUILD_TYPE), takže obsah prepísal zabudovaný Jekyll builder. Settings → Pages → Source: 'GitHub Actions'."
else
  echo "::error::Na $BASE/ nie je mapa (v HTML nie je \`id=\"map\"\`), hoci zdroj Pages je Actions. Posledná odpoveď: HTTP $KOD, $(wc -c < "$KOREN") B. Prvý riadok: $(head -c 120 "$KOREN" | tr -d '\n')"
  fail=1
fi

exit $fail
