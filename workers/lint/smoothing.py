#!/usr/bin/env python3
"""Outline rounding must neither break nor silently roll back."""
import importlib.util
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_WORKERS)
SMOOTH = os.path.join(_WORKERS, "contours-rocks", "smooth-shapes.py")
KEYS = os.path.join(_WORKERS, "plan", "cache-keys.sh")
# rounding is tuned in the DEM layers workflow's `env:`, regeneration needs it too
WF = os.path.join(_ROOT, ".github", "workflows", "dem-layers.yml")

# who rounds; the path is relative to `workers/`
CALLERS = [
    ("contours-rocks/build.sh", "workers/contours-rocks/smooth-shapes.py"),
    ("contours-rocks/rock-areas.py", "smooth-shapes.py"),
    ("rocks-shading/vector.py", "smooth-shapes.py"),
]

sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    bad = []
    sm = load("smooth_shapes", SMOOTH)

    # 1. the path to the script and 2./3. what it is passed
    for rel, _ in CALLERS:
        src = open(os.path.join(_WORKERS, rel)).read()
        if "smooth-shapes.py" not in src:
            bad.append(f"`workers/{rel}` no longer calls `smooth-shapes.py`. If "
                       f"rounding moved, fix this list too – two copies of "
                       f"rounding drift and one layer ends smoother than another.")
            continue
        for opt in ("--maxzoom", "--sag"):
            if opt not in src:
                bad.append(f"`workers/{rel}` calls `smooth-shapes.py` without "
                           f"`{opt}`. Without `--maxzoom` z16 is silently taken "
                           f"and a lower zoom's layer is sampled finer than a "
                           f"tile holds; without `--sag` the sag can't be set.")
    # a path from another folder must not go through `dirname(__file__)`
    ext = open(os.path.join(_WORKERS, "rocks-shading", "vector.py")).read()
    m = re.search(r"os\.path\.join\(([^)]*?)\"smooth-shapes\.py\"", ext, re.S)
    if not m or "contours-rocks" not in m.group(1):
        bad.append("`workers/rocks-shading/vector.py` doesn't build the path to "
                   "`smooth-shapes.py` through `contours-rocks` – the file is "
                   "there and nowhere else. The step would fail on "
                   "FileNotFoundError after hours of downloading tiles.")

    # which maxzoom goes to which layer – a swap is silent; build.sh and rocks.sh are one script
    build = "".join(
        open(os.path.join(_WORKERS, "contours-rocks", n)).read()
        for n in ("build.sh", "rocks.sh"))
    for what, arg in (("contours", '--maxzoom="$OPT_CONTOUR_MAXZOOM"'),
                      ("rocks", '--maxzoom="$OPT_ROCK_MAXZOOM"')):
        if arg not in build:
            bad.append(f"Neither `workers/contours-rocks/build.sh` nor its second "
                       f"half `rocks.sh` has `{arg}` – rounding the {what} would "
                       f"follow another layer's grid (or the default z16). A "
                       f"silent difference in point density.")

    # 3. the sag stays under the grid step
    wf = open(WF).read()
    for key in ("CONTOUR_SMOOTH", "ROCK_SMOOTH"):
        m = re.search(rf'^\s*{key}:\s*"(\d+)"', wf, re.M)
        if not m:
            bad.append(f"`dem-layers.yml` has no `{key}` – rounding follows the "
                       f"script's default and the form lies about it.")
            continue
        sag = int(m.group(1))
        if sag > 4:
            bad.append(f"`{key}` is {sag}, a sag of {sag / 4:.2f} tile grid "
                       f"steps. Over one step sampling is a bigger error than "
                       f"snapping to the tile (±half a step) and the chords "
                       f"show as facets.")

    # 4. ends and rings: an open line's ends must not move, or tile pieces won't meet
    line = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0), (30.0, 0.0)]
    out = sm.curve_line(line, 0.05)
    if tuple(out[0]) != line[0] or tuple(out[-1]) != line[-1]:
        bad.append(f"The rounded line doesn't start and end where the original "
                   f"did ({out[0]} … {out[-1]} instead of {line[0]} … "
                   f"{line[-1]}). That leaves a gap at a tile border.")
    if len(out) <= len(line):
        bad.append("Rounding the line added no point – no corner was rounded.")

    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    ring = sm.curve_ring(square, 0.05)
    if tuple(ring[0]) != tuple(ring[-1]):
        bad.append(f"The rounded ring isn't closed ({ring[0]} vs "
                   f"{ring[-1]}) – the area becomes an invalid polygon.")

    # the sag really stays under the tolerance: distance from the curve, not chord angles
    def distance(point, line):
        x, y = point
        best = float("inf")
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            dx, dy = x1 - x0, y1 - y0
            n2 = dx * dx + dy * dy
            t = 0.0 if n2 == 0 else max(0.0, min(
                1.0, ((x - x0) * dx + (y - y0) * dy) / n2))
            best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
        return best

    corner = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    for tol in (0.5, 0.05, 0.005):
        coarse = sm.curve_line(corner, tol)
        exact = sm.curve_line(corner, tol / 100.0)
        worst = max(distance(b, coarse) for b in exact)
        if worst > tol * 1.2:
            bad.append(f"At a {tol} m tolerance the sampled curve strays "
                       f"{worst:.3f} m from its exact course – sampling doesn't "
                       f"keep the sag it promises, and the map shows facets.")

    # a finer tolerance must not give fewer points
    few = len(sm.curve_line([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], 1.0))
    many = len(sm.curve_line([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], 0.01))
    if many <= few:
        bad.append(f"A ten times finer tolerance gave {many} points against "
                   f"{few} – sampling doesn't follow the sag.")

    # 5. the grid step is one number
    for z in (11, 14, 16):
        step = cell.tile_grid_m(z)
        expected = cell.tile_m_per_px(z) * cell.TILE_PX / cell.TILE_EXTENT
        if abs(step - expected) > 1e-12:
            bad.append(f"`cell.tile_grid_m({z})` doesn't match the tile pixel – "
                       f"the grid step and the pixel size are one question.")
    if cell.TILE_EXTENT != 4096:
        bad.append(f"`cell.TILE_EXTENT` is {cell.TILE_EXTENT}. Planetiler can't "
                   f"change `extent`, it is 4096 – another number means sampling "
                   f"to a grid that doesn't exist.")

    # 6. old data must not come back; the version number is in `C_SETTINGS`
    keys = open(KEYS).read()
    if not re.search(r'^C_SETTINGS="contours-v(\d+)-', keys, re.M):
        bad.append("`workers/plan/cache-keys.sh` has no version in the contours "
                   "key (`C_SETTINGS=\"contours-v<number>-…\"`). A change of "
                   "contour shape wouldn't show – the cache returns the old ones "
                   "and the build is green.")
    if not re.search(r"^\s*ROCK_ALGO:\s*v\d+", wf, re.M):
        bad.append("`dem-layers.yml` has no `ROCK_ALGO: v<number>` – the rock "
                   "asset name wouldn't carry the outline SHAPE and the store "
                   "would return the old jagged rocks.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Rounding: the script path is right, every call knows its grid, the "
          "sag holds and the ends stay ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
