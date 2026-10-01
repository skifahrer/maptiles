#!/usr/bin/env python3
"""Area boundaries: the filter passes what the schema wants, the tile has the name – and nothing foreign.

Four quiet things:

  1. the prefilter (`filter.txt`) and schema (`boundaries.yml`) drift;
  2. the filter stops pulling relation members – a municipality border is a
     relation of ways without `boundary=administrative`, so with `-R`
     Planetiler has nothing to build a polygon from and the layer is empty;
  3. `name` leaves the tile – the layer exists for it (OpenMapTiles' `boundary`
     is a line without the area's name);
  4. a region's package carries the whole state's borders – the state border
     relation comes whole from `plan/pbf.sh`, so without cutting and clipping
     one region's package spans the country.
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "boundaries", "boundaries.yml")
FILTER = os.path.join(_WORKERS, "boundaries", "filter.txt")
BUILD = os.path.join(_WORKERS, "boundaries", "build.sh")

# levels the layer PROMISES; the tile carries the number, since the meaning varies by country
LEVELS = {"2": "state", "4": "region", "6": "district", "8": "municipality"}

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
    wants = set()
    for b in blocks:
        condition = b.get("include_when") or {}
        for part in condition.get("__all__", [condition]):
            wants |= set(part.keys()) if isinstance(part, dict) else set()
    wants.discard("admin_level")     # a refinement, not object selection
    missing = sorted(wants - passes)
    if missing:
        err(f"{FILTER}: the schema asks for {', '.join(missing)}, but the prefilter "
            f"doesn't pass it (it knows {', '.join(sorted(passes))}). Planetiler "
            f"would get a PBF without that tag – tiles made, run green, and that "
            f"part of the boundaries simply missing.")

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
            f"so relation MEMBERS drop out of the PBF. A municipality border is a "
            f"relation whose members lack `boundary=administrative` – Planetiler "
            f"would have nothing to build a polygon from and the layer would be "
            f"empty on a green run. Without the switch osmium pulls them.")
    if "r/boundary=administrative" not in open(FILTER, encoding="utf-8").read():
        err(f"{FILTER}: `r/boundary=administrative` is missing. The RELATION "
            f"carries an area's name and level, not its ways – without it the "
            f"tile has lines without what the layer exists for.")

    # 2b. what lies outside the region leaves the PBF and the tiles
    if "region-cut.sh" not in build:
        err(f"{BUILD}: the PBF isn't cut to the region (`workers/lib/region-cut.sh`). "
            f"The state border relation is in it whole, so one region's package "
            f"carries borders across the country – and draws them at the lowest "
            f"zooms, where a tile spans thousands of kilometres.")
    if "region-clip.sh" not in build:
        err(f"{BUILD}: tiles aren't clipped to the region "
            f"(`workers/lib/region-clip.sh`). Without the clip a region's "
            f"package makes tiles over the whole state.")

    # 3. every block carries a name
    for i, b in enumerate(blocks, start=1):
        attrs = {a.get("key") for a in (b.get("attributes") or [])
               if isinstance(a, dict)}
        if "name" not in attrs:
            err(f"{SCHEMA}: block {i} gives no `name`. That's the difference from "
                f"the base map's `boundary` layer – without a name it's just a "
                f"line and “which municipality am I in” has no answer.")

    # 3b. all four levels are in the schema
    schema_levels = set()
    for b in blocks:
        condition = b.get("include_when") or {}
        for part in condition.get("__all__", [condition]):
            if isinstance(part, dict) and "admin_level" in part:
                values = part["admin_level"]
                schema_levels |= set(map(
                    str, values if isinstance(values, list) else [values]))
    for level, what in LEVELS.items():
        if level not in schema_levels:
            err(f"{SCHEMA}: level `admin_level={level}` ({what}) isn't in the "
                f"schema. The package promises state, region, district and "
                f"municipality borders – a missing level shows only when someone "
                f"asks which district they're in.")
    return done()


def done():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in the area boundaries.")
        return 1
    print("Area boundaries: the prefilter passes what the schema wants and pulls "
          "relation members, the tile has the name, all four levels are in the "
          "schema and nothing goes outside the region.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
