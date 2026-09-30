#!/usr/bin/env python3
"""Region mask: "does this place (tile, pixel) belong to the region?"

    m = mask_from_file("data/region.geojson", cells=2048)
    python3 workers/lib/region-mask.py --poly=… --bbox=… --zoom=14
"""
import argparse
import json
import sys


def rings_from_geojson(path):
    """GeoJSON → `[(ring, is_hole)]`; a ring is a list of `(lon, lat)`."""
    with open(path) as f:
        data = json.load(f)
    feats = (data.get("features") if data.get("type") == "FeatureCollection"
             else [data])
    out = []
    for feat in feats or []:
        geom = feat.get("geometry") if "geometry" in feat else feat
        if not geom:
            continue
        polys = ([geom.get("coordinates")] if geom.get("type") == "Polygon"
                 else geom.get("coordinates") or [])
        for poly in polys:
            for i, ring in enumerate(poly or []):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) >= 3:
                    out.append((pts, i > 0))     # first ring = outline
    return out


def inside(rings, x, y):
    """Is the point in the polygon? Ray casting, holes subtracted."""
    ok = False
    for ring, hole in rings:
        c = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xx = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < xx:
                    c = not c
        if c:
            ok = not hole if not hole else False
            if hole:
                return False
    return ok


class Mask:
    """Raster region mask over a bbox."""

    def __init__(self, rings, bbox, cells=2048):
        self.w, self.s, self.e, self.n = bbox
        self.rings = rings
        # aspect kept, so a cell is nearly square
        span_x, span_y = self.e - self.w, self.n - self.s
        if span_x <= 0 or span_y <= 0:
            raise ValueError(f"empty bbox {bbox}")
        self.nx = max(16, int(cells))
        self.ny = max(16, int(cells * span_y / span_x))
        self.dx, self.dy = span_x / self.nx, span_y / self.ny
        self.grid = bytearray(self.nx * self.ny)
        for j in range(self.ny):
            y = self.s + (j + 0.5) * self.dy
            row = j * self.nx
            for i in range(self.nx):
                if inside(rings, self.w + (i + 0.5) * self.dx, y):
                    self.grid[row + i] = 1
        self.hit = sum(self.grid)

    @property
    def pct(self):
        """Percent of the bbox inside the region – the same number as region-poly."""
        return 100.0 * self.hit / (self.nx * self.ny)

    def touches(self, w, s, e, n):
        """Does the window (already grown) touch the region?"""
        if e < self.w or w > self.e or n < self.s or s > self.n:
            return False
        i0 = max(0, int((w - self.w) / self.dx))
        i1 = min(self.nx - 1, int((e - self.w) / self.dx))
        j0 = max(0, int((s - self.s) / self.dy))
        j1 = min(self.ny - 1, int((n - self.s) / self.dy))
        for j in range(j0, j1 + 1):
            row = j * self.nx
            if 1 in self.grid[row + i0:row + i1 + 1]:
                return True
        # a window smaller than a mask cell (high zooms): the centre decides
        return inside(self.rings, (w + e) / 2, (s + n) / 2)


def mask_from_file(path, bbox, cells=2048):
    return Mask(rings_from_geojson(path), bbox, cells)


# a tile mask can't be finer than a tile, so shading needs a pixel one too


def _edges(rings):
    """Rings → four edge arrays (`x1`, `y1`, `x2`, `y2`) for the scanline."""
    x1, y1, x2, y2 = [], [], [], []
    for ring, _hole in rings:
        for i, (ax, ay) in enumerate(ring):
            bx, by = ring[(i + 1) % len(ring)]
            if ay != by:                      # a horizontal edge crosses no row
                x1.append(ax)
                y1.append(ay)
                x2.append(bx)
                y2.append(by)
    return x1, y1, x2, y2


def _dilate(mask, r, np):
    """Mask grown by `r` pixels (square neighbourhood, separable)."""
    if r <= 0:
        return mask
    out = mask.copy()
    for k in range(1, r + 1):
        out[:, k:] |= mask[:, :-k]
        out[:, :-k] |= mask[:, k:]
    mask = out.copy()
    for k in range(1, r + 1):
        out[k:, :] |= mask[:-k, :]
        out[:-k, :] |= mask[k:, :]
    return out


def pixel_mask(rings, box, width, height, grow=0):
    """Bool array `height × width`: is the pixel centre in the region (+ `grow` px)?

    `rings` and `box` share coordinates; row 0 is the top; even-odd fill makes holes.
    """
    import numpy as np
    minx, miny, maxx, maxy = box
    dx, dy = (maxx - minx) / width, (maxy - miny) / height
    ex1, ey1, ex2, ey2 = (np.asarray(a, dtype=np.float64) for a in _edges(rings))
    mask = np.zeros((height, width), dtype=bool)
    if not len(ex1):
        return mask
    lo, hi = min(ey1.min(), ey2.min()), max(ey1.max(), ey2.max())
    for j in range(height):
        y = maxy - (j + 0.5) * dy
        if y < lo or y > hi:
            continue
        cross = (ey1 > y) != (ey2 > y)
        if not cross.any():
            continue
        xs = ex1[cross] + (y - ey1[cross]) * ((ex2 - ex1)[cross]
                                              / (ey2 - ey1)[cross])
        xs.sort()
        # crossing pairs are inside; bounds round inwards to pixel centres
        i0 = np.ceil((xs[0::2] - minx) / dx - 0.5).astype(np.int64)
        i1 = np.floor((xs[1::2] - minx) / dx - 0.5).astype(np.int64)
        row = mask[j]
        for a, b in zip(np.clip(i0, 0, width), np.clip(i1 + 1, 0, width)):
            if b > a:
                row[a:b] = True
    return _dilate(mask, int(grow), np)


def tile_box(z, x, y):
    """XYZ tile window in degrees (lon/lat, Web Mercator)."""
    import math
    n = 2 ** z
    lon1 = x / n * 360.0 - 180.0
    lon2 = (x + 1) / n * 360.0 - 180.0
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat2 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon1, min(lat1, lat2), lon2, max(lat1, lat2)


def tile_touches(mask, z, x, y, grow=0.5):
    """Does the tile belong to the region, allowed to overhang `grow` of its side?"""
    w, s, e, n = tile_box(z, x, y)
    gx, gy = (e - w) * grow, (n - s) * grow
    return mask.touches(w - gx, s - gy, e + gx, n + gy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poly", required=True)
    ap.add_argument("--bbox", required=True, help="west,south,east,north")
    ap.add_argument("--zoom", type=int, default=14)
    ap.add_argument("--cells", type=int, default=2048)
    args = ap.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(","))
    m = mask_from_file(args.poly, bbox, args.cells)
    print(f"Region mask: {m.nx}×{m.ny} cells, {m.pct:.1f} % of bbox in the region")
    import math
    n = 2 ** args.zoom
    def xt(lon):
        return int((lon + 180.0) / 360.0 * n)
    def yt(lat):
        r = math.radians(lat)
        return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    x0, x1 = xt(bbox[0]), xt(bbox[2])
    y0, y1 = yt(bbox[3]), yt(bbox[1])
    total = (x1 - x0 + 1) * (y1 - y0 + 1)
    inside_n = sum(1 for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
                   if tile_touches(m, args.zoom, x, y))
    print(f"z{args.zoom}: {inside_n} of {total} tiles touch the region "
          f"({total - inside_n} outside, so "
          f"{100 * (total - inside_n) / total:.0f} % of the work is saved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
