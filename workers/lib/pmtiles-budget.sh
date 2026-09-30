#!/usr/bin/env bash
# How many zooms fit the site budget – one question, one file.
#
# Defines `pmtiles_in_budget`; afterwards `PM_Z` holds the zoom used and `PM_MB`
# the size – a return value would mix with Planetiler's stdout.
#
#     . workers/lib/pmtiles-budget.sh
#     pmtiles_in_budget <schema> <output> <maxzoom> <cap MB> <floor> \
#                       <label> <advice when over> [<zoom cap>]

# searched both ways: down when it doesn't fit, up when room is left – the tile
# grid step is what shows as stairs at max zoom, and maxzoom is the only lever
pmtiles_in_budget() { # $1 schema $2 output $3 maxzoom $4 cap MB $5 floor $6 label $7 advice $8 zoom cap
  PM_Z="$3"
  local cap="${8:-$3}" lowered=""
  while : ; do
    java -Xmx5g -jar planetiler.jar generate-custom \
      --schema="$1" \
      --output="$2" \
      --maxzoom="$PM_Z" --render_maxzoom="$PM_Z" \
      --simplify_tolerance_at_max_zoom=0 \
      --min_feature_size_at_max_zoom=0 \
      --force

    PM_MB=$(( $(stat -c%s "$2") / 1048576 ))
    echo "$6 maxzoom $PM_Z → ${PM_MB} MB (cap ${4} MB)"

    if [ "$PM_MB" -gt "$4" ]; then
      if [ "$PM_Z" -le "$5" ]; then
        echo "::warning::$6 take ${PM_MB} MB even at maxzoom ${5} – $7"
        break
      fi
      PM_Z=$(( PM_Z - 1 ))
      # once lowered, never raised: the run would swing between two zooms forever
      lowered=1
      echo "::warning::$6 are over the ${4} MB cap – trying maxzoom ${PM_Z}."
      continue
    fi

    # it fit; room for another level? a level adds about as much as all below it
    if [ -z "$lowered" ] && [ "$PM_Z" -lt "$cap" ] \
       && [ $(( PM_MB * 2 )) -le "$4" ]; then
      PM_Z=$(( PM_Z + 1 ))
      echo "$6: room left in the budget (${PM_MB} MB of ${4} MB, the next level" \
           "comes to about $(( PM_MB * 2 )) MB) – trying maxzoom ${PM_Z}," \
           "so max zoom shows no stairs from the tile grid."
      continue
    fi
    break
  done
}
