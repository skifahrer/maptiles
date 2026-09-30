#!/usr/bin/env python3
"""Package list access – the one answer to "what gets published" (`workers/data/packages.json`)."""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(os.path.dirname(_HERE), "data")
REGISTRY = os.path.join(_DATA, "packages.json")
CREDITS = os.path.join(_DATA, "credits.json")
# maps are built from DMR 5.0 unless the region names another model
DEFAULT_MODEL = "dmr5"

_CACHE = None


def _read():
    global _CACHE
    if _CACHE is None:
        with open(REGISTRY, encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


def listing():
    """Packages in file order – the order people see them in."""
    return list(_read().get("packages") or [])


def keys():
    return [p["key"] for p in listing()]


def package(key):
    for p in listing():
        if p["key"] == key:
            return p
    raise SystemExit(f"::error::Package `{key}` is not in {os.path.relpath(REGISTRY)}. "
                     f"It has: {', '.join(keys())}.")


def retired():
    """Stems nobody builds any more, former names too – their old file on Drive is deleted."""
    return tuple(s for r in _read().get("retired") or ()
                 for s in [r["key"], *(r.get("legacy") or ())])


def legacy():
    """`{former key: key}` for packages renamed since, retired ones too."""
    every = listing() + list(_read().get("retired") or ())
    return {old: p["key"] for p in every for old in p.get("legacy") or ()}


def regenerable():
    """`{regenerate key: package}` – what builds without the whole map."""
    return {p["regenerate"]: p for p in listing() if p.get("regenerate")}


def for_catalog():
    """Name, mark and line of every package for `maps.json`."""
    return {p["key"]: {"app": p["app"], "symbol": p["symbol"],
                       "detail": p["app_detail"], "description": p["description"],
                       **({"part_of": p["part_of"]} if p.get("part_of") else {})}
            for p in listing()}


def subpackages(key):
    """Keys of packages that are part of `key`, in file order."""
    return [p["key"] for p in listing() if p.get("part_of") == key]


def credits(key, models=None):
    """Data authors of a package; `models` = `{contours|rocks|shading: model}` of the region."""
    with open(CREDITS, encoding="utf-8") as f:
        sources = json.load(f)
    models = models or {}
    out = []
    for source in package(key).get("sources") or ():
        if source.startswith("dem:"):
            source = models.get(source[4:])
            if source not in sources:
                source = DEFAULT_MODEL
        credit = sources.get(source)
        if credit and credit not in out:
            out.append(dict(credit))
    return out


def main():
    """`python3 workers/deploy/packages.py [--keys|--regenerate]` – for a look."""
    if "--keys" in sys.argv:
        print("\n".join(keys()))
    elif "--regenerate" in sys.argv:
        print("\n".join(regenerable()))
    else:
        for p in listing():
            print(f"{p['key']:<18} {p['app']:<22} {p['symbol']:<32} {p['description']}")


if __name__ == "__main__":
    main()
