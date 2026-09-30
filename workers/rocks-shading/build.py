#!/usr/bin/env python3
"""Rocks from hillshading tiles (JPG) → vector areas (GeoPackage).

The second, experimental way to rocks: dark areas in a finished hillshade.

    XYZ tiles (JPG) → a grey mosaic in EPSG:3857 → a "darkness" raster →
    opening → gdal_contour -p → area filter → rounding → rock.gpkg

The threshold is three numbers:

    ref   = clip(local_background − --rel, --dark-always, --dark)
    score = max(0, ref − grey)

Work in progress lies in `<cache-dir>/_in_progress/<threshold signature>/` for
the next run to pick up; `--fresh=1` drops it first.

Usage:
    python3 workers/rocks-shading/build.py --bbox=19.9,49.09,20.32,49.25 \\
        --zoom=auto --dark=110 --local=512 --rel=18 --cliff=25 --open=3 \\
        --out=data/rock.gpkg --stats=out/rock-img-stats.txt \\
        --preview=out/preview.png
"""
import argparse
import importlib.util
import math
import os
import shlex
import shutil
import sys
import time

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# three phases, three modules, in the order of the `shading-rocks.yml` jobs:
#   tiles.py download, raster.py darkness raster, vector.py outlines and filter
tiles = load("shading_tiles", "tiles.py")
raster = load("shading_raster", "raster.py")
vector = load("shading_vector", "vector.py")

# what this file takes from which phase
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
TILES_PER_S, CONTOUR_CELLS_PER_S = tiles.TILES_PER_S, tiles.CONTOUR_CELLS_PER_S
BG_DOWN = raster.BG_DOWN
run = tiles.run
tile_range, tile_res, ground_res = tiles.tile_range, tiles.tile_res, tiles.ground_res
Fetcher, probe_zoom, BROWSERS = tiles.Fetcher, tiles.probe_zoom, tiles.BROWSERS
build_score_raster = raster.build_score_raster
bbox_km2, outlines, join, empty_rock = (vector.bbox_km2, vector.outlines, vector.join,
                                        vector.empty_rock)
write_downloaded, read_downloaded = vector.write_downloaded, vector.read_downloaded

# `watch.py` is shared by both ways to rocks, so it lives in `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb  # noqa: E402


def save_preview(rows, path):
    """A downscaled mosaic beside the areas found – grey left, red mask right."""
    if not rows:
        return
    gray = np.concatenate([g for g, _ in rows], axis=0)
    mask = np.concatenate([m for _, m in rows], axis=0)
    rgb = np.dstack([gray, gray, gray])
    hit = mask > 0
    rgb[..., 0] = np.where(hit, 255, rgb[..., 0])
    rgb[..., 1] = np.where(hit, (gray * 0.35).astype(np.uint8), rgb[..., 1])
    rgb[..., 2] = np.where(hit, (gray * 0.35).astype(np.uint8), rgb[..., 2])
    both = np.concatenate([np.dstack([gray, gray, gray]), rgb], axis=1)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(both).save(path)
    print(f"  preview: {path} ({both.shape[1]}×{both.shape[0]} px)", flush=True)


def histogram(rows):
    """The grey distribution – the first thing to see when tuning the threshold."""
    if not rows:
        return ""
    gray = np.concatenate([g for g, _ in rows], axis=0)
    hist, _ = np.histogram(gray, bins=16, range=(0, 256))
    tot = max(1, hist.sum())
    out = ["  grey     share"]
    for i, v in enumerate(hist):
        pct = 100.0 * v / tot
        out.append(f"  {i * 16:>3}–{i * 16 + 15:<3} {pct:5.1f} % "
                   f"{'█' * int(round(pct / 2))}")
    return "\n".join(out)


def print_plan(z, x0, y0, x1, y1, args):
    n_tiles = (x1 - x0) * (y1 - y0)
    cells = n_tiles * TILE * TILE
    dl_s = n_tiles / TILES_PER_S
    ct_s = cells / CONTOUR_CELLS_PER_S
    print("── Plan: rocks from hillshading tiles ───────────────")
    print(f"  zoom            z{z}  ({tile_res(z):.2f} m/px in Mercator, "
          f"~{ground_res(z, (args.bbox[1] + args.bbox[3]) / 2):.2f} m on the ground)")
    print(f"  tiles           {x1 - x0} × {y1 - y0} = {n_tiles}")
    print(f"  mosaic          {(x1 - x0) * TILE} × {(y1 - y0) * TILE} px "
          f"= {cells / 1e9:.2f} G")
    print(f"  darkness        never over {args.dark}, always under {args.dark_always}"
          + (f", in between {args.rel} under the background "
             f"(window {args.local:g} m = {args.local_px} px)"
             if args.local_px else ", no local background"))
    print(f"  classes         steep, cliff from {args.cliff} levels more")
    print("  narrower than   " + (f"{2 * args.open:g} m out "
                                  f"(opening {args.open_px} px) – "
                                  f"hairlines aren't walls"
                                  if args.open_px else
                                  "nothing (opening off)"))
    print("  structure       " + (f"filled, window {args.fill:g} m "
                                  f"({args.fill_px} px)" if args.fill_px
                                  else "a fine gully network (fill off)"))
    print("  headers         " + ("each request as another browser "
                                  f"({len(BROWSERS)} profiles)"
                                  if args.ua == "rotate" else
                                  "the project's name" if args.ua == "project"
                                  else f"own: {args.ua}"))
    print(f"  download est.   ~{hms(dl_s)}")
    print(f"  outlines est.   ~{hms(ct_s)}")
    print("─────────────────────────────────────────────────────", flush=True)
    return n_tiles, cells


# former option names, still accepted
OPTION_ALIAS = {"plne": "solid", "zapln_diery": "fill_holes", "zlepit": "stitch"}


def apply_options(ap, args):
    """`key=value` from one text field → the same options, so argparse catches typos."""
    raw = (args.options or "").strip()
    if not raw:
        return args
    known = {a.dest for a in ap._actions if a.dest not in ("help", "options")}
    extra = []
    for tok in shlex.split(raw):
        if "=" not in tok:
            print(f"::error::Option \"{tok}\" isn't key=value.",
                  file=sys.stderr)
            sys.exit(1)
        k, v = tok.split("=", 1)
        k = k.strip().replace("-", "_")
        k = OPTION_ALIAS.get(k, k)
        if k not in known:
            print(f"::error::Unknown option \"{k}\". Known options: "
                  f"{', '.join(sorted(known))}", file=sys.stderr)
            sys.exit(1)
        extra.append(f"--{k.replace('_', '-')}={v}")
    print(f"From options: {' '.join(extra)}", flush=True)
    return ap.parse_args(sys.argv[1:] + extra)


def main():
    ap = argparse.ArgumentParser(
        description="Rock areas from dark spots in hillshading tiles.")
    ap.add_argument("--bbox", required=True, help="W,S,E,N in degrees")
    ap.add_argument("--url", default="https://sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg",
                    help="an XYZ template with {z}/{x}/{y}")
    ap.add_argument("--zoom", default="auto", help="a number or `auto`")
    # z17 is the cap: z18 is 4× the tiles and overzoom stretches the areas anyway
    ap.add_argument("--zoom-max", type=int, default=17,
                    help="the highest zoom tiles are asked for at all "
                         "(`auto` tries down from there)")
    ap.add_argument("--zoom-min", type=int, default=12)
    ap.add_argument("--max-tiles", type=int, default=60000,
                    help="the tile count cap – `auto` goes under it itself")
    # a number, not `store_true`: options always come as `key=value`
    ap.add_argument("--block-tiles", type=int, default=8,
                    help="block side in tiles for outlines; smaller = less "
                         "memory and finer resuming, but more GDAL calls "
                         "(8 = 2048 px, 3 = 768 px)")
    # three jobs, each with its own time cap, passing work through the cache
    ap.add_argument("--phase", default="all",
                    choices=("all", "download", "vector", "join"),
                    help="which part to do")
    ap.add_argument("--zoom-out", default="",
                    help="where to write the chosen zoom (`zoom=17`) for the next job")
    ap.add_argument("--fresh", type=int, default=0,
                    help="1 = drop an earlier run's work in progress and compute "
                         "everything anew (tiles stay cached)")
    ap.add_argument("--log-every", type=int, default=25,
                    help="print a line every so many tiles "
                         "(1 = each, 0 = only every 15 s)")
    # 0 = no cap: stopping halfway through outlines never saved anything
    ap.add_argument("--budget-min", type=float, default=0,
                    help="how many minutes outlines may take; `auto` goes "
                         "under it and the run stops beyond (0 = no cap, "
                         "the default)")
    ap.add_argument("--dark", type=int, default=125,
                    help="the absolute cap: over this grey there is never rock")
    ap.add_argument("--dark-always", type=int, default=70,
                    help="under this grey there is always rock, whatever is around")
    ap.add_argument("--local", type=float, default=1500.0,
                    help="the local background window in METRES on the ground (0 = off)")
    ap.add_argument("--rel", type=int, default=18,
                    help="how far a pixel must be under the local background")
    ap.add_argument("--cliff", type=int, default=25,
                    help="how many levels darker the `cliff` class starts")
    ap.add_argument("--blur", type=int, default=1,
                    help="the grey blur radius in px (0 = off, max 2)")
    ap.add_argument("--fill", type=float, default=0.0,
                    help="average the darkness over a window of so many METRES – "
                         "makes a solid area of the gully network (0 = off)")
    # hairline gullies are dark but no walls; dropped by width, the network is one shape
    ap.add_argument("--open", type=float, default=3.0,
                    help="drop shapes narrower than 2× so many METRES "
                         "(0 = off, keeps hairlines too)")
    # ~11 pixels at z17; the fine gully network is what we want from hillshade
    ap.add_argument("--min-area", type=float, default=7.0,
                    help="the smallest rock area in m²")
    ap.add_argument("--solid", type=int, default=1,
                    help="1 = one band and one class (no area inside another), "
                         "0 = steep/cliff bands as before")
    # holes are gaps between the network's threads – filling made blobs
    ap.add_argument("--fill-holes", type=int, default=0,
                    help="1 = fill holes (solid areas instead of a network)")
    ap.add_argument("--stitch", type=int, default=0,
                    help="1 = stitch areas cut by a block edge "
                         "(ST_Union, needs spatialite)")
    ap.add_argument("--min-hole", type=float, default=10.0,
                    help="the smallest hole kept, in m²")
    ap.add_argument("--simplify", type=float, default=-1,
                    help="outline simplification in metres (-1 = one pixel)")
    ap.add_argument("--smooth", type=int, default=2,
                    help="allowed sag of the rounded outline in QUARTERS of the "
                         "tile grid step (0 = rounding off)")
    # the maxzoom gives the grid step the outline is sampled by
    ap.add_argument("--maxzoom", type=int, default=16,
                    help="the rock tiles' maxzoom (the `extent` grid)")
    ap.add_argument("--jobs", type=int, default=12, help="parallel downloads")
    ap.add_argument("--ua", default="rotate",
                    help="`rotate` = each request as another browser, "
                         "`project` = name the project, or a literal "
                         "User-Agent")
    ap.add_argument("--cache-dir", default="tiles-cache")
    ap.add_argument("--band-cells", type=float, default=150e6,
                    help="how many pixels one band holds in memory")
    ap.add_argument("--heartbeat", type=int, default=30)
    ap.add_argument("--preview", default="", help="where to save the PNG preview")
    ap.add_argument("--preview-down", type=int, default=16,
                    help="how many times to shrink the preview")
    ap.add_argument("--stats", default="", help="where to write key=value")
    ap.add_argument("--options", default="",
                    help="rarely changed options as `key=value`, "
                         "e.g. `local=800 min_area=300`")
    ap.add_argument("--out", required=True)
    args = apply_options(ap, ap.parse_args())

    args.bbox = [float(v) for v in args.bbox.split(",")]
    if len(args.bbox) != 4:
        print("::error::--bbox must be W,S,E,N.", file=sys.stderr)
        return 1
    args.blur = max(0, min(2, args.blur))
    lat_mid = (args.bbox[1] + args.bbox[3]) / 2.0

    os.makedirs(args.cache_dir, exist_ok=True)
    fetcher = Fetcher(args.url, args.cache_dir, jobs=args.jobs, ua=args.ua,
                      log_every=args.log_every)

    if str(args.zoom).strip().lower() == "auto":
        z = probe_zoom(fetcher, args.bbox, args.zoom_max, args.zoom_min,
                       args.max_tiles, args.budget_min * 60)
        if not z:
            return 1
    else:
        z = int(args.zoom)

    # windows are in metres; pixels only once the zoom is known
    args.local_px = (int(round(args.local / ground_res(z, lat_mid)))
                     if args.local > 0 else 0)
    args.fill_px = (int(round(args.fill / ground_res(z, lat_mid)))
                    if args.fill > 0 else 0)
    args.open_px = (max(1, int(round(args.open / ground_res(z, lat_mid))))
                    if args.open > 0 else 0)
    x0, y0, x1, y1 = tile_range(args.bbox, z)
    n_tiles, cells = print_plan(z, x0, y0, x1, y1, args)
    if n_tiles > args.max_tiles:
        print(f"::error::z{z} has {n_tiles} tiles, the cap is {args.max_tiles}. "
              f"Pick a smaller cut-out or a lower zoom (or raise --max-tiles).",
              file=sys.stderr)
        return 2

    if args.simplify < 0:
        # one pixel, not a quarter: the source is an 8-bit JPEG, below a pixel is grain
        args.simplify = tile_res(z)

    # the work dir is in the tile cache, saved after a failure too; the signature
    # keeps runs with other thresholds apart
    signature = (f"z{z}-d{args.dark}-a{args.dark_always}-r{args.rel}"
                 f"-c{args.cliff}-l{args.local:g}-f{args.fill:g}-b{int(args.blur)}"
                 # opening changes the darkness raster, so the block outlines too
                 f"-o{args.open:g}"
                 f"-m{args.min_area:g}-h{args.min_hole:g}"
                 # solid areas change the bands, so the blocks' content
                 f"{'-solid' if args.solid else ''}"
                 f"-fh{int(bool(args.fill_holes))}")
    tmp = os.path.join(args.cache_dir, "_in_progress", signature)
    # `fresh` belongs to the phases making work; `join` would delete the job's beside it
    if args.fresh and args.phase != "join":
        shutil.rmtree(tmp, ignore_errors=True)
    elif args.fresh:
        print("  `fresh` is ignored in the `join` phase: it stitches what the "
              "`vector` phase made in this run.", flush=True)
    os.makedirs(tmp, exist_ok=True)
    if os.listdir(tmp):
        print("── Work in progress from an earlier run ─────────────")
        print(f"  {tmp}")
        for f in sorted(os.listdir(tmp)):
            print(f"    {f}  {dir_mb(os.path.join(tmp, f)):.0f} MB")
        print("  finished phases are skipped; `options: fresh=true` drops it")
        print("─────────────────────────────────────────────────────", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    t_all = time.time()
    # threshold 0.5, not 1: an isoline halfway gives a sub-pixel outline
    cliff_level = 0.5 + args.cliff
    merc = math.cos(math.radians(lat_mid)) ** 2
    dl_s = sc_s = vec_s = 0.0

    if args.phase == "join":
        # stitching reads block outlines, not images
        print("── Tiles: skipped (join phase) ──────────────────────", flush=True)
        dl = read_downloaded(args.cache_dir, n_tiles)
    else:
        print("── Downloading tiles ────────────────────────────────", flush=True)
        dl_s = fetcher.fetch_all(z, x0, y0, x1, y1)
        if fetcher.n_ok + fetcher.n_cached == 0:
            print("::error::Not a single tile downloaded – without data nothing "
                  "can be vectorised.", file=sys.stderr)
            return 1
        dl = write_downloaded(args.cache_dir, fetcher, n_tiles)

        # the chosen zoom out, so the next job needn't guess it again
        if args.zoom_out:
            with open(args.zoom_out, "a") as f:
                f.write(f"zoom={z}\n")

        if args.phase == "download":
            print("── Done (download only) ─────────────────────────────")
            print(f"  zoom            z{z}")
            print(f"  tiles           {n_tiles} ({fetcher.bytes / 1048576:.0f} MB "
                  f"downloaded, {fetcher.n_cached} from the cache)")
            print(f"  time            {hms(dl_s)}")
            print("  Vectorising is a job of its own – it takes the tiles from the cache.")
            print("─────────────────────────────────────────────────────", flush=True)
            return 0

    if args.phase != "join":
        print("── Darkness raster ──────────────────────────────────", flush=True)
        preview_rows = [] if args.preview else None
        tifs, sc_s = build_score_raster(fetcher, z, x0, y0, x1, y1, args, tmp,
                                        preview_rows)

        print("── Outlines in blocks ───────────────────────────────", flush=True)
        t_vec = time.time()
        try:
            n_blocks = outlines(tifs, args, tmp, cliff_level)
        except RuntimeError as exc:
            # the message is readable, a traceback isn't
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        except TimeoutError:
            # the estimate was off; downloaded tiles stay cached
            print(f"::error::Outlines didn't finish within {args.budget_min:g} "
                  f"min. Try a lower zoom (`zoom: {z - 1}`), a smaller cut-out, "
                  f"or raise the budget (`options: budget_min=…`). The tiles are "
                  f"cached, so the next run doesn't download them again.",
                  file=sys.stderr)
            return 2
        vec_s = time.time() - t_vec

        # the preview and histogram come from the raster, not finished polygons
        if args.preview:
            save_preview(preview_rows, args.preview)
        hist = histogram(preview_rows) if preview_rows else ""
        if hist:
            print("── Grey distribution ────────────────────────────────")
            print(hist)
            print("─────────────────────────────────────────────────────",
                  flush=True)

        if args.phase == "vector":
            print("── Done (outlines only) ─────────────────────────────")
            print(f"  blocks          {n_blocks}")
            print(f"  time            darkness {hms(sc_s)}, outlines {hms(vec_s)}")
            print("  Stitching, filter and smoothing are a job of their own – "
                  "it takes the work in progress from the cache.")
            print("─────────────────────────────────────────────────────",
                  flush=True)
            return 0

    print("── Joining blocks and filter ────────────────────────", flush=True)
    t_sp = time.time()
    try:
        st = join(args, tmp, args.out, cliff_level, merc,
                  area_km2=bbox_km2(args.bbox))
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    sp_s = time.time() - t_sp
    if not st.get("n"):
        print("::warning::Not a single rock area was found – the thresholds "
              "are probably strict. See the preview and histogram of the outline phase.")
        empty_rock(args.out)

    total_km2 = st.get("total_m2", 0.0) / 1e6
    print("── Done ─────────────────────────────────────────────")
    print(f"  areas           {st.get('n', 0)} "
          f"(of them {st.get('cliff', 0)} `cliff`), "
          f"{st.get('n_in', 0) - st.get('n', 0)} under {args.min_area:g} m² out")
    print(f"  total           {total_km2:.2f} km², "
          f"largest {st.get('max_m2', 0) / 1e4:.1f} ha")
    print(f"  holes           {st.get('holes', 0)}")
    # data per km² of rock decides the budget, not the area count
    out_mb = dir_mb(args.out)
    per_km2 = out_mb / total_km2 if total_km2 > 0.001 else 0.0
    print(f"  output          {args.out} ({out_mb:.1f} MB"
          + (f", {per_km2:.1f} MB per km² of rock)" if per_km2 else ")"))
    print(f"  time            download {hms(dl_s)}, darkness {hms(sc_s)}, "
          f"outlines {hms(vec_s)}, join {hms(sp_s)}, "
          f"total {hms(time.time() - t_all)}")
    if args.phase == "join":
        print("  (download and outline times are in their own jobs)")
    print("─────────────────────────────────────────────────────", flush=True)

    if args.stats:
        os.makedirs(os.path.dirname(os.path.abspath(args.stats)) or ".",
                    exist_ok=True)
        with open(args.stats, "w") as f:
            for k, v in [
                ("count", st.get("n", 0)), ("cliff", st.get("cliff", 0)),
                ("total_km2", f"{total_km2:.3f}"),
                ("max_m2", int(st.get("max_m2", 0))),
                ("holes", st.get("holes", 0)),
                ("holes_dropped", st.get("holes_dropped", 0)),
                ("dropped", st.get("n_in", 0) - st.get("n", 0)),
                ("zoom", z), ("tiles", dl["tiles"]),
                ("tiles_missing", dl["tiles_missing"]),
                ("tiles_failed", dl["tiles_failed"]),
                ("mb_downloaded", dl["mb_downloaded"]),
                ("ua", args.ua), ("ua_profiles", dl["ua_profiles"]),
                ("cells", cells), ("px_m", f"{ground_res(z, lat_mid):.2f}"),
                ("dark", args.dark), ("dark_always", args.dark_always),
                ("local_m", f"{args.local:g}"), ("local_px", args.local_px),
                ("rel", args.rel),
                ("cliff_delta", args.cliff), ("blur", args.blur),
                ("fill_m", f"{args.fill:g}"),
                ("open_m", f"{args.open:g}"), ("open_px", args.open_px),
                ("out_mb", f"{out_mb:.1f}"), ("mb_per_km2", f"{per_km2:.1f}"),
                ("min_area_m2", f"{args.min_area:g}"),
                ("solid", int(bool(args.solid))),
                ("fill_holes", int(bool(args.fill_holes))),
                ("stitched", int(bool(args.stitch))),
                ("min_hole_m2", f"{args.min_hole:g}"),
                ("simplify_m", f"{args.simplify:.2f}"), ("smooth", args.smooth),
                ("seconds", int(time.time() - t_all)),
            ]:
                f.write(f"{k}={v}\n")

    # only now: otherwise the cache grows by every run's intermediates
    shutil.rmtree(tmp, ignore_errors=True)
    print("Work in progress deleted – the run finished whole.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
