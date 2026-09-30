#!/usr/bin/env python3
"""Round the outlines of areas and the course of lines (rocks, contours).

A quadratic B-spline, sampled by chord sag against the tile grid step; streamed
through GeoJSONSeq so the layer isn't held in memory. Analysis: docs/.
"""
import argparse
import json
import math
import os
import subprocess
import sys

# lib/cell.py knows the tile grid step
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import cell  # noqa: E402

# a guard against a control polygon with kilometre-long edges
MAX_SAMPLES = 64


def _arc(a, b, c, tol, out):
    """One quadratic B-spline arc (a–b–c) for t ∈ (0, 1]."""
    (x0, y0), (x1, y1), (x2, y2) = a[:2], b[:2], c[:2]
    # sag is measured across the chord – along it is parametrisation, not shape
    sx, sy = (x0 + x1) / 2, (y0 + y1) / 2          # arc start
    ex, ey = (x1 + x2) / 2, (y1 + y2) / 2          # arc end
    mx, my = (x0 + 6 * x1 + x2) / 8, (y0 + 6 * y1 + y2) / 8   # arc middle
    dx, dy = ex - sx, ey - sy
    d = math.hypot(dx, dy)
    if d > 0:
        sag = abs((mx - sx) * dy - (my - sy) * dx) / d
    else:
        sag = math.hypot(mx - sx, my - sy)
    # n pieces cut the sag n² times
    n = 1 if sag <= tol else min(MAX_SAMPLES,
                                 int(math.ceil(math.sqrt(sag / tol))))
    for k in range(1, n + 1):
        t = k / n
        w0, w1, w2 = 0.5 * (1 - t) ** 2, 0.5 + t - t * t, 0.5 * t * t
        out.append((w0 * x0 + w1 * x1 + w2 * x2,
                    w0 * y0 + w1 * y1 + w2 * y2))


def curve_ring(ring, tol):
    """The limit curve over a closed ring – every corner is rounded."""
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
    # no point rounding a triangle
    if len(pts) < 4:
        return list(ring)
    n = len(pts)
    first = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
    out = [first]
    for i in range(n):
        _arc(pts[i], pts[(i + 1) % n], pts[(i + 2) % n], tol, out)
    # the last arc ends at the first point – the ring is closed
    out[-1] = first
    return out


def curve_line(line, tol):
    """The same on an open line; the ends don't move, so tile pieces still meet."""
    pts = list(line)
    if len(pts) > 2 and pts[0] == pts[-1]:
        return curve_ring(pts, tol)
    if len(pts) < 3:
        return pts
    ctrl = [pts[0], pts[0]] + pts[1:-1] + [pts[-1], pts[-1]]
    out = [tuple(pts[0][:2])]
    for a, b, c in zip(ctrl, ctrl[1:], ctrl[2:]):
        _arc(a, b, c, tol, out)
    out[-1] = tuple(pts[-1][:2])
    return out


# listed once, so smooth_geometry, count_points and -nlt don't drift
POLYGONS = ("Polygon", "MultiPolygon")
LINES = ("LineString", "MultiLineString")


def smooth_geometry(geom, tol):
    if not geom:
        return geom
    t = geom.get("type")
    if t in POLYGONS:
        parts = [geom["coordinates"]] if t == "Polygon" else geom["coordinates"]
        new = [[curve_ring(ring, tol) for ring in poly] for poly in parts]
        geom["coordinates"] = new if t == "MultiPolygon" else new[0]
    elif t in LINES:
        parts = [geom["coordinates"]] if t == "LineString" else geom["coordinates"]
        new = [curve_line(line, tol) for line in parts]
        geom["coordinates"] = new if t == "MultiLineString" else new[0]
    return geom


def count_points(geom):
    t = geom["type"]
    if t in POLYGONS:
        parts = ([geom["coordinates"]] if t == "Polygon"
                 else geom["coordinates"])
        return sum(len(r) for p in parts for r in p)
    parts = ([geom["coordinates"]] if t == "LineString"
             else geom["coordinates"])
    return sum(len(line) for line in parts)


def layer_srs(path, layer):
    """(`EPSG:code`, is_projected) of the source layer."""
    # the GeoJSON driver always converts to WGS84, so a metric layer is set back after
    try:
        info = json.loads(subprocess.run(
            ["ogrinfo", "-json", "-so", path, layer],
            capture_output=True, text=True, check=True).stdout)
        cs = info["layers"][0]["geometryFields"][0]["coordinateSystem"]
        pj = cs.get("projjson") or {}
        ident = pj.get("id") or {}
        code = ident.get("code")
        auth = ident.get("authority", "EPSG")
        projected = pj.get("type") == "ProjectedCRS"
        if code:
            return f"{auth}:{code}", projected
    except (subprocess.CalledProcessError, ValueError, KeyError, IndexError):
        pass
    return "", False


def tolerance(srs, projected, maxzoom, sag):
    """The allowed chord sag in the layer's units (degrees or metres)."""
    m = cell.tile_grid_m(maxzoom) * sag / 4.0
    if not projected:
        # divided by the longer degree (latitude), so the ground tolerance isn't larger
        return m / cell.M_PER_DEG_LAT, f"{m:.3f} m"
    if srs == "EPSG:3857":
        return m / math.cos(math.radians(cell.DEFAULT_LAT)), f"{m:.3f} m"
    return m, f"{m:.3f} m"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--layer", default="rock")
    ap.add_argument("--maxzoom", type=int, default=16,
                    help="this layer's tile maxzoom – it sets the grid step "
                         "and so the sample density")
    ap.add_argument("--sag", type=float, default=1.0,
                    help="allowed chord sag in QUARTERS of the tile grid "
                         "step (0 = rounding off)")
    args = ap.parse_args()

    if args.sag <= 0:
        subprocess.run(["ogr2ogr", "-f", "GPKG", args.dst, args.src,
                        "-nln", args.layer, "-overwrite"], check=True)
        print("  rounding: off (sag=0)", flush=True)
        return 0

    srs, projected = layer_srs(args.src, args.layer)
    tol, tol_m = tolerance(srs, projected, args.maxzoom, args.sag)
    seq = args.dst + ".seq.json"
    tmp = seq + ".sm"
    for f in (seq, tmp):
        if os.path.exists(f):
            os.remove(f)
    # GeoJSONSeq = a shape per line, streamable; `-a_srs` only relabels
    export = ["ogr2ogr", "-f", "GeoJSONSeq", seq, args.src, args.layer]
    if projected:
        export += ["-a_srs", "EPSG:4326", "-lco", "COORDINATE_PRECISION=3"]
    subprocess.run(export, check=True)

    # the geometry says the type, not an option – two truths would drift
    n, pts_in, pts_out, kind = 0, 0, 0, ""
    with open(seq) as fi, open(tmp, "w") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            feat = json.loads(line)
            g = feat.get("geometry")
            n += 1
            if g and g.get("type") in POLYGONS + LINES:
                kind = "area" if g["type"] in POLYGONS else "line"
                pts_in += count_points(g)
                feat["geometry"] = smooth_geometry(g, tol)
                pts_out += count_points(feat["geometry"])
            fo.write(json.dumps(feat, separators=(",", ":")) + "\n")
    os.remove(seq)

    # an empty layer is a zero-length file the driver won't open; not an error
    if n == 0:
        os.remove(tmp)
        subprocess.run(["ogr2ogr", "-f", "GPKG", args.dst, args.src,
                        "-nln", args.layer, "-overwrite"], check=True)
        print("  rounding: the layer is empty, nothing to round", flush=True)
        return 0

    if os.path.exists(args.dst):
        os.remove(args.dst)
    # `-makevalid` only on areas: rounded edges of a thin spike may touch
    lines = kind == "line"
    cmd = ["ogr2ogr", "-f", "GPKG", args.dst, tmp, "-nln", args.layer]
    # an empty layer told no type – don't force one, the schema would drop it
    if kind:
        cmd += ["-nlt", "MULTILINESTRING" if lines else "MULTIPOLYGON"]
    if kind and not lines:
        cmd += ["-makevalid"]
    if projected and srs:
        # the coordinates are metres, only labelled as degrees
        cmd += ["-a_srs", srs]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        print("::warning::-makevalid doesn't work (old GDAL) – rounded rocks "
              "go without a validity check.")
        subprocess.run([c for c in cmd if c != "-makevalid"], check=True)
    os.remove(tmp)

    grew = pts_out / pts_in if pts_in else 1.0
    print(f"  rounding: limit curve, sag up to {args.sag / 4:.2f}× the "
          f"z{args.maxzoom} grid step ({tol_m}), {n} "
          f"{'lines' if lines else 'areas'}, "
          f"points {pts_in} → {pts_out} ({grew:.2f}×)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
