#!/usr/bin/env bash
# CCH node order over the whole area → `data/routing-order.json`.
# Called by the region build when the cache has none or a stale one, and by “Routing · node order”.
# It depends only on the network's SHAPE, so it is recomputed after ORDER_MAX_AGE_DAYS;
# a new id means regions built on the old one must be rebuilt.
#
# In:  AREA (key in routing-areas.json), OSMFR_BASE, ORDER_MAX_AGE_DAYS (default 30;
#      0 = always), FORCE=true = compute even when fresh
# Out: data/routing-order.json; `computed`, `id`, `nodes` to GITHUB_OUTPUT

set -euo pipefail
mkdir -p data steps-out
: "${AREA:?give AREA – a key from workers/data/routing-areas.json}"
OUT=data/routing-order.json
MAX_AGE="${ORDER_MAX_AGE_DAYS:-30}"

if [ "${FORCE:-false}" != "true" ] && [ -s "$OUT" ]; then
  AGE=$(python3 - "$OUT" "$AREA" <<'PY'
import json, sys, time
try:
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    when = time.mktime(time.strptime(raw["built_at"], "%Y-%m-%dT%H:%M:%SZ"))
    # a cached order may still carry the former Slovak keys
    name = raw.get("name", raw.get("nazov"))
    if name != sys.argv[2]:
        raise ValueError(f"the order is for `{name}`, not `{sys.argv[2]}`")
    print(int((time.time() - when) / 86400), raw["id"], raw.get("nodes", raw.get("uzlov")))
except (OSError, ValueError, KeyError) as exc:
    print(f"::warning::{sys.argv[1]} can't be read ({exc}) – computing anew.",
          file=sys.stderr)
    print("-1 - -")
PY
)
  read -r DAYS ID NODES <<<"$AGE"
  if [ "$DAYS" -ge 0 ] && [ "$MAX_AGE" -gt 0 ] && [ "$DAYS" -lt "$MAX_AGE" ]; then
    echo "Node order $ID ($NODES nodes) from cache is $DAYS days old – under ${MAX_AGE}, taken."
    { echo "computed=false"; echo "id=$ID"; echo "nodes=$NODES"; } >> "${GITHUB_OUTPUT:-/dev/null}"
    exit 0
  fi
  [ "$DAYS" -ge 0 ] && echo "Node order $ID from cache is $DAYS days old (cap $MAX_AGE) – computing anew."
fi

# apt before pbf.sh: several extracts need `osmium merge`
command -v osmium >/dev/null || { sudo apt-get update -qq; sudo apt-get install -y -qq osmium-tool; }
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'

T=$(date +%s)
# pbf.sh writes data/routing.osm.pbf, the name the region build reuses, so delete it after
workers/routing/pbf.sh
python3 workers/routing/order.py \
  --pbf=data/routing.osm.pbf \
  --out="$OUT" \
  --name="$AREA"
rm -f data/routing.osm.pbf

python3 - "$OUT" >> "${GITHUB_OUTPUT:-/dev/null}" <<'PY'
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
print("computed=true")
print(f"id={raw['id']}")
print(f"nodes={raw['nodes']}")
PY
printf '%s\t%s\t%s\t%s\n' "11" "Node order ($AREA)" "$(( $(date +%s) - T ))" \
  "$(du -h "$OUT" | cut -f1)" >> steps-out/routing.tsv
