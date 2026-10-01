#!/usr/bin/env python3
"""DEM → `raster-dem` (terrarium) tiles for hillshading and 3D terrain.

MapLibre can't read heights from a GeoTIFF and the public AWS Terrain Tiles are
a surface model, so tiles are made from the same DEM as the rest of the pipeline.

    height [m] = (R * 256 + G + B / 256) − 32768

The vertical step follows the horizontal pixel (`SLOPE_EPS × pixel`, plus the
`FRAC_BITS_MARGIN` margin) – a coarse step makes terraces whose edges hillshade
turns into a grid. `resampling()` picks by the pixel to cell ratio.

Outside the region is a plane (`flatten_outside`) so nothing is shaded there.
A tile without a single region pixel isn't written.

Usage:
    python3 workers/terrain/tiles.py --dem=dem/all.vrt \\
        --bbox=16.8,47.7,22.6,49.6 --maxzoom=12 --out=terrain-out
"""
import argparse
import math
import os
import struct
import subprocess
import sys
import zlib

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
# grid and zoom arithmetic is in `lib/cell.py`: `lint/terrain.py` runs it without numpy
from cell import (SLOPE_EPS, dem_cell_metres, frac_bits,  # noqa: E402
                  resampling, tile_m_per_px)
# work on the height grid is in `height.py`; here are the plan, warp and encoding
sys.path.insert(0, _HERE)
from height import (NODATA, edge_height, fill_nodata,  # noqa: E402
                    flatten_outside)

R_EARTH = 6378137.0
ORIGIN = math.pi * R_EARTH  # 20037508.342789244
TILE = 256


def merc_x(lon):
    return math.radians(lon) * R_EARTH


def merc_y(lat):
    lat = max(min(lat, 85.05112878), -85.05112878)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH


def tile_range(z, w, s, e, n):
    """The XYZ tile range covering a bbox at a zoom."""
    count = 2**z
    size = 2 * ORIGIN / count
    x0 = int((merc_x(w) + ORIGIN) // size)
    x1 = int((merc_x(e) + ORIGIN) // size)
    y0 = int((ORIGIN - merc_y(n)) // size)
    y1 = int((ORIGIN - merc_y(s)) // size)
    clamp = lambda v: max(0, min(count - 1, v))
    return clamp(x0), clamp(x1), clamp(y0), clamp(y1)


# a minimal PNG writer: no Pillow here; every filter is tried, the smallest row wins
def _filter_rows(raw):
    h, stride = raw.shape
    bpp = 3
    out = np.empty((h, stride + 1), np.uint8)
    prev = np.zeros(stride, np.uint8)
    for i in range(h):
        line = raw[i].astype(np.int16)
        left = np.zeros(stride, np.int16)
        left[bpp:] = line[:-bpp]
        up = prev.astype(np.int16)
        upleft = np.zeros(stride, np.int16)
        upleft[bpp:] = up[:-bpp]

        cands = [
            (0, line),
            (1, line - left),
            (2, line - up),
            (3, line - ((left + up) // 2)),
        ]
        # Paeth
        p = left + up - upleft
        pa, pb, pc = np.abs(p - left), np.abs(p - up), np.abs(p - upleft)
        pred = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, up, upleft))
        cands.append((4, line - pred))

        best = min(cands, key=lambda c: int(np.abs(c[1].astype(np.int8)).sum()))
        out[i, 0] = best[0]
        out[i, 1:] = best[1].astype(np.uint8)
        prev = raw[i]
    return out


def png_rgb(arr):
    h, w, _ = arr.shape
    raw = np.ascontiguousarray(arr).reshape(h, w * 3)
    data = _filter_rows(raw).tobytes()

    def chunk(kind, payload):
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(data, 9))
        + chunk(b"IEND", b"")
    )


def webp_rgb(arr):
    import io
    from PIL import Image
    buf = io.BytesIO()
    # `exact` keeps every RGB value, which is the height
    Image.fromarray(np.ascontiguousarray(arr)).save(
        buf, "WEBP", lossless=True, quality=100, method=6, exact=True)
    return buf.getvalue()


ENCODERS = {"png": png_rgb, "webp": webp_rgb}


def terrarium(heights, bits):
    """Height in metres → RGB terrarium with a `bits`-bit fraction, rounded to the step."""
    # a mask would be `floor`, a whole step down makes a stair at zoom borders
    step = 1 << (8 - bits)               # encoding step in 1/256 m
    v = np.rint((heights.astype(np.float64) + 32768.0) * 256.0 / step) * step
    v = np.clip(v, 0, (16777215 // step) * step).astype(np.uint32)
    rgb = np.empty(heights.shape + (3,), np.uint8)
    rgb[..., 0] = (v >> 16) & 255
    rgb[..., 1] = (v >> 8) & 255
    rgb[..., 2] = v & 255
    return rgb


def is_flat(heights, px_m):
    """Nothing to shade in this tile? (no slope over `SLOPE_EPS` anywhere)"""
    if heights.shape[0] < 2 or heights.shape[1] < 2:
        return False
    cap = SLOPE_EPS * px_m
    return (float(np.abs(np.diff(heights, axis=1)).max()) <= cap
            and float(np.abs(np.diff(heights, axis=0)).max()) <= cap)


def warp_level(dem, path, minx, miny, maxx, maxy, width, height, resample):
    """Resample the DEM to a grid aligned to the zoom's tiles."""
    # Float32 keeps the fraction; a zero nodata was sea level and made a wall
    subprocess.run(
        ["gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:3857",
         "-te", *map(repr, (minx, miny, maxx, maxy)),
         "-ts", str(width), str(height),
         "-r", resample, "-ot", "Float32", "-dstnodata", str(NODATA),
         "-of", "ENVI", dem, path],
        check=True,
    )


def load_mask(poly, bbox):
    """The region mask from `workers/lib/region-mask.py`, or `None` without a polygon."""
    if not poly or not os.path.exists(poly):
        return None
    import importlib.util
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "lib", "region-mask.py")
    spec = importlib.util.spec_from_file_location("region_mask", lib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Mercator here, not in `region-mask.py`: the formula lives in one place
    rings = [([(merc_x(x), merc_y(y)) for x, y in ring], hole)
             for ring, hole in mod.rings_from_geojson(poly)]
    return mod, mod.mask_from_file(poly, bbox), rings


def plane_height(dem, rm, rings, w, s, e, n, width=1024):
    """The plane's height outside – one for all zooms, otherwise they seam."""
    minx, maxx, miny, maxy = merc_x(w), merc_x(e), merc_y(s), merc_y(n)
    height = max(16, int(width * (maxy - miny) / (maxx - minx)))
    warp_level(dem, "/tmp/edge.raw", minx, miny, maxx, maxy, width, height,
               "average")
    grid = np.fromfile("/tmp/edge.raw", dtype="<f4").reshape(height, width)
    known = rm.pixel_mask(rings, (minx, miny, maxx, maxy), width, height)
    return round(edge_height(grid, known & (grid > NODATA + 1.0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", required=True, help="input DEM (.vrt/.tif)")
    ap.add_argument("--bbox", required=True, help="west,south,east,north")
    ap.add_argument("--poly", default="",
                    help="the region's GeoJSON – tiles outside aren't drawn "
                         "and those overhanging get a plane outside")
    ap.add_argument("--grow", type=float, default=0.5,
                    help="how much of its side a tile may overhang the region")
    ap.add_argument("--edge", type=int, default=2,
                    help="how many pixels of real terrain stay outside the "
                         "region before the plane starts")
    ap.add_argument("--maxzoom", type=int, default=12)
    ap.add_argument("--minzoom", type=int, default=0)
    ap.add_argument("--out", required=True, help="directory of {z}/{x}/{y}.<format> tiles")
    ap.add_argument("--format", choices=sorted(ENCODERS), default="png")
    ap.add_argument("--max-frac-bits", type=int, default=-1,
                    help="at most this many fraction bits (-1 = by the pixel only)")
    ap.add_argument("--budget-mb", type=float, default=0,
                    help="how many MB the tiles may take (0 = no cap)")
    ap.add_argument("--keep-flat", action="store_true",
                    help="write tiles without relief too (otherwise skipped "
                         "and the client takes their parent)")
    args = ap.parse_args()
    encode = ENCODERS[args.format]

    def bits_for(px_m):
        bits = frac_bits(px_m)
        return bits if args.max_frac_bits < 0 else min(bits, args.max_frac_bits)

    w, s, e, n = (float(v) for v in args.bbox.split(","))
    lat = (s + n) / 2
    # tile clip drops tiles away from the region, pixel clip does the rest
    loaded = load_mask(args.poly, (w, s, e, n))
    rm, mask, rings = loaded if loaded else (None, None, None)
    plane = None
    if mask:
        plane = plane_height(args.dem, rm, rings, w, s, e, n)
        print(f"Region clip: the region is {mask.pct:.0f} % of the bbox "
              f"(mask {mask.nx}×{mask.ny}); a tile may overhang "
              f"{args.grow:g} of its side and outside (+{args.edge} px of "
              f"terrain) is a plane at {plane} m – nothing is shaded there.",
              flush=True)
    else:
        print("::warning::No region polygon – the whole region bbox is drawn, "
              "outside the region too. (`--poly` got no file.)", flush=True)
    # the grid is measured from the raster; without a measurement `average`
    cell_dx, cell_dy = dem_cell_metres(args.dem, lat)
    cell_m = max(cell_dx, cell_dy) if cell_dx and cell_dy else 0.0
    if cell_m:
        print(f"Model grid: {cell_dx:.1f} × {cell_dy:.1f} m "
              f"({cell_m:.1f} m decides).", flush=True)
    else:
        print("::warning::The model grid can't be read from "
              f"{args.dem} – resampling by average as before. "
              "At maxzoom that may leave a grid in the hillshading.", flush=True)

    total_bytes = 0
    total_tiles = 0
    skipped = 0
    flat = 0
    cut_px = 0          # pixels outside the region
    all_px = 0
    no_model = 0        # tiles where the model has NOT ONE valid pixel
    made = args.minzoom - 1
    # how much of the plan was really made – the next zoom's budget uses it
    kept_ratio = 1.0

    # every extra zoom quadruples the tiles; show the plan up front
    plan = []
    for z in range(args.minzoom, args.maxzoom + 1):
        x0, x1, y0, y1 = tile_range(z, w, s, e, n)
        every = (x1 - x0 + 1) * (y1 - y0 + 1)
        if mask:
            inside = sum(1 for tx in range(x0, x1 + 1) for ty in range(y0, y1 + 1)
                         if rm.tile_touches(mask, z, tx, ty, args.grow))
        else:
            inside = every
        plan.append((z, inside, every))
    outside = sum(v - k for _, k, v in plan)
    print("Plan: " + ", ".join(f"z{z} {k} tiles" for z, k, _ in plan)
          + f"  (total {sum(k for _, k, _ in plan)} tiles"
          + (f", {outside} outside the region skipped" if outside else "")
          + ")"
          + (f", cap {args.budget_mb:.0f} MB" if args.budget_mb else ""),
          flush=True)
    # how it will be computed – visible before the work
    print("Resampling and vertical step: " + ", ".join(
        f"z{z} {tile_m_per_px(z, lat):.1f} m/px "
        f"{resampling(tile_m_per_px(z, lat), cell_m)}"
        f" 1/{2 ** bits_for(tile_m_per_px(z, lat))} m"
        for z, _, _ in plan), flush=True)

    for z in range(args.minzoom, args.maxzoom + 1):
        x0, x1, y0, y1 = tile_range(z, w, s, e, n)
        px_m = tile_m_per_px(z, lat)
        bits = bits_for(px_m)
        resample = resampling(px_m, cell_m)
        # size cap: the next zoom estimated from the one below
        if args.budget_mb and total_tiles:
            per_tile = total_bytes / total_tiles
            want = next(k for zz, k, _ in plan if zz == z) * kept_ratio * per_tile
            if (total_bytes + want) / 1048576 > args.budget_mb:
                print(f"::warning::Terrain tiles end at z{made}: z{z} would "
                      f"add ~{want / 1048576:.0f} MB and the hillshading "
                      f"budget is {args.budget_mb:.0f} MB. For finer relief "
                      f"shrink the area (input `area`, option `crop_bbox`), "
                      f"or raise `size_limit_mb` or the BUDGET_TERRAIN_PCT share.")
                break
        size = 2 * ORIGIN / (2**z)
        nx, ny = x1 - x0 + 1, y1 - y0 + 1
        skipped_before = skipped
        flat_before = flat
        no_model_before = no_model
        written = 0

        # in strips, so memory doesn't grow with the area
        rows_per_strip = max(1, 512 // max(1, nx))
        zbytes = 0
        for ry in range(y0, y1 + 1, rows_per_strip):
            ry_end = min(ry + rows_per_strip - 1, y1)
            minx = -ORIGIN + x0 * size
            maxx = -ORIGIN + (x1 + 1) * size
            maxy = ORIGIN - ry * size
            miny = ORIGIN - (ry_end + 1) * size
            width = nx * TILE
            height = (ry_end - ry + 1) * TILE
            warp_level(args.dem, "/tmp/level.raw", minx, miny, maxx, maxy,
                       width, height, resample)
            grid = np.fromfile("/tmp/level.raw", dtype="<f4").reshape(height, width)
            # `missing` is kept apart: a filled grid can't be told from a real one
            missing = grid <= NODATA + 1.0
            grid = fill_nodata(grid, missing)

            # `--edge` px of terrain outside: the plane's edge falls under the `outside` fill
            keep = None
            if rings is not None:
                keep = rm.pixel_mask(rings, (minx, miny, maxx, maxy),
                                     width, height, grow=args.edge)
                cut_px += int(keep.size - keep.sum())
                all_px += keep.size
                grid = flatten_outside(grid, keep, plane)

            for ty in range(ry, ry_end + 1):
                for tx in range(x0, x1 + 1):
                    # checked here, not before the warp: the warp runs on the whole strip
                    if mask and not rm.tile_touches(mask, z, tx, ty, args.grow):
                        skipped += 1
                        continue
                    # a tile without a region pixel is covered by the `outside` fill
                    if keep is not None and not keep[
                            (ty - ry) * TILE:(ty - ry + 1) * TILE,
                            (tx - x0) * TILE:(tx - x0 + 1) * TILE].any():
                        skipped += 1
                        continue
                    # no valid pixel isn't flat, the model says nothing: not even at minzoom
                    if missing[(ty - ry) * TILE:(ty - ry + 1) * TILE,
                               (tx - x0) * TILE:(tx - x0 + 1) * TILE].all():
                        no_model += 1
                        continue
                    # per tile, not the strip: a strip has 33 M pixels at z15
                    heights = grid[
                        (ty - ry) * TILE : (ty - ry + 1) * TILE,
                        (tx - x0) * TILE : (tx - x0 + 1) * TILE,
                    ]
                    # flat isn't written, MapLibre takes the parent; never minzoom, the root
                    if (not args.keep_flat and z > args.minzoom
                            and is_flat(heights, px_m)):
                        flat += 1
                        continue
                    d = os.path.join(args.out, str(z), str(tx))
                    os.makedirs(d, exist_ok=True)
                    data = encode(terrarium(heights, bits))
                    with open(os.path.join(d, f"{ty}.{args.format}"), "wb") as f:
                        f.write(data)
                    zbytes += len(data)
                    total_tiles += 1
                    written += 1
        total_bytes += zbytes
        made = z
        in_plan = next(k for zz, k, _ in plan if zz == z)
        # a zoom writing nothing keeps the ratio, or the brake would stop braking
        if in_plan and written:
            kept_ratio = written / in_plan
        print(f"z{z}: {nx}×{ny} tiles, {written} written, "
              f"{zbytes / 1048576:.1f} MB ({resample}, step 1/{2 ** bits} m)"
              + (f", outside the region {skipped - skipped_before}"
                 if mask and skipped > skipped_before else "")
              + (f", no relief {flat - flat_before}"
                 if flat > flat_before else "")
              + (f", no model {no_model - no_model_before}"
                 if no_model > no_model_before else ""), flush=True)

    # an empty layer must fail, not turn green: a cut-out may fall outside the region
    if made < args.minzoom or not total_tiles:
        print("::error::Not a single hillshading tile was made."
              + (" The run's cut-out isn't in the region, so there is nothing "
                 "to draw – move it inside (`test_at`, `crop_bbox`), or check "
                 f"that `{args.poly}` really is this region's polygon."
                 if rings is not None else ""),
              file=sys.stderr)
        return 1
    # the maxzoom really made, not the wished one – the asset and style take it
    with open(os.path.join(args.out, "maxzoom.txt"), "w") as f:
        f.write(f"{made}\n")
    if all_px:
        print(f"{100 * cut_px / all_px:.0f} % of pixels were outside the "
              f"region – a plane at {plane} m there, so nothing is shaded.")
    print(f"Total: {total_tiles} tiles, {total_bytes / 1048576:.1f} MB, "
          f"maxzoom z{made}"
          + (f"; {skipped} tiles outside the region skipped "
             f"({100 * skipped / (total_tiles + skipped):.0f} %)"
             if skipped else "")
          + (f"; {flat} tiles without relief skipped "
             f"({100 * flat / (total_tiles + flat):.0f} %) – the client draws "
             f"their parent"
             if flat else "")
          + (f"; {no_model} tiles without model skipped – the elevation "
             f"model has no data there, so no hillshading is drawn"
             if no_model else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
