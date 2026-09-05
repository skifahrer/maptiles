#!/usr/bin/env bash
# Zmenený `maps.json` commitni do repozitára – posledný krok buildu.
#
# `maps.json` je jediný zoznam hotových máp a ich odkazov na Drive; zapisuje ho
# `publish-map.py` hneď po nahratí (len ten pozná id súborov), tento krok ho už
# len uloží do repozitára. Vlastný skript, lebo build-map-region.yml je pri
# strope 128 KiB.
#
# Nezacyklí sa to: `Build map` sa spúšťa len ručne a lint pri pushi do
# `maps.json` v koreni nebeží.
#
# Rodičom commitu je čerstvá vetva, nie SHA zo začiatku behu: katalóg zapisujú
# v jednom behu dva joby za sebou a ten druhý má checkout spred prvého zápisu –
# jeho commit by niesol aj cudzí zápis a rebase by padol zakaždým. Preto sa
# pred commitom index prepne na čerstvý stav vetvy (`reset --mixed`); pracovný
# strom sa nemení, takže commit nesie už len svoj prírastok a push je
# fast-forward.
#
# Dva behy naraz: pri non-fast-forward sa to skúsi znova s `git pull --rebase`.
# Konflikt beh nezhodí – mapa je nahratá a katalóg dopíše ďalší build.
#
# Z prostredia: MAPS_JSON (ktorý súbor), BRANCH (kam pushnúť), RUN_URL.
set -uo pipefail

MAPS_JSON="${MAPS_JSON:-maps.json}"
BRANCH="${BRANCH:-master}"
TRIES=4

if [ ! -f "$MAPS_JSON" ]; then
  echo "::warning::$MAPS_JSON neexistuje – nie je čo commitnúť."
  exit 0
fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# rodičom je čerstvá vetva; `--mixed` nechá pracovný strom tak
if git fetch --quiet --depth=1 origin "$BRANCH" 2>/dev/null \
   && git reset --mixed --quiet FETCH_HEAD 2>/dev/null; then
  echo "Rodič commitu: čerstvý $BRANCH ($(git rev-parse --short FETCH_HEAD))"
else
  echo "::warning::Vetvu $BRANCH sa nepodarilo načítať – commitujem na SHA, s ktorou beh začal. Keď medzitým do katalógu zapísal iný job, push si vypýta rebase."
fi

# nový súbor je tiež zmena: `git diff` o nesledovanom súbore mlčí a beh by
# skončil zelený. Katalóg je raz nový vždy, tak sa pozná podľa `ls-files`.
if git ls-files --error-unmatch -- "$MAPS_JSON" >/dev/null 2>&1; then
  if git diff --quiet -- "$MAPS_JSON"; then
    echo "$MAPS_JSON sa nezmenil (tá istá mapa s tými istými odkazmi) – bez commitu."
    exit 0
  fi
else
  echo "$MAPS_JSON v repozitári ešte nie je – zakladám ho."
fi

git add "$MAPS_JSON"
git commit -q -m "Katalóg máp: $(git diff --cached --shortstat -- "$MAPS_JSON" | tr -s ' ')" \
  -m "Zapísal build ${RUN_URL:-(bez odkazu)} po nahratí balíkov na Drive." \
  || { echo "::warning::Commit sa nepodaril – katalóg dopíše ďalší build."; exit 0; }

# odmietnutie pravidlom vetvy nie je pretekanie dvoch behov: pri GH013
# neprejde ani ďalší build a katalóg prestane platiť úplne, ticho a so zeleným
# behom. Trvalé odmietnutie preto beh zhodí.
push_vystup=""
trvalo_odmietnute() {
  printf '%s' "$push_vystup" | grep -qE 'GH013|repository rule violations|protected branch|pre-receive hook declined'
}

for i in $(seq 1 "$TRIES"); do
  if push_vystup=$(git push origin "HEAD:$BRANCH" 2>&1); then
    printf '%s\n' "$push_vystup"
    echo "$MAPS_JSON je vo vetve $BRANCH ✓"
    exit 0
  fi
  printf '%s\n' "$push_vystup"
  if trvalo_odmietnute; then
    echo "::error::$MAPS_JSON sa nedá zapísať do vetvy $BRANCH – push odmietlo pravidlo repozitára, nie pretek dvoch behov. Ďalší build ho preto NEDOPÍŠE: balíky na Drive sa budú prepisovať ďalej a katalóg ostane stáť na tom, čo je v ňom teraz. Daj bótovi cestu do $BRANCH (bypass v rulesete alebo push cez pull request) a pusti build znova."
    exit 1
  fi
  if [ "$i" -eq "$TRIES" ]; then break
  fi
  WAIT=$(( 2 ** i ))
  echo "Push do $BRANCH neprešiel ($i. z $TRIES) – skúšam rebase a znova o ${WAIT} s."
  sleep "$WAIT"
  git pull --rebase --quiet origin "$BRANCH" || {
    echo "::warning::Rebase katalógu neprešiel (konflikt v $MAPS_JSON). Mapa je nahratá na Drive, katalóg dopíše ďalší build."
    exit 0
  }
done
echo "::warning::$MAPS_JSON sa nepodarilo pushnúť do $BRANCH ani na $TRIES. pokus. Mapa je nahratá na Drive; katalóg dopíše ďalší build."
exit 0
