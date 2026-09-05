#!/usr/bin/env bash
# Planetiler do `planetiler.jar` v pracovnom priečinku, ak tam ešte nie je –
# a kontrola, že runner má Javu, na ktorej sa ten jar spustí.
#
# Sťahuje si ho šesť jobov a každý má vlastný runner aj cache, takže sa to
# spraviť raz a podať ďalej nedá. Kým to boli kópie toho istého `run:` bloku,
# bola to štvornásobná príležitosť, aby sa rozišli.
#
#   workers/lib/planetiler.sh
set -euo pipefail

JAR="${JAR:-planetiler.jar}"
URL="${PLANETILER_URL:-https://github.com/onthegomap/planetiler/releases/latest/download/planetiler.jar}"

# akú Javu chce Planetiler: vydáva sa pre Javu 21 (class file 65), kým
# `ubuntu-latest` má 17 – bez `actions/setup-java` sa jar nespustí vôbec,
# a spadne to až pri `java -jar`, teda po stiahnutých podkladoch alebo po DEM.
# Preto sa to overuje tu, hneď po checkoute, a číslo je v tomto súbore raz:
# `workers/lint/planetiler.py` podľa neho kontroluje `setup-java` v každom jobe.
JAVA_MIN="${JAVA_MIN:-21}"

if ! command -v java >/dev/null 2>&1; then
  echo "::error::Na runneri nie je \`java\`, a Planetiler je JAR. Pridaj do jobu krok \`- uses: actions/setup-java@v5\` s \`distribution: temurin\` a \`java-version: \"$JAVA_MIN\"\` (tak, ako to majú joby v \`build-map-region.yml\`)."
  exit 1
fi

# berie sa prvé číslo verzie, takže osmičke vyjde 1 a na porovnaní neprejde.
# Hľadá sa vo všetkých riadkoch: s `JAVA_TOOL_OPTIONS` si JVM vypíše vlastný
# riadok pred verziou a kontrola viazaná na prvý by falošne padla.
# Žiadna rúra z `java`: čokoľvek, čo končí po prvom riadku, zavrie rúru pod
# stále píšucim producentom a `pipefail` z EPIPE spraví pád.
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
