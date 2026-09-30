#!/usr/bin/env python3
""""Data · DMR 5.0": window, blocks and outputs – "which piece and in what shape".

From a WGS84 bbox a window in the source projection, blocks, parallel reading
from Drive and two outputs – a WGS84 COG (a range cut-out) or 1°×1° tiles.
Sign-in, probe and CLI are in `workers/drive/dmr5.py`; the journal (`LOG`,
`log()`, `run()`) is here, shared by both. A module:
`cut = load("dmr5_cut", "dmr5-cut.py")`.
"""
import importlib.util
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
# a folder is a job, a file a step; shared things live a level up
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # registries (areas, regions, sources)

# the source's projection and heights, here because only `gdalwarp` in this module converts
SRC_EPSG = 3046           # ETRS89 / TM zone N34, straight from the GeoTIFF tags
# ellipsoidal heights over GRS80 (ETRS89) → orthometric (EGM2008 ≈ Bpv)
SRC_VERT = 4937           # ETRS89 (3D, ellipsoidal heights)
DST_VERT = 3855           # EGM2008 height


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Heartbeat and `run_live`: a long gdalwarp must say how far it is
raster = load("dmr5_raster", "dmr5-raster.py")

# the resampling is NOT decided here but in `workers/lib/cell.py`, one answer with hillshading
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import AVERAGE_RATIO, resampling  # noqa: E402

LOG = []


def log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def run(cmd, env, label=None, expect=None, watch=None):
    if label:
        print("  $ " + " ".join(str(c) for c in cmd), flush=True)
        with raster.Heartbeat(label, expect_bytes=expect, watch=watch):
            return subprocess.run([str(c) for c in cmd], check=True, env=env)
    return subprocess.run([str(c) for c in cmd], check=True, env=env,
                          capture_output=True, text=True)


def src_window(bbox_wgs, wkt_file, info, env, pad_px=8):
    """WGS84 bbox → a window in the source projection, clipped to the raster."""
    # the clip matters: `-projwin` would fill the overhang with zeros – sea on the map
    w, s, e, n = bbox_wgs
    pts = "\n".join(f"{x} {y}" for x, y in
                    ((w, s), (w, n), (e, s), (e, n),
                     ((w + e) / 2, s), ((w + e) / 2, n)))
    r = subprocess.run(["gdaltransform", "-s_srs", "EPSG:4326",
                        "-t_srs", wkt_file],
                       input=pts, capture_output=True, text=True, env=env)
    xs, ys = [], []
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 2:
            xs.append(float(f[0]))
            ys.append(float(f[1]))
    if not xs:
        raise SystemExit(f"::error::bbox {bbox_wgs} can't be converted to the source")

    gt = info["geoTransform"]
    px, py = info["size"]
    rw, rn = gt[0], gt[3]
    re_, rs = rw + gt[1] * px, rn + gt[5] * py
    pad = pad_px * abs(gt[1])
    box = (max(min(xs) - pad, rw), max(min(ys) - pad, rs),
           min(max(xs) + pad, re_), min(max(ys) + pad, rn))
    if box[0] >= box[2] or box[1] >= box[3]:
        raise SystemExit("::error::The cut-out shares not one pixel with the "
                         "raster – check `area`.")
    log(f"  window in EPSG:{SRC_EPSG}: {box[0]:.0f},{box[1]:.0f} … "
        f"{box[2]:.0f},{box[3]:.0f}  "
        f"({(box[2] - box[0]) / 1000:.1f} × {(box[3] - box[1]) / 1000:.1f} km)")
    return box


def blocks(box, grid_m, jobs, max_px=4096):
    """Window → blocks SNAPPED TO THE TARGET GRID, so `gdalbuildvrt` joins them seamlessly."""
    w = math.floor(box[0] / grid_m) * grid_m
    s = math.floor(box[1] / grid_m) * grid_m
    e = math.ceil(box[2] / grid_m) * grid_m
    n = math.ceil(box[3] / grid_m) * grid_m

    nx_px, ny_px = (e - w) / grid_m, (n - s) / grid_m
    # at least `jobs` blocks to parallelise, none over max_px to stall the end
    nx = max(1, math.ceil(nx_px / max_px))
    ny = max(1, math.ceil(ny_px / max_px))
    while nx * ny < jobs and (nx_px / nx > 512 or ny_px / ny > 512):
        if nx_px / nx >= ny_px / ny:
            nx += 1
        else:
            ny += 1

    out = []
    for j in range(ny):
        for i in range(nx):
            bw = w + math.floor(i * nx_px / nx) * grid_m
            be = w + math.floor((i + 1) * nx_px / nx) * grid_m
            bs = s + math.floor(j * ny_px / ny) * grid_m
            bn = s + math.floor((j + 1) * ny_px / ny) * grid_m
            if be > bw and bn > bs:
                out.append((bw, bs, be, bn))
    return out, (nx, ny)


def pyramid_level(info, native_m, grid_m):
    """Which overview is read – ONE answer for plan and reading: `(level, read_m)`."""
    # the coarsest overview still finer than the target, like `-ovr AUTO`; the ratio
    # decides the resampling, and `average` at 1.25 baked a grid into the tiles
    best = (None, native_m)
    for i, o in enumerate(info["bands"][0].get("overviews", []) or []):
        if not o.get("size"):
            continue
        r = native_m * info["size"][0] / o["size"][0]
        if best[1] < r <= grid_m + 1e-9:
            best = (i, r)
    return best


def read_args(grid_m, read_m, level):
    """`gdal_translate` arguments for reading a block – overview and resampling."""
    # returns `(arguments, description)`; the description goes to the log
    ovr = ["-ovr", "NONE" if level is None else str(level)]
    if abs(grid_m - read_m) < 1e-9:
        return ovr, f"{read_m:g} m without resampling"
    kernel = resampling(grid_m, read_m)
    why = ("the target is at least %g× coarser than the overview, a mean has "
           "something to average" % AVERAGE_RATIO) if kernel == "average" else (
           "ratio %.2f is under %g, a mean would make a grid of it"
           % (grid_m / read_m, AVERAGE_RATIO))
    return (ovr + ["-tr", repr(grid_m), repr(grid_m), "-r", kernel],
            f"{read_m:g} m → {grid_m:g} m by `{kernel}` ({why})")


def read_blocks(src, parts, grid_m, work, jobs, env, native_m=1.0,
                read_m=None, level=None):
    """Blocks read IN PARALLEL – nothing else beats Drive's latency."""
    # A FINISHED BLOCK ISN'T READ AGAIN: written through `.part`, the rename makes it done
    os.makedirs(work, exist_ok=True)
    # from what and by what: computed once (`pyramid_level`); never `-ovr AUTO`
    if read_m is None:
        read_m, level = native_m, None
    reading, description = read_args(grid_m, read_m, level)
    log(f"  reading blocks: {description}")
    t0 = time.time()
    done_n = [0]
    reused = [0]
    lock = threading.Lock()

    def one(idx_part):
        idx, (bw, bs, be, bn) = idx_part
        dest = os.path.join(work, f"block-{idx:04d}.tif")
        hit = os.path.exists(dest) and os.path.getsize(dest) > 0
        if not hit:
            tmp = dest + ".part"
            cmd = ["gdal_translate", "-q",
                   "-projwin", repr(bw), repr(bn), repr(be), repr(bs),
                   *reading,
                   "-of", "GTiff", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
                   "-co", "TILED=YES", "-co", "BIGTIFF=YES",
                   src, tmp]
            subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
            os.replace(tmp, dest)
        # progress AFTER EVERY block: otherwise progress can't be told from a stuck block
        with lock:
            done_n[0] += 1
            if hit:
                reused[0] += 1
            el = time.time() - t0
            eta = el / done_n[0] * (len(parts) - done_n[0])
            print(f"  [{done_n[0]}/{len(parts)}] block-{idx:04d} "
                  f"{'was there' if hit else 'read'}, "
                  f"{os.path.getsize(dest) / 1e6:.1f} MB – "
                  f"{el / 60:.1f} min elapsed, ~{eta / 60:.1f} min left",
                  flush=True)
        return dest

    with raster.Heartbeat(f"reading {len(parts)} blocks from Drive"):
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            done = list(ex.map(one, enumerate(parts)))
    mb = sum(os.path.getsize(p) for p in done) / 1048576
    log(f"  blocks done in {(time.time() - t0) / 60:.1f} min, {mb:.0f} MB on "
        f"disk" + (f" ({reused[0]} of them from an earlier try)"
                   if reused[0] else ""))
    return done


def to_wgs84(parts, dest, bbox_wgs, grid_m, work, env, geoid):
    """The block mosaic → one WGS84 COG with heights converted, over DISK, not Drive."""
    vrt = os.path.join(work, "mosaic.vrt")
    run(["gdalbuildvrt", "-q", vrt, *parts], env)

    dx, dy = raster.degrees_per_metre((bbox_wgs[1] + bbox_wgs[3]) / 2)
    if geoid == "egm2008":
        srs = ["-s_srs", f"EPSG:{SRC_EPSG}+{SRC_VERT}",
               "-t_srs", f"EPSG:4326+{DST_VERT}",
               # without it a missing geoid grid silently keeps ellipsoidal heights
               "-to", "ERROR_ON_MISSING_VERT_SHIFT=YES"]
        log("  heights: ellipsoidal (ETRS89) → orthometric (EGM2008 ≈ Bpv)")
    else:
        srs = ["-s_srs", f"EPSG:{SRC_EPSG}", "-t_srs", "EPSG:4326"]
        log("::warning::Heights stay ellipsoidal – ~42 m above Bpv. Fine for "
            "rocks and hillshading, not for contours.")

    # the conversion is 1:1; `bilinear` at that ratio makes stripes, `lib/cell.py` picks
    kernel = resampling(grid_m, grid_m)
    run(["gdalwarp", "-overwrite", *srs,
         "-te", *[repr(v) for v in bbox_wgs],
         "-tr", repr(grid_m * dx), repr(grid_m * dy),
         "-r", kernel, "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
         "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
         # COG overviews halve, where a mean is honest (`AVERAGE_RATIO` is 2)
         "-co", "RESAMPLING=AVERAGE", "-co", "NUM_THREADS=ALL_CPUS",
         vrt, dest], env, label="converting to WGS84", watch=dest)
    log(f"  {os.path.basename(dest)}: {os.path.getsize(dest) / 1048576:.0f} MB")
    return dest


def country_tiles(parts, out_dir, work, env, geoid, window=None, grid_m=5.0):
    """Mosaic → 1°×1° WGS84 tiles as the map build expects them."""
    # THE SAME WINDOW goes to `dem/tiles.py`: WGS84 bulges it, and slivers were stored
    # under whole degrees' names (runs 31476448895 → 31484544154); `None` = the whole country
    vrt = os.path.join(work, "mosaic.vrt")
    run(["gdalbuildvrt", "-q", vrt, *parts], env)
    merged = os.path.join(work, "dmr5-national.tif")
    if geoid == "egm2008":
        srs = ["-s_srs", f"EPSG:{SRC_EPSG}+{SRC_VERT}",
               "-t_srs", f"EPSG:4326+{DST_VERT}",
               "-to", "ERROR_ON_MISSING_VERT_SHIFT=YES"]
    else:
        srs = ["-s_srs", f"EPSG:{SRC_EPSG}", "-t_srs", "EPSG:4326"]
    # a 1:1 conversion, only another projection – `lib/cell.py` picks the kernel
    run(["gdalwarp", "-overwrite", *srs, "-r", resampling(grid_m, grid_m),
         "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
         "-of", "GTiff", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
         "-co", "TILED=YES", "-co", "BIGTIFF=YES", "-co", "NUM_THREADS=ALL_CPUS",
         vrt, merged], env, label="converting to WGS84", watch=merged)
    cmd = ["python3", os.path.join(_WORKERS, "dem", "tiles.py"),
           "--out", out_dir, merged]
    if window is not None:
        cmd.append("--window=" + ",".join(f"{v:g}" for v in window))
    run(cmd, env, label="cutting into 1° tiles")
    return merged
