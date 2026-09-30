#!/usr/bin/env bash
# “Is the layer already made, or must it be computed?” – one answer for contours,
# rocks and hillshading, needed in four places of each of three jobs.
#
# Three reasons to have it:
#   exact key match      nothing new
#   prefix               settings match, fingerprints don't – the default
#                        (`reuse_layers`); said with `::notice::`
#   key from before the split   a one-off migration
#
# Only what was really computed may be saved: a layer taken by prefix would
# claim today's script fingerprint under today's key.
#
# From the environment: LAYER HIT MATCHED HIT_LEGACY
set -euo pipefail

LAYER="${LAYER:?which layer is decided}"
HIT="${HIT:-}"                 # `true` only on an EXACT key match
MATCHED="${MATCHED:-}"         # the key really found (by prefix too)
HIT_LEGACY="${HIT_LEGACY:-}"   # an exact match of the key from before the split

HAVE=false
if [ "$HIT" = 'true' ]; then
  HAVE=true
  echo "$LAYER: cached under today's key – not computed."
elif [ -n "$MATCHED" ]; then
  HAVE=true
  # aloud: the one place showing the map carries a layer older than today's code
  echo "::notice::$LAYER – not recomputed, taking the finished layer of an earlier run (\`$MATCHED\`). The settings match, the model store or script fingerprint doesn't. The choice \`rebuild\` recomputes it, or a run with \`reuse_layers=false\`."
elif [ "$HIT_LEGACY" = 'true' ]; then
  HAVE=true
  echo "$LAYER: cached under the key from before the key split – not computed."
else
  echo "$LAYER: not cached – computed."
fi

{
  echo "have=$HAVE"
  # two names for one thing: a step's `if:` reads better as “compute when missing”
  [ "$HAVE" = 'true' ] && echo "compute=false" || echo "compute=true"
} >> "$GITHUB_OUTPUT"
