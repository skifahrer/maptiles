#!/usr/bin/env python3
"""Roads and paths: the filter lets through what both schemas want, and each package carries its own."""
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "transport", "transport.yml")
PATHS = os.path.join(_WORKERS, "transport", "paths.yml")
FILTER = os.path.join(_WORKERS, "transport", "filter.txt")
PACKAGES = os.path.join(_WORKERS, "data", "packages.json")

# families each layer PROMISES
FAMILIES = {
    "highway": "roads (from motorways to tracks)",
    "route": "ferries",
}
PATH_FAMILIES = {
    "highway": "footways, paths and steps",
    "aerialway": "aerialways and lifts",
}

# road restrictions, attributes of this network → what is lost without them
RESTRICTIONS = {
    "maxheight": "underpass height",
    "maxheight_physical": "measured underpass height when the sign is missing",
    "maxwidth": "width",
    "maxweight": "weight",
    "maxspeed": "speed limit",
    "lanes": "number of lanes",
    "width": "road width",
    "incline": "incline",
}

# these carry a unit (`3.8 m`, `12'6"`, `50 mph`) that a number would silently drop
STRINGS = {"maxheight", "maxheight_physical", "maxwidth", "maxweight",
           "maxspeed", "width", "incline"}

# without these an address can't be found or shown
ADDRESS = {"addr:housenumber", "addr:conscriptionnumber", "addr:street",
           "addr:place", "addr:city"}

# railways are the `railways` package, in roads they'd be twice
RAILWAY = "railway"

# classes each layer promises: a car fits a road, not a path
PASSABLE = {
    "highway": {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
        "tertiary_link", "unclassified", "residential", "living_street",
        "road", "busway", "bus_guideway", "escape", "raceway", "track",
        "service",
    },
    "route": {"ferry"},
}
WALKABLE = {
    "highway": {
        "pedestrian", "path", "footway", "cycleway", "bridleway", "steps",
        "corridor", "via_ferrata", "elevator", "ladder",
    },
    "aerialway": {
        "cable_car", "gondola", "mixed_lift", "chair_lift", "drag_lift",
        "t-bar", "j-bar", "platter", "rope_tow", "magic_carpet", "zip_line",
        "goods",
    },
}

bad = []


def err(msg):
    bad.append(msg)


def filter_keys(path):
    """Bare keys from `osmium tags-filter --expressions` (without `w/`, `nwr/`)."""
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


def blocks_of(schema):
    return [b for v in schema.get("layers") or [] for b in (v.get("features") or [])]


def classes(blocks):
    """`{key: {values}}` the blocks' `include_when` lets in."""
    out = {}
    for b in blocks:
        for key, values in (b.get("include_when") or {}).items():
            if not isinstance(values, list):
                values = [values]
            out.setdefault(key, set()).update(map(str, values))
    return out


def check_layer(path, schema, layer_id, families, promised, what):
    """Families and promised classes are in, `class` and `family` come from the match."""
    blocks = [b for v in schema.get("layers") or [] if v.get("id") == layer_id
              for b in (v.get("features") or [])]
    if not blocks:
        err(f"{path}: the `{layer_id}` layer has no block – {what} would be empty.")
        return
    in_schema = classes(blocks)
    for key, name in families.items():
        if key not in in_schema:
            err(f"{path}: {what} lack {name} (`{key}`) – the package would weigh less "
                f"and nobody would learn a whole means of travel is missing.")
    for key, want in promised.items():
        missing = sorted(want - in_schema.get(key, set()))
        if missing:
            err(f"{path}: {what} lack `{key}=" + ", ".join(missing) +
                "`. `include_when` is a whitelist, so that class never reaches "
                "the tiles – the filter passes it, the schema drops it, the "
                "package is a bit smaller and the run green.")
    for i, b in enumerate(blocks, start=1):
        attrs = {a.get("key"): a for a in (b.get("attributes") or [])
                 if isinstance(a, dict)}
        for key, kind in (("class", "match_value"), ("family", "match_key")):
            a = attrs.get(key)
            if a is None:
                err(f"{path}: block {i} doesn't give `{key}`. Without it the "
                    f"layer can't say what the line is.")
            elif a.get("type") != kind:
                err(f"{path}: block {i} has `{key}` other than `type: {kind}` – "
                    f"written by hand it's a second copy of the class list in "
                    f"`include_when` and parts with it at the first added class.")


def main():
    for path in (SCHEMA, PATHS, FILTER, PACKAGES):
        if not os.path.exists(path):
            print(f"::error::{path} doesn't exist.")
            return 1

    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    with open(PATHS, encoding="utf-8") as f:
        paths = yaml.safe_load(f)
    layers = schema.get("layers") or []
    blocks = blocks_of(schema)
    if not blocks:
        err(f"{SCHEMA}: the schema has no block – the layer would be empty.")
        return done()

    # 1. the prefilter lets through what both schemas want
    passes = filter_keys(FILTER)
    wants = set()
    for b in blocks + blocks_of(paths):
        wants |= set((b.get("include_when") or {}).keys())
    missing = sorted(wants - passes)
    if missing:
        err(f"{FILTER}: the schemas ask for {', '.join(missing)}, but the prefilter "
            f"doesn't let it through (it knows {', '.join(sorted(passes))}). Planetiler "
            f"would get a PBF without that tag – tiles made, run green and that "
            f"part of the network simply not in them.")

    # 2. roads hold what a car drives, paths the rest – each way in one package only
    check_layer(SCHEMA, schema, "transport", FAMILIES, PASSABLE, "roads")
    check_layer(PATHS, paths, "paths", PATH_FAMILIES, WALKABLE, "paths")
    road_classes, path_classes = classes(blocks), classes(blocks_of(paths))
    for key in sorted(set(road_classes) & set(path_classes)):
        both = sorted(road_classes[key] & path_classes[key])
        if both:
            err(f"{SCHEMA}, {PATHS}: `{key}=" + ", ".join(both) + "` is a road AND "
                "a path – downloaded twice, and switching one package off leaves it.")

    # 3. no railways in either
    if RAILWAY in wants or RAILWAY in passes:
        err(f"{SCHEMA}, {PATHS}, {FILTER}: roads or paths contain `railway`. Railways "
            f"are the `railways` package – here they'd be there twice.")

    # 4. road restrictions are network attributes, and strings
    tag_mappings = schema.get("tag_mappings") or {}
    for i, b in enumerate(blocks, start=1):
        # road blocks only – no `maxheight` on a ferry
        if "highway" not in (b.get("include_when") or {}):
            continue
        attrs = {a.get("key") for a in (b.get("attributes") or [])
                 if isinstance(a, dict)}
        missing = sorted(set(RESTRICTIONS) - attrs)
        if missing:
            err(f"{SCHEMA}: road block {i} doesn't carry "
                f"{', '.join(f'`{k}` ({RESTRICTIONS[k]})' for k in missing)}. "
                f"Road restrictions have no layer of their own any more – drop "
                f"them here and they are nowhere, with the same drawing and a green run.")
    for key in sorted(STRINGS):
        for path, mappings in ((SCHEMA, tag_mappings), (PATHS, paths.get("tag_mappings") or {})):
            if key in mappings:
                err(f"{path}: `{key}` is in `tag_mappings` as "
                    f"`{mappings[key]}`. The OSM value carries a unit "
                    f"(`3.8 m`, `12'6\"`, `50 mph`) and Planetiler takes the leading "
                    f"number and drops the rest – 12'6\" becomes 12 m without a "
                    f"failure. Keep it a string.")

    # 5. addresses carry street and number, or nothing can be searched
    addresses = [b for v in layers if v.get("id") == "addresses"
                 for b in (v.get("features") or [])]
    if not addresses:
        err(f"{SCHEMA}: the `addresses` layer is missing – the `roads` package "
            f"couldn't find a street with a house number.")
    for i, b in enumerate(addresses, start=1):
        attrs = {a.get("key") for a in (b.get("attributes") or [])
                 if isinstance(a, dict)}
        missing = sorted(ADDRESS - attrs)
        if missing:
            err(f"{SCHEMA}: address block {i} doesn't carry {', '.join(missing)} – "
                f"search would find a number without a street or a street without one.")

    # 6. each layer really gets into its package (`packaging.py` checks the ZIPs)
    with open(PACKAGES, encoding="utf-8") as f:
        packages = {p["key"]: p for p in json.load(f).get("packages") or []}
    for key, stem, what in (("roads", "transport", "roads"), ("paths", "paths", "paths")):
        p = packages.get(key) or {}
        if stem not in (p.get("manifest") or []) or \
                f"-{stem}.pmtiles" not in (p.get("suffixes") or []):
            err(f"{PACKAGES}: package `{key}` doesn't take the {what} (`{stem}` in "
                f"`manifest`, `-{stem}.pmtiles` in `suffixes`). The layer would be "
                f"built and never packed – promising a network and empty.")
    return done()


def done():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in roads and paths.")
        return 1
    print("Roads and paths: the prefilter passes what both schemas want, roads "
          "hold what a car drives and paths the rest, no way is in both, no "
          "railways, road restrictions are in and stayed strings, `class` and "
          "`family` come from what the block matched, addresses carry street and "
          "number, and `roads` and `paths` really carry their layers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
