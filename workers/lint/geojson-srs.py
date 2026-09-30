#!/usr/bin/env python3
"""GeoJSON output must get no SRS – otherwise metres silently turn into degrees."""
import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)

# drivers converting to WGS84; in `GPKG` `-a_srs` really only labels
GEOJSON = ("GeoJSON", "GeoJSONSeq")
SRS_FLAGS = ("-a_srs", "-t_srs")


def python_files():
    for root, _, files in os.walk(_WORKERS):
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def items(lst):
    """List items: string constants, or `None` for anything unpacked."""
    out = []
    for item in lst.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            out.append(item.value)
        elif isinstance(item, ast.Starred):
            out.append(None)
        else:
            out.append("")   # an f-string or variable – one item, not a hole
    return out


def main():
    bad = []

    # 1. and 2. commands writing GeoJSON
    found = 0
    for path in python_files():
        rel = os.path.relpath(path, os.path.dirname(_WORKERS))
        try:
            tree = ast.parse(open(path).read(), filename=path)
        except SyntaxError as exc:
            bad.append(f"`{rel}` can't be read ({exc}).")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.List):
                continue
            parts = items(node)
            texts = [p for p in parts if p]
            if not any(t.endswith("ogr2ogr") or t == "gdal_contour"
                       for t in texts):
                continue
            # is GeoJSON written? `-f <driver>` decides, as in the command
            format_ = None
            for i, p in enumerate(parts[:-1]):
                if p == "-f":
                    format_ = parts[i + 1]
            if format_ not in GEOJSON:
                continue
            found += 1
            line = node.lineno
            for flag in SRS_FLAGS:
                if flag in texts:
                    bad.append(
                        f"`{rel}:{line}` writes {format_} and passes `{flag}`. "
                        f"The GeoJSON driver then CONVERTS the coordinates to "
                        f"WGS84 – metres become degrees, ogr2ogr succeeds and "
                        f"says nothing. Keep the output without SRS and assign "
                        f"it where nothing converts – when rewriting to GPKG.")
            # unpacking matters only for `ogr2ogr`; `*levels` in gdal_contour are thresholds
            if None in parts and any(t.endswith("ogr2ogr") for t in texts):
                bad.append(
                    f"`{rel}:{line}` writes {format_}, but splices its options "
                    f"from a variable (`*…`), so whether `-a_srs` is among them "
                    f"can't be read. That is exactly how `-a_srs` got here once. "
                    f"Write the options into the list directly.")
    if not found:
        bad.append("No command writing GeoJSON was found. Either the driver was "
                   "renamed or commands are built differently – and the check "
                   "then guards nothing.")

    # 3. and 4. the two places it stands on
    blocks = os.path.join(_WORKERS, "lib", "contour-blocks.py")
    src = open(blocks).read()
    if not re.search(r"<SRS\[\^>\]\*>", src):
        bad.append("`workers/lib/contour-blocks.py` no longer drops `<SRS>` from "
                   "the block window. `gdal_contour` would write degrees, every "
                   "rock would be ~1e-9 m² and the filter would drop them all – "
                   "in a green run (31245134321, 31426542010).")

    body = src.split("def stitch_seams", 1)
    if len(body) < 2:
        bad.append("`workers/lib/contour-blocks.py` no longer has `stitch_seams` "
                   "– if stitching moved, move this check too.")
    elif "check_metric(" not in body[1]:
        bad.append("`stitch_seams` doesn't check the union with `check_metric()`. "
                   "Without it a return to degrees is silent: the union comes out "
                   "right, the area computes as zero and is dropped as \"lost\" – "
                   "with a message sending you to GEOS (run 32300347626).")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print(f"GeoJSON output without SRS: {found} commands checked, blocks drop "
          f"`<SRS>` and the seam union checks its units ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
