#!/usr/bin/env python3
"""
ÚGKK open data: one ZIP with a DMR for all of Slovakia → 1°×1° tiles.

DMR 5.0 can't be downloaded from a runner (zbgis* time out), but
`opendata.skgeodesy.sk` serves static files. DMR 3.5 at 10 m is still twice as
fine as Sonny (20 m); the grid is measured after unpacking, not guessed. Tiles
are named like Sonny's (`N49E019.tif`), so `workers/dem/fetch.sh` takes them as is.

Usage:
    python3 workers/dem/fetch-open.py --out=tiles --bbox=16.8,47.7,22.6,49.7
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
# a folder is a job, a file a step; shared things live a level up
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # registries (areas, regions, sources)
sys.path.insert(0, _HERE)

# rasters the ZIP may hold; ÚGKK doesn't say, so all GDAL reads as a raster
RASTER_EXT = (".tif", ".tiff", ".asc", ".xyz", ".img", ".dem", ".grd", ".vrt")


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def load_probe():
    """`smart_get` and `host_reachable` from the probe – no second copy of the profiles."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "probe_dem_source", os.path.join(_HERE, "probe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def download(url, dest, timeout):
    """Download the ZIP with curl, not into memory."""
    probe = load_probe()
    ok, why = probe.host_reachable(url, timeout=timeout)
    if not ok:
        print(f"::warning::{url}: the host doesn't answer ({why})")
        return False
    print(f"  the host answers ({why}), downloading…", flush=True)
    ua = probe.BROWSERS[0][1]["User-Agent"]
    cmd = ["curl", "-sSL", "--fail", "--retry", "3", "--retry-delay", "5",
           "--max-time", "3600", "-A", ua, "-o", dest, url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dest):
        print(f"::warning::curl failed (rc={r.returncode}): {r.stderr[:200]}")
        return False
    mb = os.path.getsize(dest) / 1048576
    print(f"  downloaded {mb:.0f} MB")
    # an empty or error answer looks like a file until you look inside
    with open(dest, "rb") as f:
        head = f.read(4)
    if head[:2] != b"PK":
        print(f"::warning::{dest} isn't a ZIP (starts with {head!r}) – the "
              f"server probably returned an error page.")
        return False
    return True


def unpack(zip_path, out_dir):
    """Unpack and return the rasters inside."""
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        print(f"  {len(names)} members in the archive")
        z.extractall(out_dir)
    rasters = []
    for root, _, files in os.walk(out_dir):
        for f in files:
            if f.lower().endswith(RASTER_EXT):
                rasters.append(os.path.join(root, f))
    # headerless `.asc` and `.xyz` GDAL can't read – show what is there
    if not rasters:
        sample = sorted({os.path.splitext(f)[1].lower()
                         for _, _, fs in os.walk(out_dir) for f in fs})
        print(f"::warning::The archive has not one known raster. "
              f"Suffixes inside: {', '.join(sample) or '(none)'}")
    return sorted(rasters)


def describe(path):
    """Grid and CRS – what decides whether the model is worth it."""
    try:
        info = json.loads(run(["gdalinfo", "-json", path]).stdout)
    except subprocess.CalledProcessError as exc:
        return None, f"gdalinfo failed: {(exc.stderr or '')[:120]}"
    gt = info.get("geoTransform") or [0, 0, 0, 0, 0, 0]
    wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
    dx, dy = abs(gt[1]), abs(gt[5])
    if wkt.startswith("GEOGCRS") or wkt.startswith("GEOGCS"):
        # in degrees: converted to metres at our latitude (~49° N)
        dx_m = dx * 111320 * math.cos(math.radians(49))
        dy_m = dy * 110540
    else:
        dx_m, dy_m = dx, dy
    return {"cell_x_m": dx_m, "cell_y_m": dy_m,
            "size": info.get("size"), "crs": wkt.split('"')[1] if '"' in wkt else "?"}, None


def cut_tiles(vrt, out_dir, bbox):
    """Cut the mosaic into 1°×1° N49E019.tif tiles (the SRTM convention, like Sonny)."""
    w, s, e, n = bbox
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for lat in range(math.floor(s), math.ceil(n)):
        for lon in range(math.floor(w), math.ceil(e)):
            name = (f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
                    f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
            dest = os.path.join(out_dir, f"{name}.tif")
            try:
                run(["gdalwarp", "-q", "-overwrite",
                     "-te", str(lon), str(lat), str(lon + 1), str(lat + 1),
                     "-te_srs", "EPSG:4326", "-t_srs", "EPSG:4326",
                     "-of", "COG", "-co", "COMPRESS=DEFLATE",
                     "-co", "PREDICTOR=3", "-co", "RESAMPLING=BILINEAR",
                     vrt, dest])
            except subprocess.CalledProcessError as exc:
                print(f"  – {name}: {(exc.stderr or '')[:100].strip()}")
                continue
            # a tile outside the area comes out empty – pointless to store
            try:
                stats = run(["gdalinfo", "-stats", "-json", dest]).stdout
                band = json.loads(stats)["bands"][0]
                if band.get("maximum") is None:
                    os.remove(dest)
                    continue
            except Exception:
                pass
            mb = os.path.getsize(dest) / 1048576
            print(f"  ✓ {name}.tif  {mb:.1f} MB", flush=True)
            made.append(dest)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="overrides the URL from dem-sources.json")
    ap.add_argument("--source", default="dmr35", help="the key in dem-sources.json")
    ap.add_argument("--sources", default=os.path.join(_DATA, "dem-sources.json"))
    ap.add_argument("--out", default="tiles", help="where the finished tiles go")
    ap.add_argument("--bbox", default="16.8,47.7,22.6,49.7",
                    help="the extent cut to (default Slovakia)")
    ap.add_argument("--work", default="", help="the work directory")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--stats", default="", help="where to write findings (key=value)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    src = json.load(open(args.sources)).get(args.source) or {}
    url = args.url or src.get("url", "")
    if not url:
        print(f"::error::Source \"{args.source}\" has no `url` in {args.sources} "
              f"and --url isn't given.")
        return 2

    bbox = tuple(float(v) for v in args.bbox.split(","))
    work = args.work or os.path.join(os.path.dirname(args.out) or ".", "open-work")
    os.makedirs(work, exist_ok=True)
    zip_path = os.path.join(work, "dem.zip")

    print(f"Source: {src.get('label', args.source)}")
    print(f"URL:   {url}")
    if not download(url, zip_path, args.timeout):
        # code 3 = "can't download", so the caller can fall back to Sonny
        print("::error::The ÚGKK open data couldn't be downloaded.")
        return 3

    print("Unpacking…")
    rasters = unpack(zip_path, os.path.join(work, "unz"))
    if not rasters:
        return 3
    print(f"  rasters: {len(rasters)}")

    meta, why = describe(rasters[0])
    if not meta:
        print(f"::error::The first raster can't be read: {why}")
        return 3
    print(f"  grid ~{meta['cell_x_m']:.1f}×{meta['cell_y_m']:.1f} m, "
          f"{meta['size']}, CRS {meta['crs']}")
    cell = max(meta["cell_x_m"], meta["cell_y_m"])
    if cell > 20:
        print(f"::warning::A {cell:.0f} m grid is coarser than or equal to "
              f"Sonny (20 m) – this model improves nothing.")

    vrt = os.path.join(work, "all.vrt")
    run(["gdalbuildvrt", "-q", "-resolution", "highest", vrt] + rasters)

    print("Cutting into 1°×1° tiles…")
    tiles = cut_tiles(vrt, args.out, bbox)
    if not tiles:
        print("::error::Not a single tile was made.")
        return 3
    total_mb = sum(os.path.getsize(t) for t in tiles) / 1048576
    print(f"Done: {len(tiles)} tiles, {total_mb:.0f} MB")

    if args.stats:
        with open(args.stats, "w") as f:
            f.write(f"tiles={len(tiles)}\nmb={total_mb:.0f}\n")
            f.write(f"cell_m={cell:.1f}\ncrs={meta['crs']}\nurl={url}\n")
    if not args.keep_temp:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
