#!/usr/bin/env python3
"""Nobody picks the elevation model resampling on their own.

`workers/lib/cell.py` answers – but a hard-coded `-r average` answers too. At a
1.25 ratio `average` doesn't average but skips every fourth pixel, and that
rhythm becomes a regular grid in the map.

  1. `resampling(5, 4)` mustn't be `average`;
  2. whoever resamples a model asks `lib/cell.py` – no hard-coded kernel;
  3. the pyramid is picked in `dmr5-cut.pyramid_level`, not by `-ovr AUTO`:
     the level sets the pixel/cell ratio.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402

# files that MAKE an elevation model; their kernel must come from `cell.py`
MAKERS = [
    os.path.join("workers", "drive", "dmr5-cut.py"),
    os.path.join("workers", "drive", "dmr5-raster.py"),
    os.path.join("workers", "dem", "tiles.py"),
]

# hard-codable GDAL kernels; not `near`, the one that doesn't filter at all
KERNELS = ("average", "bilinear", "cubic", "cubicspline", "lanczos", "mode")

# lines that may name a kernel without `cell.py`, each with a reason
EXCEPTIONS = {
    # COG overviews halve, exactly `AVERAGE_RATIO` – averaging is honest there
    "RESAMPLING=AVERAGE",
}


def code_lines(text):
    """Code lines – comments may TALK about resampling, code mustn't pick it."""
    out = []
    for r in text.splitlines():
        if r.lstrip().startswith("#"):
            continue
        out.append(r.split("  #")[0])
    return out


def main():
    bad = []

    # 1. the doctrine: DMR 5.0 pyramids are 2, 4, 8 … m, tiles 5 m, so the ratio is 1.25
    if cell.resampling(5.0, 4.0) == "average":
        bad.append(
            "`cell.resampling(5, 4)` returned `average`. At exactly this ratio "
            "(1.25) GDAL doesn't average but skips every fourth source cell – "
            "and hillshade turns that rhythm into a regular grid. Measured in "
            "`workers/dem/measure-resampling.py`.")
    if cell.AVERAGE_RATIO < 2.0:
        bad.append(f"`AVERAGE_RATIO` is {cell.AVERAGE_RATIO:g}, so averaging is "
                   f"allowed where a target pixel covers less than two cells. "
                   f"That's the whole grid – the limit is 2, and measured.")
    # the other side: honest downscaling MUST average, or 1 m → 5 m loses detail
    if cell.resampling(5.0, 1.0) != "average":
        bad.append("`cell.resampling(5, 1)` didn't return `average` – 1 m to 5 m "
                   "is a ratio of 5, where averaging is honest and cheap and "
                   "sampling would drop detail the model has.")

    # 2. no hard-coded kernel
    for rel in MAKERS:
        path = os.path.join(os.path.dirname(_WORKERS), rel)
        if not os.path.exists(path):
            bad.append(f"{rel} doesn't exist – if it was renamed, update "
                       f"`workers/lint/dem-resampling.py` too, or this check "
                       f"quietly checks nothing.")
            continue
        text = open(path, encoding="utf-8").read()
        if "from cell import" not in text:
            bad.append(f"{rel} resamples an elevation model but doesn't ask "
                       f"`workers/lib/cell.py` – it picks its own kernel and "
                       f"will drift from the doctrine.")
        for i, line in enumerate(code_lines(text), 1):
            if any(v in line for v in EXCEPTIONS):
                continue
            for k in KERNELS:
                if re.search(r'"-r",\s*"%s"' % k, line) or \
                        re.search(r'"%s"\s*,\s*"-of"' % k, line):
                    bad.append(
                        f"{rel}:{i}: kernel `{k}` hard-coded. The resampling "
                        f"comes from `cell.resampling(target, source)` – a "
                        f"hard-coded `-r average` at 1.25 baked the grid into "
                        f"stored tiles.")

    # 3. the pyramid is picked in one place
    cut = os.path.join(os.path.dirname(_WORKERS), "workers", "drive", "dmr5-cut.py")
    drive = os.path.join(os.path.dirname(_WORKERS), "workers", "drive", "dmr5.py")
    if os.path.exists(cut):
        text = open(cut, encoding="utf-8").read()
        if "def pyramid_level" not in text:
            bad.append("`workers/drive/dmr5-cut.py` has no `pyramid_level` – one "
                       "place must say which pyramid is read: the plan prints "
                       "that number and the resampling follows it.")
        for i, line in enumerate(code_lines(text), 1):
            if '"-ovr", "AUTO"' in line.replace("'", '"'):
                bad.append(
                    f"workers/drive/dmr5-cut.py:{i}: `-ovr AUTO` leaves the "
                    f"pyramid to GDAL. But the level sets the pixel/cell ratio "
                    f"the resampling follows – two answers to one question. "
                    f"`pyramid_level` picks the level and passes it to `-ovr`.")
    if os.path.exists(drive):
        text = open(drive, encoding="utf-8").read()
        if "pyramid_level" not in text:
            bad.append("`workers/drive/dmr5.py` counts read pixels without "
                       "`pyramid_level` – the plan would then speak of another "
                       "pyramid than the one really read.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print(f"DEM resampling: `lib/cell.py` picks the kernel "
          f"(resampling(5, 4) = `{cell.resampling(5.0, 4.0)}`, "
          f"AVERAGE_RATIO = {cell.AVERAGE_RATIO:g}), `pyramid_level` the pyramid ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
