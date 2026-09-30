#!/usr/bin/env bash
# Wikipedia articles for everything in the region linking to a wiki; the work is in `collect.py`.
# From env (see wiki.yml): REGION_KEY WIKI_COUNTRY OPT_WIKI_LANGS OPT_WIKI_MAX
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
# the only way to full text in batches of fifty (`prop=extracts` won't batch)
pip install --quiet mwparserfromhell

mkdir -p wiki-out wiki-cache steps-out

# English and the country language are added by `--country`; these are extra
LANGS="${OPT_WIKI_LANGS:-}"
COUNTRY="${WIKI_COUNTRY:-}"
MAX="${OPT_WIKI_MAX:-5000}"
case "$MAX" in
  ''|*[!0-9]*)
     echo "::error::wiki_max=$MAX isn't a whole number – give a cap on" \
          "articles, e.g. \`wiki_max=2000\`."
     exit 1 ;;
esac

# the cache folder is passed even before it exists, so `cache-save` has something after run one
python3 workers/wiki/collect.py \
  --pbf=data/region.osm.pbf \
  --out=wiki-out \
  --cache=wiki-cache \
  --country="$COUNTRY" \
  --langs="$LANGS" \
  --max="$MAX" \
  --stats=steps-out/wiki.tsv

# the count decides publishing, so it goes to the job output
COUNT=$(python3 - <<'PY'
import json
try:
    with open("wiki-out/index.json") as f:
        print(len(json.load(f).get("articles") or []))
except Exception:
    print(0)
PY
)
MB=$(du -sm wiki-out | cut -f1)
echo "count=$COUNT" >> "$GITHUB_OUTPUT"
echo "mb=$MB" >> "$GITHUB_OUTPUT"
echo "enabled=$([ "$COUNT" -gt 0 ] && echo true || echo false)" >> "$GITHUB_OUTPUT"
echo "Articles: $COUNT, $MB MB in wiki-out/ (country ${COUNTRY:-?}, extra languages ${LANGS:-none})"
# here-string, not a pipe: `head` closing it would EPIPE `ls` under pipefail
LISTING=$(ls -1 wiki-out)
head -5 <<<"$LISTING"
