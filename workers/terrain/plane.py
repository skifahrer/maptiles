#!/usr/bin/env python3
"""The height of a terrain archive's plane outside its region, as JSON (`null` for none)."""
import collections
import io
import math
import os
import sys

# real ground never repeats one height over half the coarsest tile
SHARE = 0.5


def terrarium(r, g, b):
    return r * 256 + g + b / 256 - 32768


def centre_tile(header):
    """The coarsest tile under the archive's middle."""
    z = header["min_zoom"]
    lon = (header["min_lon_e7"] + header["max_lon_e7"]) / 2e7
    lat = (header["min_lat_e7"] + header["max_lat_e7"]) / 2e7
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def plane_of(tile):
    """The plane's height in metres, or None if no one height fills the tile."""
    from PIL import Image
    pixels = list(Image.open(io.BytesIO(tile)).convert("RGB").getdata())
    value, count = collections.Counter(pixels).most_common(1)[0]
    return round(terrarium(*value)) if count >= SHARE * len(pixels) else None


def plane(path):
    if not os.path.isfile(path) or not os.path.getsize(path):
        return None
    from pmtiles.reader import MmapSource, Reader
    with open(path, "rb") as f:
        reader = Reader(MmapSource(f))
        tile = reader.get(*centre_tile(reader.header()))
    return plane_of(tile) if tile else None


def main(args):
    height = plane(args[0]) if args else None
    print("null" if height is None else height)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
