#!/usr/bin/env bash
# Basic world map → `_site` (tiles, styles, glyphs, manifest); runs locally too.
# From env: OPT_VARIANT OPT_MAXZOOM OPT_LIMIT_MB GLYPHS_ZIP; the region key comes from the variant.
set -euo pipefail

T_TOTAL=$(date +%s)
mkdir -p _site/tiles _site/styles data/world steps-out

# the variant decides layers, sources, package name and size cap
VARIANT="${OPT_VARIANT:-full}"
case "$VARIANT" in plna) VARIANT=full ;; esac
# into `data/world/`, so a local run leaves `git status` clean
SCHEMA=data/world/schema.yml
python3 workers/world/variant.py --variant="$VARIANT" \
  --schema-out="$SCHEMA" --out=data/world/variant.json
REGION=$(jq -r '.region' data/world/variant.json)
SOURCES=$(jq -r '.sources | join(",")' data/world/variant.json)
MAP_LAYERS=$(jq -r '.map_layers' data/world/variant.json)
VARIANT_LIMIT=$(jq -r '.limit_mb' data/world/variant.json)
GLYPHS_MODE=$(jq -r '.glyphs' data/world/variant.json)
NAME=$(jq -r --arg r "$REGION" '.[$r].name // ""' workers/data/regions.json)
BBOX=$(jq -r --arg r "$REGION" '.[$r].bbox // [] | join(",")' workers/data/regions.json)
if [ -z "$NAME" ] || [ -z "$BBOX" ]; then
  echo "::error::Region '$REGION' isn't in workers/data/regions.json (or has no name and bbox). The variant takes its key from \`workers/data/world-variants.json\` – a new one needs its region in regions.json too."
  exit 1
fi

# at z8 water alone is hundreds of MB, and the map is only a base for picking a region
Z="$OPT_MAXZOOM"
case "$Z" in ''|*[!0-9]*) Z=6 ;; esac
if [ "$Z" -gt 8 ]; then
  echo "::warning::maxzoom $Z is too much for the world map (water grows about 3× per level and the map is only a base for picking a region). Using 8."
  Z=8
fi
if [ "$Z" -lt 3 ]; then Z=3; fi

# `auto` = the variant's cap (full 250 MB, basic 15 MB)
LIMIT_MB="${OPT_LIMIT_MB:-auto}"
case "$LIMIT_MB" in ''|auto) LIMIT_MB="$VARIANT_LIMIT" ;; esac
case "$LIMIT_MB" in *[!0-9]*) LIMIT_MB="$VARIANT_LIMIT" ;; esac

echo "World map: $NAME ($BBOX), variant $VARIANT, maxzoom $Z, size cap ${LIMIT_MB} MB"

T0=$(date +%s)
# GDAL only for water (~1 min and 200 MB otherwise wasted)
if [ "${SOURCES#*water}" != "$SOURCES" ] && ! command -v ogr2ogr >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq gdal-bin
fi
workers/lib/planetiler.sh
echo "Tools ready in $(( $(date +%s) - T0 )) s"

T_SRC=$(date +%s)
echo "::group::Sources ($SOURCES)"
# only what the cut schema reads
python3 workers/world/sources.py --out=data/world --only="$SOURCES"
echo "::endgroup::"
echo "Sources: $(du -sh data/world | cut -f1) in $(( $(date +%s) - T_SRC )) s"

# Planetiler silently drops what has `min_zoom` above the archive's maxzoom
TOP=$(python3 -c "
import yaml
d = yaml.safe_load(open('data/world/schema.yml'))
print(max((f.get('min_zoom', 0) for l in d['layers'] for f in l['features']),
          default=0))
")
if [ "$TOP" -gt "$Z" ]; then
  echo "::warning::The schema has features from zoom $TOP, but tiles go to $Z – those features (mostly download subregions) will NOT be in the map. Raise maxzoom to $TOP, or take it as intended."
fi

T_PM=$(date +%s)
OUT="_site/tiles/${REGION}.pmtiles"
echo "::group::Planetiler – world map ($VARIANT), maxzoom $Z"
# default simplification: an overview, not exact terrain
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema="$SCHEMA" \
  --output="$OUT" \
  --minzoom=0 --maxzoom="$Z" --render_maxzoom="$Z" \
  --force
echo "::endgroup::"

MB=$(( $(stat -c%s "$OUT") / 1048576 ))
echo "Tiles: $(du -h "$OUT" | cut -f1) (${MB} MB) in $(( $(date +%s) - T_PM )) s"
if [ "$MB" -gt "$LIMIT_MB" ]; then
  echo "::warning::Tiles take ${MB} MB, above the ${LIMIT_MB} MB cap of variant $VARIANT. Lower maxzoom (now $Z) – water grows about 3× per level – switch to variant \`basic\` (no water or lakes), or raise the \`limit_mb\` input if such a package is fine."
fi

# glyphs don't go into the package (the app carries its own); `_site` just tells the truth
T_A=$(date +%s)
workers/assets/glyphs.sh
# the world style uses no italic
rm -rf "_site/fonts/Noto Sans Italic"
# here the names are known, so ranges are measured
if [ "$GLYPHS_MODE" = 'from_data' ]; then
  python3 workers/world/glyphs.py --fonts=_site/fonts --data=data/world
fi
node workers/world/style.mjs --out=_site/styles --region="$REGION" \
  --variant="$VARIANT" --maxzoom="$Z"
echo "Glyphs ($(du -sh _site/fonts 2>/dev/null | cut -f1)) and styles in $(( $(date +%s) - T_A )) s"

# the manifest says what the map holds; the app and `deploy/publish-map.py` read it
# theme → path in the package, so the app needn't guess style names
STYLES=$(find _site/styles -name '*.json' -printf '%f\n' | sort \
  | jq -R -s --arg r "$REGION" \
      'split("\n") | map(select(length > 0))
       | map({key: (sub("^\($r)-"; "") | sub("\\.json$"; "")),
              value: ("styles/" + .)}) | from_entries')
jq -n \
  --arg region "$REGION" \
  --arg name "$NAME" \
  --arg bbox "$BBOX" \
  --arg built "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg variant "$VARIANT" \
  --arg layers "$MAP_LAYERS" \
  --argjson maxzoom "$Z" \
  --argjson size_mb "$MB" \
  --argjson styles "$STYLES" \
  '{
    default_region: $region,
    kind: "world",
    # tells a `basic` map without sea from a broken build
    variant: $variant,
    layers: ($layers | split(",") | map(select(length > 0))),
    built_at: $built,
    maxzoom: $maxzoom,
    # for an unpacked package in the web viewer; the app carries its own
    glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
    styles: $styles,
    default_style: ("styles/" + $region + "-svetla.json"),
    attribution: "© OpenStreetMap contributors, Geofabrik, Natural Earth",
    regions: {
      ($region): {
        name: $name,
        bbox: ($bbox | split(",") | map(tonumber)),
        pmtiles: ("tiles/" + $region + ".pmtiles"),
        maxzoom: $maxzoom,
        size_mb: $size_mb
      }
    }
  }' > _site/tiles/manifest.json
cat _site/tiles/manifest.json

echo "maxzoom=$Z" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
echo "name=$NAME" >> "$GITHUB_OUTPUT"
# only this step knows them, and the `.aar` job needs them too
echo "variant=$VARIANT" >> "$GITHUB_OUTPUT"
echo "region_key=$REGION" >> "$GITHUB_OUTPUT"
echo "map_layers=$MAP_LAYERS" >> "$GITHUB_OUTPUT"
du -sh _site
printf '%s\t%s\t%s\t%s\n' "10" "World map" "$(( $(date +%s) - T_TOTAL ))" \
  "$VARIANT, maxzoom $Z, ${MB} MB" >> steps-out/world.tsv
