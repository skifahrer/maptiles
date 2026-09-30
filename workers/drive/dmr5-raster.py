#!/usr/bin/env python3
"""
DMR 5.0 as ONE GeoTIFF in a remote ZIP – read through /vsizip//vsicurl/.

The archive holds one continuous 151 GB raster (plus a 46 GB `.ovr`). GDAL reads
it by HTTP Range, but the ZIP member is deflated, so reading costs as much as
how FAR into the file the data lies. Hence: ONE pass (the whole country by one
`gdal_translate -tr`), read FORWARD (cut to disk first, warp from disk),
overviews when coarse enough, sidecars never hidden, a heartbeat every 30 s,
and the TIFF header's 16 bytes before GDAL (run 31191478190 hung there).

Usage:
    python3 workers/drive/dmr5-raster.py --url=URL --area=whole_country --grid-m=5 --out=tiles
    python3 workers/drive/dmr5-raster.py --url=URL --area=vysoke_tatry --grid-m=1 \\
        --out=out --asset=ugkk-vysoke_tatry.tif
    python3 workers/drive/dmr5-raster.py --url=URL --probe-only
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# a folder is a job, a file a step; shared things live a level up
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # registries (areas, regions, sources)

# the resampling – one answer for the whole pipeline, see `lib/cell.py`
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import resampling  # noqa: E402


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# opening and probing the remote raster is in `dmr5-remote.py`; this file asks
# which piece of land to cut and on what grid
remote = load("dmr5_remote", "dmr5-remote.py")
GDAL_ENV, Heartbeat = remote.GDAL_ENV, remote.Heartbeat
run, run_live, vsi_path = remote.run, remote.run_live, remote.vsi_path
pick_member, tiff_layout, probe = remote.pick_member, remote.tiff_layout, remote.probe
find_sidecar, ovr_source, ovr_fallback = (remote.find_sidecar, remote.ovr_source,
                                          remote.ovr_fallback)


def wgs_bbox_to_src(bbox_wgs, wkt_file, log):
    """(W, S, E, N) in WGS84 → the envelope in the source projection via `gdaltransform`."""
    # the sides, not just corners: Krovák is conic, a WGS84 rectangle isn't one in S-JTSK
    w, s, e, n = bbox_wgs
    pts, steps = [], 16
    for i in range(steps + 1):
        f = i / steps
        pts += [(w + (e - w) * f, s), (w + (e - w) * f, n),
                (w, s + (n - s) * f), (e, s + (n - s) * f)]
    inp = "\n".join(f"{x} {y}" for x, y in pts) + "\n"
    r = subprocess.run(["gdaltransform", "-s_srs", "EPSG:4326",
                        "-t_srs", wkt_file],
                       input=inp, capture_output=True, text=True, env=GDAL_ENV)
    if r.returncode:
        raise SystemExit(f"::error::gdaltransform failed: {r.stderr[:300]}")
    xs, ys = [], []
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 2:
            xs.append(float(f[0]))
            ys.append(float(f[1]))
    if not xs:
        raise SystemExit(f"::error::bbox {bbox_wgs} can't be converted")
    log(f"  in the source projection: {min(xs):.0f},{min(ys):.0f} … "
        f"{max(xs):.0f},{max(ys):.0f}")
    return min(xs), min(ys), max(xs), max(ys)


def clamp_to_raster(box, info, pad_px, log):
    """The window intersected with the raster (`-projwin` fills overhang with zeros, i.e. sea)."""
    gt = info["geoTransform"]
    px, py = info["size"]
    rw, rn = gt[0], gt[3]
    re_, rs = rw + gt[1] * px, rn + gt[5] * py
    pad_x, pad_y = pad_px * abs(gt[1]), pad_px * abs(gt[5])
    w = max(box[0] - pad_x, min(rw, re_))
    s = max(box[1] - pad_y, min(rs, rn))
    e = min(box[2] + pad_x, max(rw, re_))
    n = min(box[3] + pad_y, max(rs, rn))
    if w >= e or s >= n:
        raise SystemExit("::error::The cut-out shares not one pixel with the "
                         "raster – check `area`.")
    if (w, s, e, n) != tuple(box):
        log(f"  clipped to the raster: {w:.0f},{s:.0f} … {e:.0f},{n:.0f}")
    return w, s, e, n



def degrees_per_metre(lat):
    """The grid step in degrees for a step in metres at this latitude."""
    return (1.0 / (111320 * math.cos(math.radians(lat))), 1.0 / 110540)


def whole_country(vsi, grid_m, work, out_dir, log, expect=None):
    """The whole country: ONE pass to a coarser grid, then tiles from the small result."""
    os.makedirs(work, exist_ok=True)
    small = os.path.join(work, "dmr5-national.tif")
    t0 = time.time()
    log(f"Resampling the whole country to {grid_m} m – one pass, the long part.")
    if expect:
        log(f"  expecting ~{expect / 1e9:.0f} GB from the network")
    # 1 m → 5 m is well over `AVERAGE_RATIO`, but `lib/cell.py` is asked anyway
    run_live(["gdal_translate", "-tr", str(grid_m), str(grid_m),
              "-r", resampling(grid_m, 1.0), "-of", "GTiff",
              "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
              "-co", "TILED=YES", "-co", "BIGTIFF=YES",
              "-co", "NUM_THREADS=ALL_CPUS", vsi, small],
             label="resampling", expect_bytes=expect, watch=small)
    mb = os.path.getsize(small) / 1048576
    log(f"  done in {(time.time() - t0) / 60:.1f} min, {mb:.0f} MB")

    log("Cutting into 1°×1° WGS84 tiles…")
    run_live(["python3", os.path.join(_WORKERS, "dem", "tiles.py"), "--out", out_dir, small])
    return small


def area_cut(vsi, bbox_wgs, grid_m, dest, work, log, info, expect=None):
    """A cut-out in TWO steps: `-projwin` reads forward to disk, then `gdalwarp` from disk."""
    # a warp on the remote source asks in target order; each step back in deflate is GBs
    os.makedirs(work, exist_ok=True)
    native = os.path.join(work, "cutout-native.tif")
    wkt_file = os.path.join(work, "src.wkt")
    with open(wkt_file, "w") as f:
        f.write(info["wkt"])
    t0 = time.time()

    log(f"Cut-out {bbox_wgs} at {grid_m} m, step 1/2: a window in the source "
        f"projection, read sequentially…")
    box = wgs_bbox_to_src(bbox_wgs, wkt_file, log)
    bw, bs, be, bn = clamp_to_raster(box, info, 4, log)
    run_live(["gdal_translate",
              "-projwin", repr(bw), repr(bn), repr(be), repr(bs),
              "-of", "GTiff", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
              "-co", "TILED=YES", "-co", "BIGTIFF=YES",
              "-co", "NUM_THREADS=ALL_CPUS", vsi, native],
             label="reading the window", expect_bytes=expect, watch=native)
    log(f"  window: {os.path.getsize(native) / 1048576:.0f} MB, "
        f"{(time.time() - t0) / 60:.1f} min")

    dx, dy = degrees_per_metre((bbox_wgs[1] + bbox_wgs[3]) / 2)
    log(f"Step 2/2: converting to WGS84 ({grid_m * dx:.7f}° × {grid_m * dy:.7f}°) "
        f"– from disk only, fast.")
    # only the projection changes, a 1:1 ratio – `lib/cell.py` picks the kernel
    run_live(["gdalwarp", "-overwrite",
              "-t_srs", "EPSG:4326",
              "-te", *[repr(v) for v in bbox_wgs],
              "-tr", repr(grid_m * dx), repr(grid_m * dy),
              "-r", resampling(grid_m, grid_m),
              "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
              "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
              "-co", "RESAMPLING=AVERAGE", "-co", "NUM_THREADS=ALL_CPUS",
              native, dest])
    os.remove(native)
    mb = os.path.getsize(dest) / 1048576
    log(f"  done in {(time.time() - t0) / 60:.1f} min, {mb:.0f} MB")
    return dest


def resolve_area(area, areas_path):
    key = (area or "whole_country").strip()
    if key.lower() in ("", "whole", "whole_country", "cele", "cele_slovensko", "all"):
        return "whole country", None
    if "," in key:
        vals = [float(v) for v in key.split(",")]
        if len(vals) != 4:
            raise SystemExit(f"::error::a bbox must have 4 numbers: {key}")
        return f"bbox {key}", tuple(vals)
    areas = json.load(open(areas_path))
    if key not in areas:
        known = ", ".join(k for k in areas if not k.startswith("_"))
        raise SystemExit(f"::error::unknown cut-out \"{key}\". Known: {known}")
    return areas[key]["name"], tuple(areas[key]["bbox"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--plan", default="plan.json",
                    help="the largest raster in the archive is picked from it")
    ap.add_argument("--member", default="", help="a fixed path in the archive")
    ap.add_argument("--area", default="whole_country")
    ap.add_argument("--areas", default=os.path.join(_DATA, "areas.json"))
    ap.add_argument("--grid-m", type=float, default=5.0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--work", default="raster-work")
    ap.add_argument("--asset", default="", help="the file name for a cut-out")
    ap.add_argument("--probe-only", action="store_true",
                    help="only read the header and stop")
    ap.add_argument("--no-ovr", action="store_true",
                    help="don't read from overviews even when possible")
    ap.add_argument("--debug", action="store_true",
                    help="CPL_DEBUG=ON – every request to the log. Only for "
                         "short runs, 151 GB is a million lines.")
    ap.add_argument("--probe-timeout", type=float, default=900,
                    help="seconds to wait for the raster to open")
    ap.add_argument("--summary", default="")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = ap.parse_args()

    if args.debug:
        GDAL_ENV["CPL_DEBUG"] = "ON"
        GDAL_ENV["CPL_CURL_VERBOSE"] = "YES"

    lines = []

    def log(m):
        print(m, flush=True)
        lines.append(m)

    member = pick_member(args.plan, args.member)
    vsi = vsi_path(args.url, member)
    log(f"Archive member: {member}")
    log(f"Path for GDAL:  {vsi}")

    # cheap diagnostics BEFORE GDAL: 16 bytes of each file tell whether it opens fast
    log("Raster layout in the archive (16 bytes of each):")
    main_entry = find_sidecar(args.plan, member, "")
    ovr_entry = find_sidecar(args.plan, member, ".ovr")
    lay = tiff_layout(args.url, main_entry, log) if main_entry else None
    lay_ovr = tiff_layout(args.url, ovr_entry, log) if ovr_entry else None
    for name, l in (("main raster", lay), ("overviews", lay_ovr)):
        if l and l["share"] > 1.0:
            log(f"::warning::{name}: the tile directory is at {l['share']:.0f} % "
                f"of the file. The ZIP member is deflated, so GDAL reaches it "
                f"only by unpacking all before it – opening alone reads "
                f"~{l['ifd'] / 1e9:.1f} GB.")

    # the probe runs WITHOUT sidecars: a costly `.ovr` would look like the main file's fault
    t0 = time.time()
    forced = None
    info = probe(vsi, log, timeout=args.probe_timeout, no_sidecars=True,
                 expect_bytes=main_entry["csize"] if main_entry else None)
    if info is not None:
        log(f"  opened without sidecars in {time.time() - t0:.0f} s")
        gt = info["geoTransform"]
        if gt[:6] == [0.0, 1.0, 0.0, 0.0, 0.0, 1.0] or not info["wkt"]:
            # georeferencing isn't in the TIFF – it comes from .tfw or .aux.xml
            log("The raster has no georeferencing of its own – trying again "
                "with sidecars (.tfw / .aux.xml).")
            info = probe(vsi, log, timeout=args.probe_timeout)
    if info is None:
        # the main raster didn't open: try the overviews – a coarser model beats none
        forced, expect_fb, info = ovr_fallback(
            args.url, member, args.work, log, args.plan, args.probe_timeout)
        if info is None:
            log("::error::The raster couldn't be opened even through the "
                "overviews. If the tile directory lies deep in the file (see "
                "above), that is the cause: the ZIP member is deflated, so GDAL "
                "reaches it only by unpacking all before it.")
            return 3
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"member={member}\n")
            f.write(f"px={info['size'][0]}x{info['size'][1]}\n")
            f.write(f"cell_m={info['pixel'][0]}\n")
            f.write(f"overviews={len(info['overviews'])}\n")

    if args.probe_only:
        log("Probe only – nothing downloaded but the header.")
        area_name = None
    else:
        area_name, bbox = resolve_area(args.area, args.areas)
        os.makedirs(args.out, exist_ok=True)

        # main raster or overviews (151 vs 46 GB) decides the run's length – logged
        if forced:
            # the main raster didn't open, overviews it is
            src, expect = forced, expect_fb
            if args.grid_m < info["pixel"][0]:
                log(f"::warning::The asked {args.grid_m} m grid is finer than "
                    f"the overview ({info['pixel'][0]:g} m) – the result is "
                    f"interpolated, no new information in it.")
        else:
            src, expect = (None, None) if args.no_ovr else ovr_source(
                args.url, member, info, args.grid_m, args.work, log, args.plan,
                args.probe_timeout)
        if src is None:
            src = vsi
            main_entry = find_sidecar(args.plan, member, "")
            expect = main_entry["csize"] if main_entry else None
            log(f"Reading the main raster ({(expect or 0) / 1e9:.2f} GB in the archive).")

        if bbox is None:
            whole_country(src, args.grid_m, args.work, args.out, log, expect)
        else:
            asset = args.asset or "ugkk-cutout.tif"
            area_cut(src, bbox, args.grid_m, os.path.join(args.out, asset),
                     args.work, log, info, expect)
        made = sorted(f for f in os.listdir(args.out) if f.endswith(".tif"))
        total = sum(os.path.getsize(os.path.join(args.out, f)) for f in made)
        log(f"Done: {len(made)} files, {total / 1048576:.0f} MB")
        if args.github_output:
            with open(args.github_output, "a") as f:
                f.write(f"files={len(made)}\n")

    if args.summary:
        with open(args.summary, "w") as f:
            f.write("## Raster straight from the archive\n\n")
            f.write("| item | value |\n|---|---|\n")
            f.write(f"| member | `{member}` |\n")
            f.write(f"| size | {info['size'][0]}×{info['size'][1]} px |\n")
            f.write(f"| source grid | {info['pixel'][0]} m |\n")
            f.write(f"| CRS | {info['crs']} |\n")
            f.write(f"| compression | {info['compression']} |\n")
            f.write(f"| tile | {info['block']} |\n")
            f.write(f"| overview levels | {len(info['overviews'])} |\n")
            if area_name:
                f.write(f"| area | {area_name} |\n")
                f.write(f"| target grid | {args.grid_m} m |\n")
            f.write("\n<details><summary>Log</summary>\n\n```\n"
                    + "\n".join(lines) + "\n```\n\n</details>\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
