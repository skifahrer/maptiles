#!/usr/bin/env bash
# Sign nodes → `{region}-roadsigns.pmtiles`, the country's signs → sprite `{region}-roadsigns`.
# Called by `build.sh` with its maxzoom and region cut; a failure leaves roads without signs.

set -euo pipefail
TZ_="${1:?maxzoom}"
shift
SIGNS_REPO="${SIGNS_REPO:-https://github.com/skifahrer/traffic-signs}"
SIGNS_REF="${SIGNS_REF:-master}"

python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'
python3 -c 'import PIL' 2>/dev/null \
  || python3 -m pip install --quiet --break-system-packages pillow
command -v rsvg-convert >/dev/null || sudo apt-get install -y -qq librsvg2-bin

COUNTRY=$(node --input-type=module -e \
  'import { regionCountry } from "./workers/rail/signs.mjs"; console.log(regionCountry(process.argv[1]))' \
  "$REGION_KEY")

osmium tags-filter --overwrite -o data/roadsigns-in.osm.pbf \
  data/region.osm.pbf --expressions=workers/transport/signs-filter.txt
python3 workers/transport/signs.py --pbf=data/roadsigns-in.osm.pbf \
  --out=data/roadsigns.osm.pbf --country="$COUNTRY"
if [ "$(osmium fileinfo -e -g data.count.nodes data/roadsigns.osm.pbf)" = 0 ]; then
  echo "No sign in this area – roads and the base map go without them."
  exit 0
fi

OUT="_site/tiles/${REGION_KEY}-roadsigns.pmtiles"
java -Xmx2g -jar planetiler.jar generate-custom \
  --schema=workers/transport/roadsigns.yml \
  "$@" \
  --output="$OUT" \
  --maxzoom="$TZ_" --render_maxzoom="$TZ_" \
  --force
workers/lib/clip-tiles.sh "$OUT"

if [ -n "$COUNTRY" ]; then
  # only this country's folders: the whole collection is hundreds of MB
  rm -rf data/traffic-signs
  git clone --quiet --depth 1 --filter=blob:none --no-checkout --branch "$SIGNS_REF" \
    "$SIGNS_REPO" data/traffic-signs
  git -C data/traffic-signs sparse-checkout set --no-cone "/signs/*/*/${COUNTRY}/" \
    "/signs/*/*/*.json" "/osm/${COUNTRY}.json"
  git -C data/traffic-signs checkout --quiet
  python3 workers/transport/sprite.py --signs=data/traffic-signs --country="$COUNTRY" \
    --out="_site/tiles/${REGION_KEY}-roadsigns"
else
  echo "::warning::${REGION_KEY} has no country – signs are in the tiles, but with no sprite to draw them."
fi
ls -lh _site/tiles/"${REGION_KEY}"-roadsigns*
