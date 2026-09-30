#!/usr/bin/env python3
"""Terrain tiles → one `.pmtiles` (raster, terrarium PNG).

One file instead of a tree of thousands of PNGs: the same shape on Pages and in
the store, extent and zooms in its header. Identical tiles (plane, water level)
are stored once thanks to hashing. Written in Hilbert order so the archive is
"clustered".

    python3 workers/terrain/pack.py --in=terrain-out \\
        --out=_site/tiles/presovsky-terrain.pmtiles --name=presovsky
"""
import argparse
import math
import os
import sys

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

TILE = 256


def tile_bounds(z, x, y):
    """The geographic rectangle of an XYZ tile (west, south, east, north)."""
    n = 2.0**z
    w = x / n * 360.0 - 180.0
    e = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return w, south, e, north


def collect(src):
    """Find `{z}/{x}/{y}.png` and return sorted [(tileid, z, x, y, path)]."""
    out = []
    for zd in os.listdir(src):
        if not zd.isdigit():
            continue                      # `maxzoom.txt` and the like
        z = int(zd)
        zpath = os.path.join(src, zd)
        if not os.path.isdir(zpath):
            continue
        for xd in os.listdir(zpath):
            if not xd.isdigit():
                continue
            x = int(xd)
            xpath = os.path.join(zpath, xd)
            for name in os.listdir(xpath):
                base, ext = os.path.splitext(name)
                if ext != ".png" or not base.isdigit():
                    continue
                y = int(base)
                out.append((zxy_to_tileid(z, x, y), z, x, y,
                            os.path.join(xpath, name)))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True,
                    help="directory of {z}/{x}/{y}.png tiles")
    ap.add_argument("--out", dest="dst", required=True, help="target .pmtiles")
    ap.add_argument("--name", default="terrain", help="name for the metadata")
    ap.add_argument("--clip-bbox", default="",
                    help="west,south,east,north – the extent the header is "
                         "clipped to (the run's bbox). Without it the tiles' "
                         "whole extent, half of Europe at a low zoom.")
    ap.add_argument("--source", default="",
                    help="elevation model key (`sonny`, `dmr5`…) for the metadata")
    args = ap.parse_args()

    tiles = collect(args.src)
    if not tiles:
        print(f"::error::Not a single tile in {args.src} – "
              f"nothing to pack.", file=sys.stderr)
        return 1

    minz = min(d[1] for d in tiles)
    maxz = max(d[1] for d in tiles)
    # extent from tiles really made, over all zooms: maxzoom alone skips flat tiles
    w = s = e = n = None
    for _tid, z, x, y, _p in tiles:
        tw, ts, te, tn = tile_bounds(z, x, y)
        w = tw if w is None else min(w, tw)
        s = ts if s is None else min(s, ts)
        e = te if e is None else max(e, te)
        n = tn if n is None else max(n, tn)

    # a z5 tile spans 11.25°; MapLibre intersects bounds, so no tile is lost
    if args.clip_bbox:
        cw, cs, ce, cn = (float(v) for v in args.clip_bbox.split(","))
        w, s = max(w, cw), max(s, cs)
        e, n = min(e, ce), min(n, cn)
        if e <= w or n <= s:
            print(f"::error::Clipping the header to {args.clip_bbox} misses "
                  f"the tiles' extent – the tiles are from another area than "
                  f"the run's bbox says.", file=sys.stderr)
            return 1

    raw = 0
    with open(args.dst, "wb") as f:
        wr = Writer(f)
        for _tid, _z, _x, _y, p in tiles:
            with open(p, "rb") as t:
                data = t.read()
            raw += len(data)
            wr.write_tile(_tid, data)
        wr.finalize(
            {
                "tile_type": TileType.PNG,
                # PNG is already compressed
                "tile_compression": Compression.NONE,
                "min_zoom": minz,
                "max_zoom": maxz,
                "min_lon_e7": int(w * 1e7),
                "min_lat_e7": int(s * 1e7),
                "max_lon_e7": int(e * 1e7),
                "max_lat_e7": int(n * 1e7),
                "center_zoom": maxz,
                "center_lon_e7": int((w + e) / 2 * 1e7),
                "center_lat_e7": int((s + n) / 2 * 1e7),
            },
            {
                "name": args.name,
                "format": "png",
                # without it `raster-dem` draws coloured noise instead of relief
                "encoding": "terrarium",
                "description": "Terrarium PNG – elevation in RGB "
                               "(v = R*256 + G + B/256 − 32768)",
                # the archive can be downloaded on its own – the model is named nowhere else
                **({"source": args.source} if args.source else {}),
            },
        )

    size = os.path.getsize(args.dst)
    saved = raw - size
    print(f"{args.dst}: {len(tiles)} tiles z{minz}–z{maxz}, "
          f"{size / 1048576:.1f} MB "
          f"(from {raw / 1048576:.1f} MB in separate files – "
          f"{'saved' if saved >= 0 else 'extra'} "
          f"{abs(saved) / 1048576:.1f} MB on identical tiles "
          f"and file overhead)")
    print(f"  extent {w:.4f},{s:.4f},{e:.4f},{n:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
