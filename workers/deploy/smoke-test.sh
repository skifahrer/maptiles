#!/usr/bin/env bash
# Smoke test nasadenej mapy: nie „vyrobili sme súbory", ale „sú na webe a dajú
# sa prečítať tak, ako ich mapa číta".
#
# PMTiles sa číta Range requestmi, takže sa kontroluje 206, nie 200 – server,
# ktorý Range nevie, vráti celý súbor a mapa sa nenačíta.
#
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

# najprv: podáva už Pages toto nasadenie?
# `deploy-pages` skončí skôr, než Pages novú verziu naozaj podávajú, a to
# rozbíja kontroly dvomi spôsobmi: nová cesta vracia 404 (falošný pád), kým
# nemenené cesty vrátia 200 aj zo starého nasadenia (falošné zelené). Preto sa
# počká, kým sa na webe objaví `built_at` z manifestu tohto behu.
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
# retina variant si pýta telefón – a keď ho nedostane, nenakreslí žiadne ikony.
# Na počítači sa to nemusí prejaviť vôbec.
check "$BASE/sprites/$SPRITE@2x.json" 200 "sprite index @2x (retina, telefóny)"
check "$BASE/sprites/$SPRITE@2x.png" 200 "sprite bitmapa @2x (retina, telefóny)"
check "$BASE/styles/$REGION-svetla.json" 200 "style.json"
# každý typ mapy má vlastný štýl pre každú tému; overí sa jeden iný než
# predvolený, nech sa nenasadí len ten starý názov
check "$BASE/styles/$REGION-cestna-svetla.json" 200 "style.json (cestná mapa)"
check "$BASE/style-overrides.json" 200 "úpravy štýlu z developer módu"
# hranica regiónu: viewer na webe si ju ťahá odtiaľto a bez nej mapa siaha za
# región. Či ju beh vyrobil, hovorí manifest – tá istá odpoveď, z akej ju
# hľadá viewer.
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

# základné dlaždice sú vždy; prázdna premenná = vrstva sa nepočítala
check "$BASE/tiles/$REGION.pmtiles" 206 "pmtiles (Range request)" "-H Range:bytes=0-1023"
for pair in "${CONTOURS:-}:contours:vrstevnice" \
            "${ROCKS:-}:rocks:skaly" \
            "${TRAILS:-}:trails:značené trasy" \
            "${FEATURES:-}:features:krajinné prvky" \
            "${POINTS:-}:points:body v krajine" \
            "${BOUNDARIES:-}:boundaries:hranice území" \
            "${WATER:-}:water:vodstvo"; do
  IFS=: read -r on src popis <<<"$pair"
  [ "$on" = 'true' ] || continue
  check "$BASE/tiles/$REGION-$src.pmtiles" 206 "$popis (Range request)" \
        "-H Range:bytes=0-1023"
done

# na koreni stránky má byť mapa – to je jediná otázka, na ktorej návštevníkovi
# záleží. Jekyll z README vyrobí stránku bez `id="map"`.
#
# Stiahne sa raz do súboru a až potom sa hľadá: `curl … | grep -q` je pasca –
# `grep -q` po prvej zhode zavrie rúru, curl dostane EPIPE a `pipefail` z toho
# spraví nenulový pipeline, hoci grep zhodu našiel. Sú to preteky, takže to
# padalo len občas a s hláškou „na koreni nie je mapa".
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
  # príčinu poznáme z prvého kroku a opraviť sa dá len v nastaveniach repozitára
  echo "::warning::Na $BASE/ nie je mapa, ale README: zdroj Pages je vetva (build_type=$PAGES_BUILD_TYPE), takže obsah prepísal zabudovaný Jekyll builder. Settings → Pages → Source: 'GitHub Actions'."
else
  echo "::error::Na $BASE/ nie je mapa (v HTML nie je \`id=\"map\"\`), hoci zdroj Pages je Actions. Posledná odpoveď: HTTP $KOD, $(wc -c < "$KOREN") B. Prvý riadok: $(head -c 120 "$KOREN" | tr -d '\n')"
  fail=1
fi

exit $fail
