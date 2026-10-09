#!/usr/bin/env bash
# Article cache key on stdout (`prefix=…`, `key=…`); the run id last, the prefix picks the newest.
# From env: REGION COUNTRY LANGS RUN_ID
set -euo pipefail
# `text` stays in the key so old caches still match
S=$(printf '%s|%s|%s|%s' "$REGION" "${COUNTRY:-}" "${LANGS:-}" text \
    | tr -c 'a-zA-Z0-9._-' '_')
echo "prefix=wiki-v3-$S-"
echo "key=wiki-v3-$S-$RUN_ID"
