#!/usr/bin/env python3
"""Resolve the input `area` to bbox, key and name – in one place, always within the region.

The input is a range from `workers/data/areas.json`, a bbox `W,S,E,N`, or empty
(the whole region). `--test-km2` cuts a small square around the centre; its key
gets `_test4`, so a test never lands in a real run's cache or asset.

    python3 workers/plan/area.py --region-bbox=W,S,E,N --area=vysoke_tatry
"""
import argparse
import hashlib
import json
import math
import re
import sys

# a degree of longitude times the cosine of latitude
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# terrain computed past the region border – 0 since the outline comes from OSM;
# kept for `pad_bbox` and because stored layer names carry the number
BORDER_BUFFER_M = 0


def bbox_km2(w, s, e, n):
    return ((e - w) * M_PER_DEG_LON * math.cos(math.radians((s + n) / 2))
            * (n - s) * M_PER_DEG_LAT) / 1e6


def pad_bbox(bbox, meters):
    """The rectangle grown by `meters` on each side (degrees by latitude)."""
    w, s, e, n = bbox
    dlat = meters / M_PER_DEG_LAT
    dlon = meters / (M_PER_DEG_LON * math.cos(math.radians((s + n) / 2)))
    return [w - dlon, s - dlat, e + dlon, n + dlat]


def test_square(bbox, km2, at=""):
    """A small square of ~`km2` inside `bbox`, moved inward rather than clipped."""
    w, s, e, n = bbox
    clon = (w + e) / 2.0
    clat = (s + n) / 2.0
    if at.strip():
        parts = [float(v) for v in at.split(",")]
        if len(parts) != 2:
            raise ValueError(f"test_at must be `lon,lat`, not “{at}”")
        clon, clat = parts

    side_m = math.sqrt(km2 * 1e6)
    dlat = side_m / M_PER_DEG_LAT / 2.0
    dlon = side_m / (M_PER_DEG_LON * math.cos(math.radians(clat))) / 2.0

    # a square bigger than the cut-out itself makes no sense
    if 2 * dlon >= (e - w) or 2 * dlat >= (n - s):
        return [w, s, e, n]

    clon = min(max(clon, w + dlon), e - dlon)
    clat = min(max(clat, s + dlat), n - dlat)
    return [clon - dlon, clat - dlat, clon + dlon, clat + dlat]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region-bbox", required=True)
    ap.add_argument("--area", default="")
    ap.add_argument("--areas", default="workers/data/areas.json")
    ap.add_argument("--test-km2", type=float, default=0.0,
                    help="test mode: cut a square of about this many km² "
                         "around the centre of the cut-out (0 = off)")
    ap.add_argument("--test-at", default="",
                    help="centre of the test square as `lon,lat` "
                         "(empty = centre of the cut-out)")
    ap.add_argument("--out", default="", help="where to write (default stdout)")
    args = ap.parse_args()

    # the window of the DEM layers; `-cutline` cuts the outline out of it
    region = pad_bbox([float(v) for v in args.region_bbox.split(",")],
                      BORDER_BUFFER_M)
    raw = (args.area or "").strip()
    # a form choice can't be empty, so “the whole region” is a word; the former one too
    if raw in ("whole_region", "cely_region"):
        raw = ""

    if not raw:
        key, name, bbox = "whole", "whole region", region
    elif "," in raw:
        # a hash in the key: two own cut-outs under one name overwrote each other
        h = hashlib.sha1(raw.encode()).hexdigest()[:6]
        key, name = f"cutout_{h}", f"own cut-out {raw}"
        bbox = [float(v) for v in raw.split(",")]
    else:
        areas = json.load(open(args.areas))
        if raw not in areas or raw.startswith("_"):
            known = ", ".join(k for k in areas if not k.startswith("_"))
            print(f"::error::Unknown cut-out '{raw}'. Known cut-outs "
                  f"({args.areas}): {known}. Or give a bbox W,S,E,N.",
                  file=sys.stderr)
            return 1
        key = re.sub(r"[^a-zA-Z0-9]", "_", raw)
        name = areas[raw]["name"]
        bbox = areas[raw]["bbox"]

    # the intersection with the region – outside it there is neither data nor map
    w, s = max(region[0], bbox[0]), max(region[1], bbox[1])
    e, n = min(region[2], bbox[2]), min(region[3], bbox[3])
    if e <= w or n <= s:
        print(f"::error::Cut-out '{raw}' doesn't lie in the region ({args.region_bbox}) – "
              f"they don't overlap. Pick another region or cut-out.",
              file=sys.stderr)
        return 1

    out = []
    if args.test_km2 > 0:
        # the whole cut-out goes out too: the “where it is” picture needs the surroundings
        out.append(f"full_bbox={w},{s},{e},{n}")
        out.append(f"full_km2={bbox_km2(w, s, e, n):.0f}")
        try:
            w, s, e, n = test_square([w, s, e, n], args.test_km2, args.test_at)
        except ValueError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        # into the key, not only the name; `whole` is a sentinel, no area name
        if key != "whole":
            key = f"{key}_test{args.test_km2:g}"
            if args.test_at.strip():
                key += "_" + hashlib.sha1(args.test_at.encode()).hexdigest()[:4]
        name = f"{name} – test {args.test_km2:g} km²"
        out.append("test=1")
        out.append(f"test_km2={args.test_km2:g}")

    km2 = bbox_km2(w, s, e, n)
    out += [f"key={key}", f"name={name}", f"bbox={w},{s},{e},{n}",
            f"km2={km2:.0f}", f"cells_1m={km2 * 1e6:.0f}",
            f"center={(w + e) / 2:.5f},{(s + n) / 2:.5f}"]
    text = "\n".join(out) + "\n"
    if args.out:
        with open(args.out, "a") as f:
            f.write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
