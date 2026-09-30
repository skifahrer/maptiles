#!/usr/bin/env python3
"""Does the downloaded DEM mosaic cover the area to compute on?

A tile promises a whole degree and `workers/dem/check.sh` knows only names; a
tile's extent decides, not its valid cells. An empty tile is signed with the
check's version (`EMPTY_CHECK`); an unsigned one goes out of the store.

Usage:
    python3 workers/dem/coverage.py --bbox=19.865,48.745,22.585,49.48 \\
        --dir=dem/dmr5/tiles [--min-pct=95] [--out=cov.txt]

Prints `covered_pct`, `liars`, `empty` and `missing`; exit 1 = under `--min-pct`.
"""
import argparse
import json
import math
import os
import subprocess
import sys

# what an empty tile looks like and which check may call it so – known by its writer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tiles  # noqa: E402

# how much of its degree a tile must cover for its name not to lie (half-pixel slack)
HONEST_PCT = 99.0


def tile_info(path):
    """A tile's `gdalinfo -json`, or None when unreadable (extent and stamp in one call)."""
    try:
        return json.loads(subprocess.run(
            ["gdalinfo", "-json", path], capture_output=True, text=True,
            check=True, env={**os.environ, "GDAL_PAM_ENABLED": "NO"}).stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return None


def empty_stamp(info):
    """An empty tile's stamp, or None when it isn't one ("" = written by check v1)."""
    # known by its grid: `tiles.py` gives it `EMPTY_PX` a side, a real 1° tile has thousands
    if (info.get("size") or [])[:2] != [tiles.EMPTY_PX, tiles.EMPTY_PX]:
        return None
    return ((info.get("metadata") or {}).get("", {})).get(tiles.EMPTY_TAG, "")


def extent_of(info):
    """A tile's (w, s, e, n) in degrees, or None when it can't be told."""
    ext = info.get("wgs84Extent") or {}
    pts = []

    def walk(node):
        if node and isinstance(node[0], (int, float)):
            pts.append(node)
        else:
            for child in node or []:
                walk(child)

    walk(ext.get("coordinates"))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def degree_of(name):
    """`N49E020.tif` → (20, 49); an unrelated name returns None."""
    base = os.path.basename(name).split(".")[0].upper()
    if len(base) != 7 or base[0] not in "NS" or base[3] not in "EW":
        return None
    try:
        lat, lon = int(base[1:3]), int(base[4:7])
    except ValueError:
        return None
    return (-lon if base[3] == "W" else lon, -lat if base[0] == "S" else lat)


def covers_own_degree(extent, degree):
    """What percent of its degree a tile covers (by extent)."""
    lon, lat = degree
    w = max(0.0, min(extent[2], lon + 1) - max(extent[0], lon))
    h = max(0.0, min(extent[3], lat + 1) - max(extent[1], lat))
    return 100.0 * w * h


def covered_pct(bbox, extents, cells=400):
    """How much of the bbox the extents' union covers, on a 400×400 grid (no shapely)."""
    w, s, e, n = bbox
    if e <= w or n <= s or not extents:
        return 0.0
    dx, dy = (e - w) / cells, (n - s) / cells
    hit = 0
    for j in range(cells):
        y = s + (j + 0.5) * dy
        row = [x for x in extents if x[1] <= y <= x[3]]
        if not row:
            continue
        for i in range(cells):
            x = w + (i + 0.5) * dx
            if any(t[0] <= x <= t[2] for t in row):
                hit += 1
    return 100.0 * hit / (cells * cells)


def data_pct(path, region=None):
    """What percent of a tile really has heights (not nodata), by GDAL's `-stats`."""
    # extent isn't enough: a 5 MB tile beside a 265 MB one showed "100 %" and a flat edge
    r = subprocess.run(["gdalinfo", "-json", "-stats", path],
                       capture_output=True, text=True, check=False)
    if r.returncode:
        return None
    try:
        info = json.loads(r.stdout)
    except ValueError:
        return None
    for band in info.get("bands") or []:
        md = (band.get("metadata") or {}).get("") or {}
        pct = md.get("STATISTICS_VALID_PERCENT")
        if pct is not None:
            try:
                return float(pct)
            except ValueError:
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", required=True, help="W,S,E,N of the area computed")
    ap.add_argument("--dir", default="", help="the tile directory")
    ap.add_argument("tiles", nargs="*", help="or files directly")
    ap.add_argument("--min-pct", type=float, default=95.0,
                    help="under this coverage the exit code is 1")
    ap.add_argument("--out", default="", help="where to write key=value")
    ap.add_argument("--data-pct", type=float, default=0.0,
                    help="a tile under this share of real heights is "
                         "reported as suspicious (0 = don't check)")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    if len(bbox) != 4:
        raise SystemExit(f"::error::--bbox wants W,S,E,N: \"{args.bbox}\"")

    paths = list(args.tiles)
    if args.dir and os.path.isdir(args.dir):
        paths += [os.path.join(args.dir, f) for f in sorted(os.listdir(args.dir))
                  if f.lower().endswith(".tif")]
    if not paths:
        print("::error::coverage.py got not a single tile.")
        return 2

    good, liars, empty = [], [], []
    for p in sorted(set(paths)):
        name = os.path.basename(p)
        info = tile_info(p)
        ext = extent_of(info) if info else None
        deg = degree_of(name)
        stamp = empty_stamp(info) if info else None
        if stamp is not None and stamp != tiles.EMPTY_CHECK:
            # an empty tile from a check no longer trusted: its extent is fine
            liars.append(name)
            print(f"  ✗ {name} is an empty tile from check "
                  f"\"{stamp or 'v1 (unsigned)'}\", today it is "
                  f"\"{tiles.EMPTY_CHECK}\" – that degree must be read again")
            continue
        if stamp is not None:
            empty.append(name)
        if ext is None:
            # the extent can't be told – counted by name, or "unverifiable" becomes "missing"
            print(f"  ? {name} – extent unknown, taking it as valid")
            if deg is not None:
                good.append((float(deg[0]), float(deg[1]),
                             float(deg[0] + 1), float(deg[1] + 1)))
            continue
        if deg is None:
            good.append(ext)
            continue
        pct = covers_own_degree(ext, deg)
        if pct < HONEST_PCT:
            liars.append(name)
            print(f"  ✗ {name} covers only {pct:.2f} % of its degree "
                  f"({ext[0]:.4f},{ext[1]:.4f} … {ext[2]:.4f},{ext[3]:.4f}) – "
                  f"the name claims the whole degree")
        else:
            good.append((float(deg[0]), float(deg[1]),
                         float(deg[0] + 1), float(deg[1] + 1)))

    # do tiles have data, not only extent? a warning, a tile may rightly be empty
    sparse = []
    if args.data_pct > 0:
        print(f"  data in the tiles (share of real heights, threshold "
              f"{args.data_pct:g} %):")
        for p_ in sorted(set(paths)):
            name = os.path.basename(p_)
            if name in liars:
                continue
            d = data_pct(p_)
            mb = os.path.getsize(p_) / 1e6 if os.path.exists(p_) else 0
            if d is None:
                print(f"    ? {name} – the data share can't be told ({mb:.0f} MB)")
                continue
            mark = "✓" if d >= args.data_pct else "✗"
            print(f"    {mark} {name}: {d:.1f} % heights, {mb:.0f} MB")
            if d < args.data_pct and name not in empty:
                sparse.append((name, d, mb))
        if sparse:
            listed = ", ".join(f"{n} ({d:.1f} % heights, {mb:.0f} MB)"
                               for n, d, mb in sparse)
            print(f"::warning::Tiles with almost no heights: {listed}. Their "
                  f"extent is fine, so coverage came out fine – but the map "
                  f"gets a BLANK SPOT with a straight edge over the whole "
                  f"degree, and the data's edge makes false rock walls. When "
                  f"that degree should be full, delete it from the store and "
                  f"let it refill (`store.py --rm`); when it lies wholly "
                  f"beyond Slovakia, that is fine.")

    # which of the bbox's degrees no honest tile covers
    missing = []
    for lat in range(math.floor(bbox[1]), math.floor(bbox[3]) + 1):
        for lon in range(math.floor(bbox[0]), math.floor(bbox[2]) + 1):
            if not any(t[0] <= lon + 0.5 <= t[2] and t[1] <= lat + 0.5 <= t[3]
                       for t in good):
                ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
                missing.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")

    pct = covered_pct(bbox, good)
    lines = [f"covered_pct={pct:.1f}",
             "liars=" + " ".join(liars),
             "empty=" + " ".join(empty),
             "missing=" + " ".join(missing)]
    print(f"Area coverage {args.bbox}: {pct:.1f} % from {len(good)} tiles"
          + (f", {len(liars)} dishonest" if liars else ""))
    if missing:
        print(f"  no tile: {' '.join(missing)}")
    if empty:
        # an empty tile counts as covered, so otherwise the log wouldn't mention it
        print(f"  read and without terrain: {' '.join(empty)}")
    text = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    sys.stdout.write(text)
    return 1 if pct < args.min_pct else 0


if __name__ == "__main__":
    sys.exit(main())
