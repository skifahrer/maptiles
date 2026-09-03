#!/usr/bin/env bash
# Planetiler do `planetiler.jar` v pracovnom priečinku, ak tam ešte nie je –
# a kontrola, že runner má Javu, na ktorej sa ten jar vôbec spustí.
#
# Sťahuje si ho ŠESŤ jobov (tiles, contours, rocks, trails, features
# v Build map a mapa sveta vo Build svet) – každý má vlastný runner a vlastnú
# cache, takže sa to spraviť raz a podať ďalej nedá. Kým to boli štyri kópie
# toho istého `run:` bloku, bola to štvornásobná príležitosť, aby sa rozišli:
# verzia sa zmení na jednom mieste a tri joby ticho stavajú z inej. Jedna
# otázka, jedna odpoveď, jedno miesto.
#
# A tá otázka je aj „na akej Jave beží". Odpoveď je tu, lebo tu je aj jar –
# rozpis je nižšie pri `JAVA_MIN`.
#
# Použitie:  workers/lib/planetiler.sh
set -euo pipefail

JAR="${JAR:-planetiler.jar}"
URL="${PLANETILER_URL:-https://github.com/onthegomap/planetiler/releases/latest/download/planetiler.jar}"

# AKÚ JAVU CHCE PLANETILER. Vydáva sa preložený pre Javu 21 (class file 65),
# kým `ubuntu-latest` má predvolene 17 (61) – bez `actions/setup-java` sa jar
# nespustí vôbec:
#
#     UnsupportedClassVersionError: … class file version 65.0, this version
#     of the Java Runtime only recognizes class file versions up to 61.0
#
# A spadne to AŽ pri `java -jar`, nie tu. Beh 31948543768 (Build svet): päť
# jobov v Build map si `setup-java` pridalo, šiesty – mapa sveta – nie, takže
# beh najprv stiahol 100 MB podkladov a padol až za nimi. V jobe `contours`
# by to bolo za DEM, teda po desiatkach minút práce. Preto sa to overuje
# TU, v kroku, ktorý je hneď po checkoute, a preto je číslo `21` v tomto
# súbore len raz: `workers/lint/planetiler.py` podľa neho kontroluje, že
# každý job, ktorý Planetiler púšťa, má `setup-java` s tou istou hodnotou.
JAVA_MIN="${JAVA_MIN:-21}"

if ! command -v java >/dev/null 2>&1; then
  echo "::error::Na runneri nie je \`java\`, a Planetiler je JAR. Pridaj do jobu krok \`- uses: actions/setup-java@v5\` s \`distribution: temurin\` a \`java-version: \"$JAVA_MIN\"\` (tak, ako to majú joby v \`build-map-region.yml\`)."
  exit 1
fi

# `openjdk version "21.0.5" …` aj `java version "1.8.0_402"` – berie sa prvé
# číslo, takže osmičke vyjde 1 a na porovnaní neprejde. Tak to má byť.
#
# HĽADÁ SA VO VŠETKÝCH RIADKOCH, nie v prvom: keď je nastavené
# `JAVA_TOOL_OPTIONS`, JVM si pred verziu vypíše vlastný riadok („Picked up
# JAVA_TOOL_OPTIONS: …") a kontrola viazaná na prvý riadok by na Jave 21
# ohlásila „verzia sa nedá prečítať". Falošný pád tejto kontroly by bol horší
# než to, čo chytá – zastavil by beh, ktorý by inak prešiel.
# ŽIADNA RÚRA Z `java`. Čokoľvek, čo končí po prvom riadku (`head -1`, aj
# `sed …q`), zavrie rúru pod stále píšucim producentom; ten dostane EPIPE
# a `pipefail` z toho spraví pád, hoci sa hodnota prečítala. Výstup sa preto
# najprv uloží do premennej a hľadá sa až v nej.
JAVA_RAW=$(java -version 2>&1)
JAVA_VER=$(awk 'match($0, /version "[0-9]+/) \
  { print substr($0, RSTART + 9, RLENGTH - 9); exit }' <<<"$JAVA_RAW")
if [ -z "$JAVA_VER" ]; then
  echo "::error::Verzia Javy sa nedá prečítať z \`java -version\`: $(head -1 <<<"$JAVA_RAW"). Planetiler chce aspoň $JAVA_MIN – over, že job má krok \`actions/setup-java\`."
  exit 1
fi
if [ "$JAVA_VER" -lt "$JAVA_MIN" ]; then
  echo "::error::Planetiler je preložený pre Javu $JAVA_MIN, runner má $JAVA_VER – \`java -jar planetiler.jar\` by spadol na UnsupportedClassVersionError, a to až o desiatky minút neskôr. Pridaj do tohto jobu PRED tento krok \`- uses: actions/setup-java@v5\` s \`distribution: temurin\` a \`java-version: \"$JAVA_MIN\"\`."
  exit 1
fi
echo "Java $JAVA_VER ✓ (Planetiler chce aspoň $JAVA_MIN)"

[ -s "$JAR" ] && { echo "Planetiler z cache ✓"; exit 0; }
curl -fL --retry 4 --retry-delay 5 -o "$JAR" "$URL"
