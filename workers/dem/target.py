#!/usr/bin/env python3
"""One answer to “which store and which files” – for check-dem and `fetch.sh` alike.

DMR 5.0 has two shapes, decided by the cut-out key alone: contours and rocks
pass `AREA_KEY`, hillshading doesn't (the whole region, where 1 m doesn't exist).

    cut-out key (`area`)   ugkk-<cutout>.tif in dem-ugkk      full 1 m
    no cut-out (`whole`)   N49E019.tif … in dem-dmr5-v2       resampled to 5 m

`sonny` and `dmr35` are always tiles. Output is `key=value` (like GITHUB_OUTPUT):
form, store, assets, mirror, degrees, label.

    python3 workers/dem/target.py --source=dmr5 --bbox=19.9,49.0,20.4,49.3
    python3 workers/dem/target.py --source=dmr5 --area-key=vysoke_tatry
"""
import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # registries (areas, regions, sources)

# a store name can be overridden from the environment, to redirect a build to a test store
ENV_TILES = {"sonny": "DEM_STORE", "sonny1": "SONNY1_STORE",
             "dmr35": "DMR35_STORE", "dmr5": "DMR5_STORE"}
ENV_AREA = {"dmr5": "UGKK_STORE"}

# sources with a cut-out shape too (one full-resolution COG per range)
HAS_AREA_FORM = ("dmr5",)


def tiles_for(bbox):
    """Bbox → names of 1°×1° tiles by their south-west corner (the SRTM convention)."""
    w, s, e, n = bbox
    out = []
    for lat in range(math.floor(s), math.floor(n) + 1):
        for lon in range(math.floor(w), math.floor(e) + 1):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            out.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return out


def degrees_box(bbox):
    """Bbox widened to whole degrees – a tile's name promises its whole degree."""
    w, s, e, n = bbox
    return (math.floor(w), math.floor(s), math.ceil(e), math.ceil(n))


def store_area(key):
    """The cut-out key as stored names spell it (`workers/lib/store-area.sh`)."""
    if key.startswith("cutout_"):
        return "vyrez_" + key[len("cutout_"):]
    return "cely" if key == "whole" else key


def target(source, area_key, bbox, sources_path=None):
    src = (source or "sonny").strip()
    key = (area_key or "whole").strip()
    path = sources_path or os.path.join(_DATA, "dem-sources.json")
    meta = json.load(open(path)).get(src) or {}
    label = meta.get("label", src)

    if src in HAS_AREA_FORM and key and key not in ("whole", "cely"):
        rel = os.environ.get(ENV_AREA.get(src, ""), "") or \
            meta.get("store_area", "dem-ugkk")
        asset = f"ugkk-{store_area(key)}.tif"
        return {
            "form": "area",
            "store": rel,
            "assets": asset,
            "mirror": f"{src}:area:{key}",
            "degrees": "",
            "label": f"{label} – cut-out {key}, full resolution",
        }

    rel = os.environ.get(ENV_TILES.get(src, ""), "") or \
        meta.get("store", "dem-sonny")
    if not bbox:
        # an own region without a bbox: the caller copes with an empty list
        return {"form": "tiles", "store": rel, "assets": "",
                "mirror": f"{src}:tiles", "degrees": "",
                "label": f"{label} – tiles"}
    deg = degrees_box(bbox)
    return {
        "form": "tiles",
        "store": rel,
        "assets": " ".join(f"{t}.tif" for t in tiles_for(bbox)),
        "mirror": f"{src}:tiles:" + ",".join(str(v) for v in deg),
        "degrees": ",".join(str(v) for v in deg),
        "label": f"{label} – tiles",
    }


def parse_bbox(text):
    text = (text or "").strip()
    if not text:
        return None
    vals = [float(v) for v in text.split(",")]
    if len(vals) != 4:
        raise SystemExit(f"::error::a bbox needs 4 numbers W,S,E,N: “{text}”")
    return tuple(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--area-key", default="whole",
                    help="`whole` or empty = no cut-out (the tile shape)")
    ap.add_argument("--bbox", default="", help="W,S,E,N in WGS84")
    ap.add_argument("--sources", default=None)
    ap.add_argument("--out", default="", help="where to write (e.g. GITHUB_OUTPUT)")
    args = ap.parse_args()

    res = target(args.source, args.area_key, parse_bbox(args.bbox), args.sources)
    lines = "".join(f"{k}={v}\n" for k, v in res.items())
    sys.stdout.write(lines)
    if args.out:
        with open(args.out, "a") as f:
            f.write(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
