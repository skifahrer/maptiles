#!/usr/bin/env bash
# Intermediate results of a run into the Drive store – nothing goes to GitHub.
#
# The name says what is inside and is unique (date and run number added here);
# the store is thinned to 90 days by `cleanup-cache.yml`. One file goes alone,
# more are packed into `.tar.zst`. A failure never fails the run.
#
#   KIND=terrain NAME=terrain-vysoke_tatry-s45-g2   workers/deploy/publish-results.sh
#   NAME=preview-vysoke_tatry-z16 PATHS=out/preview.png  …
set -uo pipefail

NAME="${NAME:?name without extension}"
KIND="${KIND:-files}"

case "$KIND" in
  terrain)
    # rocks and contours: source geometry (GPKG) and finished tiles
    FILES=(data/rock.gpkg data/contours.gpkg
           contours-out/contours.pmtiles contours-out/rocks.pmtiles
           contours-out/rock-stats.txt)
    NOTE="Contours and rocks of one run – GPKG and PMTiles"
    ;;
  trails)
    FILES=(data/trails.geojson steps-out/trail-stats.txt)
    NOTE="Waymarked trails of one run – GeoJSON before tiling"
    ;;
  files)
    # checked here, not `:?`: the env lint reads `:?` as "the step MUST pass it"
    if [ -z "${PATHS:-}" ]; then
      echo "::error::KIND=files needs PATHS – paths split by space or newline."
      exit 1
    fi
    # shellcheck disable=SC2206  # word splitting is the point here
    FILES=(${PATHS})
    NOTE="${NOTE:-Intermediate run result to look at}"
    ;;
  *)
    echo '::error::Unknown KIND – it is `terrain`, `trails` or `files`.'
    exit 1
    ;;
esac

# a missing file is skipped and said; an empty archive would look like a result
FOUND=()
for f in "${FILES[@]}"; do
  if [ -d "$f" ] || [ -s "$f" ]; then
    FOUND+=("$f")
  else
    echo "  ($f missing – skipping)"
  fi
done
if [ ${#FOUND[@]} -eq 0 ]; then
  echo "::warning::None of the files ($KIND) came to be – nothing goes to the store."
  exit 0
fi

STAMP="$(date -u +%Y%m%d-%H%M)-r${GITHUB_RUN_NUMBER:-0}"
TMP="${RUNNER_TEMP:-/tmp}"

if [ ${#FOUND[@]} -eq 1 ] && [ -f "${FOUND[0]}" ]; then
  # a single FILE goes alone with its own extension, so Drive can open it
  BASE="$(basename "${FOUND[0]}")"
  EXT="${BASE##*.}"
  [ "$EXT" = "$BASE" ] && EXT="dat"
  SEND="$TMP/${NAME}-${STAMP}.${EXT}"
  cp "${FOUND[0]}" "$SEND"
elif command -v zstd >/dev/null 2>&1; then
  SEND="$TMP/${NAME}-${STAMP}.tar.zst"
  tar --use-compress-program='zstd -9 -T0' -cf "$SEND" "${FOUND[@]}"
else
  SEND="$TMP/${NAME}-${STAMP}.tar.gz"
  tar -czf "$SEND" "${FOUND[@]}"
fi

if [ ! -s "$SEND" ]; then
  echo "::warning::Packing the intermediate results ($KIND) failed – nothing goes to the store."
  exit 0
fi
echo "Into the results store: $(basename "$SEND") ($(du -h "$SEND" | cut -f1)), holding ${FOUND[*]}"

python3 workers/drive/store.py --put --store=results \
    --file="$SEND" --note="$NOTE" \
  || echo "::warning::The intermediate results ($KIND) couldn't be stored. The map doesn't suffer – it's something to look at."
rm -f "$SEND"
exit 0
