#!/usr/bin/env bash
# A custom schema with `name:xx` beside every `name` attribute, one per tile language.
# usage: name-languages.sh <schema.yml> <out.yml>

set -euo pipefail
source "$(dirname "$0")/languages.sh"

awk -v langs="$TILE_LANGUAGES" '
  { print }
  /^[[:space:]]*- key: name[[:space:]]*$/ {
    indent = substr($0, 1, index($0, "-") - 1)
    n = split(langs, code, ",")
    for (i = 1; i <= n; i++) printf "%s- key: \"name:%s\"\n", indent, code[i]
  }' "$1" > "$2"
