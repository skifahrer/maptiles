#!/usr/bin/env python3
"""A mountain's styles: the map build's, with only the range's own layers – no base map under them.

    python3 workers/mountain/styles.py _site/styles
"""
import json
import os
import sys

# what a mountain package carries, as `poc/web/themes.js` names the sources
OWN_SOURCES = ("contours", "rocks", "dem")


def strip(style):
    """Sources and layers of the range alone; the paper stays, so it draws on its own."""
    sources = {k: v for k, v in (style.get("sources") or {}).items() if k in OWN_SOURCES}
    style["sources"] = sources
    style["layers"] = [layer for layer in style.get("layers") or []
                       if layer.get("source") in sources
                       or (not layer.get("source") and layer.get("type") == "background")]
    if (style.get("terrain") or {}).get("source") not in sources:
        style.pop("terrain", None)
    # no sprite travels with a mountain, and none of its layers draws an icon
    style.pop("sprite", None)
    return style


def main(args):
    folder = args[0] if args else "_site/styles"
    names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    if not names:
        raise SystemExit(f"::error::{folder} holds no style – did workers/styles/build.mjs run?")
    for name in names:
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as f:
            style = strip(json.load(f))
        if not any(layer.get("source") for layer in style["layers"]):
            raise SystemExit(f"::error::{name} draws nothing of the mountain – its layers are gone.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(style, f, ensure_ascii=False, separators=(",", ":"))
        print(f"{name}: {len(style['layers'])} layers over {', '.join(sorted(style['sources']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
