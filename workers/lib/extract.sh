# shellcheck shell=bash
# The day's extract the `extracts` action left, moved to $2; fails when there is none.
extract_taken() { # $1 = URL, $2 = file
  local f
  f="extracts/$(basename "$1")"
  [ -s "$f" ] || return 1
  mv "$f" "$2"
  echo "Extract of the day: $(basename "$1") ✓"
}
