#!/usr/bin/env python3
"""Rail and aerialways: the filter passes what the schema wants, routing runs on what the map draws."""
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "rail", "rail.yml")
FILTER = os.path.join(_WORKERS, "rail", "filter.txt")
BUILD = os.path.join(_WORKERS, "rail", "build.sh")
DICTIONARY = os.path.join(_WORKERS, "data", "rail-routing-tags.json")

# keys `lines.py` adds to points – the prefilter needn't pass them
DERIVED = {"rail_speed"}

# what the package promises in the app
PROMISED = {"rail", "tram", "subway", "light_rail", "abandoned", "disused",
         "station", "halt", "level_crossing"}
# aerialways in every state – under construction, proposed and abandoned too
PROMISED_AERIAL = {"cable_car", "gondola", "chair_lift", "goods", "construction",
                 "proposed", "disused", "abandoned", "station"}
STATES = {"construction:aerialway", "proposed:aerialway", "disused:aerialway",
         "abandoned:aerialway", "razed:aerialway", "was:aerialway",
         "removed:aerialway", "demolished:aerialway", "historic:aerialway"}


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
    """Key → values pairs of `include_when`, also under `__all__`."""
    if not when:
        return []
    if "__all__" in when:
        return [p for c in when["__all__"] for p in conditions(c)]
    return [(k, v if isinstance(v, list) else [v]) for k, v in when.items()]


def main():
    bad = []
    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    blocks = [b for v in schema.get("layers") or [] for b in v.get("features") or []]

    passes, classes, aerial, all_keys = filter_keys(FILTER), set(), set(), set()
    for b in blocks:
        keys = set()
        for key, values in conditions(b.get("include_when")):
            keys.add(key)
            all_keys.add(key)
            if key == "railway":
                classes |= set(map(str, values))
            if key == "aerialway":
                aerial |= set(map(str, values))
        # under `__all__` one key is enough – the rest come with the same object
        if keys and not keys & (passes | DERIVED):
            bad.append(f"{FILTER}: the schema asks for {', '.join(sorted(keys))}, "
                       f"the prefilter doesn't pass it – tiles would be made without it.")

    for promise in sorted(PROMISED - classes):
        bad.append(f"{SCHEMA}: `railway={promise}` isn't in the schema, yet the "
                   f"package promises it.")

    for promise in sorted(PROMISED_AERIAL - aerial):
        bad.append(f"{SCHEMA}: `aerialway={promise}` isn't in the schema, yet the "
                   f"package promises it.")
    for key in sorted(STATES - all_keys):
        bad.append(f"{SCHEMA}: aerialways with `{key}` aren't in the schema – the "
                   f"state would be lost.")
    for key in sorted((STATES | {"aerialway"}) - passes):
        bad.append(f"{FILTER}: the prefilter doesn't pass `{key}` – aerialways "
                   f"wouldn't be in the tiles.")

    with open(DICTIONARY, encoding="utf-8") as f:
        network = set(json.load(f)["network"]["railway"])
    for cls in sorted(network - classes):
        bad.append(f"{DICTIONARY}: routing runs on `railway={cls}`, which the map "
                   f"doesn't draw – a route would run off the drawing.")

    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    if "rail-routing-tags.json" not in build:
        bad.append(f"{BUILD}: the rail network isn't built with its own dictionary – "
                   f"with the road one it would hold not a single line.")
    if " -R" in build or "--omit-referenced" in build:
        bad.append(f"{BUILD}: `-R` drops relation members – station areas vanish.")
    if "signs.mjs" not in build:
        bad.append(f"{BUILD}: country signs aren't baked – the app would draw the defaults.")
    with open(os.path.join(_WORKERS, "data", "packages.json"), encoding="utf-8") as f:
        rail = [p for p in json.load(f)["packages"] if p["key"] == "railways"]
    if not rail or "rail_signs" not in (rail[0].get("manifest") or []):
        bad.append("workers/data/packages.json: `railways` doesn't carry `rail_signs` – "
                   "the signs wouldn't reach the package.")

    for b in bad:
        print(f"::error::{b}")
    if not bad:
        print(f"rail ✓ ({len(blocks)} blocks, {len(classes)} classes, "
              f"{len(aerial)} aerialway kinds, network of {len(network)} classes)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
