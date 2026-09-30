#!/usr/bin/env python3
"""What is written where we have no height or don't want one."""
import numpy as np


# `gdalwarp` sentinel; must not be 0 – zero is a valid height
NODATA = -9999.0


def fill_nodata(grid, missing):
    """Fill missing heights with the nearest valid one, not a constant."""
    if not missing.any() or missing.all():
        return grid
    g = grid
    valid = ~missing
    # rows first, then columns: a corner pixel may have no valid neighbour in either
    for axis in (1, 0):
        n = g.shape[axis]
        shape = [1, 1]
        shape[axis] = n
        idx = np.broadcast_to(np.arange(n).reshape(shape), g.shape)
        fwd = np.maximum.accumulate(np.where(valid, idx, -1), axis=axis)
        back = np.flip(np.minimum.accumulate(
            np.flip(np.where(valid, idx, n), axis=axis), axis=axis), axis=axis)
        d_fwd = np.where(fwd < 0, n + 1, idx - fwd)
        d_back = np.where(back >= n, n + 1, back - idx)
        v_fwd = np.take_along_axis(g, fwd.clip(0, n - 1), axis)
        v_back = np.take_along_axis(g, back.clip(0, n - 1), axis)
        has_fwd, has_back = d_fwd <= n, d_back <= n
        # linear between two valid sides: jumping to the nearer one leaves a seam
        total = np.where(has_fwd, d_fwd, 0) + np.where(has_back, d_back, 0)
        share = np.divide(np.where(has_back, d_back, 0), np.maximum(total, 1),
                          dtype=np.float64)
        both = has_fwd & has_back
        value = np.where(both, v_fwd * share + v_back * (1.0 - share),
                         np.where(has_fwd, v_fwd, v_back))
        found = has_fwd | has_back
        g = np.where(valid, g, np.where(found, value.astype(g.dtype), g))
        valid = valid | found
    return g


def edge_height(grid, known):
    """Median height on the region's edge – the plane outside, keeping the wall low."""
    inner = known.copy()
    inner[1:, :] &= known[:-1, :]
    inner[:-1, :] &= known[1:, :]
    inner[:, 1:] &= known[:, :-1]
    inner[:, :-1] &= known[:, 1:]
    edge = grid[known & ~inner]
    if not edge.size:
        edge = grid[known]
    return float(np.median(edge)) if edge.size else 0.0


def flatten_outside(grid, known, height):
    """One height for the whole run outside the region – a plane has no slope to shade."""
    return np.where(known, grid, np.asarray(height, dtype=grid.dtype))
