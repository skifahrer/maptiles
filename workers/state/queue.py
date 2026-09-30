#!/usr/bin/env python3
"""Region order for “Build map state” – which regions a country has, in registry order.

    python3 workers/state/queue.py --regions=slovensko   # regions, one per line
    python3 workers/state/queue.py --countries           # what can be given
"""
import argparse
import json
import os
import sys

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data")
REGIONS = os.path.join(_DATA, "regions.json")
# the same number decides whether a package gets a region folder on Drive
REGION_LEVEL = 4


def read():
    with open(REGIONS) as f:
        return json.load(f)


def regions_of(regions, country):
    """Region keys of the country in registry order (west to east)."""
    return [k for k, v in regions.items()
            if v.get("country") == country
            and v.get("admin_level") == REGION_LEVEL]


def countries(regions):
    """Countries that HAVE regions – a country without any is no choice."""
    return [k for k, v in regions.items()
            if v.get("admin_level") != REGION_LEVEL and regions_of(regions, k)]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", default="", help="a country – list its regions")
    ap.add_argument("--countries", action="store_true",
                    help="list countries that have regions")
    args = ap.parse_args()

    regions = read()
    if args.countries:
        print("\n".join(countries(regions)))
        return
    if not args.regions:
        ap.error("give --regions=<country> or --countries")
    found = regions_of(regions, args.regions)
    if not found:
        # a hard error: empty output would end the batch green with nothing built
        print(f"::error::Country “{args.regions}” has no region in {REGIONS} "
              f"(`admin_level: {REGION_LEVEL}`). Possible: "
              f"{', '.join(countries(regions)) or '(none)'}.", file=sys.stderr)
        sys.exit(1)
    print("\n".join(found))


if __name__ == "__main__":
    main()
