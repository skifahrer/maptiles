#!/usr/bin/env python3
"""Outline of the downloaded region for the viewer: `data/region.geojson` → `_site/region.geojson`.

Tiles are made on the bbox rectangle, so the style masks everything outside the
region (`outside`) and draws its outline (`outline`) – from the same polygon the
PBF is cut with, never a second one. A run smaller than the region is clipped to
its bbox first (Sutherland–Hodgman).

    python3 workers/deploy/region-mask.py --poly=data/region.geojson \\
        --bbox=19.865,48.745,22.585,49.48 --out=_site/region.geojson
"""
import argparse
import json
import math
import os
import sys

# Web Mercator ends at ±85.0511°, the mask needs no more
LAT_MAX = 85.0511


def rings_from_geojson(path):
    """GeoJSON → `[(ring, is_hole)]`; a ring is a list of `(lon, lat)`."""
    with open(path) as f:
        data = json.load(f)
    feats = (data.get("features") if data.get("type") == "FeatureCollection"
             else [data])
    out = []
    for feat in feats or []:
        geom = feat.get("geometry") if "geometry" in feat else feat
        if not geom:
            continue
        polys = ([geom.get("coordinates")] if geom.get("type") == "Polygon"
                 else geom.get("coordinates") or [])
        for poly in polys:
            for i, ring in enumerate(poly or []):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) >= 3:
                    out.append((pts, i > 0))     # the first ring is the outline
    return out


def clip_ring(ring, bbox):
    """Ring clipped to a rectangle (Sutherland–Hodgman), or `[]`; the map ends on the bbox edge."""
    w, s, e, n = bbox
    edges = (("x>", w), ("x<", e), ("y>", s), ("y<", n))
    pts = list(ring)
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    for side, value in edges:
        if not pts:
            return []

        def inside(p):
            return (p[0] >= value if side == "x>" else
                    p[0] <= value if side == "x<" else
                    p[1] >= value if side == "y>" else
                    p[1] <= value)

        def cross(a, b):
            if side in ("x>", "x<"):
                t = (value - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
                return (value, a[1] + t * (b[1] - a[1]))
            t = (value - a[1]) / (b[1] - a[1]) if b[1] != a[1] else 0.0
            return (a[0] + t * (b[0] - a[0]), value)

        kept = []
        for i, b in enumerate(pts):
            a = pts[i - 1]
            if inside(b):
                if not inside(a):
                    kept.append(cross(a, b))
                kept.append(b)
            elif inside(a):
                kept.append(cross(a, b))
        pts = kept
    return pts if len(pts) >= 3 else []


def close(ring, precision=6):
    """A ring as GeoJSON coordinates – rounded and closed."""
    coords = [[round(x, precision), round(y, precision)] for x, y in ring]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def ring_area_km2(ring):
    """Ring area in km² – a planar approximation, enough for the log."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(y for _, y in ring) / len(ring)
    kx = 111.32 * math.cos(math.radians(lat0))
    ky = 110.57
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(s) / 2.0


def world_ring():
    return [(-180.0, -LAT_MAX), (180.0, -LAT_MAX),
            (180.0, LAT_MAX), (-180.0, LAT_MAX)]


def mask_geojson(outlines, holes):
    """`outside` (one world polygon with the region as holes) and `outline`; enclaves masked too."""
    mask = [[close(world_ring())] + [close(r) for r in outlines]]
    mask += [[close(r)] for r in holes]
    # a `line` layer strokes every ring, so enclaves get an outline as well
    outline = [[close(r)] + [close(h) for h in holes] for r in outlines[:1]]
    outline += [[close(r)] for r in outlines[1:]]
    return {
        "type": "FeatureCollection",
        "_comment": ("Outline of the downloaded region for the viewer (web and iOS): "
                     "`outside` is the area around the region, `outline` its edge. "
                     "Made by workers/deploy/region-mask.py from the polygon the "
                     "PBF is cut with."),
        "features": [
            {"type": "Feature", "properties": {"kind": "outside"},
             "geometry": {"type": "MultiPolygon", "coordinates": mask}},
            {"type": "Feature", "properties": {"kind": "outline"},
             "geometry": {"type": "MultiPolygon", "coordinates": outline}},
        ],
    }


def pad_bbox(bbox, meters):
    """`bbox` grown by `meters` on each side, so the clip keeps `region-poly.py`'s buffer."""
    if not meters:
        return bbox
    w, s, e, n = bbox
    lat0 = max(min((s + n) / 2, LAT_MAX), -LAT_MAX)
    dlat = meters / 110540.0
    dlon = meters / (111320.0 * math.cos(math.radians(lat0)))
    return (w - dlon, s - dlat, e + dlon, n + dlat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poly", default="data/region.geojson",
                    help="region polygon from workers/plan/region-poly.py")
    ap.add_argument("--bbox", default="", help="bbox of the run: west,south,east,north")
    ap.add_argument("--pad-m", type=float, default=0.0,
                    help="metres to grow --bbox by before clipping – the same "
                         "number `region-poly.py` buffered --poly by "
                         "(BORDER_BUFFER_M), see `pad_bbox`")
    ap.add_argument("--out", default="_site/region.geojson")
    args = ap.parse_args()

    if not os.path.isfile(args.poly):
        print(f"::warning::The region polygon ({args.poly}) is missing – the map "
              f"deploys without an outline and reaches beyond the region in the "
              f"app. Usually the `plan` job didn't download the `.poly`; "
              f"try the run again.")
        return 0

    rings = rings_from_geojson(args.poly)
    if not rings:
        print(f"::error::{args.poly} holds not one ring.",
              file=sys.stderr)
        return 1

    bbox = None
    if args.bbox:
        try:
            w, s, e, n = (float(v) for v in args.bbox.split(","))
            bbox = pad_bbox((w, max(s, -LAT_MAX), e, min(n, LAT_MAX)),
                            args.pad_m)
        except ValueError:
            print(f"::error::--bbox must be west,south,east,north, got "
                  f"'{args.bbox}'.", file=sys.stderr)
            return 1

    # clip ONLY when the region sticks out of the run's bbox (crop_bbox, custom region)
    clip = False
    if bbox:
        xs = [x for ring, _ in rings for x, _ in ring]
        ys = [y for ring, _ in rings for _, y in ring]
        clip = (min(xs) < bbox[0] or max(xs) > bbox[2]
                or min(ys) < bbox[1] or max(ys) > bbox[3])

    outlines, holes = [], []
    for ring, hole in rings:
        r = clip_ring(ring, bbox) if clip else list(ring)
        if not r:
            continue
        (holes if hole else outlines).append(r)

    if not outlines:
        print(f"::error::Clipped to bbox {args.bbox} nothing of the region is "
              f"left – the run's bbox and the region polygon don't overlap. Check "
              f"that `crop_bbox` (and `custom_bbox`) really lie in that region.",
              file=sys.stderr)
        return 1

    data = mask_geojson(outlines, holes)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f)

    area = (sum(ring_area_km2(r) for r in outlines)
            - sum(ring_area_km2(r) for r in holes))
    points = sum(len(r) for r in outlines) + sum(len(r) for r in holes)
    kb = os.path.getsize(args.out) / 1024
    print(f"Region outline: {args.out}")
    print(f"  rings                {len(outlines)} (+{len(holes)} holes), "
          f"{points} points, {kb:.1f} kB")
    print(f"  region area          {area:,.0f} km²")
    print(f"  clip to run bbox     "
          f"{args.bbox if clip else 'not needed (the region is inside the bbox)'}")
    print("  The style draws nothing past this outline – not even water and "
          "Natural Earth, which Planetiler puts into tiles over the whole rectangle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
