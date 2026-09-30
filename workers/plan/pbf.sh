#!/usr/bin/env bash
# The region's PBF on disk – download, optional crop, key and bbox for the build.
#
# Order: take the PBF (own URL or the parent extract) → read the exact region
# outline from it (`region-poly.py`) and cut the region by it → optionally
# crop → print `key`, `name`, `bbox`, `bboxkey`.
#
# A region is cut from its parent, never from osm.fr's region export: that one
# isn't referentially complete, and Planetiler drops a multipolygon reaching
# into the next region whole. `-S types=multipolygon,boundary` is needed – the
# default `smart` completes only `type=multipolygon`, protected areas are
# `type=boundary`. `set -e` without `-u` and `pipefail` is on purpose.
set -e

T0=$(date +%s)
mkdir -p data
CUSTOM_URL="$OPT_CUSTOM_PBF_URL"

# a PBF (cropped too) from an earlier run needs no download
CACHED=""
if [ -s data/region.osm.pbf ]; then
  CACHED=1
  echo "PBF from cache ✓ ($(du -h data/region.osm.pbf | cut -f1))"
fi

# `$2` is the target: the parent extract downloads aside
download() { # $1 = URL, $2 = file
  [ -n "$CACHED" ] && return 0
  echo "Trying: $1"
  curl -fL --retry 3 --retry-delay 5 -o "${2:-data/region.osm.pbf}" "$1"
}

need_osmium() {
  command -v osmium >/dev/null && return 0
  sudo apt-get update -qq && sudo apt-get install -y -qq osmium-tool
}

# `ogr2ogr` with SpatiaLite intersects the outline with the state; without it
# the full relation geometry cuts, slower (a `::warning::` says so)
need_gdal() {
  command -v ogr2ogr >/dev/null && return 0
  sudo apt-get update -qq \
    && sudo apt-get install -y -qq gdal-bin libsqlite3-mod-spatialite
}

POLY="${REGION_POLY:-data/region.poly}"

# the exact region outline into `$POLY` and `data/region.geojson` – one outline
# for osmium, Planetiler, DEM layers and the viewer
outline_from() { # $1 = PBF the outline is read from
  need_osmium
  need_gdal
  python3 workers/plan/region-poly.py --region="$KEY" --from-pbf="$1" \
    --out=data/region.geojson --poly-out="$POLY" \
    --summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
}

if [ -n "$CUSTOM_URL" ]; then
  # ----- own region (Europe / world) -----
  NAME="$OPT_CUSTOM_NAME"
  ISO=""
  ROUTING_AREA=""
  [ -n "$NAME" ] || NAME=$(basename "$CUSTOM_URL" .osm.pbf)
  KEY=$(echo "$NAME" | LC_ALL=C.UTF-8 iconv -f utf8 -t ascii//TRANSLIT | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/^_//;s/_*$//')
  download "$CUSTOM_URL" || { echo "::error::Couldn't download $CUSTOM_URL"; exit 1; }

  BBOX="$OPT_CUSTOM_BBOX"
  if [ -z "$BBOX" ]; then
    need_osmium
    # no pipe from `osmium`: `head -1` closes it under a writer, EPIPE under `pipefail`
    BOXES=$(osmium fileinfo -g header.boxes data/region.osm.pbf)
    BBOX=$(head -1 <<<"$BOXES" | tr -d '() ')
  fi
  if [ -z "$BBOX" ]; then
    echo "::error::The PBF has no bbox in its header – fill in custom_bbox (west,south,east,north)."
    exit 1
  fi
else
  # ----- a preset region from workers/data/regions.json -----
  KEY="$REGION"
  NAME=$(jq -r --arg r "$KEY" '.[$r].name' workers/data/regions.json)
  BBOX=$(jq -r --arg r "$KEY" '.[$r].bbox | join(",")' workers/data/regions.json)
  DIR=$(jq -r --arg r "$KEY" '.[$r].osmfr.dir' workers/data/regions.json)
  # the country ISO for routing: an edge carries its country, for vignettes
  ISO=$(jq -r --arg r "$KEY" '. as $d | ($d[$r].iso // $d[$d[$r].country].iso // "")' workers/data/regions.json)
  # the CCH node order area – the same for all regions of a country, or their archives won't join
  ROUTING_AREA=$(jq -r --arg r "$KEY" '. as $d | ($d[$r].routing_area // $d[$d[$r].country].routing_area // "")' workers/data/regions.json)
  # the parent is another region key of the same registry, not a second URL
  PARENT=$(jq -r --arg r "$KEY" '.[$r].osmfr.parent // ""' workers/data/regions.json)
  if [ "$NAME" = "null" ]; then echo "::error::Unknown region: $KEY"; exit 1; fi

  # osm.fr renames its files now and then; the first existing one is taken
  slugs() { jq -r --arg r "$1" '.[$r].osmfr.slugs[]' workers/data/regions.json; }

  if [ -z "$PARENT" ]; then
    # ----- a region without a parent (a whole country) – the ready export -----
    OK=""
    for SLUG in $(slugs "$KEY"); do
      if download "$OSMFR_BASE/$DIR/$SLUG.osm.pbf"; then OK=1; break; fi
    done
    if [ -z "$OK" ]; then
      echo "::error::The PBF for '$KEY' couldn't be downloaded. Contents of $OSMFR_BASE/$DIR/ (fix slugs in workers/data/regions.json):"
      curl -sL "$OSMFR_BASE/$DIR/" | grep -oE 'href="[^"]+\.osm\.pbf"' | sort -u || true
      echo "…or fill in custom_pbf_url with a direct URL of a .osm.pbf."
      exit 1
    fi
    # osm.fr's export is widened around the border, so it's cut like a region, at `admin_level=2`
    if [ -z "$CACHED" ]; then
      outline_from data/region.osm.pbf
      if [ ! -s "$POLY" ]; then
        echo "::error::The region outline ($POLY) is missing – without it the map “$NAME” would carry a strip beyond the state border, unseen from the run. workers/plan/region-poly.py makes it from the \`boundary=administrative\` relation in the downloaded PBF; when it found none, it said why a line above."
        exit 1
      fi
      need_osmium
      # a plan with an estimate: cutting a state costs more than a region
      echo "Cutting $NAME exactly to the state border ($POLY) – for a whole state, minutes to tens of minutes."
      TCUT=$(date +%s)
      if ! osmium extract --overwrite -s smart -S types=multipolygon,boundary \
           --polygon "$POLY" -o data/region-cut.osm.pbf data/region.osm.pbf; then
        echo "::error::Cutting to the state border failed. Try the run again; if it keeps failing, check that $POLY is a valid \`.poly\` (workers/plan/region-poly.py)."
        exit 1
      fi
      mv data/region-cut.osm.pbf data/region.osm.pbf
      echo "Cut in $(( $(date +%s) - TCUT )) s → $(du -h data/region.osm.pbf | cut -f1)"
    fi
  elif [ -z "$CACHED" ]; then
    # ----- a region: cut from its parent (why: the file header) -----
    PDIR=$(jq -r --arg r "$PARENT" '.[$r].osmfr.dir' workers/data/regions.json)
    PNAME=$(jq -r --arg r "$PARENT" '.[$r].name' workers/data/regions.json)
    if [ "$PDIR" = "null" ]; then
      echo "::error::Region '$KEY' has \`osmfr.parent: $PARENT\`, but workers/data/regions.json has no such region (or it lacks \`osmfr.dir\`). Fix the registry."
      exit 1
    fi

    need_osmium
    # a plan with an estimate before the expensive part – silence looks stuck
    echo "The region is cut from its parent – $PNAME (~373 MB, then a cut of ~1 min)."
    echo "  why: the region export lacks members of areas reaching into the next region (protected areas, large forests), and Planetiler drops them whole"
    OK=""
    for SLUG in $(slugs "$PARENT"); do
      if download "$OSMFR_BASE/$PDIR/$SLUG.osm.pbf" data/parent.osm.pbf; then OK=1; break; fi
    done
    if [ -z "$OK" ]; then
      echo "::error::The parent extract '$PARENT' couldn't be downloaded. Contents of $OSMFR_BASE/$PDIR/ (fix slugs in workers/data/regions.json):"
      curl -sL "$OSMFR_BASE/$PDIR/" | grep -oE 'href="[^"]+\.osm\.pbf"' | sort -u || true
      exit 1
    fi
    # the exact outline from the parent, the same data that is cut
    outline_from data/parent.osm.pbf

    # no outline, no cut; falling back to the region export was a silent mistake
    if [ ! -s "$POLY" ]; then
      echo "::error::The region outline ($POLY) is missing, so there is nothing to cut the region by – and the region export isn't used (areas reaching into the next region would be missing). workers/plan/region-poly.py makes it from the \`boundary=administrative\` relation in the parent extract (the fallback is osm.fr's \`.poly\`); when both failed, it said why a line above – try the run again."
      exit 1
    fi

    echo "Parent downloaded ($(du -h data/parent.osm.pbf | cut -f1)), cutting $NAME by $POLY …"

    # `-s smart` = whole ways and completed relation members; `-S types=…` for `type=boundary`
    TCUT=$(date +%s)
    if ! osmium extract --overwrite -s smart -S types=multipolygon,boundary \
         --polygon "$POLY" -o data/region.osm.pbf data/parent.osm.pbf; then
      echo "::error::Cutting the region from the parent extract failed. Try the run again; if it keeps failing, check that $POLY is a valid \`.poly\` (workers/plan/region-poly.py)."
      exit 1
    fi
    # 373 MB gone at once: the test crop further on needs the space
    rm -f data/parent.osm.pbf
    echo "Cut in $(( $(date +%s) - TCUT )) s → $(du -h data/region.osm.pbf | cut -f1)"
  fi

  # a cached PBF comes without its outline; read it from the same PBF
  if [ ! -s "$POLY" ]; then
    outline_from data/region.osm.pbf
  fi
fi

# ----- optional crop to a smaller area -----
# crops the PBF, the map itself; works with a test (the test picks a square from it)
CROP="$OPT_CROP_BBOX"
if [ -n "$CROP" ]; then
  if [ -z "$CACHED" ]; then
    need_osmium
    echo "Cropping to bbox $CROP …"
    if ! osmium extract --overwrite -b "$CROP" -s smart \
         -S types=multipolygon,boundary \
         -o data/region-crop.osm.pbf data/region.osm.pbf; then
      echo "::error::Cropping to bbox '$CROP' failed – the expected form is west,south,east,north (e.g. 18.98,49.18,19.20,49.28)."
      exit 1
    fi
    mv data/region-crop.osm.pbf data/region.osm.pbf
  fi
  BBOX="$CROP"
  KEY="${KEY}_crop"
  NAME="$NAME (cut-out)"
fi

# a quick test shrinks the whole run to a square in the middle of the cut-out –
# the map too, so the run's `bbox` equals `dem_bbox`
TEST_KM2="$OPT_TEST_KM2"
# the window of the DEM layers; `BORDER_BUFFER_M` is 0 today, the call stays for when it isn't
DEM_BBOX=$(python3 - "$BBOX" <<'PY'
import sys
sys.path.insert(0, "workers/plan")
from area import pad_bbox, BORDER_BUFFER_M
w, s, e, n = pad_bbox([float(v) for v in sys.argv[1].split(",")], BORDER_BUFFER_M)
print(f"{w},{s},{e},{n}")
PY
)
if [ "${TEST_KM2:-0}" != "0" ]; then
  AREA="$AREA_IN"
  AREA_BBOX="$OPT_AREA_BBOX"
  [ -n "$AREA_BBOX" ] && AREA="$AREA_BBOX"
  RES=$(python3 workers/plan/area.py \
    --region-bbox="$BBOX" --area="$AREA" \
    --test-km2="$TEST_KM2" \
    --test-at="$OPT_TEST_AT")
  DEM_BBOX=$(printf '%s\n' "$RES" | sed -n 's/^bbox=//p')
  [ -n "$DEM_BBOX" ] || { echo "::error::The test square couldn't be computed."; exit 1; }
  # the “where it is” picture shows the whole cut-out; 4 km² on a country map is invisible
  printf '%s\n' "$RES" | sed -n 's/^full_bbox=/full_bbox=/p' >> "$GITHUB_OUTPUT"
  echo "test_bbox=$DEM_BBOX" >> "$GITHUB_OUTPUT"
  # the whole answer for “Resolve the cut-out”: it has the `_test4` key a
  # second computation can't give
  printf '%s\n' "$RES" > /tmp/cutout.txt
  # `-s smart -S types=…` as for the parent cut: nearly every area sticks out of 4 km²
  if [ -z "$CACHED" ]; then
    need_osmium
    echo "Cropping the MAP to the test square $DEM_BBOX …"
    if ! osmium extract --overwrite -b "$DEM_BBOX" -s smart \
         -S types=multipolygon,boundary \
         -o data/region-test.osm.pbf data/region.osm.pbf; then
      echo "::error::Cropping the map to the test square ($DEM_BBOX) failed. Try the run without the switch \`test\`, or another centre via \`options: test_at=lon,lat\`."
      exit 1
    fi
    mv data/region-test.osm.pbf data/region.osm.pbf
  fi
  # the map is the square now; `full_bbox` stays the whole cut-out for the picture
  BBOX="$DEM_BBOX"
  KEY="${KEY}_test${TEST_KM2}"
  NAME="$NAME – test ${TEST_KM2} km²"
  echo "Test mode: the whole run (map and terrain) on $TEST_KM2 km² → $DEM_BBOX"
fi

# what falls out of the PBF must show: Planetiler drops an incomplete area whole, green
if command -v osmium >/dev/null; then
  python3 workers/plan/pbf-areas.py data/region.osm.pbf \
    --summary="${GITHUB_STEP_SUMMARY:-/dev/null}" || true
fi

echo "key=$KEY"   >> "$GITHUB_OUTPUT"
echo "name=$NAME" >> "$GITHUB_OUTPUT"
echo "iso=$ISO"   >> "$GITHUB_OUTPUT"
echo "routing_area=$ROUTING_AREA" >> "$GITHUB_OUTPUT"
echo "bbox=$BBOX" >> "$GITHUB_OUTPUT"
echo "dem_bbox=$DEM_BBOX" >> "$GITHUB_OUTPUT"
# the bbox safe for a cache key, from `dem_bbox`: only DEM layer caches use it
echo "dem_bboxkey=$(echo "$DEM_BBOX" | tr ',.-' '___')" >> "$GITHUB_OUTPUT"
echo "Region: $NAME (key=$KEY, bbox=$BBOX)"
ls -lh data/region.osm.pbf
printf '%s\t%s\t%s\t%s\n' "10" "Region PBF" "$(( $(date +%s) - T0 ))" \
  "$NAME, $(du -h data/region.osm.pbf | cut -f1)$([ -n "$CACHED" ] && echo ' (from cache)')" \
  >> steps-out/plan.tsv
