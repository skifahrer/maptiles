#!/usr/bin/env python3
"""Measure which resampling leaves a grid in the shading (a tool, not a pipeline step).

Usage:
    python3 workers/dem/measure-resampling.py
    python3 workers/dem/measure-resampling.py --seeds=1,2,3,4,5
"""
import argparse
import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import AVERAGE_RATIO, resampling  # noqa: E402

# DMR 5.0 pyramids are 2, 4, 8 … m, so a 5 m target reads from 4 m
NATIVE_M = 1.0
OVR_M = 4.0
GRID_M = 5.0
# EPSG:3046 → EPSG:4326 keeps the scale but drifts the grid phase
DRIFT = 1.002


def _b3(x):
    """Cubic B-spline – the kernel GDAL calls `cubicspline`."""
    x = np.abs(x)
    out = np.zeros_like(x)
    m1, m2 = x < 1, (x >= 1) & (x < 2)
    out[m1] = (4 - 6 * x[m1] ** 2 + 3 * x[m1] ** 3) / 6
    out[m2] = (2 - x[m2]) ** 3 / 6
    return out


def weights(n_src, src_res, n_dst, dst_res, kernel):
    """Resampling matrix along one axis (n_dst × n_src)."""
    W = np.zeros((n_dst, n_src))
    if kernel == "average":
        # like GDAL: whole source pixels in the window, not area weights
        for j in range(n_dst):
            a, b = j * dst_res / src_res, (j + 1) * dst_res / src_res
            i0 = max(0, int(math.floor(a + 1e-9)))
            i1 = min(n_src, max(i0 + 1, int(math.ceil(b - 1e-9))))
            W[j, i0:i1] = 1.0 / (i1 - i0)
        return W
    if kernel == "average-exact":
        # true area average – the reference
        for j in range(n_dst):
            a, b = j * dst_res, (j + 1) * dst_res
            for i in range(max(0, int(a // src_res)),
                           min(n_src, int(math.ceil(b / src_res)))):
                W[j, i] = max(0.0, min(b, (i + 1) * src_res) - max(a, i * src_res))
            s = W[j].sum()
            if s:
                W[j] /= s
        return W
    # only `cubicspline` widens with the scale, so `bilinear` depends on phase
    scale = min(1.0, src_res / dst_res) if kernel == "cubicspline" else 1.0
    rad = {"bilinear": 1.0, "cubicspline": 2.0, "near": 0.5}[kernel] / scale
    for j in range(n_dst):
        c = (j + 0.5) * dst_res / src_res - 0.5
        idx = np.arange(max(0, int(math.floor(c - rad))),
                        min(n_src - 1, int(math.ceil(c + rad))) + 1)
        t = (idx - c) * scale
        if kernel == "bilinear":
            w = np.maximum(0.0, 1.0 - np.abs(t))
        elif kernel == "cubicspline":
            w = _b3(t)
        else:
            w = (np.abs(t) <= 0.5).astype(float)
        s = w.sum()
        if s:
            W[j, idx] = w / s
    return W


def resample(a, src_res, dst_res, kernel, n_dst=None):
    ny, nx = a.shape
    if n_dst is None:
        n_dst = (int(ny * src_res / dst_res) - 2, int(nx * src_res / dst_res) - 2)
    return (weights(ny, src_res, n_dst[0], dst_res, kernel) @ a
            @ weights(nx, src_res, n_dst[1], dst_res, kernel).T)


def terrain(n, res, seed=3, min_lam=0.0):
    """fBm terrain; `min_lam` is the shortest wavelength in metres."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] * res
    z = 300 + 0.004 * x + 0.002 * y
    for k in range(1, 9):
        lam = 2000.0 / (2 ** k)
        if lam < min_lam:
            continue
        amp = 40.0 * (lam / 2000.0) ** 0.85
        for _ in range(3):
            ang, ph = rng.uniform(0, math.pi), rng.uniform(0, 2 * math.pi)
            z += amp * np.sin(2 * math.pi * (x * math.cos(ang)
                                             + y * math.sin(ang)) / lam + ph)
    return z


def hillshade(z, res, az=315.0, alt=45.0):
    dzdx = (np.roll(z, -1, 1) - np.roll(z, 1, 1)) / (2 * res)
    dzdy = (np.roll(z, -1, 0) - np.roll(z, 1, 0)) / (2 * res)
    slope, aspect = np.arctan(np.hypot(dzdx, dzdy)), np.arctan2(dzdy, -dzdx)
    a, zn = math.radians(alt), math.radians(90 - az)
    hs = (math.sin(a) * np.cos(slope)
          + math.cos(a) * np.sin(slope) * np.cos(zn - aspect))
    return np.clip(hs, 0, 1)[2:-2, 2:-2]


def grid_noise(z, res):
    """Mean |Laplacian| of the shading ×10⁻³ – the measure in `workers/lib/cell.py`."""
    hs = hillshade(z, res)
    lap = (np.roll(hs, 1, 0) + np.roll(hs, -1, 0)
           + np.roll(hs, 1, 1) + np.roll(hs, -1, 1) - 4 * hs)
    return float(np.abs(lap[2:-2, 2:-2]).mean()) * 1e3


def variation(z, res, block=32):
    """Roughness variation over the area in % of its mean – the grid the eye sees."""
    hs = hillshade(z, res)
    lap = np.abs(hs[1:-1, 1:-1] * 4 - hs[:-2, 1:-1] - hs[2:, 1:-1]
                 - hs[1:-1, :-2] - hs[1:-1, 2:])
    ny, nx = lap.shape
    b = lap[:ny // block * block, :nx // block * block]
    b = b.reshape(ny // block, block, nx // block, block).mean((1, 3))
    return 100.0 * float(b.std() / b.mean())


def chains(z, fine):
    """Candidate resampling chains, named as in the code."""
    ovr = resample(z, fine, OVR_M, "average-exact")     # .ovr pyramid
    avg = resample(ovr, OVR_M, GRID_M, "average")       # block read
    cs = resample(ovr, OVR_M, GRID_M, "cubicspline")
    n = (avg.shape[0] - 2, avg.shape[1] - 2)
    warp = lambda a, k: resample(a, GRID_M, GRID_M * DRIFT, k, n_dst=n)
    return {
        "reference (straight onto the target grid)":
            resample(z, fine, GRID_M, "average-exact"),
        "BEFORE   average@1.25 + bilinear@1:1": warp(avg, "bilinear"),
        "  only the first step fixed": warp(cs, "bilinear"),
        "  only the second step fixed": warp(avg, "cubicspline"),
        "NOW      cubicspline@1.25 + cubicspline@1:1": warp(cs, "cubicspline"),
        "  (for comparison: second step unfiltered)": warp(cs, "near"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--px", type=int, default=3200, help="side of the fine field")
    ap.add_argument("--fine", type=float, default=0.5, help="step of the fine field (m)")
    args = ap.parse_args()
    seeds = [int(v) for v in args.seeds.split(",") if v.strip()]

    print(f"Pyramid {OVR_M:g} m → target {GRID_M:g} m (ratio "
          f"{GRID_M / OVR_M:.2f}), then to WGS84 at ratio 1.0.")
    print(f"`lib/cell.py` says: resampling({GRID_M:g}, {OVR_M:g}) = "
          f"`{resampling(GRID_M, OVR_M)}` – averaging only from a "
          f"{AVERAGE_RATIO:g}× coarser pixel.\n")

    hl, re_ = {}, {}
    for seed in seeds:
        for name, z in chains(terrain(args.px, args.fine, seed, min_lam=60.0),
                               args.fine).items():
            hl.setdefault(name, []).append(grid_noise(z, GRID_M))
        for name, z in chains(terrain(args.px, args.fine, seed, min_lam=3.0),
                               args.fine).items():
            re_.setdefault(name, []).append(variation(z, GRID_M))

    print(f"{'chain':48s} {'grid':>8s} {'variation':>10s}")
    print(f"{'':48s} {'(smooth)':>8s} {'(real)':>10s}")
    for name in hl:
        print(f"{name:48s} {np.mean(hl[name]):8.1f} "
              f"{np.mean(re_[name]):9.1f} %")
    print(f"\n({len(seeds)} terrains, {args.px}² cells of {args.fine:g} m; "
          f"the closer to the reference, the less grid)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
