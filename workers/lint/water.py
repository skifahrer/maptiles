#!/usr/bin/env python3
"""Water: the filter passes what the schema wants – and the name is on the same feature.

Five quiet things:

  1. the prefilter (`filter.txt`) and schema (`water.yml`) drift – Planetiler
     gets a PBF without that tag and the run goes green;
  2. the filter stops pulling relation members: lakes and reservoirs are
     multipolygons whose members lack `natural=water`, so with `-R` they vanish;
  3. `name` leaves the tile – the layer exists for it (OpenMapTiles keeps water
     names in a separate layer);
  4. the sea gets drawn as an area – OSM has no ocean area, so a cut PBF would
     give a sea ending at the cutout edge;
  5. the PBF stops being cut to the region – Planetiler cuts by tile and a z6
     tile is 5 600 km wide, so rivers far outside the region fit in.
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "water", "water.yml")
FILTER = os.path.join(_WORKERS, "water", "filter.txt")
BUILD = os.path.join(_WORKERS, "water", "build.sh")

# what the layer PROMISES – class → what it is in OSM
PROMISED = {
    "river": "rivers",
    "stream": "streams",
    "water": "lakes, reservoirs and ponds (`natural=water`)",
    "coastline": "the sea (coastline)",
}

bad = []


def err(msg):
    bad.append(msg)


def filter_keys(path):
    """Bare keys from `osmium tags-filter --expressions` (without `n/`, `w/`, `r/`)."""
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "/" in line.split("=", 1)[0]:
                line = line.split("/", 1)[1]
            out.add(line.split("=", 1)[0].strip())
    return out


def filter_switches(build):
    """Switches of the REAL `osmium tags-filter` call, continuation lines included."""
    lines = build.splitlines()
    for i, r in enumerate(lines):
        if r.lstrip().startswith("#") or "osmium tags-filter" not in r:
            continue
        command = [r]
        while command[-1].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            command.append(lines[i])
        return " " + " ".join(command) + " "
    return ""


def main():
    for path in (SCHEMA, FILTER, BUILD):
        if not os.path.exists(path):
            print(f"::error::{path} doesn't exist.")
            return 1

    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    blocks = [b for v in (schema.get("layers") or [])
             for b in (v.get("features") or [])]
    if not blocks:
        err(f"{SCHEMA}: the schema has not a single block – the layer would be empty.")
        return done()

    # 1. the prefilter passes what the schema wants
    passes = filter_keys(FILTER)
    wants, classes = set(), set()
    for b in blocks:
        condition = b.get("include_when") or {}
        wants |= set(condition.keys())
        for values in condition.values():
            classes |= set(map(str, values if isinstance(values, list)
                              else [values]))
    missing = sorted(wants - passes)
    if missing:
        err(f"{FILTER}: the schema asks for {', '.join(missing)}, but the prefilter "
            f"doesn't pass it (it knows {', '.join(sorted(passes))}). Planetiler "
            f"would get a PBF without that tag – tiles made, run green, and that "
            f"part of the water missing.")

    # 2. the filter pulls relation members
    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    switches = filter_switches(build)
    if not switches:
        err(f"{BUILD}: no `osmium tags-filter` here – without a prefilter "
            f"Planetiler reads the whole region and this check has nothing to verify.")
    # `-r` doesn't exist; osmium only knows `-R` (the opposite) and fails on `-r`
    if " -r " in switches:
        err(f"{BUILD}: `osmium tags-filter -r` – osmium has no such switch and "
            f"fails with “unrecognised option”. It pulls relation members "
            f"itself, no need to ask.")
    if " -R " in switches or "--omit-referenced" in switches:
        err(f"{BUILD}: `osmium tags-filter` runs with `-R`/`--omit-referenced`, "
            f"so relation MEMBERS drop out of the PBF. Big lakes and reservoirs "
            f"are multipolygons whose members lack `natural=water` – they'd "
            f"quietly vanish from the tiles. Without the switch osmium pulls them.")

    # 2b. what lies outside the region leaves the PBF
    if "region-cut.sh" not in build:
        err(f"{BUILD}: the PBF isn't cut to the region (`workers/lib/region-cut.sh`). "
            f"Tile clipping can't replace it – it cuts whole tiles, so at low zoom "
            f"rivers hundreds of kilometres away fit the one tile crossing the "
            f"region and show in the map.")

    # 3. the name is on the same feature
    for i, b in enumerate(blocks, start=1):
        attrs = {a.get("key") for a in (b.get("attributes") or [])
               if isinstance(a, dict)}
        if "name" not in attrs:
            err(f"{SCHEMA}: block {i} gives no `name`. That's the difference from "
                f"OpenMapTiles, where water names lie in a separate layer – "
                f"without it it's just a blue line again.")

    # 3b. what the layer promises is really in it
    for cls, what in PROMISED.items():
        if cls not in classes:
            err(f"{SCHEMA}: the schema lacks {what} (`{cls}`). The package "
                f"promises “rivers, lakes and the sea” – a dropped class shows "
                f"only when someone looks where it flows.")

    # 4. the coastline goes as a line, not an area
    for i, b in enumerate(blocks, start=1):
        condition = b.get("include_when") or {}
        values = condition.get("natural") or []
        if not isinstance(values, list):
            values = [values]
        if "coastline" in map(str, values) and b.get("geometry") != "line":
            err(f"{SCHEMA}: block {i} takes `natural=coastline` as "
                f"`{b.get('geometry')}`. OSM has no ocean area – it's built from "
                f"the whole planet's coastlines, so a cut regional PBF would give "
                f"a sea ending at the cutout edge. The base map draws the area "
                f"from `water_polygons`.")
    return done()


def done():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in the water layer.")
        return 1
    print("Water: the prefilter passes what the schema wants and pulls relation "
          "members, the PBF is cut to the region, the name is on the same feature "
          "and the coastline goes as a line.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
