#!/usr/bin/env python3
"""`gdal_contour -p` in blocks – so it finishes over a large area too.

Assembling rings isn't linear in cells, so one pass over a cut-out never
finished; in a block rings assemble fast and finished blocks stay on disk.
The price is seams, which `stitch_seams()` joins by `ST_Union`.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from watch import dir_mb, hms, run_watched  # noqa: E402


# printed over every block and expected here: `<SRS>` is dropped from the window on purpose
EXPECTED_WARNING = "No SRS set on layer"


def _pass_stderr(text, *, first, where):
    """Print GDAL's stderr; summarise the expected warning, let the rest through."""
    expected = 0
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if EXPECTED_WARNING in line:
            expected += 1
            if first:
                print(f"    (GDAL: \"{line.strip()}\" – as it should be, "
                      f"`<SRS>` is dropped from the block window on purpose so "
                      f"coordinates stay metric. Further ones are only "
                      f"counted.)", flush=True)
            continue
        print(f"    {where}: {line.rstrip()}", flush=True)
    return expected


def raster_size(vrt):
    """(width, height) of a raster in pixels."""
    try:
        info = json.loads(subprocess.run(["gdalinfo", "-json", vrt],
                                         check=True, capture_output=True,
                                         text=True).stdout)
        return info["size"][0], info["size"][1]
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return 0, 0


def plan(w_px, h_px, block_px):
    """Top-left corners of the blocks; a block is a `block_px` square, the last smaller."""
    return [(bx, by)
            for by in range(0, h_px, block_px)
            for bx in range(0, w_px, block_px)]


def mark_seams(src, dst, on_edge):
    """Rewrite a GeoJSONSeq, adding `"seam":1` to shapes on the block edge."""
    n = 0
    with open(src) as fi, open(dst, "w") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if on_edge(obj.get("geometry") or {}):
                obj.setdefault("properties", {})["seam"] = 1
                n += 1
            fo.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return n


def _coords(geom):
    """A geometry's points, Polygon or MultiPolygon alike."""
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        for ring in c or []:
            yield from ring
    elif t == "MultiPolygon":
        for poly in c or []:
            for ring in poly:
                yield from ring


def _area(geom):
    """A geometry's area in m² (shoelace over metric coordinates), holes subtracted."""
    def ring(points):
        s = 0.0
        for i in range(len(points) - 1):
            x0, y0 = points[i][0], points[i][1]
            x1, y1 = points[i + 1][0], points[i + 1][1]
            s += x0 * y1 - x1 * y0
        return abs(s) / 2.0

    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        rings = c or []
        return ring(rings[0]) - sum(ring(r) for r in rings[1:]) if rings else 0.0
    if t == "MultiPolygon":
        total = 0.0
        for poly in c or []:
            if poly:
                total += ring(poly[0]) - sum(ring(r) for r in poly[1:])
        return total
    return 0.0


def file_area(path):
    """The sum of all shapes' areas in a GeoJSONSeq (m²)."""
    total = 0.0
    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    total += _area(json.loads(line).get("geometry") or {})
                except ValueError:
                    continue
    except FileNotFoundError:
        return 0.0
    return total


def _touches(geom, x0, y0, x1, y1, tol):
    """Does the geometry reach the window's edge (in raster coordinates)?"""
    for x, y in _coords(geom):
        if (abs(x - x0) <= tol or abs(x - x1) <= tol
                or abs(y - y0) <= tol or abs(y - y1) <= tol):
            return True
    return False


def check_metric(seq, minimum=1000.0, samples=200):
    """Are coordinates in metres, or were they lost to degrees somewhere?"""
    # an error, not a warning: the run ends green with every area ~1e-9 m² filtered out
    largest = 0.0
    seen = False
    try:
        with open(seq) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for x, y in _coords(obj.get("geometry") or {}):
                    seen = True
                    largest = max(largest, abs(x), abs(y))
                    samples -= 1
                    if samples <= 0:
                        break
                if samples <= 0:
                    break
    except FileNotFoundError:
        return True
    if seen and largest < minimum:
        # `RuntimeError`: the caller prints it as `::error::`, a readable message
        raise RuntimeError(
            f"coordinates look like degrees (largest {largest:.6f}), not "
            f"metres – `<SRS>` wasn't dropped from the block window and GDAL "
            f"converted them to WGS84. Areas would come to ~1e-9 m² and the "
            f"smallest-area filter would drop ALL rocks, the run staying "
            f"green (runs 31245134321 and 31426542010).")
    return True


def by_blocks(vrt, out_dir, levels, attributes, block_px, geo, *, budget_s=0):
    """Outlines in blocks into `out_dir/b*.geojsonl`. Returns (folder, count)."""
    # geo = (ox, oy, res) in metres; finished blocks stay, so `TimeoutError` loses nothing
    w_px, h_px = raster_size(vrt)
    if not w_px:
        raise RuntimeError(f"the raster size can't be read from {vrt}")
    ox, oy, res = geo
    blocks = plan(w_px, h_px, block_px)
    os.makedirs(out_dir, exist_ok=True)
    finished = sum(1 for i in range(len(blocks))
                   if os.path.exists(os.path.join(out_dir, f"b{i:05d}.geojsonl")))
    print(f"  block {block_px}×{block_px} px, {len(blocks)} blocks"
          + (f", {finished} already done by an earlier run" if finished else ""),
          flush=True)

    t0 = time.time()
    done = 0
    no_srs = 0
    for i, (bx, by) in enumerate(blocks):
        path = os.path.join(out_dir, f"b{i:05d}.geojsonl")
        if os.path.exists(path):
            continue
        bw, bh = min(block_px, w_px - bx), min(block_px, h_px - by)
        window = os.path.join(out_dir, "window.vrt")
        # `-of VRT` is XML over the same raster – the cut-out costs no byte
        subprocess.run(["gdal_translate", "-q", "-of", "VRT",
                        "-srcwin", str(bx), str(by), str(bw), str(bh),
                        vrt, window], check=True)
        # drop <SRS>: the GeoJSON driver converts to WGS84 whenever it knows the source's
        with open(window) as f:
            xml = f.read()
        with open(window, "w") as f:
            f.write(re.sub(r"\s*<SRS[^>]*>.*?</SRS>", "", xml, flags=re.S))
        part = path + ".part"
        if os.path.exists(part):
            os.remove(part)
        # stderr is caught, not muted; on failure all of it is printed first
        result = subprocess.run(
            ["gdal_contour", "-p", "-q", "-fl", *levels, *attributes,
             "-f", "GeoJSONSeq", "-nln", "band",
             # metric coordinates, two decimals = a centimetre
             "-lco", "COORDINATE_PRECISION=2", window, part],
            capture_output=True, text=True)
        # `first` binds to the first occurrence, not the first block
        no_srs += _pass_stderr(result.stderr, first=(no_srs == 0),
                               where="gdal_contour")
        if result.stdout.strip():
            print(f"    gdal_contour: {result.stdout.strip()}", flush=True)
        result.check_returncode()
        # a guard: the first block checks the coordinates really are metric
        if done == 0:
            check_metric(part)
        # coordinates are in the cut-out's metres; the block's edge is its border
        x0, y0 = ox + bx * res, oy - by * res
        x1, y1 = x0 + bw * res, y0 - bh * res
        mark_seams(part, path, lambda g: _touches(g, x0, y1, x1, y0, res))
        os.remove(part)
        done += 1
        el = time.time() - t0
        # progress by block is all that tells anything about this long phase
        if done and (i % max(1, len(blocks) // 50) == 0 or i == len(blocks) - 1):
            rest = el / done * (len(blocks) - i - 1)
            print(f"  … outlines: block {i + 1}/{len(blocks)}, running {hms(el)}, "
                  f"~{hms(rest)} left, {dir_mb(out_dir):.0f} MB on disk",
                  flush=True)
        # the budget only after a written block – the next run picks up here
        if budget_s and el > budget_s:
            raise TimeoutError(f"outlines: {i + 1}/{len(blocks)} blocks")
    # the count is shown: one block of 364 without it is worth seeing
    if no_srs:
        print(f"  (GDAL reported \"{EXPECTED_WARNING}\" for {no_srs} "
              f"of {done} computed blocks – expected)", flush=True)
    return out_dir, len(blocks)


def stitch_seams(seq, tmp, *, key_attribute="smin", heartbeat=30,
                 max_s=0, label="seams"):
    """Join areas cut by a block edge, per class. Returns the result's path."""
    # ST_Union may fail silently on invalid geometry, so ST_MakeValid, and the
    # area is checked after; no SRS on output: `-a_srs` over GeoJSONSeq makes degrees
    seams = os.path.join(tmp, "seams.geojsonl")
    rest = os.path.join(tmp, "no-seams.geojsonl")
    n_seam = n_ok = 0
    with open(seq) as fi, open(seams, "w") as fs, open(rest, "w") as fz:
        for line in fi:
            if not line.strip():
                continue
            if '"seam":1' in line.replace(" ", ""):
                fs.write(line)
                n_seam += 1
            else:
                fz.write(line)
                n_ok += 1
    if not n_seam:
        print("  seams: no area reaches a block edge", flush=True)
        return rest

    print(f"  seams: {n_seam} areas on a block edge, {n_ok} away from it – "
          f"stitching the former", flush=True)
    stitched = os.path.join(tmp, "stitched.geojsonl")
    # no `-a_srs` or `-t_srs`; `ST_Union` is planar and ignores SRID
    error = None
    try:
        run_watched(["ogr2ogr", "-f", "GeoJSONSeq", stitched, seams,
                     "-lco", "COORDINATE_PRECISION=2",
                     "-dialect", "SQLITE", "-explodecollections",
                     "-sql", f"SELECT {key_attribute}, "
                             f"ST_Union(ST_MakeValid(geometry)) AS geometry "
                             f"FROM seams GROUP BY {key_attribute}"],
                    label, tmp=stitched, every=heartbeat, max_s=max_s)
    except Exception as exc:
        error = f"{type(exc).__name__}"

    # ogr2ogr's success isn't enough, nor the shape count – the area decides
    n_stitched = 0
    if not error and os.path.exists(stitched):
        with open(stitched) as f:
            n_stitched = sum(1 for line in f if line.strip())
    # units before area, or degrees would be reported as "lost area"
    if n_stitched:
        try:
            check_metric(stitched)
        except RuntimeError as exc:
            error = ("the union came out in DEGREES, not metres – the output "
                     "got an SRS (`-a_srs`/`-t_srs`) and the GeoJSON driver "
                     f"converted the coordinates to WGS84; {exc}")
    area_before = file_area(seams)
    area_after = file_area(stitched) if n_stitched and not error else 0.0
    lost = (area_before > 0 and area_after < area_before * 0.5)
    if error or not n_stitched or lost:
        why = (f"({error})" if error else
               "(the union came out empty – look for `TopologyException` in the log)"
               if not n_stitched else
               f"(of {area_before/1e6:.2f} km² {area_after/1e6:.2f} km² were left)")
        # the reason comes from what was found, never a guess
        print(f"::warning::Stitching the seams can't be used {why}"
              + f". Returning {n_seam} original areas unstitched: on block edges "
              f"({label}) they will be cut and their holes open, but THERE – "
              f"on the map a straight edge in the outline. When the reason is an "
              f"empty union, look above for GEOS `TopologyException` over the "
              f"gdal_contour outline; it isn't spatialite, that is installed.",
              flush=True)
        return seq

    print(f"  seams: {n_seam} areas stitched into {n_stitched} "
          f"({area_before/1e6:.2f} → {area_after/1e6:.2f} km²)", flush=True)
    together = os.path.join(tmp, "stitched-all.geojsonl")
    with open(together, "w") as fo:
        for src in (rest, stitched):
            if os.path.exists(src):
                with open(src) as fi:
                    for line in fi:
                        if line.strip():
                            fo.write(line)
    return together


def join_blocks(out_dir, dst):
    """Glue the blocks into one GeoJSONSeq (in order, so a run is repeatable)."""
    n = 0
    with open(dst, "w") as fo:
        for name in sorted(os.listdir(out_dir)):
            if not name.endswith(".geojsonl"):
                continue
            with open(os.path.join(out_dir, name)) as fi:
                for line in fi:
                    if line.strip():
                        fo.write(line)
                        n += 1
    return n
