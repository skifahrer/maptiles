#!/usr/bin/env python3
"""A region's signs, mapped by `road-signs.json` to traffic-signs images → sprite `{region}-roadsigns`."""
import argparse
import io
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from signs import MAPPING, folders, generic  # noqa: E402

# side of the box a sign fits in, at 1x
SIDE = 24
ROW = 32


def supported(country, mapping=MAPPING):
    """`{sprite name: sign folder}`: the country's keys, then any folder by its generic name."""
    by_country = folders(mapping)
    out = dict(by_country.get(country) or {})
    for names in by_country.values():
        for folder in names.values():
            out.setdefault(generic(country, folder), folder)
    return out


def needed(country, used, mapping=MAPPING):
    """`{sprite name: sign folder}` of the names the region uses that have a folder."""
    known = supported(country, mapping)
    return {n: known[n] for n in sorted(used) if n in known}


def with_every_limit(country, used, mapping=MAPPING):
    """`used` plus each speed-limit sign the country has: the app draws limits no sign names."""
    out = dict(used)
    for name in supported(country, mapping):
        if ".ts.maxspeed-" in name and not name.endswith("_end"):
            out.setdefault(name, 0)
    return out


def entries(root, country, used, mapping=MAPPING):
    """`{image file: {"names": [...], "sign": folder, "uses": n}}`, `uses` the region's count."""
    out = {}
    translated = translations(root)
    for name, sign in needed(country, used, mapping).items():
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
                                       "label": labels(folder, slug, sign, translated)})
        entry["names"].append(name)
        entry["uses"] += used[name]
    return out


def read_used(path):
    """`{name: count}` from `signs.py --names`."""
    with open(path, encoding="utf-8") as f:
        rows = (line.rstrip("\n").split("\t") for line in f if line.strip())
        return {r[0]: int(r[1]) if len(r) > 1 else 0 for r in rows}


def labels(folder, slug, sign=None, translated=None):
    """The sign's official names from `<slug>.json`, then the collection's translations."""
    try:
        with open(os.path.join(folder, f"{slug}.json"), encoding="utf-8") as f:
            out = json.load(f)
    except (OSError, ValueError):
        out = {}
    for language, names in (translated or {}).items():
        if sign in names:
            out.setdefault(language, names[sign])
    return out


def translations(root):
    """`{language: {sign folder: name}}` from the collection's `names/<language>.json`."""
    out = {}
    folder = os.path.join(root, "names")
    for file in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not file.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, file), encoding="utf-8") as f:
                out[file[:-5]] = json.load(f)
        except (OSError, ValueError):
            continue
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
    ap.add_argument("--country", required=True)
    ap.add_argument("--used", required=True, help="the region's names, `signs.py --names`")
    ap.add_argument("--folders", action="store_true",
                    help="print the collection folders to fetch, one per line, and stop")
    ap.add_argument("--signs", help="checkout of skifahrer/traffic-signs")
    ap.add_argument("--out", help="base name, without .json/.png")
    a = ap.parse_args()
    country = a.country.lower()
    used = with_every_limit(country, read_used(a.used))
    if a.folders:
        print("\n".join(sorted(set(needed(country, used).values()))))
        return
    if not (a.signs and a.out):
        ap.error("--signs and --out build the sheet")
    found = entries(a.signs, country, used)
    if not found:
        print(f"“{a.country}”: no sign this region uses has an image – no road sign sprite.")
        return
    n = write(found, a.out)
    names = sum(len(v["names"]) for v in found.values())
    print(f"Road signs {a.country}: {n} images, {names} names → {a.out}.json/.png (+@2x)")


if __name__ == "__main__":
    main()
