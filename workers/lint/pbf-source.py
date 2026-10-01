#!/usr/bin/env python3
"""A region is cut from its parent extract – the ready regional export mustn't return.

A ready `{region}-latest.osm.pbf` isn't referentially complete: an area reaching
into a neighbouring region lacks members and Planetiler drops it whole.

  1. every region with `osmfr` has `dir` and non-empty `slugs`;
  2. every region has `osmfr.parent` on a region with its own `osmfr`;
  3. `plan/pbf.sh` cuts the parent with `osmium extract -s smart --polygon`;
  4. with `-S types=multipolygon,boundary` – `smart` otherwise completes only
     `type=multipolygon`, while a protected area is `type=boundary`;
  5. the cut mustn't be quietly skipped when the border is missing.

Figures are in the `workers/plan/pbf.sh` header.
"""
import json
import re
import sys

REGIONS = "workers/data/regions.json"
PBF = "workers/plan/pbf.sh"

bad = []

# 1. and 2. the region lookup
with open(REGIONS, encoding="utf-8") as f:
    regions = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

for key, reg in regions.items():
    osmfr = reg.get("osmfr") or {}
    if not osmfr:
        continue
    if not osmfr.get("dir") or not osmfr.get("slugs"):
        bad.append(
            f"Region `{key}` has `osmfr` but not `dir` and non-empty `slugs`. "
            f"The URL is `<base>/<dir>/<slug>.osm.pbf`, so without them the "
            f"PBF has nowhere to come from.")

    parent = osmfr.get("parent")
    if (reg.get("admin_level") or 0) > 2 and not parent:
        bad.append(
            f"Region `{key}` is a sub-national region but has no `osmfr.parent`. "
            f"It's cut from the parent extract – osm.fr's ready "
            f"`{key}-latest.osm.pbf` isn't referentially complete and areas "
            f"reaching into a neighbour (protected areas, big forests) would "
            f"quietly vanish whole.")
    if parent and parent not in regions:
        bad.append(
            f"Region `{key}` has `osmfr.parent` = `{parent}`, but {REGIONS} has "
            f"no such region. The parent is a region KEY, not a URL.")
    elif parent and not (regions[parent].get("osmfr") or {}).get("dir"):
        bad.append(
            f"Parent `{parent}` of region `{key}` has no `osmfr.dir` – no "
            f"address to cut from can be built.")
    if parent == key:
        bad.append(f"Region `{key}` is its own parent.")

# 3. to 5. what it cuts with
with open(PBF, encoding="utf-8") as f:
    text = f.read()
code = "\n".join(r for r in text.splitlines() if not r.lstrip().startswith("#"))

cuts = re.findall(r"osmium extract((?:[^\n]*\\\n)*[^\n]*)", code)
parent_cut = [v for v in cuts if "--polygon" in v]

if not parent_cut:
    bad.append(
        f"{PBF} doesn't cut the region from the parent extract (`osmium extract "
        f"--polygon`). osm.fr's ready regional export mustn't be used: it lacks "
        f"members of areas reaching into a neighbour and Planetiler drops them "
        f"WHOLE – a protected area vanishes, its in-region part too.")

# `-S types=` on EVERY cut: `crop_bbox` and quick-test squares have the same problem
for call in cuts:
    if "-s smart" not in call:
        bad.append(
            f"{PBF}: `osmium extract` without `-s smart`. Without it relation "
            f"members aren't completed and the cut adds nothing over the ready "
            f"export.")
    if "types=multipolygon,boundary" not in call:
        bad.append(
            f"{PBF}: `osmium extract -s smart` without `-S types=multipolygon,boundary`. "
            f"By default `smart` completes only `type=multipolygon` relations, "
            f"while a protected area is `type=boundary` – without the switch "
            f"they stay broken and miss from the map. Nothing fails.")

if not re.search(r'\$OSMFR_BASE/\$PDIR/\$SLUG\.osm\.pbf', code):
    bad.append(
        f"{PBF} doesn't build the parent URL as `$OSMFR_BASE/$PDIR/$SLUG.osm.pbf` – "
        f"it comes from `osmfr.dir` and `osmfr.slugs` of the region "
        f"`osmfr.parent` points at in {REGIONS}.")

# 5. a missing border must FAIL, not fall back to a direct download
if not re.search(r'if \[ ! -s "\$POLY" \]; then\n[^\n]*::error::', code):
    bad.append(
        f"{PBF} doesn't fail when the region `.poly` is missing. That's where a "
        f"previous version fell back to a direct download – the run was green "
        f"and protected areas were missing again. A missing border must be "
        f"`::error::` and `exit 1`.")

for b in bad:
    print(f"::error::{b}")
print(f"Regions are cut from the parent extract: {len(bad)} errors")
sys.exit(1 if bad else 0)
