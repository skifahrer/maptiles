#!/usr/bin/env python3
"""Rocks from hillshading, 3/3: outlines, seams and the filter from the raster.

From the finished darkness raster to the `rock` layer in a GeoPackage. Outlines
in blocks and their seams are shared with rocks from slope in
`workers/lib/contour-blocks.py`. Used as a module, not from the command line.
"""
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# for another job's scripts; our own go through `_HERE`
_WORKERS = os.path.dirname(_HERE)


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# grid, `run()` and contour speed come from the layer below
tiles = load("shading_tiles", "tiles.py")
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
run = tiles.run
CONTOUR_CELLS_PER_S = tiles.CONTOUR_CELLS_PER_S

# `watch.py` is shared by both ways to rocks, so it lives in `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb  # noqa: E402

# outlines in blocks and seams are the same as for rocks from slope
blocks_mod = load("contour_blocks", os.path.join(
    os.path.dirname(_HERE), "lib", "contour-blocks.py"))


def bbox_km2(bbox):
    """A bbox's area in km² – only to check the result doesn't cover everything."""
    w, s_, e, n = bbox
    return ((e - w) * 111.32 * math.cos(math.radians((s_ + n) / 2))
            * (n - s_) * 110.54)


def ring_area(ring):
    """A ring's signed area (shoelace) in coordinate units."""
    s = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def filter_stream(src, dst, min_area, min_hole, cliff_level, merc_factor,
                  every=30, fill_holes=False, min_level=0.5):
    """A streaming filter over GeoJSONSeq: crumbs out, small holes out, classes set."""
    # areas from EPSG:3857 times `merc_factor` (cos² latitude), or 2.3× too big at 49°;
    # holes are the gaps in the gully network and stay unless `fill_holes`
    n_in = n_out = 0
    n_background = 0
    holes_kept = holes_drop = 0
    total = 0.0
    n_cliff = 0
    biggest = 0.0
    # written as it goes into `.part`, renamed when done
    part = dst + ".part"
    t0 = time.time()
    last = t0
    with open(src) as fi, open(part, "w") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            feat = json.loads(line)
            g = feat.get("geometry") or {}
            t = g.get("type")
            if t == "Polygon":
                parts = [g["coordinates"]]
            elif t == "MultiPolygon":
                parts = g["coordinates"]
            else:
                continue
            dmin = feat.get("properties", {}).get("dmin")
            try:
                dmin = float(dmin)
            except (TypeError, ValueError):
                dmin = 0.0
            # background out: `gdal_contour -p` makes the band under the threshold too
            if dmin < min_level:
                n_background += 1
                continue
            cls = "cliff" if dmin >= cliff_level else "steep"

            for poly in parts:
                if not poly:
                    continue
                n_in += 1
                area = abs(ring_area(poly[0])) * merc_factor
                rings = [poly[0]]
                if fill_holes:
                    holes_drop += len(poly) - 1
                else:
                    for hole in poly[1:]:
                        a = abs(ring_area(hole)) * merc_factor
                        if a >= min_hole:
                            rings.append(hole)
                            area -= a
                            holes_kept += 1
                        else:
                            holes_drop += 1
                if area < min_area:
                    continue
                fo.write(json.dumps({
                    "type": "Feature",
                    # `ceil`, not `round`: the band's floor is 0.5 and would round to zero
                    "properties": {"class": cls, "dark": int(math.ceil(dmin)),
                                   "area": int(round(area))},
                    "geometry": {"type": "Polygon", "coordinates": rings},
                }, separators=(",", ":")) + "\n")
                n_out += 1
                now = time.time()
                if every and now - last >= every:
                    last = now
                    fo.flush()
                    print(f"  … area filter: {n_in} read, "
                          f"{n_out} kept, running {hms(now - t0)}",
                          flush=True)
                total += area
                biggest = max(biggest, area)
                n_cliff += (cls == "cliff")
    os.replace(part, dst)
    return {"n_in": n_in, "n": n_out, "cliff": n_cliff, "total_m2": total,
            "background": n_background,
            "max_m2": biggest, "holes": holes_kept, "holes_dropped": holes_drop}


# download numbers beside the cache, not in `_in_progress`: they survive a threshold change
DOWNLOADED = "_downloaded.txt"


def write_downloaded(cache_dir, fetcher, n_tiles):
    """Keep what the network cost – the `join` phase downloads nothing to know it."""
    dl = {"tiles": n_tiles, "tiles_missing": fetcher.n_miss,
          "tiles_failed": fetcher.n_fail,
          "mb_downloaded": f"{fetcher.bytes / 1048576:.0f}",
          "ua_profiles": len(fetcher.ua_seen)}
    try:
        with open(os.path.join(cache_dir, DOWNLOADED), "w") as f:
            for k, v in dl.items():
                f.write(f"{k}={v}\n")
    except OSError as exc:
        print(f"  download numbers weren't saved ({exc}) – the next phase's "
              f"stats will show zeros.", flush=True)
    return dl


def read_downloaded(cache_dir, n_tiles):
    """Numbers from the download phase; zeros rather than invented values when missing."""
    dl = {"tiles": n_tiles, "tiles_missing": 0, "tiles_failed": 0,
          "mb_downloaded": "0", "ua_profiles": 0}
    path = os.path.join(cache_dir, DOWNLOADED)
    try:
        with open(path) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k in dl:
                    dl[k] = int(v) if k not in ("mb_downloaded",) else v
        print(f"  download numbers from {path}: {dl['tiles']} tiles, "
              f"{dl['mb_downloaded']} MB", flush=True)
    except OSError:
        print(f"  {path} is missing – the tile numbers in the stats will be zeros.",
              flush=True)
    return dl


def done(path, label):
    """True = an earlier run did this phase (written to `.part`, renamed when whole)."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"  {label}: done by an earlier run "
              f"({dir_mb(path):.0f} MB) – skipping", flush=True)
        return True
    return False


def band_levels(args, cliff_level):
    """Thresholds for `-fl`; solid areas (default) = one band."""
    return (["0.5", "256"] if args.solid else
            ["0.5", repr(cliff_level), "256"])


def vrt_geo(vrt):
    """The top-left corner and pixel size from a VRT header."""
    with open(vrt) as f:
        head = f.read(8192)
    m = re.search(r"<GeoTransform>(.*?)</GeoTransform>", head, re.S)
    if not m:
        raise RuntimeError(f"{vrt} has no GeoTransform")
    g = [float(x) for x in m.group(1).split(",")]
    return g[0], g[3], g[1]     # ox, oy, pixel size (x)


def outlines(tifs, args, tmp, cliff_level):
    """The darkness mosaic → outlines in blocks in `tmp/blocks`. Returns the block count."""
    vrt = os.path.join(tmp, "score.vrt")
    run(["gdalbuildvrt", "-q", vrt] + tifs)
    ox, oy, res = vrt_geo(vrt)
    # a block is measured in tiles here: the raster is assembled from tiles
    block_px = max(1, args.block_tiles) * TILE
    _, n_blocks = blocks_mod.by_blocks(
        vrt, os.path.join(tmp, "blocks"),
        band_levels(args, cliff_level), ["-amin", "dmin", "-amax", "dmax"],
        block_px, (ox, oy, res), budget_s=args.budget_min * 60)
    return n_blocks


def join(args, tmp, out, cliff_level, merc, area_km2=0.0):
    """Block outlines → a finished rock.gpkg in EPSG:4326."""
    d_blocks = os.path.join(tmp, "blocks")
    if not os.path.isdir(d_blocks):
        raise RuntimeError(
            f"The block outlines are missing ({d_blocks}). The `join` phase "
            f"follows the `vector` phase – it either didn't run, or the cache "
            f"with the work in progress got lost. Run with `--phase=all`.")
    n_blocks = len([f for f in os.listdir(d_blocks) if f.endswith(".geojsonl")])

    # no `-explodecollections` – the filter takes MultiPolygons apart itself
    seq = os.path.join(tmp, "bands.geojsonl")
    if not done(seq, "joining blocks"):
        part = seq + ".part"
        n = blocks_mod.join_blocks(d_blocks, part)
        os.replace(part, seq)
        print(f"  joining blocks: {n} shapes from {n_blocks} blocks", flush=True)

    # stitching is cosmetic with one opaque grey and costs ST_Union, so off by default
    if args.stitch:
        # `dmin` is the band's class – join only within it; metric coordinates, no `srs`
        seq = blocks_mod.stitch_seams(seq, tmp, key_attribute="dmin",
                                      heartbeat=args.heartbeat,
                                      max_s=args.budget_min * 60,
                                      label="stitching seams")
    else:
        print("  seams: not stitching (`options: stitch=1` turns it on) – one "
              "opaque grey doesn't need the join", flush=True)

    filt = os.path.join(tmp, "rock.geojsonl")
    st = filter_stream(seq, filt, args.min_area, args.min_hole,
                       cliff_level, merc, every=args.heartbeat,
                       fill_holes=bool(args.fill_holes), min_level=0.5)
    print(f"  filter: {st['n_in']} → {st['n']} areas "
          f"({st.get('background', 0)} bands under the threshold = background out, "
          f"under {args.min_area:g} m² out), "
          + (f"holes FILLED ({st['holes_dropped']} dropped) – "
             f"the areas' shape is gone, `fill_holes=0` brings it back"
             if args.fill_holes else
             f"{st['holes']} holes kept, {st['holes_dropped']} under "
             f"{args.min_hole:g} m² out"), flush=True)
    # a guard: rocks covering most of the area are background; 9.5 % was a right result
    total_km2 = st.get("total_m2", 0) / 1e6
    if area_km2 > 0 and total_km2 > 0.3 * area_km2:
        print(f"::warning::Rocks cover {total_km2:.2f} km² of "
              f"{area_km2:.2f} km² ({100 * total_km2 / area_km2:.0f} %). "
              f"There are that many rocks nowhere – even the cirque under "
              f"Gerlach comes to ~10 %. At lower zooms the map shows a solid "
              f"grey area without detail. Raise `options: open=…` (drops the "
              f"thinnest threads of the network) or lower `dark`.", flush=True)

    if not st["n"]:
        if st["n_in"] > 1000:
            # thousands of shapes and none big enough isn't a strict threshold – units are wrong
            print(f"::warning::The filter dropped ALL {st['n_in']} shapes as "
                  f"smaller than {args.min_area:g} m². With that many it isn't a "
                  f"strict threshold but an area computed in units other than "
                  f"metres – check the coordinates in {seq}.", flush=True)
        return st

    metric = os.path.join(tmp, "rock-metric.gpkg")
    cmd = ["ogr2ogr", "-f", "GPKG", metric, filt, "-nln", "rock",
           "-nlt", "MULTIPOLYGON", "-a_srs", WEBMERC,
           "-lco", "GEOMETRY_NAME=geom"]
    if args.simplify > 0:
        cmd += ["-simplify", repr(args.simplify)]
    run(cmd)

    smooth = os.path.join(tmp, "rock-smooth.gpkg")
    src = metric
    if args.smooth > 0:
        # `smooth-shapes.py` is in `contours-rocks/`, not beside this file (`lint/layout.py`)
        subprocess.run([sys.executable,
                        os.path.join(_WORKERS, "contours-rocks",
                                     "smooth-shapes.py"),
                        f"--in={metric}", f"--out={smooth}", "--layer=rock",
                        f"--maxzoom={args.maxzoom}",
                        f"--sag={args.smooth}"], check=True)
        src = smooth

    if os.path.exists(out):
        os.remove(out)
    run(["ogr2ogr", "-f", "GPKG", out, src, "rock", "-nln", "rock",
         "-t_srs", "EPSG:4326", "-nlt", "MULTIPOLYGON",
         "-lco", "GEOMETRY_NAME=geom"])
    return st


def empty_rock(out):
    """An empty layer – the rock schema always refers to it, the file must exist."""
    tmp = out + ".empty.geojson"
    with open(tmp, "w") as f:
        f.write('{"type":"FeatureCollection","features":[]}')
    if os.path.exists(out):
        os.remove(out)
    run(["ogr2ogr", "-f", "GPKG", out, tmp, "-nln", "rock", "-nlt", "POLYGON",
         "-a_srs", "EPSG:4326", "-lco", "GEOMETRY_NAME=geom"])
    os.remove(tmp)
