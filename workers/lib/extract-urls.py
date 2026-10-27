#!/usr/bin/env python3
"""The OSM extracts a job downloads, one a line, for the `extracts` action."""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OSMFR = "https://download.openstreetmap.fr/extracts"


def read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def region(key, regions, base=OSMFR):
    """A region's parent, or the country itself; its slugs are one extract's names."""
    osmfr = (regions.get(key) or {}).get("osmfr") or {}
    source = (regions.get(osmfr.get("parent")) or {}).get("osmfr") or {} if osmfr.get("parent") else osmfr
    if not source.get("dir") or not source.get("slugs"):
        return []
    return [" ".join(f"{base}/{source['dir']}/{slug}.osm.pbf" for slug in source["slugs"])]


def routing(area, areas, base=OSMFR):
    return [f"{base}/{p}-latest.osm.pbf" for p in (areas.get(area) or {}).get("pbf", [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="")
    ap.add_argument("--routing-area", default="")
    ap.add_argument("--each", default="", help="whole URLs, one extract each")
    ap.add_argument("--base", default=os.environ.get("OSMFR_BASE") or OSMFR)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.region:
        lines = region(args.region, read("regions.json"), args.base)
    elif args.routing_area:
        lines = routing(args.routing_area, read("routing-areas.json").get("areas") or {}, args.base)
    else:
        lines = args.each.split()
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write("urls<<URLS\n" + "".join(f"{line}\n" for line in lines) + "URLS\n")
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
