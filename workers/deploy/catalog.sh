#!/usr/bin/env bash
# Zmenený `maps.json` commitni do repozitára – posledný krok buildu.
#
# ČO TO JE. `maps.json` je jediný zoznam toho, ktoré mapy sú hotové a kde na
# Drive ležia (krajina → kraj → výsek → odkazy na tri balíky). Zapisuje ho
# `workers/deploy/publish-map.py` hneď po nahratí, lebo len ten pozná id
# súborov; tento krok ten súbor už len uloží do repozitára, aby ho bolo vidieť
# aj bez prístupu na Drive.
#
# PREČO SAMOSTATNÝ SKRIPT A NIE `run:` V WORKFLOWE: `build-map.yml` má strop
# 500 kB a nad ním ho GitHub ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# NEZACYKLÍ SA TO. `Build map` sa spúšťa len ručne (`workflow_dispatch`), takže
# commit z neho nespustí ďalší build. `Kontrola · lint workflowov` beží pri pushi do
# `.github/workflows/**`, `workers/**` a `poc/web/**` – `maps.json` je v koreni,
# takže ani ten.
#
# RODIČOM COMMITU JE ČERSTVÁ VETVA, NIE SHA, S KTOROU BEH ZAČAL. V jednom behu
# zapisujú katalóg DVA joby za sebou – `deploy` (ZIPy) a job na macOS (`.aar`) –
# a ten druhý má checkout ešte spred prvého zápisu. Keby commitoval na svoju
# SHA, jeho commit by niesol aj to, čo do súboru napísal ten prvý job, rebase by
# to skúšal pridať druhýkrát a KAŽDÝ beh by skončil konfliktom: „113 insertions"
# proti „89 insertions" v tom istom mieste súboru (beh 31782846262 – balíky na
# Drive boli, `formats.aar` v katalógu nie).
#
# Preto sa pred commitom index prepne na čerstvý stav vetvy (`reset --mixed`).
# Pracovný strom sa nemení, takže `maps.json` ostáva ten, ktorý si
# `publish-map.py` práve zapísal, a commit z neho nesie UŽ LEN ten svoj
# prírastok. Push je potom fast-forward a niet čo rebasovať.
#
# DVA BEHY NARAZ. Keď medzitým do vetvy pushol niekto iný (alebo iný build inej
# mapy), push zlyhá na „non-fast-forward". Preto sa to skúša znova s
# `git pull --rebase`: katalóg je JSON, kde každý build mení inú položku, takže
# rebase prejde – a odkedy je commit len ten prírastok, prejde aj naozaj. Keby
# prišiel konflikt, beh nezhodíme – mapa je nahratá a katalóg dopíše ďalší
# build; len to musí byť v logu.
#
# Hodnoty z prostredia (viď krok „Zapíš mapu do maps.json" v build-map.yml):
#   MAPS_JSON   ktorý súbor commitnúť (default maps.json)
#   BRANCH      do ktorej vetvy pushnúť (github.ref_name)
#   RUN_URL     odkaz na beh do commit message
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

# Rodičom je čerstvá vetva (viď rozpis hore). `--mixed` prepne HEAD aj index,
# pracovný strom nechá tak – teda `maps.json` ostáva ten práve zapísaný a
# porovnanie nižšie beží proti tomu, čo je vo vetve TERAZ.
if git fetch --quiet --depth=1 origin "$BRANCH" 2>/dev/null \
   && git reset --mixed --quiet FETCH_HEAD 2>/dev/null; then
  echo "Rodič commitu: čerstvý $BRANCH ($(git rev-parse --short FETCH_HEAD))"
else
  echo "::warning::Vetvu $BRANCH sa nepodarilo načítať – commitujem na SHA, s ktorou beh začal. Keď medzitým do katalógu zapísal iný job, push si vypýta rebase."
fi

if git diff --quiet -- "$MAPS_JSON"; then
  echo "$MAPS_JSON sa nezmenil (tá istá mapa s tými istými odkazmi) – bez commitu."
  exit 0
fi

git add "$MAPS_JSON"
git commit -q -m "Katalóg máp: $(git diff --cached --shortstat -- "$MAPS_JSON" | tr -s ' ')" \
  -m "Zapísal build ${RUN_URL:-(bez odkazu)} po nahratí balíkov na Drive." \
  || { echo "::warning::Commit sa nepodaril – katalóg dopíše ďalší build."; exit 0; }

for i in $(seq 1 "$TRIES"); do
  if git push origin "HEAD:$BRANCH"; then
    echo "$MAPS_JSON je vo vetve $BRANCH ✓"
    exit 0
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
