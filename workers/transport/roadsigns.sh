#!/usr/bin/env bash
# Names the sign nodes in `data/transport.osm.pbf` and packs their images → sprite `{region}-roadsigns`.
# Called by `build.sh` before the roads are tiled; a failure leaves roads without signs.

set -euo pipefail
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

python3 workers/transport/signs.py --pbf=data/transport.osm.pbf \
  --out=data/transport-signs.osm.pbf --country="$COUNTRY" --names=data/roadsigns-used.txt \
  --report=data/roadsigns-report.tsv
mv data/transport-signs.osm.pbf data/transport.osm.pbf
# which signs the region has and what each is drawn as, in the job summary
summary() {
  python3 workers/transport/signs-summary.py --report=data/roadsigns-report.tsv \
    --region="$REGION_KEY" --country="$COUNTRY" \
    --sprite="_site/tiles/${REGION_KEY}-roadsigns@2x.json" >> "${GITHUB_STEP_SUMMARY:-/dev/null}" || true
}
trap summary EXIT

FOLDERS=$([ -n "$COUNTRY" ] && python3 workers/transport/sprite.py --country="$COUNTRY" \
  --used=data/roadsigns-used.txt --folders || true)
if [ -z "$FOLDERS" ]; then
  echo "${REGION_KEY}: no sign here has an image for “${COUNTRY}” – the roads go without sign images."
  exit 0
fi
# only the folders this region's signs name: the collection is hundreds of MB
rm -rf data/traffic-signs
git clone --quiet --depth 1 --filter=blob:none --no-checkout --branch "$SIGNS_REF" \
  "$SIGNS_REPO" data/traffic-signs
{
  echo /names/
  while read -r sign; do
    printf '/signs/%s/%s/\n/signs/%s/%s.json\n' "$sign" "$COUNTRY" "$sign" "${sign#*/}"
  done <<<"$FOLDERS"
} | git -C data/traffic-signs sparse-checkout set --no-cone --stdin
git -C data/traffic-signs checkout --quiet
python3 workers/transport/sprite.py --signs=data/traffic-signs --country="$COUNTRY" \
  --used=data/roadsigns-used.txt --out="_site/tiles/${REGION_KEY}-roadsigns"
ls -lh _site/tiles/"${REGION_KEY}"-roadsigns* 2>/dev/null || true
