#!/usr/bin/env python3
"""How much contour smoothing is just right – measured, not guessed.

Not part of the pipeline: the tool that picked `CONTOUR_DEM_LOWPASS`,
`CONTOUR_SIMPLIFY` and `CONTOUR_SMOOTH`. Also measured on the tile grid, whose
rounded coordinates are the stairs seen at max zoom.

    python3 workers/contours-rocks/measure-smoothing.py [--seed=7]
"""
import argparse
import importlib.util
import math
import os
import sys

import numpy as np

# the same curve the pipeline sends; the dash in the name blocks import
_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


shapes = _load("smooth_shapes", "smooth-shapes.py")
# lib/cell.py tells the tile grid step
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lib"))
import cell  # noqa: E402

NX, NY = 640, 320          # 1 m grid
LAT = 49.1                 # latitude (Tatras) – for the tile grid
EXTENT = cell.TILE_EXTENT  # the vector tile's coordinate grid
SLOPE = 0.10               # a 10 % slope – the isoline is then a graph y(x)
# real terrain shapes: (wavelength m, amplitude m)
FEATS = [(60.0, 1.20), (25.0, 0.50), (12.0, 0.22)]
NOISE = 0.15               # micro-relief: shrubs, boulders, measurement noise
LEVEL = 16.0


def feature(x):
    out = np.zeros_like(x, dtype=float)
    for lam, amp in FEATS:
        out += amp * np.sin(2 * math.pi * x / lam + lam)
    return out


def terrain(rng=None):
    X, Y = np.meshgrid(np.arange(NX, dtype=float), np.arange(NY, dtype=float))
    Z = SLOPE * Y + feature(X)
    return Z if rng is None else Z + rng.normal(0.0, NOISE, Z.shape)


def lowpass(Z, win):
    """A mean over a `win`×`win` window and back to the grid (two gdalwarps)."""
    if win <= 1:
        return Z
    ny, nx = Z.shape
    my, mx = ny // win, nx // win
    C = Z[:my * win, :mx * win].reshape(my, win, mx, win).mean(axis=(1, 3))
    cy = (np.arange(my) + 0.5) * win - 0.5
    cx = (np.arange(mx) + 0.5) * win - 0.5
    tmp = np.vstack([np.interp(np.clip(np.arange(nx), cx[0], cx[-1]), cx, row)
                     for row in C])
    return np.column_stack([
        np.interp(np.clip(np.arange(ny), cy[0], cy[-1]), cy, col)
        for col in tmp.T])


# marching squares: how gdal_contour traces an isoline too
def _edge(p, q, zp, zq, level):
    t = (level - zp) / (zq - zp)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def contour(Z, level):
    ny, nx = Z.shape
    segs = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            z = (Z[j, i], Z[j, i + 1], Z[j + 1, i + 1], Z[j + 1, i])
            c = ((float(i), float(j)), (float(i + 1), float(j)),
                 (float(i + 1), float(j + 1)), (float(i), float(j + 1)))
            if all(v >= level for v in z) or all(v < level for v in z):
                continue
            pts = [_edge(c[k], c[(k + 1) % 4], z[k], z[(k + 1) % 4], level)
                   for k in range(4)
                   if (z[k] >= level) != (z[(k + 1) % 4] >= level)]
            if len(pts) == 2:
                segs.append((pts[0], pts[1]))
            elif len(pts) == 4:          # a saddle – the cell centre decides
                if (sum(z) / 4 >= level) == (z[0] >= level):
                    segs += [(pts[0], pts[1]), (pts[2], pts[3])]
                else:
                    segs += [(pts[1], pts[2]), (pts[3], pts[0])]
    return longest_chain(segs)


def longest_chain(segs):
    """The longest continuous line – across the cut-out, not crumbs at the edge."""
    def key(p):
        return round(p[0], 6), round(p[1], 6)

    adj = {}
    for si, (a, b) in enumerate(segs):
        adj.setdefault(key(a), []).append((si, 0))
        adj.setdefault(key(b), []).append((si, 1))
    used = [False] * len(segs)
    best = []
    for start in range(len(segs)):
        if used[start]:
            continue
        chain = list(segs[start])
        used[start] = True
        for at_end in (0, 1):
            while True:
                tip = chain[-1] if at_end else chain[0]
                nxt = next(((si, s) for si, s in adj.get(key(tip), [])
                            if not used[si]), None)
                if nxt is None:
                    break
                si, side = nxt
                used[si] = True
                other = segs[si][1 - side]
                chain.append(other) if at_end else chain.insert(0, other)
        if len(chain) > len(best):
            best = chain
    return best


# the same as ogr2ogr -simplify and smooth-shapes.py do
def simplify(pts, tol):
    if tol <= 0 or len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        (x0, y0), (x1, y1) = pts[a], pts[b]
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy) or 1e-12
        dmax, imax = 0.0, a
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / norm
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol:
            keep[imax] = True
            stack += [(a, imax), (imax, b)]
    return [p for p, k in zip(pts, keep) if k]


def chaikin(pts, passes):
    """Corner cutting – the pipeline's former state, for comparison only."""
    pts = list(pts)
    for _ in range(passes):
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        out.append(pts[-1])
        pts = out
    return pts


def limit(pts, sag, maxzoom):
    """The limit curve from smooth-shapes.py; `sag` in quarters of the grid step."""
    tol = tile_step(maxzoom) * sag / 4.0
    return shapes.curve_line([tuple(p) for p in pts], tol)


# metrics
def tile_step(z, lat=LAT):
    """The tile grid step in metres at a zoom."""
    return cell.tile_grid_m(z, lat)


def quantize(pts, step):
    """Snapping to the tile grid – what writing an MVT does."""
    return [(round(x / step) * step, round(y / step) * step) for x, y in pts]


def bends(pts):
    out = []
    for (xa, ya), (xb, yb), (xc, yc) in zip(pts, pts[1:], pts[2:]):
        ux, uy, vx, vy = xb - xa, yb - ya, xc - xb, yc - yb
        nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
        if nu < 1e-12 or nv < 1e-12:
            continue
        out.append(math.degrees(math.acos(
            max(-1.0, min(1.0, (ux * vx + uy * vy) / (nu * nv))))))
    return np.array(out or [0.0])


def resample(pts, step=0.5):
    """Evenly by length – otherwise metrics would weigh dense stretches."""
    P = np.asarray(pts)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    s = np.arange(0, d[-1], step)
    return np.c_[np.interp(s, d, P[:, 0]), np.interp(s, d, P[:, 1])]


def metrics(pts):
    R = resample(pts)
    R = R[(R[:, 0] > 20) & (R[:, 0] < NX - 20)]     # skip the cut-out's edges
    dev = math.sqrt(float(np.mean((R[:, 1] - (LEVEL - feature(R[:, 0]))
                                   / SLOPE) ** 2)))
    x = R[:, 0]
    cols = [np.ones_like(x), x]
    for lam, _ in FEATS:
        cols += [np.sin(2 * math.pi * x / lam), np.cos(2 * math.pi * x / lam)]
    coef = np.linalg.lstsq(np.vstack(cols).T, R[:, 1], rcond=None)[0]
    shapes_kept = [100.0 * math.hypot(coef[2 + 2 * k], coef[3 + 2 * k])
             / (amp / SLOPE) for k, (_, amp) in enumerate(FEATS)]
    return dev, shapes_kept


# the resampling step before measuring teeth – the same for every row
SHAPE_STEP = 0.5


def per_km(pts, thr=30.0):
    """Sharp bends per kilometre, after even resampling (or density is measured)."""
    R = resample(pts, SHAPE_STEP)
    ang = bends([tuple(p) for p in R])
    km = SHAPE_STEP * len(R) / 1000.0
    return float(np.sum(ang > thr)) / km if km else 0.0


def run(Z, win, quarters, how, label, maxzoom):
    """`how` = ("chaikin", passes) or ("limit", sag in 1/4)."""
    simp = simplify(contour(lowpass(Z, win), LEVEL), quarters / 4.0)
    pts = (chaikin(simp, how[1]) if how[0] == "chaikin"
           else limit(simp, how[1], maxzoom))
    ang = bends(pts)
    dev, kept = metrics(pts)
    # and the same on the tile grid – how it ends in .pmtiles
    qpts = quantize(pts, tile_step(maxzoom))
    qang = bends(qpts)
    print(f"{label:50s} {len(pts):5d} {ang.mean():6.1f}° "
          f"{100 * float(np.mean(ang > 30)):5.1f}% {per_km(pts):6.1f} "
          f"{dev:6.2f} m "
          + " ".join(f"{t:4.0f}%" for t in kept)
          + f"  │ {qang.mean():6.1f}° {100 * float(np.mean(qang > 30)):5.1f}%"
          f" {per_km(qpts):6.1f}")


def main():
    ap = argparse.ArgumentParser(
        description="Measuring contour smoothing on simulated terrain.")
    ap.add_argument("--seed", type=int, default=20260810)
    ap.add_argument("--maxzoom", type=int, default=14,
                    help="maxzoom of the contour tiles (a 4096 grid)")
    args = ap.parse_args()

    Z = terrain(np.random.default_rng(args.seed))
    lam = "  ".join(f"{int(l)} m" for l, _ in FEATS)
    step = tile_step(args.maxzoom)
    print(f"terrain: slope {SLOPE:.0%}, noise σ = {NOISE} m, shapes {lam}, "
          f"seed {args.seed}")
    print(f"tiles: maxzoom z{args.maxzoom} → grid {step:.3f} m "
          f"(extent {EXTENT}, latitude {LAT}°)")
    print(f"{'setting':50s} {'points':>5s} {'bend':>7s} {'>30°':>6s} "
          f"{'teeth/km':>6s} {'deviation':>8s}  shapes (λ 60 / 25 / 12 m)"
          f"  │ on the z{args.maxzoom} grid: bend, >30°, teeth/km")
    run(terrain(), 1, 0, ("chaikin", 0),
        "reference (terrain without noise, untouched)", args.maxzoom)
    print()
    for win, q, how, note in [
        (1, 1, ("chaikin", 1), "  ← 2025"),
        (5, 2, ("chaikin", 2), "  ← August (rounded)"),
        (3, 1, ("chaikin", 1), ""),
        (3, 1, ("chaikin", 2), "  ← until now"),
        (3, 1, ("chaikin", 3), "  (teeth gone, but the grid worse)"),
        (3, 1, ("limit", 1), ""),
        (3, 1, ("limit", 2), "  ← now"),
        (3, 1, ("limit", 4), ""),
        (7, 2, ("limit", 2), ""),
    ]:
        window = f"window {win}×{win}" if win > 1 else "no smoothing"
        rounding = (f"{how[1]}× Chaikin" if how[0] == "chaikin"
                    else f"limit, sag {how[1]}/4 grid")
        run(Z, win, q, how, f"{window}, {q}/4 cell, {rounding}{note}", args.maxzoom)


if __name__ == "__main__":
    main()
