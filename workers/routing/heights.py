#!/usr/bin/env python3
"""Heights from the model – a profile along each edge at a fixed step, bilinear from the mosaic."""
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402

E7 = 1e7
# `gdalwarp` sentinel; never 0 – zero is a valid height
NODATA = -9999.0
# margin so bilinear sampling has a neighbour at the edge too
MARGIN_PX = 2
# sampling window side in pixels; a whole degree of a 5 m model would be 1.3 GB
WINDOW_PX = 4096
DEGREE_M = 111320.0
# distance between profile samples
STEP_M = 5.0
# bridges and tunnels don't stand on the terrain, so their profile is a straight line
ABOVE_TERRAIN = ("bridge", "tunnel")


def resolution(dem):
    info = json.loads(subprocess.run(["gdalinfo", "-json", dem], check=True,
                                     capture_output=True, text=True).stdout)
    gt = info["geoTransform"]
    return abs(gt[1]), abs(gt[5])


def _size(hdr):
    text = open(hdr, encoding="utf-8").read()
    w = int(re.search(r"^samples\s*=\s*(\d+)", text, re.M).group(1))
    h = int(re.search(r"^lines\s*=\s*(\d+)", text, re.M).group(1))
    return w, h


def _grid(dem, path, w, s, e, n, dx, dy):
    """A mosaic cutout at native resolution as raw Float32."""
    subprocess.run(
        ["gdalwarp", "-q", "-overwrite", "-te", *map(repr, (w, s, e, n)),
         "-tr", repr(dx), repr(dy), "-r", "near", "-ot", "Float32",
         "-dstnodata", str(NODATA), "-of", "ENVI", dem, path],
        check=True)
    width, height = _size(os.path.splitext(path)[0] + ".hdr")
    return np.fromfile(path, dtype="<f4").reshape(height, width)


def bilinear(grid, col, row):
    """Height at a grid point; a missing neighbour gets no weight, none at all is NaN."""
    h, w = grid.shape
    c = np.clip(col, 0, w - 1)
    r = np.clip(row, 0, h - 1)
    c0 = np.floor(c).astype(np.int64)
    r0 = np.floor(r).astype(np.int64)
    c1 = np.minimum(c0 + 1, w - 1)
    r1 = np.minimum(r0 + 1, h - 1)
    fc, fr = c - c0, r - r0
    total = np.zeros(len(c), dtype=np.float64)
    weights = np.zeros(len(c), dtype=np.float64)
    for rr, cc, weight in ((r0, c0, (1 - fr) * (1 - fc)), (r0, c1, (1 - fr) * fc),
                           (r1, c0, fr * (1 - fc)), (r1, c1, fr * fc)):
        v = grid[rr, cc].astype(np.float64)
        valid = v > NODATA + 1.0
        total += np.where(valid, v * weight, 0.0)
        weights += np.where(valid, weight, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(weights > 0, total / weights, np.nan)


def _by_windows(lat, lon, window):
    """Points by squares of side `window` – one grid in memory at a time."""
    key = np.stack([np.floor(lon / window), np.floor(lat / window)],
                   axis=1).astype(np.int64)
    cells, where = np.unique(key, axis=0, return_inverse=True)
    for i, (west, south) in enumerate(cells):
        yield west * window, south * window, np.flatnonzero(where.ravel() == i)


def sample(dem, lat, lon, tmp="/tmp/routing-heights"):
    """Height (m) for every point, NaN where the model has nothing."""
    dx, dy = resolution(dem)
    window = min(1.0, max(dx, dy) * WINDOW_PX)
    out = np.full(len(lat), np.nan)
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "grid.raw")
    for west, south, idx in _by_windows(lat, lon, window):
        la, lo = lat[idx], lon[idx]
        # aligned to source pixels, so pixel centres don't shift
        w = west + math.floor((lo.min() - west) / dx - MARGIN_PX) * dx
        e = west + math.ceil((lo.max() - west) / dx + MARGIN_PX) * dx
        s = south + math.floor((la.min() - south) / dy - MARGIN_PX) * dy
        n = south + math.ceil((la.max() - south) / dy + MARGIN_PX) * dy
        grid = _grid(dem, path, w, s, e, n, dx, dy)
        out[idx] = bilinear(grid, (lo - w) / dx - 0.5, (n - la) / dy - 0.5)
        del grid
    return out


def fill_from_neighbours(heights, edges, nodes):
    """A node without a height takes a graph neighbour's – while there is one."""
    missing = set(nodes) - set(heights)
    while missing:
        new = {}
        for h in edges:
            a, b = h["from"], h["to"]
            if a in missing and b in heights:
                new[a] = heights[b]
            elif b in missing and a in heights:
                new[b] = heights[a]
        if not new:
            break
        heights.update(new)
        missing -= set(new)
    return len(missing)


def fill(network, dem):
    """`network.heights` from the model; returns (from model, from neighbours, none)."""
    ids = list(network.nodes)
    lat = np.array([network.nodes[u][0] for u in ids], dtype=np.float64) / E7
    lon = np.array([network.nodes[u][1] for u in ids], dtype=np.float64) / E7
    v = sample(dem, lat, lon)
    has = ~np.isnan(v)
    heights = {u: int(round(float(x))) for u, x, ok in zip(ids, v, has) if ok}
    from_model = len(heights)
    if not heights:
        return 0, 0, len(ids)
    none = fill_from_neighbours(heights, network.edges, ids)
    network.heights = heights
    return from_model, len(heights) - from_model, none


def _samples(points, step_m, length_m):
    """Points along the polyline every `step_m`; the last is always the edge's end."""
    lat = np.array([b[0] for b in points], dtype=np.float64) / E7
    lon = np.array([b[1] for b in points], dtype=np.float64) / E7
    # planar approximation places samples, it doesn't measure length
    dy = np.diff(lat) * DEGREE_M
    dx = np.diff(lon) * DEGREE_M * math.cos(math.radians(float(lat.mean())))
    at = np.concatenate([[0.0], np.cumsum(np.hypot(dx, dy))])
    if at[-1] <= 0 or length_m <= 0:
        return lat[:1], lon[:1]
    # the phone counts samples from `length_cm`, so they're placed by it
    at *= length_m / at[-1]
    n = fmt.sample_count(length_m, step_m)
    pos = np.arange(n - 1) * step_m
    pos = np.append(pos, length_m)
    return np.interp(pos, at, lat), np.interp(pos, at, lon)


def _no_holes(v):
    """Holes in a profile bridged from valid neighbours; an empty one stays empty."""
    valid = ~np.isnan(v)
    if not valid.any():
        return None
    if valid.all():
        return v
    at = np.flatnonzero(valid)
    return np.interp(np.arange(len(v)), at, v[at])


def _smoothed(v):
    """[1 2 1] twice – at a 5 m step the model's noise exceeds the road's slope."""
    if len(v) < 3:
        return v
    for _ in range(2):
        v = np.concatenate([v[:1], (v[:-2] + 2 * v[1:-1] + v[2:]) / 4, v[-1:]])
    return v


def _straight(v):
    return np.linspace(v[0], v[-1], len(v))


def profiles(network, dem, step_m=STEP_M):
    """`edge["profile"]` – heights in dm every `step_m`; returns (with profile, without)."""
    lat, lon, pieces = [], [], []
    for h in network.edges:
        la, lo = _samples([network.nodes[h["from"]], *h["geom"], network.nodes[h["to"]]],
                          step_m, h["length_cm"] / 100)
        pieces.append(len(la))
        lat.append(la)
        lon.append(lo)
    if not pieces:
        return 0, 0
    v = sample(dem, np.concatenate(lat), np.concatenate(lon))
    del lat, lon

    with_profile = 0
    for h, piece in zip(network.edges, np.split(v, np.cumsum(pieces)[:-1])):
        whole = _no_holes(piece)
        if whole is None or len(whole) < 2:
            h["profile"] = []
            continue
        if any(h["tags"].get(k, "no") not in ("no", "") for k in ABOVE_TERRAIN):
            whole = _straight(whole)
        else:
            whole = _smoothed(whole)
        h["profile"] = [int(round(x * 10)) for x in whole]
        with_profile += 1
    return with_profile, len(network.edges) - with_profile


def _to_nodes(h, from_dm, to_dm):
    """Profile ends onto node heights; the difference spreads along the edge, no jump."""
    p = h["profile"]
    d0, d1 = from_dm - p[0], to_dm - p[-1]
    if d0 or d1:
        fix = np.linspace(d0, d1, len(p))
        h["profile"] = [int(round(v + o)) for v, o in zip(p, fix)]


def fill_with_profiles(network, dem, step_m=STEP_M):
    """Edge profiles, and node heights from their ends – one sampling for both."""
    with_profile, without_profile = profiles(network, dem, step_m)
    ends = {}
    for h in network.edges:
        p = h.get("profile")
        if p:
            ends.setdefault(h["from"], []).append(p[0])
            ends.setdefault(h["to"], []).append(p[-1])
    node_dm = {u: int(round(sum(v) / len(v))) for u, v in ends.items()}
    for h in network.edges:
        if h.get("profile"):
            _to_nodes(h, node_dm[h["from"]], node_dm[h["to"]])
    heights = {u: int(round(dm / 10)) for u, dm in node_dm.items()}
    from_model = len(heights)
    if not heights:
        return 0, 0, len(network.nodes), with_profile, without_profile
    none = fill_from_neighbours(heights, network.edges, list(network.nodes))
    network.heights = heights
    return (from_model, len(heights) - from_model, none, with_profile, without_profile)
