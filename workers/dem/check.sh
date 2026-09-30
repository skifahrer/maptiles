#!/usr/bin/env bash
# Is the height model for our area in the Drive store – and if not, what to refill?
#
# For each of the three layers `workers/dem/target.py` says which store and
# files its source needs; this looks whether they are there. `layer_area_key`
# below must match the three `fetch.sh` calls – the workflow lint guards it.
#
# The cut-out goes as a bbox, not a range key: `Data · DMR 5.0` must read
# exactly the area the run asked for. The asset name goes separately.
#
#   BBOX=W,S,E,N AREA_KEY=vysoke_tatry AREA_BBOX=W,S,E,N \
#   SRC_CONTOURS=dmr5 SRC_ROCKS=dmr5 SRC_TERRAIN=dmr5 \
#   GDRIVE_CREDENTIALS=… workers/dem/check.sh
#
# Into $GITHUB_OUTPUT: `demkey_<layer>`, `mirror_<layer>`, `mirror_dmr5_area`,
# `mirror_dmr5_asset`, `mirror_dmr5_tiles`.
set -euo pipefail

# neighbour paths are built from the own folder, not hard-coded
HERE="$(dirname "$0")"
WORKERS="$(dirname "$HERE")"
BBOX="${BBOX:-}"
AREA_KEY="${AREA_KEY:-whole}"
# the cut-out bbox, intersected with the region; empty = the whole region
AREA_BBOX="${AREA_BBOX:-$BBOX}"
OUT="${GITHUB_OUTPUT:-/dev/null}"

# which layer passes the cut-out key – see the header
layer_area_key() {
  case "$1" in
    terrain) echo whole ;;
    *) echo "$AREA_KEY" ;;
  esac
}

MIRROR=""       # queued for refilling (by SHAPE, not source)
MIRROR_LIST=""  # for the log
DMR5_AREA=""    # a bbox to read as a full-resolution cut-out
DMR5_ASSET=""   # and the name the build looks for it by
DMR5_TILES=""   # which degrees to refill as 1° tiles

# one source: is anything for our area in its store, and its content fingerprint
check_source() { # $1 = layer (for the log), $2 = source
  local what="$1" src="$2" akey rel assets names need=false
  local form target want mirror degrees
  akey=$(layer_area_key "$what")
  target=$(python3 "$HERE/target.py" --source="$src" \
    --area-key="$akey" --bbox="$BBOX")
  tget() { printf '%s\n' "$target" | sed -n "s/^$1=//p" | head -1; }
  form=$(tget form); rel=$(tget store); want=$(tget assets)
  mirror=$(tget mirror); degrees=$(tget degrees)

  # name and size at once: names are searched, whole lines fingerprinted;
  # `|| true`: a store not created yet would fail the step under `pipefail`
  assets=$({ python3 "$WORKERS/drive/store.py" --index --store="$rel" \
    2>/dev/null || true; } | sort)
  names=$(printf '%s\n' "$assets" | cut -d: -f1)

  if [ "$form" = 'area' ]; then
    # full resolution is mirrored by cut-outs (a 1° tile is ~48 GB at 1 m)
    if printf '%s\n' "$names" | grep -qx "$want"; then
      echo "$what ($src): $want is in store $rel ✓"
    else
      echo "$what ($src): $want isn't in store $rel → refilling"
      need=true
    fi
  elif [ -z "$want" ]; then
    # an own region without a bbox – the tile list can't be known
    [ -z "$assets" ] && need=true || true
    echo "$what ($src): the bbox is unknown; store $rel has $(printf '%s' "$assets" | grep -c . || true) files → refill: $need"
  else
    local have=0 total=0 t missing=""
    for t in $want; do
      total=$(( total + 1 ))
      if printf '%s\n' "$names" | grep -qx "$t"; then
        have=$(( have + 1 ))
      else
        missing="$missing $t"
      fi
    done
    # how many must be there depends on whether the missing one can be refilled:
    # `dmr5` stores every degree it read (empty too), so a missing name means
    # “never read”; `sonny`/`dmr35` drop empty tiles, so it may mean “no data”.
    # A name isn't a model yet: `trust.py` opens suspiciously small files.
    if [ "$src" = 'dmr5' ] && [ "$have" -gt 0 ]; then
      local small untrusted
      small=$(printf '%s\n' "$assets" | python3 "$HERE/trust.py" \
        --store="$rel" --names="$want" --only-suspect)
      if [ -n "$small" ]; then
        # `gdalinfo` only when there is something to open: installing GDAL takes half a minute
        if ! command -v gdalinfo >/dev/null 2>&1; then
          echo "  (adding gdal-bin – the store holds a suspiciously small tile)"
          sudo apt-get update -qq
          sudo apt-get install -y -qq gdal-bin
        fi
        untrusted=$(printf '%s\n' "$assets" | python3 "$HERE/trust.py" \
          --store="$rel" --names="$want")
        for t in $untrusted; do
          case " $missing " in
            *" $t "*) ;;
            *) missing="$missing $t"; have=$(( have - 1 )) ;;
          esac
        done
      fi
    fi
    if [ "$src" = 'dmr5' ]; then
      [ -n "$missing" ] && need=true || true
    else
      [ "$have" -eq 0 ] && need=true || true
    fi
    echo "$what ($src): tiles for the bbox $total, in store $rel $have → refill: $need"
    [ -n "$missing" ] && echo "  missing:$missing" || true
    # refill only the missing degrees (half an hour of Drive reading each);
    # a tile name is its south-west corner, so the envelope comes from names
    if [ "$need" = true ] && [ "$src" = 'dmr5' ] && [ -n "$missing" ]; then
      degrees=$(python3 - $missing <<'PY'
import sys
lons, lats = [], []
for t in sys.argv[1:]:
    t = t.split(".")[0]
    lat, lon = int(t[1:3]), int(t[4:7])
    lats.append(-lat if t[0] == "S" else lat)
    lons.append(-lon if t[3] == "W" else lon)
print(f"{min(lons)},{min(lats)},{max(lons) + 1},{max(lats) + 1}")
PY
)
    fi
  fi

  if [ "$need" = true ]; then
    # deduplicated by shape, not source: one `dmr5` may miss both shapes
    case " $MIRROR " in
      *" $mirror "*) echo "  ($mirror is refilled by another layer already)" ;;
      *)
        MIRROR="$MIRROR $mirror"
        MIRROR_LIST="$MIRROR_LIST $mirror"
        if [ "$src" = 'dmr5' ]; then
          # DMR 5.0 is refilled by `Data · DMR 5.0` over HTTP Range (145 GB won't download)
          if [ "$form" = 'area' ]; then
            # a bbox, not a key; the asset name is the `$want` searched above
            DMR5_AREA="$AREA_BBOX"
            DMR5_ASSET="$want"
          else
            DMR5_TILES="$degrees"
          fi
        else
          NEED_SRC="$src"
        fi
        ;;
    esac
  fi
  # a fingerprint only of the tiles the layer reads, or a neighbour's refill drops every cache
  DEMKEY=$(printf '%s\n' "$assets" | awk -v want="$want" '
    BEGIN { n = split(want, w, " "); for (i = 1; i <= n; i++) wanted[w[i]] = 1 }
    n == 0 || substr($0, 1, index($0, ":") - 1) in wanted
  ' | sha256sum | cut -c1-12)
}

for pair in \
  "contours:${SRC_CONTOURS:-}" \
  "rocks:${SRC_ROCKS:-}" \
  "terrain:${SRC_TERRAIN:-}"; do
  layer="${pair%%:*}"
  src="${pair#*:}"
  DEMKEY=""
  NEED_SRC=""
  # DMR 5.0 rocks read slope from Drive in parts (`slope-chunks.py`), no DEM refill
  if [ "$layer" = 'rocks' ] && [ "$src" = 'dmr5' ]; then
    echo "rocks ($src): no DEM refill – slope is read from Drive in parts"
  # an empty source = the layer is off (or rocks come from hillshading)
  elif [ -n "$src" ] && [ "$src" != 'none' ] && [ "$src" != 'ziadne' ]; then
    check_source "$layer" "$src"
  fi
  echo "demkey_$layer=$DEMKEY" >> "$OUT"
  echo "mirror_$layer=$NEED_SRC" >> "$OUT"
done

# DMR 5.0 tiles refill by whole degrees, which is expensive – say so in the log
if [ -n "$DMR5_TILES" ]; then
  IFS=, read -r DW DS DE DN <<< "$DMR5_TILES"
  DEG=$(( (DE - DW) * (DN - DS) ))
  echo "DMR 5.0 tiles: refilling $DEG degrees ($DMR5_TILES)"
  # an estimate: a 5 m degree is read from the 4 m pyramid, ~2 GB and half an hour
  if [ "$DEG" -gt 2 ]; then
    echo "::warning::Refilling $DEG degrees of DMR 5.0 takes about $(( DEG / 2 ))–$DEG hours. A smaller area (input \`area\`) or the switch \`test\` is quicker; a coarser model (sonny, dmr35) is ready at once."
  fi
  # and the other way: an area far smaller than the degree read for it
  python3 - "$BBOX" "$DEG" <<'PY' || true
import math, sys
try:
    w, s, e, n = (float(v) for v in sys.argv[1].split(","))
except ValueError:
    raise SystemExit(0)
deg = int(sys.argv[2])
km2 = ((e - w) * 111.32 * math.cos(math.radians((s + n) / 2))) * ((n - s) * 110.54)
tile_km2 = deg * 111.32 * 110.54 * math.cos(math.radians((s + n) / 2))
if km2 > 0 and tile_km2 / km2 > 50:
    print(f"::warning::Hillshading from DMR 5.0 needs {deg}° tiles, "
          f"~{tile_km2:.0f} km² of reading for an area of {km2:.0f} km² "
          f"({tile_km2 / km2:.0f}× more). A tile must be read whole – its name "
          f"promises the whole degree. About half an hour per degree; for a quick "
          f"test `shading_source: sonny` is cheaper. A refilled tile stays in the "
          f"store, so the next run doesn't pay for it.")
PY
fi
if [ -n "$DMR5_AREA" ]; then
  echo "DMR 5.0 cut-out: reading $DMR5_AREA → $DMR5_ASSET"
fi
{
  echo "mirror_dmr5_area=$DMR5_AREA"
  echo "mirror_dmr5_asset=$DMR5_ASSET"
  echo "mirror_dmr5_tiles=$DMR5_TILES"
} >> "$OUT"

echo "To refill:${MIRROR_LIST:- nothing}"
