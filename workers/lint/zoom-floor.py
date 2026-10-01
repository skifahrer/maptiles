#!/usr/bin/env python3
"""Contours and rocks aren't tiled below the zoom the style draws them from.

The zoom floor lives in two places by necessity: the schema decides what is
made, the style what is drawn. A lower schema = tiles nobody draws; a lower
style = a hole in the map. Nobody says either.
"""
import os
import re
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_WORKERS)

THEMES = os.path.join(_ROOT, "poc", "web", "themes.js")
CONTOURS = os.path.join(_WORKERS, "contours-rocks", "contours.yml")
ROCKS = os.path.join(_WORKERS, "contours-rocks", "rocks.yml")

# below this no contour or rock is readable; above it only `major` contours, the rest higher
FLOOR = 11


def schema_min_zoom(path, layer, include=None):
    """A layer feature's `min_zoom` in a Planetiler schema; `include` picks by `include_when`."""
    doc = yaml.safe_load(open(path))
    for lay in doc.get("layers", []):
        if lay.get("id") != layer:
            continue
        for feat in lay.get("features", []):
            when = feat.get("include_when") or {}
            if include is None or include in when.values():
                return feat.get("min_zoom")
    return None


def named_z(text, token):
    """A number from a style expression – a literal or a constant name (`TERRAIN_MIN_Z`)."""
    token = token.strip()
    if token.isdigit():
        return int(token)
    m = re.search(r"export const " + re.escape(token) + r"\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def style_min_zoom(text, layer_id):
    """A style layer's `minzoom`, searched after its `id`."""
    m = re.search(r'id:\s*"' + re.escape(layer_id) + r'"', text)
    if not m:
        return None
    m2 = re.search(r"minzoom:\s*([A-Za-z_0-9]+)", text[m.end():m.end() + 1200])
    return named_z(text, m2.group(1)) if m2 else None


def contour_line_min_zoom(text, level):
    """A contour class floor from its `contourLine("major", …, TERRAIN_MIN_Z, …)` call."""
    m = re.search(r'contourLine\(\s*"[^"]+"\s*,\s*"[^"]*"\s*,\s*"'
                  + re.escape(level) + r'"\s*,\s*([A-Za-z_0-9]+)', text, re.S)
    return named_z(text, m.group(1)) if m else None


def main():
    text = open(THEMES, encoding="utf-8").read()
    bad = []

    checks = [
        ("contours (class major)",
         schema_min_zoom(CONTOURS, "contour", include="major"),
         contour_line_min_zoom(text, "major"),
         'workers/contours-rocks/contours.yml (min_zoom of class major) '
         'vs poc/web/themes.js (contourLine("major", …))'),
        ("rocks",
         schema_min_zoom(ROCKS, "rock"),
         style_min_zoom(text, "rock-area"),
         "workers/contours-rocks/rocks.yml (min_zoom) vs "
         "poc/web/themes.js (layer rock-area)"),
    ]

    for what, schema, style, where in checks:
        if schema is None or style is None:
            bad.append(f"{what}: the zoom floor can't be read "
                       f"(schema={schema}, style={style}) – {where}. "
                       f"When those places change, update this check too.")
            continue
        if schema != style:
            bad.append(f"{what}: the schema makes from z{schema}, the style draws "
                       f"from z{style} – either paying for tiles nobody sees or a "
                       f"hole in the map. Align {where}.")
        elif schema < FLOOR:
            bad.append(f"{what}: the floor is z{schema}, but below z{FLOOR} "
                       f"neither contours nor rocks are drawn (no line is readable "
                       f"there and the data grows). Raise it in {where}.")
        else:
            print(f"  ✓ {what}: from z{schema} in schema and style")

    # the other two classes must start above the major one, or they smear at small scale
    major = contour_line_min_zoom(text, "major")
    for level in ("mid", "minor"):
        z = contour_line_min_zoom(text, level)
        if z is None:
            bad.append(f"contours: class {level} can't be found in the style "
                       f"– update the check or the style.")
        elif major is not None and z <= major:
            bad.append(f"contours: class {level} is drawn from z{z}, no higher "
                       f"than the major one (z{major}). At small scale ONLY the "
                       f"major contour belongs in the map, or they smear and the "
                       f"data doubles.")
        else:
            print(f"  ✓ contours (class {level}): from z{z}, above major")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("The contour and rock zoom floor matches in schema and style ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
