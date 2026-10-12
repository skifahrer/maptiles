#!/usr/bin/env bash
# A schema's `examples` through `planetiler.jar verify`, which exits 0 even when one fails.
#
#   workers/lib/verify-schema.sh workers/rail/rail.yml
set -euo pipefail

SCHEMA="${1:?schema yml}"
JAR="${JAR:-planetiler.jar}"

OUT=$(java -jar "$JAR" verify "$SCHEMA" 2>&1) || { printf '%s\n' "$OUT"; exit 1; }
printf '%s\n' "$OUT"
if grep -qE '[0-9]+ failed' <<<"$OUT"; then
  echo "::error::$SCHEMA: schema examples fail (above) – the tiles wouldn't hold what the examples promise."
  exit 1
fi
if ! grep -qE '[0-9]+ passed' <<<"$OUT"; then
  echo "::error::$SCHEMA: Planetiler verified no example – is \`examples:\` there?"
  exit 1
fi
