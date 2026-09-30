#!/usr/bin/env bash
# Planetiler into `planetiler.jar` unless it's there – and a check the runner's Java can run it.
#
#   workers/lib/planetiler.sh
set -euo pipefail

JAR="${JAR:-planetiler.jar}"
URL="${PLANETILER_URL:-https://github.com/onthegomap/planetiler/releases/latest/download/planetiler.jar}"

# checked right after checkout, not at `java -jar` an hour later; `lint/planetiler.py` reads it
JAVA_MIN="${JAVA_MIN:-21}"

if ! command -v java >/dev/null 2>&1; then
  echo "::error::The runner has no \`java\`, and Planetiler is a JAR. Add a \`- uses: actions/setup-java@v5\` step with \`distribution: temurin\` and \`java-version: \"$JAVA_MIN\"\` to the job (as the jobs in \`build-map-region.yml\` have)."
  exit 1
fi

# all lines searched: `JAVA_TOOL_OPTIONS` prints its own line first; no pipe, EPIPE + pipefail
JAVA_RAW=$(java -version 2>&1)
JAVA_VER=$(awk 'match($0, /version "[0-9]+/) \
  { print substr($0, RSTART + 9, RLENGTH - 9); exit }' <<<"$JAVA_RAW")
if [ -z "$JAVA_VER" ]; then
  echo "::error::The Java version can't be read from \`java -version\`: $(head -1 <<<"$JAVA_RAW"). Planetiler needs at least $JAVA_MIN – check the job has an \`actions/setup-java\` step."
  exit 1
fi
if [ "$JAVA_VER" -lt "$JAVA_MIN" ]; then
  echo "::error::Planetiler is built for Java $JAVA_MIN, the runner has $JAVA_VER – \`java -jar planetiler.jar\` would die of UnsupportedClassVersionError, tens of minutes later. Add \`- uses: actions/setup-java@v5\` with \`distribution: temurin\` and \`java-version: \"$JAVA_MIN\"\` to this job BEFORE this step."
  exit 1
fi
echo "Java $JAVA_VER ✓ (Planetiler needs at least $JAVA_MIN)"

[ -s "$JAR" ] && { echo "Planetiler from cache ✓"; exit 0; }
curl -fL --retry 4 --retry-delay 5 -o "$JAR" "$URL"
