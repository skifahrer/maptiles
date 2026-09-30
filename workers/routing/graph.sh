#!/usr/bin/env bash
# Valhalla's routing graph from a PBF – and a package a phone can open:
#   valhalla_tiles.tar (the graph), valhalla.json (config), admins.sqlite (borders, driving
#   side – without it vignettes and country penalties silently fail), timezones.sqlite.
# Built by the Valhalla docker image at a pinned tag, whose version goes into the package.
# Two scopes: a whole state (`AREA`) or one region (`REGION_KEY`, cut at its border).
#
# In:  ROUTING_PBF, AREA or REGION_KEY, VALHALLA_IMAGE
# Out: _site/routing/* and `graph_mb`, `valhalla` to GITHUB_OUTPUT

set -euo pipefail
mkdir -p custom_files _site/routing steps-out
T=$(date +%s)

AREA="${AREA:-}"
REGION_KEY="${REGION_KEY:-}"
if [ -n "$AREA" ]; then
  SCOPE="area"                        # a whole state (or states) from the lookup
  WHAT="area \`$AREA\`"
  PBF="${ROUTING_PBF:-data/routing.osm.pbf}"
  MADE_BY="workers/routing/pbf.sh"
elif [ -n "$REGION_KEY" ]; then
  SCOPE="region"                      # one region, its own package beside the map
  WHAT="region \`$REGION_KEY\`"
  PBF="${ROUTING_PBF:-data/region.osm.pbf}"
  MADE_BY="workers/plan/pbf.sh (step “Region PBF”)"
else
  echo "::error::Say what scope the graph is built for: AREA (a key from workers/data/routing-areas.json, a national package) or REGION_KEY (a region, its own package beside its map). Without it graph.json couldn't say what the graph covers – and the scope is the main thing to know about routing."
  exit 1
fi
IMAGE="${VALHALLA_IMAGE:-ghcr.io/valhalla/valhalla-scripted:latest}"
# kept: Valhalla logs how many ways are routable – the one honest measure
BUILD_LOG="valhalla-build.log"

[ -s "$PBF" ] || {
  echo "::error::$PBF is missing – $MADE_BY must pass first."
  exit 1
}
cp "$PBF" custom_files/routing.osm.pbf

PBF_MB=$(( $(stat -c%s custom_files/routing.osm.pbf) / 1048576 ))
# the plan before the slow part; a rough estimate
echo "::notice::Building the graph from ${PBF_MB} MB of PBF ($WHAT, image $IMAGE). A region takes minutes; Slovakia alone tens of minutes and with neighbours it can be hours – the job cap is 360 minutes. Measured national numbers belong in workers/data/routing-areas.json."

# the version before the build; no pipe from `docker run` (EPIPE under pipefail)
VALHALLA_RAW=$(docker run --rm --entrypoint valhalla_build_tiles "$IMAGE" \
               --version 2>/dev/null || true)
VALHALLA_VER=$(tr -d '\r' <<<"$VALHALLA_RAW" | head -1)
if [ -z "$VALHALLA_VER" ]; then
  VALHALLA_VER=$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || true)
  echo "::warning::Valhalla's version couldn't be read from the image; the package gets digest “${VALHALLA_VER:-unknown}”. The client must check the graph version itself."
fi
echo "Valhalla: ${VALHALLA_VER:-unknown}"

echo "::group::valhalla_build_tiles (Docker)"
# `serve_tiles=False` or the container runs to the time cap; `force_rebuild` or an old tar returns
docker run --rm \
  -e serve_tiles=False \
  -e force_rebuild=True \
  -e build_admins=True \
  -e build_time_zones=True \
  -e build_tar=True \
  -e build_elevation=False \
  -e tileset_name=valhalla_tiles \
  -e server_threads="$(nproc)" \
  -v "$PWD/custom_files:/custom_files" \
  "$IMAGE" 2>&1 | tee "$BUILD_LOG"
echo "::endgroup::"

# an image may exit 0 having skipped a step; a small cutout's graph is legitimately tiny
failed=0
for pair in "valhalla_tiles.tar:0:graph" \
            "valhalla.json:200:configuration" \
            "admins.sqlite:20000:state borders and driving side" \
            "timezones.sqlite:20000:time zones"; do
  IFS=: read -r f min what <<<"$pair"
  src="custom_files/$f"
  if [ ! -s "$src" ]; then
    echo "::error::The graph lacks $f ($what). Image $IMAGE finished but didn't make the file – try \`force_rebuild=True\` and see the step log above."
    failed=1
    continue
  fi
  size=$(stat -c%s "$src")
  if [ "$size" -lt "$min" ]; then
    echo "::error::$f is only ${size} B ($what) – a truncated file. It's the same every run, so not a small area; see the step log above for a memory kill (lower server_threads)."
    failed=1
    continue
  fi
  cp "$src" "_site/routing/$f"
  echo "  $f  $(du -h "$src" | cut -f1)  ($what)"
done
[ "$failed" = 0 ] || exit 1

# routable ways incl. footways; zero is a warning, and the number goes into graph.json
WAYS=$(grep -oE '[0-9]+ routable ways' "$BUILD_LOG" | tail -1 \
       | grep -oE '^[0-9]+' || true)
if [ -z "$WAYS" ]; then
  echo "::warning::The build log has no “routable ways” line, so how many ways the graph covers can't be said – \`graph.json\` gets \`ways: null\`. Image $IMAGE's output probably changed."
elif [ "$WAYS" = 0 ]; then
  echo "::warning::Valhalla found NOT ONE way to take in the PBF – no road, footway, path, steps or \`sidewalk\`. The graph ($WHAT) is empty: no route computes in it. Expected for a small cutout or quick test, so the run doesn't fail; otherwise check the PBF wasn't cut to an empty area."
else
  echo "Ways in the graph: $WAYS (footways, paths and \`sidewalk\` too)"
fi

# what the package holds and from what; `contents.json` comes from `deploy/publish-map.py`
python3 - "$SCOPE" "${AREA:-$REGION_KEY}" "$VALHALLA_VER" "$PBF_MB" "$WAYS" \
        > _site/routing/graph.json <<'PY'
import json, os, sys, time
scope, key, valhalla, pbf_mb = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
ways = int(sys.argv[5]) if sys.argv[5] else None
graph = {
    # the main thing about routing: `area` is a whole state, `region` one region
    "scope": scope,
    "key": key,
    "pbf_mb": pbf_mb,
    # `null` means "couldn't be read from the log", not zero
    "ways": ways,
    # graph and library must match
    "valhalla": valhalla or "unknown",
    "profiles": ["auto", "bus", "bicycle", "pedestrian"],
    # `multimodal` needs GTFS, which OSM lacks
    "multimodal": False,
    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "run": os.environ.get("GITHUB_RUN_NUMBER", ""),
    "run_id": os.environ.get("GITHUB_RUN_ID", ""),
}
if scope == "area":
    areas = json.load(open(os.path.join("workers", "data", "routing-areas.json"),
                           encoding="utf-8"))["areas"]
    area = areas[key]
    graph.update({
        "name": area["name"],
        "region_key": area["region_key"],
        "countries": area["countries"],
        "pbf": area["pbf"],
        # whole national extracts, nothing cut – `routing/pbf.sh` must not cut
        "border": "a route may run to the edge of the scope",
    })
else:
    regions = json.load(open(os.path.join("workers", "data", "regions.json"),
                             encoding="utf-8"))
    graph.update({
        "name": (regions.get(key) or {}).get("name") or key,
        "region_key": key,
        # `country` in regions.json is a catalog node (`slovensko`), not `SK`
        "country_node": (regions.get(key) or {}).get("country") or "",
        # the PBF is cut at the region border, so an edge missing its end is a dead end
        "border": "a route ends at the region border; across it runs the "
                  "national graph from .github/workflows/navigation.yml",
    })
print(json.dumps(graph, ensure_ascii=False, indent=2))
PY
cat _site/routing/graph.json

MB=$(( $(du -sb _site/routing | cut -f1) / 1048576 ))
echo "graph_mb=$MB" >> "$GITHUB_OUTPUT"
echo "valhalla=${VALHALLA_VER:-unknown}" >> "$GITHUB_OUTPUT"
SEC=$(( $(date +%s) - T ))
echo "::notice::Graph done: ${MB} MB in $(( SEC / 60 )) min $(( SEC % 60 )) s (PBF ${PBF_MB} MB, $WHAT). For a national run this number belongs in workers/data/routing-areas.json; for a region it's in the catalog under its own package (\`maps.routing\`)."
printf '%s\t%s\t%s\t%s\n' "20" "Routing graph (Valhalla)" "$SEC" \
  "${MB} MB from ${PBF_MB} MB PBF" >> steps-out/routing.tsv
