#!/usr/bin/env python3
"""The signs OSM supports in a country (traffic-signs `osm/<cc>.json`) → sprite `{region}-roadsigns`."""
import argparse
import io
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from signs import sign_name  # noqa: E402

# side of the box a sign fits in, at 1x
SIDE = 24
ROW = 32


def supported(root, country):
    """`{sprite name: (sign path, uses)}` for what `osm/<cc>.json` says OSM has and draws."""
    path = os.path.join(root, "osm", f"{country}.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        osm = json.load(f)
    out = {}
    for value, info in (osm.get("signs") or {}).items():
        name = sign_name(value, country)
        if name and name not in out:
            out[name] = (info["sign"], int(info.get("count") or 0))
    for tag, by_figure in (osm.get("figures") or {}).items():
        for figure, sign in by_figure.items():
            out.setdefault(f"{country}.ts.{tag}-{figure}", (sign, 0))
    for word, sign in (osm.get("implied") or {}).items():
        out.setdefault(f"{country}.ts.{word}", (sign, 0))
    return out


def entries(root, country):
    """`{image file: {"names": [...], "sign": path, "uses": n}}` for the signs OSM supports."""
    out = {}
    for name, (sign, uses) in sorted(supported(root, country).items()):
        category, slug = sign.split("/")
        folder = os.path.join(root, "signs", category, slug)
        meta = os.path.join(folder, country, f"{slug}-{country}.json")
        if not os.path.isfile(meta):
            continue
        with open(meta, encoding="utf-8") as f:
            image = os.path.join(folder, country, (json.load(f).get("image") or {}).get("file") or "")
        if not os.path.isfile(image):
            continue
        entry = out.setdefault(image, {"names": [], "sign": sign, "uses": 0,
                                       "label": labels(folder, slug)})
        entry["names"].append(name)
        entry["uses"] += uses
    return out


def labels(folder, slug):
    """The sign's name by language, from the collection's `<slug>.json`."""
    try:
        with open(os.path.join(folder, f"{slug}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


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
            e = found[path]
            for name in e["names"]:
                index.setdefault(name, {"x": cx, "y": cy, "width": img.width,
                                        "height": img.height, "pixelRatio": ratio,
                                        "category": e["sign"].split("/")[0], "uses": e["uses"],
                                        "label": e["label"]})
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
        print(f"Country “{a.country}” has no sign OSM supports with an image – no road sign sprite.")
        return
    n = write(found, a.out)
    names = sum(len(v["names"]) for v in found.values())
    print(f"Road signs {a.country}: {n} images, {names} names → {a.out}.json/.png (+@2x)")


if __name__ == "__main__":
    main()
