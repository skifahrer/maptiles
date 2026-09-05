#!/usr/bin/env bash
# Balíky mapy ešte raz ako Apple Archive (`.aar`) a hore na Drive.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 KiB, nad ktorým
# ho GitHub ticho neprijme. Vlastný job na macOS, lebo nástroj `aa` je len tam.
#
# Robí to isté, čo `deploy` so ZIPmi (`publish-map.py --format=aar`): ten istý
# obsah, mená aj priečinok na Drive. iOS a macOS `.aar` rozbalia systémovo.
#
# Z prostredia príde ten istý zoznam ako pri kroku „Publikuj mapu na Drive"
# (skladá sa z neho `obsah.json`), prípadne `MAP_LAYERS` – a musí to byť tá
# istá hodnota ako v jobe so ZIPom, inak `.aar` prebije, čo o vrstvách napísal.
# K tomu ONLY/WIKI/SITE (ktorý balík) a BRANCH (odkiaľ čerstvý `maps.json`).
set -euo pipefail

if ! command -v aa >/dev/null 2>&1; then
  echo "::error::Nástroj aa tu nie je. Apple Archive je súčasť macOS 11+, takže tento job musí bežať na macos-latest; na Linuxe sa .aar vyrobiť nedá."
  exit 1
fi
echo "Apple Archive: $(command -v aa)"

# čo sa ide baliť: prázdne ONLY = balíky mapy z `_site`, `wikipedia` = balík
# s článkami z WIKI, iné meno = balík jednej vrstvy zo SITE. Jeden skript pre
# všetky tri pipeline zámerne – tri kópie by sa raz rozišli.
ONLY="${ONLY:-}"
WIKI="${WIKI:-}"
# ktorý katalóg: odpovedá na to jedno miesto (`catalog.py`), lebo ten istý
# súbor si nižšie pýtame z vetvy a potom ho commituje `catalog.sh`
MAPS="$(python3 workers/deploy/catalog.py --subor)"
echo "Katalóg tohto behu: $MAPS"
ARGS=(--format=aar --maps="$MAPS" --summary="${GITHUB_STEP_SUMMARY:-/dev/null}")

if [ "$ONLY" = wikipedia ]; then
  ARGS+=(--only="$ONLY")
  if [ -z "$WIKI" ] || [ ! -f "$WIKI/index.json" ]; then
    echo "::error::ONLY=$ONLY, ale články nie sú (WIKI=${WIKI:-prázdne}). Nepokračujem: publish-map.py by spadol na prázdnom balíku."
    exit 1
  fi
  ARGS+=(--wiki="$WIKI" --site="${SITE:-_site}")
  echo "Balí sa jediný balík: $ONLY ($(du -sh "$WIKI" | cut -f1))"
elif [ -n "$ONLY" ]; then
  # balík jednej vrstvy z `_site` (Pregeneruj vrstvu kraja) – tie isté súbory,
  # z akých balí build mapy; čo do balíka patrí, hovorí `subory.py`.
  # Kontrola zloženého `_site` sem nepatrí: balík vrstvy manifest ani štýly
  # neobsahuje. Prázdny `--only` balík je u `publish-map.py` tvrdá chyba.
  SITE_DIR="${SITE:-_site}"
  ARGS+=(--only="$ONLY" --site="$SITE_DIR")
  echo "Balí sa jediný balík: $ONLY z $SITE_DIR ($(du -sh "$SITE_DIR" | cut -f1))"
else
  # je `_site` naozaj zložené?
  # Job si ho skladá z artefaktov `site-*`, čo je stav pred zložením – bez
  # štýlov, viewera a `manifest.json`, ktoré vyrába až `deploy`. Bez manifestu
  # by `.aar` nebol mapa a položka katalógu by prišla o bbox, zoomy a zdroj
  # výšok (prepisuje sa celá). Preto tvrdá chyba, nie varovanie.
  if [ ! -f _site/tiles/manifest.json ]; then
    echo "::error::_site nie je zložené – chýba tiles/manifest.json (a s ním štýly aj viewer). Sem chodia kusy site-* a navrch artefakt deploy-site z jobu deploy; pozri krok „Pozbieraj zloženú časť webu“. Nepokračujem: .aar by nebol mapa a maps.json by prišiel o bbox a zoomy."
    exit 1
  fi
  if [ ! -d _site/styles ]; then
    echo "::error::_site nemá priečinok styles – bez štýlov nie je .aar mapa, len dlaždice. Pozri krok „Pozbieraj zloženú časť webu“."
    exit 1
  fi
  ARGS+=(--site=_site)
  echo "Zložené _site ✓ ($(find _site -type f | wc -l | tr -d ' ') súborov, $(du -sh _site | cut -f1))"
  # články z Wikipédie majú vlastnú pipeline; bez `--wiki` ich tento beh
  # nezaradí do zoznamu, takže ich ani nezmaže
fi

# katalóg čítaj z vetvy, nie z checkoutu
# Tento job beží až po tom, čo predošlý `maps.json` do vetvy commitol, ale
# checkout má SHA zo začiatku behu. Rebase by potom padol na konflikte
# a zápis by sa zahodil – s varovaním a zeleným jobom. Konflikt je
# systematický, nie smola: predošlý job commituje vždy.
# `|| true`: pri prvej mape vôbec `maps.json` vo vetve ešte nie je.
# Druhú polovicu (čerstvý rodič commitu) rieši `deploy/catalog.sh`.
BRANCH="${BRANCH:-master}"
if git fetch --depth=1 origin "$BRANCH" >/dev/null 2>&1 \
   && git checkout FETCH_HEAD -- "$MAPS" 2>/dev/null; then
  echo "$MAPS: čerstvý z vetvy $BRANCH (ten predošlý job doň práve zapísal)"
else
  echo "$MAPS: vo vetve $BRANCH ho nemám – beriem ten z checkoutu."
fi

python3 workers/deploy/publish-map.py "${ARGS[@]}"
