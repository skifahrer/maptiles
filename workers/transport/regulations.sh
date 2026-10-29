#!/usr/bin/env bash
# The country's traffic regulations → `{region}-regulations.json`, beside the road signs.
# Called by `build.sh`; a failure leaves the app with the limits it was built with.

set -euo pipefail
SIGNS_REPO="${SIGNS_REPO:-https://github.com/skifahrer/traffic-signs}"
SIGNS_REF="${SIGNS_REF:-master}"

COUNTRY=$(node --input-type=module -e \
  'import { regionCountry } from "./workers/rail/signs.mjs"; console.log(regionCountry(process.argv[1]))' \
  "$REGION_KEY")
if [ -z "$COUNTRY" ]; then
  echo "${REGION_KEY}: no country – no regulations."
  exit 0
fi
rm -rf data/traffic-regulations
git clone --quiet --depth 1 --filter=blob:none --no-checkout --branch "$SIGNS_REF" \
  "$SIGNS_REPO" data/traffic-regulations
echo "/regulations/${COUNTRY}.json" \
  | git -C data/traffic-regulations sparse-checkout set --no-cone --stdin
git -C data/traffic-regulations checkout --quiet
mkdir -p _site/tiles
python3 workers/transport/regulations.py --signs=data/traffic-regulations --country="$COUNTRY" \
  --out="_site/tiles/${REGION_KEY}-regulations.json"
