#!/usr/bin/env python3
"""The rock plan: which grid, how many cells and how long it will take."""
import json
import math
import os
import subprocess
import sys

# `watch.py` is shared by both ways to rocks, so it lives in `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms  # noqa: E402
import cell  # noqa: E402

# hillshading asks for the raster grid too, so the conversion is in `lib/cell.py`
dem_cell_metres = cell.dem_cell_metres

METRIC = "EPSG:3035"  # LAEA Europe – barely distorts areas at our latitudes
# slope as Int16 in hundredths of a degree: a 0.5° Byte step made terraces the isoline stairs over
SCALE = 100

# measured on a GitHub runner, only for estimating: 170 chunks / 23.1 G cells in 75 min
SLOPE_CELLS_PER_S = 5.1e6    # gdalwarp + gdaldem slope + gdal_translate

# `gdal_contour -p` costs by SOURCE cells, not the tracing grid; measured in blocks
# (`ROCK_BLOCK_PX`) at 12.1 M cells/s on flat land – lower on a rocky cut-out
CONTOUR_SRC_CELLS_PER_S = 1.2e7
# the same run stayed under 16 GB at 23.1 G cells: time kills a request, not memory
MOSAIC_MB_PER_GCELL = 240    # Int16 + DEFLATE + PREDICTOR


class CommandError(subprocess.CalledProcessError):
    """A CalledProcessError whose message carries stderr too."""

    def __str__(self):
        tail = (self.stderr or "").strip()[-2000:]
        return super().__str__() + (f"\nstderr: {tail}" if tail else "")


def run(cmd, **kw):
    # without it a failure leaves only "exit status 1" and no reason
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)
    except subprocess.CalledProcessError as exc:
        raise CommandError(exc.returncode, exc.cmd, exc.output, exc.stderr) from None


def to_metric(bbox):
    """A bbox in degrees → an extent in metres (EPSG:3035)."""
    w, s, e, n = bbox
    pts = "\n".join(f"{x} {y}" for x, y in
                    [(w, s), (e, s), (w, n), (e, n), ((w + e) / 2, s), ((w + e) / 2, n)])
    out = run(["gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", METRIC],
              input=pts).stdout.split()
    xs = [float(v) for v in out[0::3]]
    ys = [float(v) for v in out[1::3]]
    return min(xs), min(ys), max(xs), max(ys)


def chunk_plan(x0, y0, x1, y1, res, chunk_cells, bbox, side_m=0):
    """Split into chunks + the list of those really in the area."""
    # EPSG:3035 is rotated against meridians; `side_m` overrides the chunk size
    snap = lambda v, up: (math.ceil(v / res) if up else math.floor(v / res)) * res
    x0, y0, x1, y1 = snap(x0, False), snap(y0, False), snap(x1, True), snap(y1, True)
    width_m, height_m = x1 - x0, y1 - y0

    side = side_m or math.sqrt(chunk_cells) * res
    nx = max(1, math.ceil(width_m / side))
    ny = max(1, math.ceil(height_m / side))
    step_x = math.ceil(width_m / nx / res) * res
    step_y = math.ceil(height_m / ny / res) * res

    chunks = []
    for iy in range(ny):
        for ix in range(nx):
            cx0, cy0 = x0 + ix * step_x, y0 + iy * step_y
            cx1, cy1 = min(cx0 + step_x, x1), min(cy0 + step_y, y1)
            if cx1 <= cx0 or cy1 <= cy0:
                continue
            chunks.append((iy, ix, cx0, cy0, cx1, cy1))

    keep = [c for c in chunks if intersects_bbox(c[2], c[3], c[4], c[5], bbox)]
    cells = sum(((c[4] - c[2]) / res) * ((c[5] - c[3]) / res) for c in keep)
    return keep, len(chunks), cells, (nx, ny, step_x, step_y, width_m, height_m)


def intersects_bbox(cx0, cy0, cx1, cy1, bbox):
    """Does a chunk (in metres) reach the area bbox (in degrees)?"""
    pts = "\n".join(f"{x} {y}" for x, y in
                     [(cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1),
                      ((cx0 + cx1) / 2, cy0), ((cx0 + cx1) / 2, cy1),
                      (cx0, (cy0 + cy1) / 2), (cx1, (cy0 + cy1) / 2)])
    try:
        out = run(["gdaltransform", "-s_srs", METRIC, "-t_srs", "EPSG:4326"],
                  input=pts).stdout.split()
    except subprocess.CalledProcessError:
        return True  # when it can't be told, compute rather than skip
    xs = [float(v) for v in out[0::3]]
    ys = [float(v) for v in out[1::3]]
    return not (max(xs) < bbox[0] or min(xs) > bbox[2]
                or max(ys) < bbox[1] or min(ys) > bbox[3])


# what `--res=auto` picks from; 1 m is the finest, a z16 tile pixel is 1.57 m anyway
RES_LADDER = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 15.0, 20.0)

# the vectorising grid's floor: finer than a z16 tile pixel can't show on the map
VEC_FLOOR_M = 1.6


def pick_vec_res(res, floor=VEC_FLOOR_M):
    """The vectorising grid: the finest still visible, never finer than the stored slope."""
    for r in RES_LADDER:
        if r < res or r < floor:
            continue
        return r
    return max(res, RES_LADDER[-1])


def pick_res(x0, y0, x1, y1, chunk_cells, bbox, budget_min, dem_cell_m):
    """The finest grid still meaningful (and fitting the budget)."""
    # the area really inside, on a coarse chunk raster – independent of the grid
    side = max(2000.0, math.sqrt((x1 - x0) * (y1 - y0) / 50.0))
    probe, _, _, _ = chunk_plan(x0, y0, x1, y1, 10.0, chunk_cells, bbox,
                                side_m=side)
    area_m2 = sum((c[4] - c[2]) * (c[5] - c[3]) for c in probe)
    if not area_m2:
        return RES_LADDER[3]  # nothing hit – let chunk_plan say it

    # the store grid's floor, both about what shows: a tenth of the DEM cell and a z16 pixel
    floor = max(VEC_FLOOR_M, round((dem_cell_m or 0) / 10.0, 1))
    budget_s = budget_min * 60 if budget_min else float("inf")

    print("── Picking the grid (rock_res=auto) ─────────────────")
    print(f"  area            {area_m2/1e6:.0f} km²")
    print("  budget          " + ("no cap – the finest meaningful one "
                                  "is taken"
                                  if budget_s == float("inf")
                                  else f"{budget_min:g} min"))
    if dem_cell_m:
        print(f"  DEM cell        {dem_cell_m:.0f} m → finer than "
              f"{floor:g} m is meaningless")
    else:
        print(f"  DEM cell        unknown → floor {floor:g} m")
    # two halves, two numbers: at 1 m the slope costs two minutes, vectorising an hour and a half
    chosen = None
    for res in RES_LADDER:
        if res < floor:
            continue
        vec = pick_vec_res(res)
        cells = area_m2 / (res * res)
        s_slope = cells / SLOPE_CELLS_PER_S
        # vectorising is charged to this grid: `gdal_contour` reads the source cells anyway
        s_vec = cells / CONTOUR_SRC_CELLS_PER_S
        est = s_slope + s_vec
        fits = est <= budget_s
        # without a budget the column is an estimate, not a verdict
        mark = "" if budget_s == float("inf") else (
            "  ✓" if fits else "  × over budget")
        print(f"  {res:>4g} m  {cells/1e9:5.2f} G  slope ~{hms(s_slope)}"
              f"  + vectors ~{hms(s_vec)} (traced at {vec:g} m)"
              f"  = ~{hms(est)}{mark}")
        if fits and chosen is None:
            chosen = res
    if chosen is None:
        chosen = RES_LADDER[-1]
        print(f"::warning::Not even the coarsest {chosen:g} m grid fits the "
              f"{hms(budget_s)} budget – try a smaller cut-out (input \"area\").")
    print(f"  picked          {chosen:g} m")
    print("─────────────────────────────────────────────────────", flush=True)
    return chosen


def mosaic_cells(vrt):
    """How many cells the finished slope mosaic has – to estimate vectorising time."""
    try:
        info = json.loads(run(["gdalinfo", "-json", vrt]).stdout)
        w, h = info["size"]
        return float(w) * float(h)
    except Exception:
        return 0.0


def mosaic_info(vrt):
    """(width, height, extent in metres, source count) of a finished mosaic."""
    try:
        info = json.loads(run(["gdalinfo", "-json", vrt]).stdout)
        w, h = info["size"]
        gt = info["geoTransform"]
        x0, y1 = gt[0], gt[3]
        x1, y0 = x0 + gt[1] * w, y1 + gt[5] * h
        try:
            sources = open(vrt).read().count("<SourceFilename")
        except OSError:
            sources = 0
        return int(w), int(h), (x0, y0, x1, y1), sources
    except Exception:
        return 0, 0, None, 0


def clip_vrt(vrt, box, res, tmp, src_res=0.0):
    """The mosaic clipped to exactly the area asked for – coarser when needed."""
    # the VRT is clipped, not the data; `average`, since `nearest` keeps the grain
    x0 = math.floor(box[0] / res) * res
    y0 = math.floor(box[1] / res) * res
    x1 = math.ceil(box[2] / res) * res
    y1 = math.ceil(box[3] / res) * res
    out = os.path.join(tmp, "slope-clip.vrt")
    coarser = ["-r", "average"] if src_res and res > src_res else []
    run(["gdalbuildvrt", "-q", "-te", repr(x0), repr(y0), repr(x1), repr(y1),
         "-tr", repr(res), repr(res)] + coarser + [out, vrt])
    return out
