#!/usr/bin/env python3
"""Transport network: the filter lets through what the schema wants, and the package carries it."""
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "transport", "transport.yml")
FILTER = os.path.join(_WORKERS, "transport", "filter.txt")
PACKAGES = os.path.join(_WORKERS, "data", "packages.json")

# transport families the layer PROMISES
FAMILIES = {
    "highway": "roads (from motorways to steps)",
    "route": "ferries",
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

# classes the layer promises
PASSABLE = {
    "highway": {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
        "tertiary_link", "unclassified", "residential", "living_street",
        "pedestrian", "road", "busway", "bus_guideway", "escape", "raceway",
        "track", "path", "footway", "cycleway", "bridleway", "steps",
        "corridor", "via_ferrata", "elevator", "ladder", "service",
    },
    "route": {"ferry"},
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


def main():
    for path in (SCHEMA, FILTER, PACKAGES):
        if not os.path.exists(path):
            print(f"::error::{path} doesn't exist.")
            return 1

    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    layers = schema.get("layers") or []
    blocks = [b for v in layers for b in (v.get("features") or [])]
    if not blocks:
        err(f"{SCHEMA}: the schema has no block – the layer would be empty.")
        return done()

    # 1. the prefilter lets through what the schema wants
    passes = filter_keys(FILTER)
    wants = set()
    for b in blocks:
        wants |= set((b.get("include_when") or {}).keys())
    missing = sorted(wants - passes)
    if missing:
        err(f"{FILTER}: the schema asks for {', '.join(missing)}, but the prefilter "
            f"doesn't let it through (it knows {', '.join(sorted(passes))}). Planetiler "
            f"would get a PBF without that tag – tiles made, run green and that "
            f"part of the network simply not in them.")

    # 2. all three transport families are in the network
    for key, what in FAMILIES.items():
        if key not in wants:
            err(f"{SCHEMA}: the network lacks {what} (`{key}`). The layer promises "
                f"“everything one can travel on” – the package would weigh less and "
                f"nobody would learn a whole means of transport is missing.")

    # 3. no railways in the network
    if RAILWAY in wants or RAILWAY in passes:
        err(f"{SCHEMA}, {FILTER}: roads contain `railway`. Railways are the "
            f"`railways` package – in `roads` they'd be there twice.")

    # 4. promised classes really are in the schema
    in_schema = {}
    for b in blocks:
        for key, values in (b.get("include_when") or {}).items():
            if not isinstance(values, list):
                values = [values]
            in_schema.setdefault(key, set()).update(map(str, values))
    for key, promised in PASSABLE.items():
        missing = sorted(promised - in_schema.get(key, set()))
        if missing:
            err(f"{SCHEMA}: the network lacks `{key}=" + ", ".join(missing) +
                "`. `include_when` is a whitelist, so that class never reaches "
                "the tiles – the filter passes it, the schema drops it, the "
                "package is a bit smaller and the run green.")

    # 5. road restrictions are network attributes, and strings
    tag_mappings = schema.get("tag_mappings") or {}
    for i, b in enumerate(blocks, start=1):
        # road blocks only – no `maxheight` on an aerialway or ferry
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
        if key in tag_mappings:
            err(f"{SCHEMA}: `{key}` is in `tag_mappings` as "
                f"`{tag_mappings[key]}`. The OSM value carries a unit "
                f"(`3.8 m`, `12'6\"`, `50 mph`) and Planetiler takes the leading "
                f"number and drops the rest – 12'6\" becomes 12 m without a "
                f"failure. Keep it a string.")

    # 6. `class` and `family` come from what the block matched
    network = [b for v in layers if v.get("id") == "transport"
               for b in (v.get("features") or [])]
    for i, b in enumerate(network, start=1):
        attrs = {a.get("key"): a for a in (b.get("attributes") or [])
                 if isinstance(a, dict)}
        for key, kind in (("class", "match_value"), ("family", "match_key")):
            a = attrs.get(key)
            if a is None:
                err(f"{SCHEMA}: block {i} doesn't give `{key}`. Without it the "
                    f"network can't say what the line is.")
            elif a.get("type") != kind:
                err(f"{SCHEMA}: block {i} has `{key}` other than `type: {kind}` – "
                    f"written by hand it's a second copy of the class list in "
                    f"`include_when` and parts with it at the first added class.")

    # 7. addresses carry street and number, or nothing can be searched
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

    # 8. the layer really gets into package `roads` (`packaging.py` checks the ZIPs)
    with open(PACKAGES, encoding="utf-8") as f:
        packages = {p["key"]: p for p in json.load(f).get("packages") or []}
    roads = packages.get("roads") or {}
    if "transport" not in (roads.get("manifest") or []) or \
            "-transport.pmtiles" not in (roads.get("suffixes") or []):
        err(f"{PACKAGES}: package `roads` doesn't take the road network (`transport` "
            f"in `manifest`, `-transport.pmtiles` in `suffixes`). The layer would be "
            f"built and never packed – promising a network and empty.")
    return done()


def done():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in the transport network.")
        return 1
    print("Transport network: the prefilter passes what the schema wants, roads, "
          "ferries and aerialways are in, every promised class is in the schema, "
          "no railways, road restrictions are in and stayed strings, `class` and "
          "`family` come from what the block matched, addresses carry street and "
          "number, and the `roads` package really carries it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
