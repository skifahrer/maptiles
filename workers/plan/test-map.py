#!/usr/bin/env python3
"""An image of where exactly the test cut-out is, plus coordinates and a map link.

Numbers can't say whether the square fell on a ridge with walls or a meadow.
The base is the freemap.sk hillshading; when it doesn't download, the frames
are drawn on a blank base – diagnostics mustn't fail a run about something else.

Usage:
    python3 workers/plan/test-map.py \\
        --bbox=20.10,49.163,20.12,49.176 --full-bbox=19.9,49.09,20.32,49.25 \\
        --name=\"Vysoké Tatry – test 4 km²\" --png=out/where-it-is.png \\
        --md=out/where-it-is.md --pages-url=https://user.github.io/fricomaps/
"""
import argparse
import io
import math
import os
import random
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

TILE = 256
R = 6378137.0
# the same base as shading-rocks; an overview zoom is a handful of tiles
SHADING_URL = "https://sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg"
UA = ("fricomaps/1.0 (+https://github.com/skifahrer/fricomaps) "
      "test-cutout-preview")

RED = (231, 60, 60)
BLUE = (60, 120, 231)
BACKGROUND = (232, 232, 228)


def lonlat_to_px(lon, lat, z):
    """WGS84 → a Web Mercator pixel at a zoom."""
    n = TILE * 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    lat = max(-85.05112878, min(85.05112878, lat))
    sy = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sy) / (1 - sy)) / (4 * math.pi)) * n
    return x, y


def ground_res(z, lat):
    """Metres per pixel at a latitude."""
    return 2.0 * math.pi * R * math.cos(math.radians(lat)) / (TILE * 2.0 ** z)


def download(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def mosaic(w, s, e, n, max_px, max_tiles):
    """The base for window `w,s,e,n`: (image, zoom, top-left pixel)."""
    # the highest zoom fitting `max_px` and `max_tiles`; blank when nothing downloads
    for z in range(16, 5, -1):
        x0, y0 = lonlat_to_px(w, n, z)
        x1, y1 = lonlat_to_px(e, s, z)
        width, height = x1 - x0, y1 - y0
        tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
        tx1, ty1 = int(x1 // TILE), int(y1 // TILE)
        n_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if max(width, height) <= max_px and n_tiles <= max_tiles:
            break
    else:
        z = 6

    x0, y0 = lonlat_to_px(w, n, z)
    x1, y1 = lonlat_to_px(e, s, z)
    tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
    tx1, ty1 = int(x1 // TILE), int(y1 // TILE)
    width = (tx1 - tx0 + 1) * TILE
    height = (ty1 - ty0 + 1) * TILE
    image = Image.new("RGB", (width, height), BACKGROUND)

    ok = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = SHADING_URL.format(z=z, x=tx, y=ty)
            for attempt in range(3):
                try:
                    tile = Image.open(io.BytesIO(download(url))).convert("RGB")
                    image.paste(tile, ((tx - tx0) * TILE, (ty - ty0) * TILE))
                    ok += 1
                    break
                except Exception as exc:            # noqa: BLE001 – see the docstring
                    if attempt == 2:
                        print(f"  base: {url} didn't download ({exc})",
                              file=sys.stderr)
                    else:
                        time.sleep(0.5 * (attempt + 1) + random.random() * 0.3)
    print(f"  base: z{z}, {ok} of {(tx1 - tx0 + 1) * (ty1 - ty0 + 1)} "
          f"tiles, {width}×{height} px", flush=True)
    return image, z, (tx0 * TILE, ty0 * TILE)


# DejaVu on the runner and in Pillow; PIL's built-in font is ASCII-only bitmap
FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
)


def font_of(size):
    """(font, line height) – the font is None when no TTF is anywhere."""
    for path in FONTS:
        try:
            f = ImageFont.truetype(path, size)
            return f, size + 4
        except OSError:
            continue
    return None, 11


def strip_diacritics(text):
    table = str.maketrans({
        "á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i", "ĺ": "l",
        "ľ": "l", "ň": "n", "ó": "o", "ô": "o", "ŕ": "r", "š": "s", "ť": "t",
        "ú": "u", "ý": "y", "ž": "z", "Á": "A", "Č": "C", "Ď": "D", "É": "E",
        "Í": "I", "Ľ": "L", "Ň": "N", "Ó": "O", "Ô": "O", "Š": "S", "Ť": "T",
        "Ú": "U", "Ý": "Y", "Ž": "Z", "²": "2", "×": "x", "·": "|", "–": "-",
    })
    return text.translate(table)


def rectangle(draw, bbox, z, offset, colour, width):
    w, s, e, n = bbox
    x0, y0 = lonlat_to_px(w, n, z)
    x1, y1 = lonlat_to_px(e, s, z)
    box = (x0 - offset[0], y0 - offset[1], x1 - offset[0], y1 - offset[1])
    draw.rectangle(box, outline=colour, width=width)
    return box


def window(test, full, at_least, at_most):
    """The section to draw, as a multiple of the test square."""
    # the WHOLE cut-out first; widened to `at_least`, shrunk to `at_most` times the square
    w, s, e, n = test
    clon, clat = (w + e) / 2, (s + n) / 2
    sw, sh = e - w, n - s

    if full:
        fw, fs, fe, fn = full
        mw, mh = (fe - fw) * 0.06, (fn - fs) * 0.06
        section = [fw - mw, fs - mh, fe + mw, fn + mh]
        times = max((section[2] - section[0]) / sw, (section[3] - section[1]) / sh)
        if at_least <= times <= at_most:
            return section
        times = min(max(times, at_least), at_most)
    else:
        times = at_least

    dlon, dlat = sw * times / 2, sh * times / 2
    return [clon - dlon, clat - dlat, clon + dlon, clat + dlat]


def link_zoom(bbox, width_px=900):
    """The zoom at which the test square fills the browser window."""
    w, s, e, n = bbox
    clat = (s + n) / 2
    side_m = (e - w) * 111320.0 * math.cos(math.radians(clat))
    if side_m <= 0:
        return 15
    z = math.log2(2 * math.pi * R * math.cos(math.radians(clat))
                  * width_px / (TILE * side_m))
    return max(9, min(18, int(round(z))))


def write(args, test, clat, clon, width_km, height_km, km2, whole_visible):
    """Coordinates and links – to stdout and (optionally) as a piece for the run summary."""
    w, s, e, n = test
    zl = link_zoom(test)
    map_url = ""
    if args.pages_url.strip():
        base = args.pages_url.strip().rstrip("/") + "/"
        # `#map=`, not a bare `#`: MapLibre keeps other hash parameters beside it
        map_url = f"{base}#map={zl}/{clat:.5f}/{clon:.5f}"
        if args.region.strip():
            map_url += f"&region={args.region.strip()}"
    osm = f"https://www.openstreetmap.org/#map={zl}/{clat:.5f}/{clon:.5f}"
    freemap = f"https://www.freemap.sk/?map={zl}/{clat:.5f}/{clon:.5f}"

    lines = [
        f"### Test cut-out – {km2:.2f} km²", "",
        f"**{args.name}**" + (f" · {args.layers}" if args.layers else ""), "",
        "| | |", "|---|---|",
        f"| centre | `{clat:.5f}, {clon:.5f}` |",
        f"| bbox | `{w:.6f},{s:.6f},{e:.6f},{n:.6f}` |",
        f"| size | {width_km:.2f} × {height_km:.2f} km |", "",
        "Contours, rocks and hillshading are only on this square – **the map "
        "around it is the whole region** by the run's settings.", "",
    ]
    links = []
    if map_url:
        links.append(f"**[Open in the map]({map_url})**")
    links += [f"[OSM]({osm})", f"[Freemap]({freemap})"]
    lines += [" · ".join(links), ""]
    legend = ("red square = the tested cut-out"
              + (", blue = the whole cut-out" if whole_visible else ""))
    if args.img_url.strip():
        lines += [f"![where it is]({args.img_url.strip()})", f"*{legend}*", ""]
    elif args.png.strip():
        lines += [f"The image with surroundings (`{os.path.basename(args.png)}`) "
                  f"is in this run's artifact – {legend}.", ""]

    if args.md:
        os.makedirs(os.path.dirname(os.path.abspath(args.md)) or ".",
                    exist_ok=True)
        with open(args.md, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"  summary  {args.md}", flush=True)
    if map_url:
        print(f"  map      {map_url}", flush=True)
    print("─────────────────────────────────────────────────────", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="An image and a link to the test cut-out's place.")
    ap.add_argument("--bbox", required=True, help="test cut-out W,S,E,N")
    ap.add_argument("--full-bbox", default="", help="the whole cut-out for context")
    ap.add_argument("--name", default="test cut-out")
    ap.add_argument("--layers", default="", help="what is computed on it")
    ap.add_argument("--png", default="out/where-it-is.png")
    ap.add_argument("--md", default="", help="where to write the summary piece")
    ap.add_argument("--img-url", default="",
                    help="the URL the image will be at – put into the summary")
    ap.add_argument("--pages-url", default="",
                    help="the map address, e.g. https://user.github.io/fricomaps/")
    ap.add_argument("--region", default="", help="region key for the link")
    ap.add_argument("--context", type=float, default=10.0,
                    help="at least how many times the test square to show")
    ap.add_argument("--max-context", type=float, default=90.0,
                    help="at most how many times – beyond it the tested square "
                         "is a dot and the image says nothing")
    ap.add_argument("--max-px", type=int, default=1400)
    ap.add_argument("--max-tiles", type=int, default=48)
    args = ap.parse_args()

    test = [float(v) for v in args.bbox.split(",")]
    if len(test) != 4:
        print("::error::--bbox must be W,S,E,N.", file=sys.stderr)
        return 1
    full = ([float(v) for v in args.full_bbox.split(",")]
            if args.full_bbox.strip() else None)

    w, s, e, n = test
    clon, clat = (w + e) / 2, (s + n) / 2
    width_km = (e - w) * 111.32 * math.cos(math.radians(clat))
    height_km = (n - s) * 110.54
    km2 = width_km * height_km

    print("── Where the test cut-out is ────────────────────────")
    print(f"  {args.name}")
    print(f"  centre   {clat:.5f}, {clon:.5f}")
    print(f"  bbox     {w:.6f},{s:.6f},{e:.6f},{n:.6f}")
    print(f"  size     {width_km:.2f} × {height_km:.2f} km = {km2:.2f} km²",
          flush=True)

    # without `--png` nothing is drawn or downloaded: the plan already made the image
    if not args.png.strip():
        return write(args, test, clat, clon, width_km, height_km, km2,
                     whole_visible=bool(full))

    section = window(test, full, args.context, args.max_context)
    image, z, offset = mosaic(*section, args.max_px, args.max_tiles)
    draw = ImageDraw.Draw(image)
    whole_visible = False
    if full:
        fbox = rectangle(draw, full, z, offset, BLUE, 2)
        whole_visible = (fbox[0] >= -1 and fbox[1] >= -1
                         and fbox[2] <= image.width + 1
                         and fbox[3] <= image.height + 1)
    box = rectangle(draw, test, z, offset, RED, 3)
    # crosshairs: at an overview zoom 4 km² is too small to find by eye
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for a, b in (((cx, 0), (cx, box[1] - 6)), ((cx, box[3] + 6), (cx, image.height)),
                 ((0, cy), (box[0] - 6, cy)), ((box[2] + 6, cy), (image.width, cy))):
        draw.line([a, b], fill=RED, width=1)

    caption = (f"{args.name}   ·   {clat:.5f}, {clon:.5f}   ·   "
               f"{width_km:.2f} × {height_km:.2f} km = {km2:.2f} km²"
               + (f"   ·   {args.layers}" if args.layers else ""))
    font, line_h = font_of(16)
    if font is None:
        # the built-in bitmap font is ASCII-only: better no accents than question marks
        caption = strip_diacritics(caption)
    bar = line_h + 8
    draw.rectangle([0, image.height - bar, image.width, image.height],
                   fill=(20, 20, 20))
    draw.text((8, image.height - bar + 4), caption, fill=(255, 255, 255),
              font=font)

    os.makedirs(os.path.dirname(os.path.abspath(args.png)) or ".", exist_ok=True)
    image.save(args.png)
    print(f"  image    {args.png} ({image.width}×{image.height} px)", flush=True)

    return write(args, test, clat, clon, width_km, height_km, km2, whole_visible)


if __name__ == "__main__":
    sys.exit(main())
