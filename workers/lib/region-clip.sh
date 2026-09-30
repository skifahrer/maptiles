#!/usr/bin/env bash
# How Planetiler is told "stay in the region": `--polygon` OR `--bounds`, never both.
# Both at once: `tileExtents` is computed in the constructor, so the polygon cuts nothing.
#
#   mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")
#   java -jar planetiler.jar … "${CLIP[@]}"
set -euo pipefail

BBOX="${1:-}"
POLY="${2:-data/region.poly}"
# on by default: turning the cut off must be written down
CLIP_ON="${OPT_REGION_CLIP:-true}"

# the same window the DEM layers get (`plan/area.py::pad_bbox`)
pad_bbox() {
  python3 - "$1" <<'PY'
import sys
sys.path.insert(0, "workers/plan")
from area import pad_bbox, BORDER_BUFFER_M
w, s, e, n = pad_bbox([float(v) for v in sys.argv[1].split(",")], BORDER_BUFFER_M)
print(f"{w},{s},{e},{n}")
PY
}

# arguments to stdout (the caller reads them), explanation to the log
if [ -s "$POLY" ] && [ "$CLIP_ON" != 'true' ]; then
  if [ -n "$BBOX" ]; then echo "--bounds=$(pad_bbox "$BBOX")"; fi
  echo "::warning::Cutting to the region is off (\`region_clip=false\`), so tiles are made on the whole bbox rectangle – in the Bratislava region that is 26 % more tiles and 0.7 % more bytes, carrying a fringe of data beyond the region border. The map doesn't show it, since the style mask draws the border. Turn it back on with \`region_clip=true\` in the \`options\` input." >&2
elif [ -s "$POLY" ]; then
  echo "--polygon=$POLY"
  echo "Cut to region: $POLY – tiles outside the region aren't made. (\`--bounds\` is deliberately NOT added, it silently disables the polygon.)" >&2
else
  # `set -e`: `[ … ] && echo` would kill the script on an empty bbox
  if [ -n "$BBOX" ]; then echo "--bounds=$BBOX"; fi
  echo "::warning::The region polygon ($POLY) is missing, so tiles are made on the WHOLE bbox rectangle – the map reaches beyond the region (Planetiler draws water and Natural Earth everywhere). Usually the \`plan\` job didn't get the \`.poly\`; try the run again." >&2
fi
