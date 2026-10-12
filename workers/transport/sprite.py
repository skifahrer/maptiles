#!/usr/bin/env python3
"""A country's signs from `skifahrer/traffic-signs` → sprite `{region}-roadsigns` (+`@2x`)."""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from signs import code  # noqa: E402

# what a map shows; panels and devices stand under or beside these
CATEGORIES = ("warning", "regulatory", "information")
# OSM words for a sign → its folder in the collection
ALIASES = {
    "stop": "regulatory/stop",
    "give_way": "regulatory/give-way",
    "traffic_signals": "warning/traffic-signals",
    "speed_camera": "information/speed-camera",
    "city_limit": "information/built-up-area",
}
SPEED = re.compile(r"^speed-limit-(\d+)$")
# side of the box a sign fits in, at 1x
SIDE = 24
ROW = 32


def entries(root, country):
    """`{image file: [sprite names]}` of a country, current images only."""
    out = {}
    for meta in sorted(glob.glob(os.path.join(root, "signs", "*", "*", country, "*.json"))):
        rel = os.path.relpath(meta, os.path.join(root, "signs")).split(os.sep)
        category, folder = rel[0], rel[1]
        with open(meta, encoding="utf-8") as f:
            data = json.load(f)
        image = os.path.join(os.path.dirname(meta), (data.get("image") or {}).get("file") or "")
        if not os.path.isfile(image):
            continue
        names = []
        if category in CATEGORIES and data.get("code"):
            names.append(f"{country}.ts.{code(data['code'])}")
        names += [f"{country}.ts.{word}" for word, path in ALIASES.items()
                  if path == f"{category}/{folder}"]
        speed = SPEED.match(folder)
        if category == "regulatory" and speed:
            names.append(f"{country}.ts.maxspeed-{speed.group(1)}")
        if names:
            out.setdefault(image, []).extend(names)
    return out


def raster(path, side):
    """The image fitted into a `side` square, keeping its shape."""
    from PIL import Image

    if path.endswith(".svg"):
        png = subprocess.run(["rsvg-convert", "-w", str(side), "-h", str(side),
                              "--keep-aspect-ratio", path],
                             check=True, capture_output=True).stdout
        return Image.open(io.BytesIO(png)).convert("RGBA")
    img = Image.open(path).convert("RGBA")
    img.thumbnail((side, side))
    return img


def write(found, base, width=1024):
    """Shelf-packed sheets at 1x and 2x, every name of an image pointing at one cut."""
    from PIL import Image

    images = sorted(found)
    for suffix, ratio in (("", 1), ("@2x", 2)):
        cuts, x, y = [], 0, 0
        for path in images:
            try:
                img = raster(path, SIDE * ratio)
            except (subprocess.CalledProcessError, OSError) as exc:
                print(f"::warning::{path} couldn't be drawn: {exc}")
                continue
            if x + img.width > width * ratio:
                x, y = 0, y + ROW * ratio
            cuts.append((path, img, x, y))
            x += img.width + 2 * ratio
        sheet = Image.new("RGBA", (width * ratio, max(y + ROW * ratio, 1)))
        index = {}
        for path, img, cx, cy in cuts:
            sheet.paste(img, (cx, cy))
            for name in found[path]:
                index.setdefault(name, {"x": cx, "y": cy, "width": img.width,
                                        "height": img.height, "pixelRatio": ratio})
        sheet.save(f"{base}{suffix}.png", optimize=True)
        with open(f"{base}{suffix}.json", "w", encoding="utf-8") as f:
            json.dump(index, f, indent=1, sort_keys=True)
            f.write("\n")
    return len(images)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signs", required=True, help="checkout of skifahrer/traffic-signs")
    ap.add_argument("--country", required=True)
    ap.add_argument("--out", required=True, help="base name, without .json/.png")
    a = ap.parse_args()
    found = entries(a.signs, a.country.lower())
    if not found:
        print(f"Country “{a.country}” has no signs in the collection – no road sign sprite.")
        return
    n = write(found, a.out)
    names = sum(len(v) for v in found.values())
    print(f"Road signs {a.country}: {n} images, {names} names → {a.out}.json/.png (+@2x)")


if __name__ == "__main__":
    main()
