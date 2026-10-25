#!/usr/bin/env python3
"""Resolve a mountain package to its country, cut-out, keys and outline (`data/region.geojson`).

    python3 workers/mountain/plan.py --mountain=vysoke_tatry --out=$GITHUB_OUTPUT
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

sys.path.insert(0, os.path.join(_WORKERS, "plan"))
import area  # noqa: E402

OSMFR = "https://download.openstreetmap.fr/extracts"


def registry(name):
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def bbox_key(bbox):
    """The bbox as a cache key spells it: `_` for `,.-`."""
    text = ",".join(f"{v:g}" for v in bbox)
    return "".join("_" if ch in ",.-" else ch for ch in text)


def outline(bbox):
    """The cut-out as the region polygon the DEM layers clip to."""
    w, s, e, n = bbox
    ring = [[w, s], [e, s], [e, n], [w, n], [w, s]]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {},
         "geometry": {"type": "Polygon", "coordinates": [ring]}}]}


def osm_urls(entry, country):
    """Every extract the range's OSM layers are cut from; its country's when it names none."""
    paths = entry.get("osm") or [f"{country['osmfr']['dir']}/{country['osmfr']['slugs'][0]}"]
    return [f"{OSMFR}/{p}.osm.pbf" for p in paths]


def poly(bbox):
    """The cut-out as an osmium/Planetiler `.poly`, for the OSM layers."""
    ring = outline(bbox)["features"][0]["geometry"]["coordinates"][0]
    points = "".join(f"   {x:.7f} {y:.7f}\n" for x, y in ring)
    return f"mountain\n1\n{points}END\nEND\n"


def plan(key, test_km2=0.0, test_at="", mountains=None, areas=None, regions=None):
    mountains = registry("mountains.json") if mountains is None else mountains
    areas = registry("areas.json") if areas is None else areas
    regions = registry("regions.json") if regions is None else regions
    if key not in mountains:
        raise SystemExit(f"::error::Unknown mountain “{key}”. Known "
                         f"(workers/data/mountains.json): {', '.join(sorted(mountains))}.")
    entry = mountains[key]
    country, cut = entry["country"], entry["area"]
    if country not in regions:
        raise SystemExit(f"::error::Mountain {key}: country “{country}” isn't in regions.json.")
    if cut not in areas:
        raise SystemExit(f"::error::Mountain {key}: cut-out “{cut}” isn't in areas.json.")
    bbox = [float(v) for v in areas[cut]["bbox"]]
    name = areas[cut]["name"]
    region_key, area_key = key, cut
    if test_km2 > 0:
        bbox = area.test_square(bbox, test_km2, test_at)
        # a test never shares a cache, store asset or catalog node with the real one
        region_key, area_key = f"{key}_test{test_km2:g}", f"{cut}_test{test_km2:g}"
        name = f"{name} – test {test_km2:g} km²"
    return {
        "key": region_key,
        "mountain": key,
        "country": country,
        "area": cut,
        "area_key": area_key,
        "name": name,
        "bbox": ",".join(f"{v:g}" for v in bbox),
        "bboxkey": bbox_key(bbox),
        "km2": f"{area.bbox_km2(*bbox):.0f}",
        "osm": " ".join(osm_urls(entry, regions[country])),
        "countries": ",".join(entry.get("countries") or []),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mountain", required=True)
    ap.add_argument("--test-km2", type=float, default=0.0)
    ap.add_argument("--test-at", default="")
    ap.add_argument("--geojson", default="data/region.geojson")
    ap.add_argument("--poly", default="data/region.poly")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    got = plan(args.mountain, args.test_km2, args.test_at)
    os.makedirs(os.path.dirname(args.geojson) or ".", exist_ok=True)
    bbox = [float(v) for v in got["bbox"].split(",")]
    with open(args.geojson, "w") as f:
        json.dump(outline(bbox), f)
    with open(args.poly, "w") as f:
        f.write(poly(bbox))
    text = "".join(f"{k}={v}\n" for k, v in got.items())
    sys.stdout.write(text)
    if args.out:
        with open(args.out, "a") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
