#!/usr/bin/env python3
"""A range's outline from OSM areas cut to its box: `workers/data/outlines/<range>.geojson`.

    python3 workers/mountain/outline.py --mountain=vysoke_tatry
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
# a park's scattered plots are no part of the range
MIN_KM2 = 1.0
# ~11 m, finer than the borders are drawn
TOLERANCE = 0.0001


def registry(name):
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def path_for(key):
    return os.path.join(OUTLINES, f"{key}.geojson")


def fetch(relation):
    """An OSM relation's area as GeoJSON, from Nominatim."""
    query = urllib.parse.urlencode({"osm_ids": f"R{relation}", "format": "json",
                                    "polygon_geojson": 1})
    req = urllib.request.Request(f"{LOOKUP}?{query}",
                                 headers={"User-Agent": "maptiles outline (skifahrer/maptiles)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        found = json.load(resp)
    if not found or "geojson" not in found[0]:
        raise SystemExit(f"::error::OSM relation {relation} has no area in Nominatim.")
    return found[0]["geojson"]


def km2(geom):
    lat = (geom.bounds[1] + geom.bounds[3]) / 2
    return geom.area * 111.32 * math.cos(math.radians(lat)) * 110.54


def outline(areas, bbox, relations):
    """The areas' union inside `bbox`, small parts dropped, simplified, as GeoJSON."""
    from shapely.geometry import box, mapping, shape  # noqa: PLC0415
    from shapely.ops import unary_union                # noqa: PLC0415

    cut = unary_union([shape(a) for a in areas]).intersection(box(*bbox))
    parts = [p for p in getattr(cut, "geoms", [cut]) if p.geom_type == "Polygon" and km2(p) >= MIN_KM2]
    if not parts:
        raise SystemExit(f"::error::OSM relations {relations} have no area of {MIN_KM2:g} km² "
                         f"inside the box {bbox}.")
    shaped = unary_union(parts).simplify(TOLERANCE, preserve_topology=True)
    geom = json.loads(json.dumps(mapping(shaped)), parse_float=lambda v: round(float(v), 6))
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"osm_relations": relations, "bbox": bbox},
         "geometry": geom}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mountain", required=True)
    args = ap.parse_args()
    entry = registry("mountains.json").get(args.mountain)
    if not entry or not entry.get("outline"):
        raise SystemExit(f"::error::{args.mountain} names no `outline` relations in mountains.json.")
    bbox = [float(v) for v in registry("areas.json")[entry["area"]]["bbox"]]
    relations = [int(r) for r in entry["outline"]]
    areas = []
    for relation in relations:
        areas.append(fetch(relation))
        # Nominatim's usage policy: one request a second
        time.sleep(1.1)
    data = outline(areas, bbox, relations)
    os.makedirs(OUTLINES, exist_ok=True)
    with open(path_for(args.mountain), "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    geom = data["features"][0]["geometry"]
    rings = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    print(f"{path_for(args.mountain)}: {geom['type']}, "
          f"{sum(len(r) for poly in rings for r in poly)} points, OSM {relations}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
