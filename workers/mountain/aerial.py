#!/usr/bin/env python3
"""A mountain's aerial photos: XYZ JPEG tiles over its box → one raster `.pmtiles`.

    python3 workers/mountain/aerial.py --season=summer --bbox=19.9,49.09,20.32,49.25 \
        --out=_site/tiles/vysoke_tatry-aerial_summer.pmtiles --cache=aerial-cache
"""
import argparse
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)


def _load(name, path):
    """By path: `workers/dem/tiles.py` is another `tiles` module."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tiles = _load("shading_tiles", os.path.join(_WORKERS, "rocks-shading", "tiles.py"))
Fetcher, tile_range, lonlat_to_tile = _tiles.Fetcher, _tiles.tile_range, _tiles.lonlat_to_tile


def season(name, path=os.path.join(_WORKERS, "data", "aerial.json")):
    with open(path, encoding="utf-8") as f:
        known = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    if name not in known:
        raise SystemExit(f"::error::Unknown season “{name}” – {path} has {', '.join(known)}.")
    return known[name]


def wanted(bbox, minzoom, maxzoom):
    """Every tile over the box, shallow zooms first."""
    out = []
    for z in range(minzoom, maxzoom + 1):
        x0, y0, x1, y1 = tile_range(bbox, z)
        out += [(z, x, y) for x in range(x0, x1) for y in range(y0, y1)]
    return out


def window(bbox, z, x, y, size):
    """The box's pixels in the tile, or None when the tile lies wholly inside it."""
    w, s, e, n = bbox
    left, top = lonlat_to_tile(w, n, z)
    right, bottom = lonlat_to_tile(e, s, z)
    px = [round(min(max((v - o) * size, 0), size))
          for v, o in ((left, x), (top, y), (right, x), (bottom, y))]
    return None if px == [0, 0, size, size] else tuple(px)


def cut(path, bbox, z, x, y):
    """A tile crossing the box's edge, as a WebP clear beyond it; else the JPEG as it is."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    with Image.open(path) as img:
        box = window(bbox, z, x, y, img.width)
        if box is None:
            return path
        mask = Image.new("L", img.size, 0)
        if box[2] > box[0] and box[3] > box[1]:
            ImageDraw.Draw(mask).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
        clear = img.convert("RGBA")
    clear.putalpha(mask)
    out = path + ".cut.webp"
    clear.save(out, "WEBP", quality=85)
    return out


def e7(value):
    return int(round(value * 1e7))


def write(out, tiles, bbox, minzoom, maxzoom, name):
    """`tiles` maps (z, x, y) to a JPEG on disk; the archive says what it holds."""
    from pmtiles.tile import Compression, TileType, zxy_to_tileid  # noqa: PLC0415
    from pmtiles.writer import Writer                                # noqa: PLC0415

    w, s, e, n = bbox
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        writer = Writer(f)
        for zxy in sorted(tiles, key=lambda t: zxy_to_tileid(*t)):
            with open(tiles[zxy], "rb") as jpeg:
                writer.write_tile(zxy_to_tileid(*zxy), jpeg.read())
        writer.finalize(
            {"tile_type": TileType.JPEG, "tile_compression": Compression.NONE,
             "min_zoom": minzoom, "max_zoom": maxzoom,
             "min_lon_e7": e7(w), "min_lat_e7": e7(s), "max_lon_e7": e7(e), "max_lat_e7": e7(n),
             "center_zoom": min(maxzoom, minzoom + 4),
             "center_lon_e7": e7((w + e) / 2), "center_lat_e7": e7((s + n) / 2)},
            {"name": name, "format": "jpg", "type": "baselayer",
             "description": "Aerial photos (orthophoto mosaic)"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--bbox", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="aerial-cache")
    ap.add_argument("--url", default="", help="instead of the season's own")
    ap.add_argument("--maxzoom", default="", help="instead of the season's own")
    # a volunteer server: few connections, and the cache spares it the next run
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = ap.parse_args()

    conf = season(args.season)
    url = args.url or conf.get("url") or ""
    out = {"enabled": "false"}
    if url:
        bbox = [float(v) for v in args.bbox.split(",")]
        minzoom = int(conf.get("minzoom", 8))
        maxzoom = int(args.maxzoom or conf.get("maxzoom", 17))
        fetcher = Fetcher(url, os.path.join(args.cache, args.season), jobs=args.jobs, ua="project")
        tiles = {}
        for z in range(minzoom, maxzoom + 1):
            x0, y0, x1, y1 = tile_range(bbox, z)
            print(f"z{z}: {(x1 - x0) * (y1 - y0)} tiles", flush=True)
            fetcher.fetch_all(z, x0, y0, x1, y1)
        for z, x, y in wanted(bbox, minzoom, maxzoom):
            path = fetcher.path(z, x, y)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                tiles[(z, x, y)] = cut(path, bbox, z, x, y)
        if fetcher.n_fail > len(tiles) * 0.02:
            raise SystemExit(f"::error::{fetcher.n_fail} {args.season} tiles failed – "
                             f"a package with holes isn't published. Run it again; "
                             f"the cache keeps what came.")
        if tiles:
            name = os.path.basename(args.out).removesuffix(".pmtiles")
            write(args.out, tiles, bbox, minzoom, maxzoom, name)
            size = os.path.getsize(args.out)
            print(f"{args.out}: {len(tiles)} tiles, z{minzoom}–z{maxzoom}, "
                  f"{size / 1048576:.0f} MB")
            out = {"enabled": "true", "maxzoom": str(maxzoom)}
        else:
            print(f"::warning::{url} gave no tile over {args.bbox} – no {args.season} photos.")
    else:
        print(f"::notice::No {args.season} aerial photos: workers/data/aerial.json has no "
              f"`url` for it.")
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write("".join(f"{k}={v}\n" for k, v in out.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
