#!/usr/bin/env python3
"""Any elevation raster → 1°×1° EPSG:4326 tiles named by the south-west corner
(N49E019.tif), as the map build expects them.

`--window` keeps a tile's name honest: a degree not wholly in the window isn't
stored, and a whole one without a single height is stored empty – a record that
it was looked at, decided by an exact pass and signed (`EMPTY_CHECK`).

Usage:
    python3 workers/dem/tiles.py --out tiles/ Slovakia_20m.tif [more.tif …]
    python3 workers/dem/tiles.py --out tiles/ --window=21,49,22,50 nation.tif
"""
import argparse
import json
import math
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
# `workers/lib/cell.py` picks the resampling – the same question as hillshading's
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import M_PER_DEG_LAT, resampling  # noqa: E402


# otherwise `gdalinfo -stats` leaves statistics in `.aux.xml`
NO_PAM = {**os.environ, "GDAL_PAM_ENABLED": "NO"}

# an empty tile carries which check called it empty; a new version makes
# `dem/coverage.py` drop the old ones
EMPTY_PX = 60                  # an empty tile's side in pixels
EMPTY_TAG = "EMPTY_CHECK"      # the GDAL metadata item's name
# v1 = sampled, v2 = an exact pass; the value is stamped into stored tiles, keep it
EMPTY_CHECK = "v2-presne"
# no empty tile is bigger (60×60 px is a few kB) – `dem/trust.py` opens only smaller
EMPTY_MAX_BYTES = 1 << 20


def gdalinfo(path, stats=""):
    """`stats`: empty = none, `approx` = sampled, `exact` = exact."""
    flag = {"": [], "approx": ["-approx_stats"], "exact": ["-stats"]}[stats]
    cmd = ["gdalinfo", "-json"] + flag + [path]
    out = subprocess.run(
        cmd, capture_output=True, text=True, check=True, env=NO_PAM
    ).stdout
    return json.loads(out)


def elevation_range(path, exact=False):
    """(min, max) of heights, or None without a valid pixel; sampled only proves "yes"."""
    try:
        b = gdalinfo(path, stats="exact" if exact else "approx")["bands"][0]
        return b["minimum"], b["maximum"]
    except Exception:
        return None


def has_elevations(path):
    """Is there at least one valid height? The answer must be exact."""
    # sampling walks a diagonal; half the Bratislava region vanished as "empty" so
    rng = elevation_range(path)
    if rng is not None:
        return rng
    rng = elevation_range(path, exact=True)
    if rng is not None:
        print(f"  (sampling found no heights in {os.path.basename(path)}, "
              f"the exact pass did: {rng[0]:.1f} … {rng[1]:.1f} m)")
    return rng


def wgs84_bounds(info):
    """The raster's extent in degrees – even when it is metric itself."""
    ext = info.get("wgs84Extent")
    if not ext or not ext.get("coordinates"):
        raise SystemExit("The raster has no knowable WGS84 extent (no projection?).")
    pts = []
    def walk(node):
        if isinstance(node[0], (int, float)):
            pts.append(node)
        else:
            for n in node:
                walk(n)
    walk(ext["coordinates"])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def is_geographic(info):
    """Geographic (degrees) or projected (metres), by the WKT type."""
    # COMPOUNDCRS once looked metric and gdalwarp tried a 1.2 billion pixel tile
    wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
    wkt = wkt.strip().upper()
    if wkt.startswith("COMPOUNDCRS"):
        # the horizontal part is the first nested CRS
        inner = wkt.split("[", 1)[1] if "[" in wkt else ""
        inner = inner.split(",", 1)[1].lstrip() if "," in inner else ""
        return inner.startswith(("GEOGCRS", "GEOGCS", "BASEGEOGCRS"))
    return wkt.startswith(("GEOGCRS", "GEOGCS", "BASEGEOGCRS"))


def pixel_degrees(info, lat):
    """Pixel size in degrees; for a metric projection via cos(latitude)."""
    gt = info["geoTransform"]
    px, py = abs(gt[1]), abs(gt[5])
    if is_geographic(info):
        return px, py
    return px / (111320 * math.cos(math.radians(lat))), py / 110540


def tile_name(lon, lat):
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def plan_tiles(bounds, window, dlon, dlat):
    """Which degrees are written: `(write, partial)` – one answer for the file."""
    # `write` is `(lon, lat, name, has_data)`; with a window the grid comes from the window
    w, s, e, n = bounds
    lat_range = range(math.floor(s), math.ceil(n))
    lon_range = range(math.floor(w), math.ceil(e))
    if window is not None:
        # the union of window and raster: empty degrees stored, overhangs reported
        lat_range = range(min(lat_range.start, math.floor(window[1])),
                          max(lat_range.stop, math.ceil(window[3])))
        lon_range = range(min(lon_range.start, math.floor(window[0])),
                          max(lon_range.stop, math.ceil(window[2])))

    write, partial = [], []
    for lat in lat_range:
        for lon in lon_range:
            # sources overhang a degree by half a pixel, so "at least a few pixels"
            over_x = min(lon + 1, e) - max(lon, w)
            over_y = min(lat + 1, n) - max(lat, s)
            thin = over_x <= 2 * dlon or over_y <= 2 * dlat
            name = tile_name(lon, lat)
            if window is None:
                if not thin:
                    write.append((lon, lat, name, True))
                continue
            # a pixel of slack: the window widens to whole degrees
            if (lon < window[0] - dlon or lon + 1 > window[2] + dlon
                    or lat < window[1] - dlat or lat + 1 > window[3] + dlat):
                if not thin:
                    partial.append(name)
                continue
            write.append((lon, lat, name, not thin))
    return write, partial


def empty_tile(dst, lon, lat, dtype, nodata, px=EMPTY_PX):
    """An empty tile for a whole degree – "we looked and nothing is here". True when made."""
    # a sourceless VRT (kilobytes), stamped and checked empty: zeros would be sea
    nd = nodata if nodata is not None else (
        -9999.0 if dtype.startswith("Float") else -32768)
    vrt = dst + ".vrt"
    with open(vrt, "w") as f:
        f.write(
            f'<VRTDataset rasterXSize="{px}" rasterYSize="{px}">'
            f'<SRS>EPSG:4326</SRS>'
            f'<GeoTransform>{lon}, {1.0 / px}, 0, {lat + 1}, 0, {-1.0 / px}'
            f'</GeoTransform>'
            f'<VRTRasterBand dataType="{dtype}" band="1">'
            f'<NoDataValue>{nd!r}</NoDataValue></VRTRasterBand></VRTDataset>')
    try:
        subprocess.run(
            ["gdal_translate", "-q", "-of", "GTiff", "-a_nodata", repr(nd),
             "-mo", f"{EMPTY_TAG}={EMPTY_CHECK}",
             "-co", "COMPRESS=DEFLATE", vrt, dst],
            check=True, env=NO_PAM)
    except subprocess.CalledProcessError as exc:
        print(f"::warning::Empty tile {os.path.basename(dst)} couldn't be made "
              f"({exc}) – the refill will ask for that degree again.")
        return False
    finally:
        os.remove(vrt)
    if elevation_range(dst, exact=True) is not None:
        os.remove(dst)
        print(f"::warning::Empty tile {os.path.basename(dst)} didn't come out "
              f"empty (GDAL put values instead of nodata) – not storing it, zero "
              f"is sea on the map.")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+", help="input rasters")
    ap.add_argument("--out", required=True)
    # empty = by the pixel/cell ratio; a fixed `bilinear` striped the hillshading
    ap.add_argument("--resampling", default="",
                    help="a fixed resampling; empty = by the pixel/cell ratio "
                         "(workers/lib/cell.py)")
    ap.add_argument("--window", default="",
                    help="W,S,E,N – the window the caller REALLY read. A degree "
                         "not wholly in it isn't stored; a degree without "
                         "heights is stored empty (see the header).")
    args = ap.parse_args()

    window = None
    if args.window.strip():
        vals = [float(v) for v in args.window.split(",")]
        if len(vals) != 4:
            raise SystemExit(f"::error::--window wants W,S,E,N: \"{args.window}\"")
        window = tuple(vals)

    temps = []
    src = args.src[0]
    if len(args.src) > 1:
        # one VRT over all inputs – handles overlaps too
        src = os.path.join(args.out or ".", "_dem-tiles.vrt")
        os.makedirs(args.out, exist_ok=True)
        subprocess.run(["gdalbuildvrt", "-q", "-resolution", "highest", src, *args.src],
                       check=True)
        temps.append(src)
        print(f"Joined into a VRT: {len(args.src)} rasters")

    info = gdalinfo(src)

    # scaled integer heights would reach the map ten times too big; gdalwarp ignores scale
    band = info["bands"][0]
    scale, offset = band.get("scale", 1) or 1, band.get("offset", 0) or 0
    if scale != 1 or offset != 0:
        print(f"Heights are scaled (scale={scale}, offset={offset}) – unpacking to metres")
        os.makedirs(args.out, exist_ok=True)
        unscaled = os.path.join(args.out, "_dem-tiles-unscaled.tif")
        subprocess.run(
            ["gdal_translate", "-q", "-unscale", "-ot", "Float32",
             "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3", src, unscaled],
            check=True,
        )
        temps.append(unscaled)
        src = unscaled
        info = gdalinfo(src)

    w, s, e, n = wgs84_bounds(info)
    dtype = info["bands"][0]["type"]
    predictor = "3" if dtype.startswith("Float") else "2"
    lat_mid = (s + n) / 2
    dlon, dlat = pixel_degrees(info, lat_mid)
    nodata = info["bands"][0].get("noDataValue")
    same_grid = is_geographic(info)
    print(
        f"{os.path.basename(src)}: {w:.3f},{s:.3f} … {e:.3f},{n:.3f}, "
        f"{dtype}, grid {dlon * 3600:.2f}″ × {dlat * 3600:.2f}″"
        f"{'' if same_grid else ' (converted from metres)'}"
    )

    # other units or an unapplied scale show here – not as a map all rock
    rng = has_elevations(src)
    if rng:
        lo, hi = rng
        print(f"Heights in the source: {lo:.1f} … {hi:.1f} m")
        if lo < -500 or hi > 9000:
            print("::warning::The height range doesn't look like metres above "
                  "sea level – check the source's units (decimetres? feet?).")

    # `near` on the same grid is a pure sub-pixel shift; a metric source is 1:1, `lib/cell.py` picks
    cell_m = dlat * M_PER_DEG_LAT
    how = args.resampling or resampling(cell_m, cell_m)
    if not same_grid:
        print(f"Resampling to WGS84: `{how}`"
              + (" (fixed)" if args.resampling else
                 f" – the {cell_m:.1f} m cell stays, the projection changes, "
                 f"so it must filter the same everywhere"))

    os.makedirs(args.out, exist_ok=True)
    made = []
    empty = []
    write, partial = plan_tiles((w, s, e, n), window, dlon, dlat)
    for lon, lat, name, has_data in write:
        dst = os.path.join(args.out, f"{name}.tif")
        if not has_data:
            # a degree in the window the raster doesn't reach: an empty tile without a warp
            if empty_tile(dst, lon, lat, dtype, nodata):
                empty.append(name)
                print(f"  ○ {name} (in the window, but the model doesn't reach it)")
            continue
        cmd = [
            "gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:4326",
            "-te", str(lon), str(lat), str(lon + 1), str(lat + 1),
            "-tr", repr(dlon), repr(dlat),
            "-r", "near" if same_grid else how,
            "-co", "COMPRESS=DEFLATE", "-co", f"PREDICTOR={predictor}",
            "-co", "TILED=YES", "-multi",
        ]
        if nodata is not None:
            cmd += ["-dstnodata", repr(nodata)]
        subprocess.run(cmd + [src, dst], check=True)
        # `has_elevations`: sampling's "no" must be checked exactly
        if has_elevations(dst) is None:
            if window is None:
                # the whole tile is nodata – nothing to add to the store
                os.remove(dst)
                continue
            # with a window an empty tile is an answer; rewritten coarse to take no room
            os.remove(dst)
            # how much of the degree the raster reached – half-reached and empty is suspicious
            over = (max(0.0, min(lon + 1, e) - max(lon, w))
                    * max(0.0, min(lat + 1, n) - max(lat, s))) * 100.0
            if empty_tile(dst, lon, lat, dtype, nodata):
                empty.append(name)
                print(f"  ○ {name} (read whole, no heights in it; "
                      f"the raster reached {over:.0f} % of the degree)")
            continue
        made.append(name)
        print(f"  ✓ {name}")

    for t in temps:
        if os.path.exists(t):
            os.remove(t)
    if partial:
        # no warning, the right result – but logged, or it is searched for in the store
        print(f"Outside the window, not stored: {' '.join(sorted(set(partial)))} – "
              f"window {args.window} didn't read those degrees whole and a "
              f"tile's name promises a whole degree.")
    if not made and not empty:
        raise SystemExit("The raster doesn't cover a single whole 1° tile.")

    print(f"{len(made)} tiles: {' '.join(sorted(set(made)))}"
          + (f" (+ {len(empty)} empty: {' '.join(sorted(set(empty)))})"
             if empty else ""))


if __name__ == "__main__":
    sys.exit(main())
