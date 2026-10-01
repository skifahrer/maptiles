#!/usr/bin/env python3
"""Settlements: the filter passes what the schema wants, and someone really writes a building's area."""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "buildings", "buildings.yml")
FILTER = os.path.join(_WORKERS, "buildings", "filter.txt")
BUILD = os.path.join(_WORKERS, "buildings", "build.sh")
AREAS = os.path.join(_WORKERS, "buildings", "areas.py")

# keys a condition may use, since they come with an object the filter passed
ALONG = {"name"}


def filter_keys(path):
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


def conditions(when):
    if not when:
        return []
    if "__all__" in when:
        return [p for c in when["__all__"] for p in conditions(c)]
    return list(when)


def main():
    bad = []
    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    layers = {v["id"]: v for v in schema.get("layers") or []}
    passes = filter_keys(FILTER)
    for v in layers.values():
        for b in v.get("features") or []:
            keys = set(conditions(b.get("include_when"))) - ALONG
            if keys - passes:
                bad.append(f"{FILTER}: the schema asks for {', '.join(sorted(keys - passes))}, "
                           f"the prefilter doesn't pass it.")

    for layer in ("building", "building_name", "settlement"):
        if layer not in layers:
            bad.append(f"{SCHEMA}: layer `{layer}` is missing, the package promises it.")

    attributes = {a.get("key") for a in schema["definitions"][0]}
    for key in ("name", "area"):
        if key not in attributes:
            bad.append(f"{SCHEMA}: a building doesn't carry `{key}` – that's what the package is for.")

    if "local_path: data/buildings-area.osm.pbf" not in open(SCHEMA, encoding="utf-8").read():
        bad.append(f"{SCHEMA}: planetiler doesn't read the PBF with areas from `areas.py`.")
    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    if "areas.py" not in build or "buildings-area.osm.pbf" not in build:
        bad.append(f"{BUILD}: doesn't call `areas.py` – buildings would have no area.")
    if " -R" in build or "--omit-referenced" in build:
        bad.append(f"{BUILD}: `-R` drops relation members – building multipolygons vanish.")
    if not os.path.exists(AREAS):
        bad.append(f"{AREAS} doesn't exist.")

    for b in bad:
        print(f"::error::{b}")
    if not bad:
        print(f"settlements ✓ ({len(layers)} layers)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
