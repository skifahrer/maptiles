#!/usr/bin/env python3
"""DEM → rock areas as vectors (GeoPackage).

"Dense contours = rock" is only another view of steep slope that also depends
on interval and zoom, so rocks are computed straight from the slope:

    finished slope mosaic → gdal_contour -p (isolines as areas) →
    split into areas → smallest-area filter → one class

The outline is the slope isoline, exactly where terrain crosses the threshold.
Holes stay: a gentler spot inside a wall isn't filled, which makes a rock's
shape readable (`--fill-holes=1` fills them).

Usage (slope-chunks.py gives the grid and the mosaic):
    python3 workers/contours-rocks/rock-areas.py --slope-vrt=slope-chunks/slope-r2.vrt \\
        --bbox=W,S,E,N --res=2 --slope=50 --cliff=65 --out=data/rock.gpkg
"""
import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time


# grid, extents and time estimates are in `rock-plan.py`; `slope-chunks.py` needs them first
def _load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(os.path.abspath(__file__)), path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


plan = _load("rock_plan", "rock-plan.py")
# outlines in blocks are shared with rocks from hillshading, so they live in lib
blocks_mod = _load("contour_blocks", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "lib", "contour-blocks.py"))
METRIC, SCALE = plan.METRIC, plan.SCALE
SLOPE_CELLS_PER_S = plan.SLOPE_CELLS_PER_S
CONTOUR_SRC_CELLS_PER_S = plan.CONTOUR_SRC_CELLS_PER_S
MOSAIC_MB_PER_GCELL = plan.MOSAIC_MB_PER_GCELL
RES_LADDER, VEC_FLOOR_M = plan.RES_LADDER, plan.VEC_FLOOR_M
run, to_metric, dem_cell_metres = plan.run, plan.to_metric, plan.dem_cell_metres
chunk_plan, intersects_bbox = plan.chunk_plan, plan.intersects_bbox
pick_res, pick_vec_res = plan.pick_res, plan.pick_vec_res
mosaic_cells, mosaic_info, clip_vrt = plan.mosaic_cells, plan.mosaic_info, plan.clip_vrt

# heartbeat, GDAL progress and measuring are in `workers/lib/watch.py`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, run_watched  # noqa: E402


def bbox_km2(bbox):
    """A bbox's rough area in km² – to compare how much of the area is rock."""
    w, s, e, n = bbox
    mid = math.radians((s + n) / 2.0)
    return abs(e - w) * 111.32 * math.cos(mid) * abs(n - s) * 110.54


def check_position(path, bbox, layer="rock"):
    """Do the finished rocks lie where the area is? Returns a message, or None."""
    # the last guard before the map: a layer without CRS lands at the other end of the world
    try:
        info = json.loads(run(["ogrinfo", "-json", "-so", path, layer]).stdout)
        ext = (info.get("layers") or [{}])[0].get("geometryFields", [{}])[0].get("extent")
    except (subprocess.CalledProcessError, ValueError, IndexError, KeyError):
        return None  # can't be told – no reason to fail a finished computation
    if not ext or len(ext) != 4:
        return None
    x0, y0, x1, y1 = ext
    w, s, e, n = bbox
    # a 1° tolerance: an outline may overhang a bit, not by orders of magnitude
    if x1 < w - 1 or x0 > e + 1 or y1 < s - 1 or y0 > n + 1:
        return (f"the finished rocks lie at {x0:.4f},{y0:.4f} … {x1:.4f},{y1:.4f}, "
                f"but the area is {w},{s} … {e},{n} – not a shift, other "
                f"coordinates. The layer probably ended without CRS and `-t_srs "
                f"EPSG:4326` had nothing to convert from (look for `No SRS set "
                f"on layer` in the log). Planetiler makes an empty .pmtiles of "
                f"it and the map is silently without rocks (run 31428413843).")
    return None


def ogr_count(path, layer="rock"):
    try:
        out = run(["ogrinfo", "-so", path, layer]).stdout
        for line in out.splitlines():
            if line.startswith("Feature Count"):
                return int(line.split(":")[1])
    except subprocess.CalledProcessError:
        pass
    return 0


def area_stats(metric_gpkg):
    """Count, total/largest/smallest/mean area in m², and how much holes cut out."""
    sql = ("SELECT COUNT(*) AS n, SUM(ST_Area(geom)) AS total, "
           "MAX(ST_Area(geom)) AS amax, MIN(ST_Area(geom)) AS amin, "
           "AVG(ST_Area(geom)) AS aavg FROM rock")
    try:
        out = run(["ogr2ogr", "-f", "CSV", "/vsistdout/", metric_gpkg,
                   "-dialect", "SQLITE", "-sql", sql]).stdout.strip().splitlines()
        st = {k: float(v or 0) for k, v in
              zip(["n", "total", "max", "min", "avg"], out[1].split(","))}
    except Exception:
        return {}
    # what holes cut out = the outer outline's area minus the real one
    try:
        sql2 = ("SELECT SUM(ST_Area(ST_Buildarea(ST_ExteriorRing(geom)))) AS outer_, "
                "SUM(CASE WHEN ST_NumInteriorRing(geom) > 0 THEN 1 ELSE 0 END) AS withholes "
                "FROM (SELECT ST_GeometryN(geom, 1) AS geom FROM rock)")
        out2 = run(["ogr2ogr", "-f", "CSV", "/vsistdout/", metric_gpkg,
                    "-dialect", "SQLITE", "-sql", sql2]).stdout.strip().splitlines()
        o, wh = out2[1].split(",")
        st["holes_km2"] = max(0.0, (float(o or 0) - st["total"]) / 1e6)
        st["with_holes"] = float(wh or 0)
    except Exception:
        pass
    return st


def main():
    ap = argparse.ArgumentParser()
    # the slope comes finished from `slope-chunks.py`; vectorising is one pass here
    ap.add_argument("--slope-vrt", required=True,
                    help="slope mosaic from workers/contours-rocks/slope-chunks.py")
    ap.add_argument("--dem", default="",
                    help="the source DEM – only to report the real detail")
    ap.add_argument("--bbox", required=True, help="west,south,east,north in degrees")
    ap.add_argument("--out", required=True, help="output GeoPackage (layer rock)")
    ap.add_argument("--vec-res", default="auto",
                    help="vectorising grid in metres, or `auto` "
                         "(never finer than --res)")
    ap.add_argument("--res", default="auto",
                    help="slope grid in metres, or `auto` = the finest "
                         "fitting the time budget")
    ap.add_argument("--slope", type=float, default=50.0, help="slope threshold in degrees")
    ap.add_argument("--cliff", type=float, default=65.0,
                    help="the `cliff` class threshold (only without `--solid`)")
    ap.add_argument("--solid", type=int, default=1,
                    help="1 = one band and one class (no area inside another), "
                         "0 = steep/cliff bands as before")
    ap.add_argument("--fill-holes", type=int, default=0,
                    help="1 = fill holes (solid areas instead of shape)")
    ap.add_argument("--min-area", type=float, default=-1.0,
                    help="smallest area in m²; -1 = one grid cell "
                         "(smaller is one cell, not a terrain shape)")
    ap.add_argument("--simplify", type=float, default=-1.0,
                    help="outline simplification tolerance in metres; "
                         "-1 = a quarter grid (removes stairs), 0 = off")
    ap.add_argument("--smooth", type=int, default=2,
                    help="allowed sag of the rounded outline in QUARTERS of "
                         "the tile grid step; 0 = rounding off")
    ap.add_argument("--maxzoom", type=int, default=16,
                    help="the rock tiles' maxzoom – it sets the grid step and "
                         "so the outline's point density")
    ap.add_argument("--chunk-cells", type=float, default=150e6,
                    help="the cell cap per chunk when computing slope")
    # blocks bound memory and keep finished work on disk; 0 = one pass
    ap.add_argument("--block-px", type=int, default=4096,
                    help="block side in pixels when vectorising "
                         "(0 = one pass over the whole mosaic)")
    ap.add_argument("--budget-min", type=float, default=0.0,
                    help="how many minutes the computation SHOULD take: picks "
                         "the grid (`--res=auto`) and says what to shrink when "
                         "over – but does NOT stop it (0 = ignore)")
    ap.add_argument("--max-rss-gb", type=float, default=12.0,
                    help="memory cap for gdal_contour (0 = none)")
    ap.add_argument("--heartbeat", type=float, default=30.0,
                    help="how often to report it is still computing (s)")
    ap.add_argument("--stats", default="", help="where to write the stats (key=value)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    dem_dx, dem_dy = (dem_cell_metres(args.dem, (bbox[1] + bbox[3]) / 2)
                      if args.dem else (None, None))

    # `slope-chunks.py` picks the grid; two picks would drift
    if str(args.res).strip().lower() in ("auto", "", "0"):
        print("::error::--res must be a number: workers/contours-rocks/"
              "slope-chunks.py picks the grid (`--print-res`) and this script "
              "gets it finished.")
        return 2
    res = float(args.res)

    # the vectorising grid needn't be the store's: saves memory and output, not time
    box = to_metric(bbox)
    area = (box[2] - box[0]) * (box[3] - box[1])
    if str(args.vec_res).strip().lower() in ("auto", "", "0"):
        vec_res = pick_vec_res(res)
    else:
        vec_res = max(res, float(args.vec_res))
    # a quarter cell: removes stairs without moving the outline more; `--smooth` rounds corners
    if args.simplify < 0:
        args.simplify = vec_res / 4.0
    # the smallest rock = one grid cell, known only here
    if args.min_area < 0:
        args.min_area = round(vec_res * vec_res, 2)
    if dem_dx:
        print(f"The source DEM has a ~{dem_dx:.0f}×{dem_dy:.0f} m cell – the cap "
              f"of real detail; a {res:g} m grid only smooths the outline.")

    # 1. the finished slope mosaic
    vrt = args.slope_vrt
    if not os.path.exists(vrt):
        print(f"::error::Slope mosaic {vrt} doesn't exist – "
              f"workers/contours-rocks/slope-chunks.py must run first.")
        return 2
    mw, mh, mbox, sources = mosaic_info(vrt)
    cells = float(mw) * mh if mw else mosaic_cells(vrt)
    print(f"Slope mosaic: {vrt}, {mw}×{mh} px = {cells / 1e9:.2f} G cells "
          f"at a {res:g} m grid ({sources} store chunks)")

    t_start = time.time()
    tmp = tempfile.mkdtemp(prefix="rock-", dir=os.path.dirname(args.out) or ".")
    try:
        # 2. clip the mosaic to the area, before the budget guard measures the work
        needed = area / (vec_res * vec_res)
        if vec_res > res or (mbox and cells and needed and cells > needed * 1.05):
            vrt = clip_vrt(vrt, box, vec_res, tmp, src_res=res)
            cw, ch, _, _ = mosaic_info(vrt)
            clipped = float(cw) * ch
            why = ("clip to the area" if vec_res == res else
                   f"clip to the area and grid {res:g} → {vec_res:g} m")
            # fewer cells to trace, not less work: coarsening still reads them all
            print(f"View of the store ({why}): {mw}×{mh} → {cw}×{ch} px, "
                  f"{cells / 1e9:.2f} → {clipped / 1e9:.2f} G cells to trace. "
                  f"Store chunks stay whole at full resolution, only the view "
                  f"is cut.")
            cells = clipped
        else:
            print(f"The mosaic already fits the area ({needed / 1e9:.2f} G cells "
                  f"needed) – nothing is clipped.")

        # how much is read decides the time, not how much is traced
        src_cells = cells * (vec_res / res) ** 2

        # the budget is an estimate, not a switch: a killed gdal_contour leaves nothing
        estimate_s = src_cells / CONTOUR_SRC_CELLS_PER_S if src_cells else 0.0
        if args.budget_min > 0 and estimate_s > args.budget_min * 60:
            print(f"::warning::Vectorising reads {src_cells / 1e9:.2f} G store "
                  f"cells and will take ~{hms(estimate_s)}, over the "
                  f"{args.budget_min:.0f} min budget – NOT stopping it, letting "
                  f"it finish (only the job timeout stops it). To be faster: a "
                  f"COARSER STORE (`rock_res`, now {res:g} m – doubling is a "
                  f"quarter of the reading) or a smaller cut-out (`area`); "
                  f"coarser tracing (`rock_vec_res`) changes nothing here. The "
                  f"slope stays in the store either way.")

        # 3. vectorising over the whole mosaic at once: no seams, holes stay holes
        bands = os.path.join(tmp, "bands.gpkg")
        print("── Vectorising the slope (gdal_contour -p) ──────────")
        print(f"  input           {vrt}")
        print(f"  reading         {src_cells / 1e9:.2f} G store cells "
              f"({res:g} m) – this decides the time")
        print(f"  tracing         {cells / 1e9:.2f} G cells at {vec_res:g} m")
        print(f"  thresholds      slope ≥ {args.slope:g}°"
              + ("" if args.solid else f", cliffs ≥ {args.cliff:g}°"))
        print(f"  estimate        ~{hms(estimate_s)} at "
              f"{CONTOUR_SRC_CELLS_PER_S / 1e3:.0f} k cells/s"
              + (f", budget {args.budget_min:.0f} min"
                 if args.budget_min > 0 else "") + "; the exact one comes from percentages")
        if args.block_px > 0:
            print(f"  in blocks       {args.block_px}×{args.block_px} px – a "
                  f"finished block stays on disk, so a cancelled run can resume")
            print(f"  caps            memory {args.max_rss_gb:g} GB; time UNLIMITED "
                  f"(heartbeat every {args.heartbeat:g} s)")
        else:
            print(f"  caps            memory {args.max_rss_gb:g} GB; time UNLIMITED "
                  f"– a pass can't be interrupted and resumed, so it runs until "
                  f"done (2.5 % steps, heartbeat every {args.heartbeat:g} s)")
        print("─────────────────────────────────────────────────────", flush=True)
        # solid areas (default): one band; a second level only doubled the rings
        levels = ([repr(args.slope * SCALE)] if args.solid else
                  [repr(args.slope * SCALE), repr(args.cliff * SCALE)])
        attributes = ["-amin", "smin", "-amax", "smax"]
        try:
            if args.block_px > 0:
                _, _, mbox_v, _ = mosaic_info(vrt)
                ox, oy = (mbox_v[0], mbox_v[3]) if mbox_v else (0.0, 0.0)
                # no time or memory cap: a block is small and what is done stays on disk
                d, n_blocks = blocks_mod.by_blocks(
                    vrt, os.path.join(tmp, "blocks"), levels, attributes,
                    args.block_px, (ox, oy, vec_res))
                seq = os.path.join(tmp, "blocks.geojsonl")
                n_shapes = blocks_mod.join_blocks(d, seq)
                print(f"  {n_blocks} blocks → {n_shapes} shapes", flush=True)
                # seams: no `srs` – the GeoJSON driver would turn metres into degrees
                seq = blocks_mod.stitch_seams(seq, tmp, key_attribute="smin",
                                              heartbeat=args.heartbeat)
                # `-a_srs` only labels the metric coordinates; without it Planetiler
                # gets lengths of 4 800 000 and `rocks.pmtiles` has zero tiles
                run(["ogr2ogr", "-f", "GPKG", bands, seq, "-nln", "band",
                     "-a_srs", METRIC, "-nlt", "PROMOTE_TO_MULTI"],
                    env={**os.environ, "OGR_GEOJSON_MAX_OBJ_SIZE": "0"})
            else:
                # no `max_s`: a time cap saves nothing here
                run_watched(["gdal_contour", "-p", "-fl"] + levels + attributes +
                            ["-f", "GPKG", "-nln", "band", vrt, bands],
                            "gdal_contour", tmp=tmp, every=args.heartbeat,
                            max_rss_mb=args.max_rss_gb * 1024)
        except MemoryError:
            print("::error::Vectorising didn't fit in memory. Shrink the area "
                  "with rock_area or pick a coarser rock_res grid.")
            return 2

        # the mosaic stays although it is over a gigabyte: chunks of the persistent store

        # 4. split into areas: gdal_contour glues each band into one multipolygon
        exploded = os.path.join(tmp, "rock-exploded.gpkg")
        lo, hi = int(args.slope), int(args.cliff)
        klass = ("'steep' AS class" if args.solid else
                 f"CASE WHEN smin >= {args.cliff * SCALE} THEN 'cliff' "
                 f"ELSE 'steep' END AS class")
        run(["ogr2ogr", "-f", "GPKG", exploded, bands, "band", "-nln", "rock",
             "-dialect", "SQLITE",
             "-sql", f"SELECT {klass}, geom FROM band "
                     f"WHERE smin >= {args.slope * SCALE}",
             "-explodecollections", "-nlt", "POLYGON"])
        os.remove(bands)
        if ogr_count(exploded) == 0:
            print("::warning::Not a single area over the slope threshold was found.")
            return 1

        # 5. smallest-area filter + attributes; holes stay unless `--fill-holes=1`
        stage = exploded
        final_metric = os.path.join(tmp, "rock-final.gpkg")
        geom = ("ST_BuildArea(ST_ExteriorRing(geom))"
                if args.fill_holes else "geom")
        sql = (f"SELECT class, CASE WHEN class = 'cliff' THEN {hi} ELSE {lo} END "
               f"AS slope, CAST(ST_Area({geom}) AS INTEGER) AS area, "
               f"{geom} AS geom "
               f"FROM rock WHERE ST_Area({geom}) >= {args.min_area}")
        simplify = ["-simplify", repr(args.simplify)] if args.simplify else []
        try:
            run(["ogr2ogr", "-f", "GPKG", final_metric, stage, "-nln", "rock",
                 "-dialect", "SQLITE", "-sql", sql] + simplify)
        except subprocess.CalledProcessError:
            # `ST_BuildArea` is spatialite's; rocks with holes beat no rocks
            if args.fill_holes:
                print("::warning::Filling holes (ST_BuildArea) doesn't work – "
                      "spatialite is probably missing. Rocks go with holes.")
                geom = "geom"
                sql = (f"SELECT class, CASE WHEN class = 'cliff' THEN {hi} "
                       f"ELSE {lo} END AS slope, "
                       f"CAST(ST_Area(geom) AS INTEGER) AS area, geom "
                       f"FROM rock WHERE ST_Area(geom) >= {args.min_area}")
            try:
                run(["ogr2ogr", "-f", "GPKG", final_metric, stage, "-nln",
                     "rock", "-dialect", "SQLITE", "-sql", sql] + simplify)
            except subprocess.CalledProcessError:
                print("::warning::The smallest-area filter (ST_Area) doesn't "
                      "work – rocks go without it.")
                sql = sql.replace(f" WHERE ST_Area(geom) >= {args.min_area}", "")
                sql = sql.replace("CAST(ST_Area(geom) AS INTEGER) AS area, ", "")
                run(["ogr2ogr", "-f", "GPKG", final_metric, stage, "-nln",
                     "rock", "-dialect", "SQLITE", "-sql", sql] + simplify)

        # 6. rounding the outline: sharp corners after simplifying look jagged at max zoom
        if args.smooth > 0:
            smoothed = os.path.join(tmp, "rock-smooth.gpkg")
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "smooth-shapes.py")
            try:
                out = run([sys.executable, script, f"--in={final_metric}",
                           f"--out={smoothed}", "--layer=rock",
                           f"--maxzoom={args.maxzoom}",
                           f"--sag={args.smooth}"])
                print(out.stdout.rstrip(), flush=True)
                final_metric = smoothed
            except subprocess.CalledProcessError as exc:
                print("::warning::Rounding the outline failed, rocks go jagged: "
                      f"{(exc.stderr or '').strip()[:300]}")

        st = area_stats(final_metric)
        run(["ogr2ogr", "-f", "GPKG", args.out, final_metric, "-nln", "rock",
             "-overwrite", "-t_srs", "EPSG:4326"])
        wrong = check_position(args.out, bbox)
        if wrong:
            print(f"::error::{wrong}")
            return 1
        n = int(st.get("n", ogr_count(args.out)))
        # zero rocks after the filter is a suspicion, not a result
        if n == 0:
            print(f"::error::There was something over the {args.slope:g}° slope "
                  f"threshold, but after the smallest-area filter "
                  f"({args.min_area:g} m²) not one rock was left. Either the "
                  f"threshold is too high and `rock_slope` should go down, or "
                  f"the area is computed in other units than the coordinates "
                  f"(see `check_metric` in `workers/lib/contour-blocks.py`). The "
                  f"map would otherwise silently come out without rocks.")
            return 1
        took = time.time() - t_start
        actual = src_cells / max(took, 1)
        print(f"Rock areas: {n} (whole computation {hms(took)}, "
              f"{src_cells/1e9:.2f} G store cells read → "
              f"{actual/1e3:.0f} k cells/s; traced "
              f"{cells/1e9:.2f} G at {vec_res:g} m)")
        # the estimates rest on the constants above; let the run say when they drift
        if actual and max(CONTOUR_SRC_CELLS_PER_S / actual,
                          actual / CONTOUR_SRC_CELLS_PER_S) > 3:
            print(f"::warning::Vectorising read {actual/1e3:.0f} k store "
                  f"cells/s, but `CONTOUR_SRC_CELLS_PER_S` in rock-areas.py says "
                  f"{CONTOUR_SRC_CELLS_PER_S/1e3:.0f} k – "
                  f"{max(CONTOUR_SRC_CELLS_PER_S/actual, actual/CONTOUR_SRC_CELLS_PER_S):.0f}× "
                  f"off. The estimate and the budget guard stand on it; rewrite "
                  f"it by this run (store {res:g} m, tracing {vec_res:g} m).")
        if st:
            print(f"  total {st['total']/1e6:.2f} km², largest "
                  f"{st['max']/10000:.1f} ha, smallest {st['min']:.0f} m², "
                  f"mean {st['avg']:.0f} m²")
            # many areas but no area: stitching once silently dropped 22 of 24
            area_km2 = bbox_km2(bbox)
            share = st["total"] / 1e6 / area_km2 * 100 if area_km2 else 0.0
            # 0.05 %, not 0.01 %: Bratislava came to 0.014 % and looked ungenerated
            if share < 0.05:
                print(f"::warning::Rocks take {share:.3f} % of the area "
                      f"({st['total']/1e6:.2f} km² of {area_km2:.0f} km², "
                      f"{int(st['n'])} areas averaging {st['avg']:.0f} m²) – on "
                      f"the map it will look as if there are no rocks. Normal in "
                      f"a flat region (the {args.slope:g}° `rock_slope` threshold "
                      f"doesn't cut the terrain there – try 40°); in a mountain "
                      f"cut-out something got lost – check above whether seam "
                      f"stitching returned nothing.")
            if "holes_km2" in st:
                print(f"  holes (spots under the threshold inside a rock): "
                      f"{int(st['with_holes'])} areas have them, "
                      f"{st['holes_km2']:.2f} km² cut out")

        if args.stats:
            with open(args.stats, "w") as f:
                # where the rocks are from; the build summary picks its table by it
                f.write("source=dem\n")
                f.write(f"count={n}\n")
                f.write(f"grid_m={res:g}\n")
                f.write(f"vec_grid_m={vec_res:g}\n")
                f.write(f"min_area_m2={args.min_area:g}\n")
                f.write(f"slope_deg={lo}\ncliff_deg={hi}\n")
                f.write(f"solid={int(bool(args.solid))}\n")
                f.write(f"fill_holes={int(bool(args.fill_holes))}\n")
                f.write(f"slope_step_deg={1.0/SCALE:g}\n")
                f.write(f"simplify_m={args.simplify:g}\n")
                f.write(f"smooth_sag={args.smooth}\n")
                f.write(f"cells_g={cells/1e9:.2f}\n")
                f.write(f"took={hms(took)}\n")
                if dem_dx:
                    f.write(f"dem_cell_m={dem_dx:.0f}\n")
                if st:
                    f.write(f"total_km2={st['total']/1e6:.2f}\n")
                    f.write(f"max_ha={st['max']/10000:.1f}\n")
                    f.write(f"min_m2={st['min']:.0f}\n")
                    f.write(f"avg_m2={st['avg']:.0f}\n")
                if "holes_km2" in st:
                    f.write(f"with_holes={int(st['with_holes'])}\n")
                    f.write(f"holes_km2={st['holes_km2']:.2f}\n")
        return 0
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
