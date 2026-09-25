#!/usr/bin/env python3
"""Sídla: filter pustí, čo schéma chce, a výmeru na budovu naozaj niekto zapíše."""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "buildings", "buildings.yml")
FILTER = os.path.join(_WORKERS, "buildings", "filter.txt")
BUILD = os.path.join(_WORKERS, "buildings", "build.sh")
AREAS = os.path.join(_WORKERS, "buildings", "areas.py")

# kľúče, ktoré podmienke stačia, lebo prídu s objektom, ktorý filter pustil
SPOLU = {"name"}


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


def podmienky(when):
    if not when:
        return []
    if "__all__" in when:
        return [p for c in when["__all__"] for p in podmienky(c)]
    return list(when)


def main():
    bad = []
    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    vrstvy = {v["id"]: v for v in schema.get("layers") or []}
    pusta = filter_keys(FILTER)
    for v in vrstvy.values():
        for b in v.get("features") or []:
            kluce = set(podmienky(b.get("include_when"))) - SPOLU
            if kluce - pusta:
                bad.append(f"{FILTER}: schéma sa pýta na {', '.join(sorted(kluce - pusta))}, "
                           f"predfilter to nepúšťa.")

    for vrstva in ("building", "building_name", "settlement"):
        if vrstva not in vrstvy:
            bad.append(f"{SCHEMA}: chýba vrstva `{vrstva}`, balík ju sľubuje.")

    atributy = {a.get("key") for a in schema["definitions"][0]}
    for kluc in ("name", "area"):
        if kluc not in atributy:
            bad.append(f"{SCHEMA}: budova nenesie `{kluc}` – kvôli tomu balík je.")

    if "local_path: data/buildings-area.osm.pbf" not in open(SCHEMA, encoding="utf-8").read():
        bad.append(f"{SCHEMA}: planetiler nečíta PBF s výmerou z `areas.py`.")
    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    if "areas.py" not in build or "buildings-area.osm.pbf" not in build:
        bad.append(f"{BUILD}: nevolá `areas.py` – budovy by boli bez výmery.")
    if " -R" in build or "--omit-referenced" in build:
        bad.append(f"{BUILD}: `-R` vyhodí členov relácií – multipolygóny budov zmiznú.")
    if not os.path.exists(AREAS):
        bad.append(f"{AREAS} neexistuje.")

    for b in bad:
        print(f"::error::{b}")
    if not bad:
        print(f"sídla ✓ ({len(vrstvy)} vrstvy)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
