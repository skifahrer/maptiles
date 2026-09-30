#!/usr/bin/env bash
# The area key as stored names spell it; a new spelling would orphan hours of stored work.
store_area() {
  case "$1" in
    whole) echo cely ;;
    cutout_*) echo "vyrez_${1#cutout_}" ;;
    *) echo "$1" ;;
  esac
}

# The same for sources and the area input in cache keys.
store_token() {
  case "$1" in
    shading) echo tienovanie ;;
    none) echo ziadne ;;
    whole_region) echo cely_region ;;
    *) echo "$1" ;;
  esac
}
