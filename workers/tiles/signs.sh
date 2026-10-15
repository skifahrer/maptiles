#!/usr/bin/env bash
# Traffic signs into the base map: `signs.yml` at its zooms, spliced into `{region}.pmtiles`.
# Called by `build.sh` with the maxzoom; a failure leaves the base map without signs.

set -euo pipefail
OUT="${1:?pmtiles}"
Z="${2:?maxzoom}"
shift 2

command -v osmium >/dev/null || sudo apt-get install -y -qq osmium-tool
python3 -c 'import osmium' 2>/dev/null \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'
python3 -c 'import pmtiles' 2>/dev/null || python3 -m pip install --quiet pmtiles

COUNTRY=$(node --input-type=module -e \
  'import { regionCountry } from "./workers/rail/signs.mjs"; console.log(regionCountry(process.argv[1]))' \
  "$REGION_KEY")
SIGNS=(n/traffic_sign n/traffic_sign:forward n/traffic_sign:backward
       n/highway=stop,give_way,traffic_signals,speed_camera)
# the ways, without their nodes, tell `signs.py` which signs stand on a path
osmium tags-filter --overwrite -R -o data/signs-in.osm.pbf data/region.osm.pbf \
  "${SIGNS[@]}" w/highway
python3 workers/transport/signs.py --pbf=data/signs-in.osm.pbf --out=data/signs-named.osm.pbf \
  --country="$COUNTRY"
osmium tags-filter --overwrite -o data/signs.osm.pbf data/signs-named.osm.pbf "${SIGNS[@]}"
if [ "$(osmium fileinfo -e -g data.count.nodes data/signs.osm.pbf)" = 0 ]; then
  echo "No sign in this area – the base map goes without them."
  exit 0
fi
java -Xmx2g -jar planetiler.jar generate-custom --schema=workers/tiles/signs.yml "$@" \
  --output=data/signs.pmtiles --maxzoom="$Z" --render_maxzoom="$Z" --force
python3 workers/tiles/add-layer.py --into="$OUT" --from=data/signs.pmtiles --layer=traffic_sign
