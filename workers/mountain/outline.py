#!/usr/bin/env python3
"""A range's outline: its OSM areas and its box, within its height model's coverage.

    python3 workers/mountain/outline.py --mountain=vysoke_tatry
    python3 workers/mountain/outline.py --all

A range wholly inside its model and naming no areas keeps its box: no file is written.
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(os.path.dirname(_HERE), "data")
OUTLINES = os.path.join(_DATA, "outlines")
LOOKUP = "https://nominatim.openstreetmap.org/lookup"
# a range is built from DMR 5.0, as `mountain.yml` asks for it
MODEL = "dmr5"
# a park's scattered plots are no part of the range
MIN_KM2 = 1.0
# ~11 m, finer than the borders are drawn
TOLERANCE = 0.0001
# a cut losing less than this of the box is the box
WHOLE = 0.9999


def registry(name):
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def path_for(key):
    return os.path.join(OUTLINES, f"{key}.geojson")


def fetch(relation):
    """An OSM relation's area as GeoJSON, from Nominatim."""
    query = urllib.parse.urlencode({"osm_ids": f"R{relation}", "format": "json",
                                    "polygon_geojson": 1, "polygon_threshold": TOLERANCE})
    req = urllib.request.Request(f"{LOOKUP}?{query}",
                                 headers={"User-Agent": "maptiles outline (skifahrer/maptiles)"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        found = json.load(resp)
    # Nominatim's usage policy: one request a second
    time.sleep(1.1)
    if not found or "geojson" not in found[0]:
        raise SystemExit(f"::error::OSM relation {relation} has no area in Nominatim.")
    return found[0]["geojson"]


def km2(geom):
    lat = (geom.bounds[1] + geom.bounds[3]) / 2
    return geom.area * 111.32 * math.cos(math.radians(lat)) * 110.54


def outline(areas, bbox, relations, coverage=None, model=MODEL):
    """The areas' union (or the box) inside `bbox` and `coverage`; None when that is the box."""
    from shapely.geometry import box, mapping, shape  # noqa: PLC0415
    from shapely.ops import unary_union                # noqa: PLC0415

    frame = box(*bbox)
    cut = unary_union([shape(a) for a in areas]).intersection(frame) if areas else frame
    if coverage is not None:
        cut = cut.intersection(shape(coverage))
    parts = [p for p in getattr(cut, "geoms", [cut]) if p.geom_type == "Polygon" and km2(p) >= MIN_KM2]
    if not parts:
        raise SystemExit(f"::error::Nothing of {relations or 'the box'} {bbox} lies inside "
                         f"{model}'s coverage.")
    whole = unary_union(parts)
    if not areas and whole.area >= WHOLE * frame.area:
        return None
    shaped = whole.simplify(TOLERANCE, preserve_topology=True)
    geom = json.loads(json.dumps(mapping(shaped)), parse_float=lambda v: round(float(v), 6))
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"osm_relations": relations, "bbox": bbox, "model": model},
         "geometry": geom}]}


def write(key, data):
    """The outline file, or none for a range that keeps its box."""
    path = path_for(key)
    if data is None:
        if os.path.exists(path):
            os.remove(path)
        print(f"{key}: its box, wholly inside {MODEL}")
        return
    os.makedirs(OUTLINES, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    geom = data["features"][0]["geometry"]
    rings = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    print(f"{path}: {geom['type']}, {sum(len(r) for poly in rings for r in poly)} points")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mountain", default="")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    mountains, areas = registry("mountains.json"), registry("areas.json")
    keys = sorted(mountains) if args.all else [args.mountain]
    if not all(k in mountains for k in keys):
        raise SystemExit(f"::error::Name a range of mountains.json, or --all: {', '.join(sorted(mountains))}.")
    covered = registry("dem-sources.json")[MODEL].get("coverage_osm")
    coverage = fetch(covered) if covered else None
    for key in keys:
        relations = [int(r) for r in mountains[key].get("outline") or []]
        bbox = [float(v) for v in areas[mountains[key]["area"]]["bbox"]]
        write(key, outline([fetch(r) for r in relations], bbox, relations, coverage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
