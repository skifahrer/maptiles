#!/usr/bin/env python3
"""Keeps only the font ranges the map's names use – measured from the data, never guessed.

Usage:
    python3 workers/world/glyphs.py --fonts=_site/fonts --data=data/world
"""
import argparse
import glob
import json
import os
import sys

# what `style.mjs` writes as text; a new `text-field` belongs here too
TEXT_KEYS = ("name", "name_en")
PREFIX = "name:"

# MapLibre draws CJK with the system font
LOCAL = set(range(0x2E80 // 256, 0xA000 // 256)) | set(range(0xAC00 // 256, 0xD800 // 256))

# digits and basic Latin, for any fallback text
ALWAYS = {0}


def ranges_in_geojson(path):
    """The 256-character ranges the names in this file use."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = set()
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        for key, value in props.items():
            if (key in TEXT_KEYS or key.startswith(PREFIX)) and isinstance(value, str):
                out.update(ord(z) // 256 for z in value)
    return out - LOCAL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", default="_site/fonts")
    ap.add_argument("--data", default="data/world",
                    help="prepared sources (`*.geojson` with names)")
    args = ap.parse_args()

    stacks = sorted(d for d in glob.glob(os.path.join(args.fonts, "*"))
                    if os.path.isdir(d))
    if not stacks:
        print(f"`{args.fonts}` has no fonts – nothing to cut.")
        return 0

    sources = sorted(glob.glob(os.path.join(args.data, "*.geojson")))
    needed = set(ALWAYS)
    read = []
    for z in sources:
        try:
            r = ranges_in_geojson(z)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # a bigger package beats empty boxes instead of names
            print(f"::warning::Source {z} can't be read ({exc}) – fonts are "
                  f"NOT cut and the package keeps the whole font.")
            return 0
        needed |= r
        read.append((os.path.basename(z), len(r)))

    if not read:
        print(f"::warning::`{args.data}` has no `.geojson` with names – "
              f"fonts are NOT cut.")
        return 0

    print("Character ranges in the map's names:")
    for name, count in read:
        print(f"  {name:<24} {count} ranges")
    print("  total: " + ", ".join(f"{r * 256}-{r * 256 + 255}"
                                  for r in sorted(needed)))

    deleted = kept = 0
    before = after = 0
    for stack in stacks:
        for pbf in glob.glob(os.path.join(stack, "*.pbf")):
            name = os.path.basename(pbf)
            size = os.path.getsize(pbf)
            before += size
            try:
                lo = int(name.split("-", 1)[0])
            except ValueError:
                after += size
                kept += 1
                continue
            if lo // 256 in needed:
                after += size
                kept += 1
            else:
                os.remove(pbf)
                deleted += 1

    print(f"Fonts: {kept} files kept ({after / 1048576:.1f} MB), "
          f"{deleted} deleted ({(before - after) / 1048576:.1f} MB saved "
          f"of {before / 1048576:.1f} MB).")
    if not kept:
        print("::error::Not a single font file is left after the cut – the map "
              "would have no labels. Check `--fonts` and `--data`.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
