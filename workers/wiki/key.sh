#!/usr/bin/env bash
# Kľúč cache článkov na stdout (`prefix=…`, `key=…`).
#
# Do kľúča ide všetko, čo mení obsah balíka. Na konci je číslo behu, lebo
# existujúci kľúč sa neprepisuje – predpona vyberie najnovší.
#
# Z prostredia: REGION COUNTRY LANGS RUN_ID
set -euo pipefail
# `text` ostáva v kľúči, aby staré cache sadli
S=$(printf '%s|%s|%s|%s' "$REGION" "${COUNTRY:-}" "${LANGS:-}" text \
    | tr -c 'a-zA-Z0-9._-' '_')
echo "prefix=wiki-v2-$S-"
echo "key=wiki-v2-$S-$RUN_ID"
