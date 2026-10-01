#!/usr/bin/env python3
"""What can be regenerated across a country – and which workflow does it over a region.

Packages come from `workers/data/packages.json`; this adds form order, a summary
line and the workflow. `workers/lint/regenerate.py` guards the form's `choice`.

    python3 workers/state/jobs.py --list | --workflow=points | --name=points
    python3 workers/state/jobs.py --describe=points | --fields=points
"""
import argparse
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)


def _load(name, path):
    """workers/*.py can't be imported normally because of the dash in their names."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_packages = _load("deploy_packages", os.path.join(_WORKERS, "deploy", "packages.py"))

# `passes`: inputs the target takes from the BATCH FORM, `input: (env var, default)`;
# passed whole every time, or a leg would regenerate with defaults and stay green
TARGETS = {
    "regenerate-region.yml": {
        "name": "Map · Regenerate region layer",
        "passes": {
            # height sources and slope matter only for DEM layers; passed always anyway
            "contour_source": ("CONTOUR_SOURCE", "dmr5"),
            "rock_source": ("ROCK_SOURCE", "dmr5"),
            "shading_source": ("SHADING_SOURCE", "dmr5"),
            "rock_slope": ("ROCK_SLOPE", "50"),
            "test": ("TEST", "false"),
            "options": ("OPTIONS", ""),
        },
    },
}

# form order, cheapest first: OSM layers take minutes, DEM layers hours
COST = {
    # key: (name, what it is)
    "points": ("Points of interest",
               "springs, caves, lookouts, monuments and other point features"),
    "roads": ("Roads & paths",
              "the whole OSM road network with road limits (clearance, weight, "
              "speed) and the routing network the phone routes on"),
    "boundaries": ("Boundaries and area names",
                   "state, region, district and municipality boundaries with their names"),
    "water": ("Water bodies",
              "rivers, streams, lakes, reservoirs and the sea with their names"),
    "railways": ("Railways & cable cars",
                 "every railway and cable car, planned and abandoned too, named "
                 "stations, line signs and the track network for navigation"),
    "settlements": ("Settlements",
                    "every building with floor area, name, kind and address, and place names"),
    "contours": ("Contours", "contour lines from the height model"),
    "rocks": ("Rocks", "rock areas from the model's slope"),
    "terrain": ("Hillshading and 3D terrain",
                "height tiles for hillshading and 3D"),
}


def _build():
    """`{key: {name, description, package, workflow, inputs}}` from the registry and `COST`."""
    registry = _packages.regenerable()
    out = {}
    for key, (name, what) in COST.items():
        p = registry.get(key)
        if not p:
            raise SystemExit(
                f"::error::`{key}` is in COST, but the package registry "
                f"({_packages.REGISTRY}) has no `regenerate` for it – "
                f"the form would offer a choice the packer doesn't know and the run "
                f"would fail on `--only`.")
        out[key] = {
            "name": name,
            "description": f"{what} – package `-{p['key']}.zip`",
            "package": p["key"],
            "workflow": "regenerate-region.yml",
            "inputs": {"what": key},
        }
    return out


JOBS = _build()


def job(key):
    """A registry entry, or a hard stop naming what can be given."""
    if key not in JOBS:
        print(f"::error::What can be regenerated: {', '.join(JOBS)} – “{key}” "
              f"is unknown. The list is in {os.path.relpath(__file__)}.",
              file=sys.stderr)
        sys.exit(1)
    return JOBS[key]


def fields(key, env=None):
    """`-f` fields of a run over one region: {input: value}; the relay adds `region`."""
    env = os.environ if env is None else env
    j = job(key)
    out = dict(j["inputs"])
    for name, (var, default) in TARGETS[j["workflow"]]["passes"].items():
        out[name] = env.get(var) or default
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true",
                    help="keys that can be regenerated")
    ap.add_argument("--workflow", default="", help="workflow over one region")
    ap.add_argument("--name", default="", help="that workflow's name")
    ap.add_argument("--describe", default="", help="what the choice regenerates")
    ap.add_argument("--fields", default="",
                    help="`-f` fields of the run over a region, `key=value` per line")
    args = ap.parse_args()

    if args.list:
        print("\n".join(JOBS))
    elif args.workflow:
        print(job(args.workflow)["workflow"])
    elif args.name:
        print(TARGETS[job(args.name)["workflow"]]["name"])
    elif args.describe:
        j = job(args.describe)
        print(f"{j['name']} – {j['description']}")
    elif args.fields:
        # one per line: a value may hold spaces (`options`)
        for k, v in fields(args.fields).items():
            print(f"{k}={v}")
    else:
        ap.error("give --list, --workflow=, --name=, --describe= or --fields=")


if __name__ == "__main__":
    main()
