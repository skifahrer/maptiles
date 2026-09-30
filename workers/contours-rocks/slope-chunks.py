#!/usr/bin/env python3
"""The slope raster in chunks – with a persistent store, so nothing is computed twice.

Each CHUNK is read from Drive, turned to slope and stored on its own, so a
cancelled run keeps finished chunks. Chunks snap to a grid anchored at the
EPSG:3035 origin, so the same land always falls in the same chunk.

Usage:
    python3 workers/contours-rocks/slope-chunks.py --bbox=19.9,49.09,20.32,49.25 \\
        --res=2 --drive --out=slope-chunks --jobs=6
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in the name."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# planning, the metric system and the slope scale are in `rock-areas.py`
rock = load("rock_areas", "rock-areas.py")
METRIC, SCALE = rock.METRIC, rock.SCALE

# the persistent chunk store is a Drive folder, used as a module to list it once
store = load("drive_store", os.path.join(os.pardir, "drive", "store.py"))

# chunk side in pixels: smaller = finer recovery, larger = less overhead
CHUNK_PX = 4096
MARGIN_PX = 8    # overlap, so slope at a chunk's edge isn't cut
MAX_CHUNKS = 600  # above it the store stops paying off
RETRY_S = 120     # Drive's limit window outlasts one chunk's tries


def chunk_grid(bbox, res, chunk_px=CHUNK_PX):
    """Chunks of the absolute grid reaching the bbox, as `(ix, iy, x0, y0, x1, y1)`."""
    # one `gdaltransform` over all corners: a process per chunk outlasts the computation
    side = chunk_px * res
    mx0, my0, mx1, my1 = rock.to_metric(bbox)
    cand = []
    for iy in range(math.floor(my0 / side), math.ceil(my1 / side)):
        for ix in range(math.floor(mx0 / side), math.ceil(mx1 / side)):
            x0, y0 = ix * side, iy * side
            cand.append((ix, iy, x0, y0, x0 + side, y0 + side))
    if not cand:
        return []

    # eight points a chunk: converted, a side bulges into the bbox while corners stay out
    pts = []
    for _, _, x0, y0, x1, y1 in cand:
        pts += [(x0, y0), (x1, y0), (x0, y1), (x1, y1),
                ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1),
                (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
    try:
        out = subprocess.run(
            ["gdaltransform", "-s_srs", METRIC, "-t_srs", "EPSG:4326"],
            input="\n".join(f"{x} {y}" for x, y in pts),
            capture_output=True, text=True, check=True).stdout.split()
    except subprocess.CalledProcessError:
        return cand   # when it can't be told, compute rather than skip

    xs = [float(v) for v in out[0::3]]
    ys = [float(v) for v in out[1::3]]
    keep = []
    for i, c in enumerate(cand):
        cx, cy = xs[i * 8:(i + 1) * 8], ys[i * 8:(i + 1) * 8]
        if not (max(cx) < bbox[0] or min(cx) > bbox[2]
                or max(cy) < bbox[1] or min(cy) > bbox[3]):
            keep.append(c)
    return keep


def chunk_name(ix, iy, res):
    """A chunk's store name: grid and position, no slope threshold (applied later)."""
    # the sign goes into a letter (E/W, N/S): `slope-r2--615--358` reads badly
    sx = f"E{ix:04d}" if ix >= 0 else f"W{-ix:04d}"
    sy = f"N{iy:04d}" if iy >= 0 else f"S{-iy:04d}"
    return f"slope-r{res:g}-{sx}{sy}.tif"


NOTE = ("Rock intermediate: terrain slope in hundredths of a degree (Int16, "
        "EPSG:3035) in chunks of an absolute grid (workers/contours-rocks/slope-chunks.py)")


class Store:
    """Chunks in a directory (the run's cache) and in the Drive store (persistent)."""
    # the cache is fast but thins out; the Drive store never expires

    def __init__(self, path, store_name, use_store=True):
        self.path = path
        self.store_name = store_name
        self.lock = threading.Lock()
        self.hits_local = 0
        self.hits_store = 0
        self.made = 0
        os.makedirs(path, exist_ok=True)
        self.creds = None
        self.items = {}      # name → {id, size, created}; listed ONCE
        self.assets = set()
        self.use_store = False
        if not use_store:
            return
        # without a token it goes on, loudly: costs time, not correctness
        try:
            self.creds = store.creds_or_die("slope chunk store")
            # one folder listing for the whole run
            self.items = store.index(self.creds, store_name)
            self.assets = set(self.items)
            self.use_store = True
        except SystemExit as exc:
            print(f"::warning::The slope chunk store on Drive is off "
                  f"({str(exc).splitlines()[0][:200]}) – chunks are computed "
                  f"and lost after the run.", flush=True)

    def local(self, name):
        p = os.path.join(self.path, name)
        return p if os.path.exists(p) and os.path.getsize(p) > 0 else None

    def take(self, name):
        """A chunk from the cache or the store; None = it must be computed."""
        p = self.local(name)
        if p:
            with self.lock:
                self.hits_local += 1
            return p
        if not self.use_store or name not in self.items:
            return None
        try:
            store.download(self.creds, dict(self.items[name], name=name),
                           os.path.join(self.path, name))
        except (RuntimeError, OSError, SystemExit):
            return None
        if self.local(name):
            with self.lock:
                self.hits_store += 1
            return os.path.join(self.path, name)
        return None

    def put(self, name):
        """A finished chunk into the store; a failed upload mustn't fail the run."""
        with self.lock:
            self.made += 1
        if not self.use_store:
            return
        try:
            # `clobber=False`: uploaded only when missing, nothing to overwrite
            store.upload(self.creds, self.store_name,
                         os.path.join(self.path, name), name, NOTE,
                         clobber=False)
        except (RuntimeError, OSError, SystemExit) as exc:
            print(f"::warning::Chunk {name} couldn't be saved to store "
                  f"{self.store_name} – next time it is computed again. "
                  f"{str(exc)[:200]}", flush=True)
        else:
            with self.lock:
                self.assets.add(name)


def slope_chunk(dem, chunk, res, out_path, work, env=None):
    """DEM → slope for one chunk, clipped exactly to its border."""
    # `MARGIN_PX`: `gdaldem slope` uses a cell's neighbours, edges would checker the mosaic
    ix, iy, x0, y0, x1, y1 = chunk
    m = MARGIN_PX * res
    dem_tif = os.path.join(work, f"dem-{ix}-{iy}.tif")
    slope_tif = os.path.join(work, f"slope-{ix}-{iy}.tif")

    def run(cmd):
        # stderr must be in the error, or only "non-zero exit status 1" is left
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if r.returncode:
            raise RuntimeError(
                f"{cmd[0]} ended with code {r.returncode} for chunk {ix},{iy}:\n"
                f"  {' '.join(cmd)}\n  {r.stderr.strip()[:500]}")
        return r
    try:
        run(["gdalwarp", "-q", "-overwrite", "-t_srs", METRIC,
             "-te", repr(x0 - m), repr(y0 - m), repr(x1 + m), repr(y1 + m),
             "-tr", repr(res), repr(res), "-r", "cubicspline",
             "-ot", "Float32", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
             "-multi", "-ovr", "AUTO", dem, dem_tif])
        run(["gdaldem", "slope", "-q", "-compute_edges",
             "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", dem_tif, slope_tif])
        # Float32 → Int16 hundredths: a range's Float32 mosaic won't fit the runner's disk
        tmp_out = out_path + ".part"
        # `-of GTiff` explicitly: `.part` is unknown to GDAL, and must not look finished
        run(["gdal_translate", "-q", "-of", "GTiff", "-ot", "Int16",
             "-scale", "0", repr(90.0), "0", repr(90.0 * SCALE),
             "-projwin", repr(x0), repr(y1), repr(x1), repr(y0),
             "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=2", "-co", "TILED=YES",
             slope_tif, tmp_out])
        # only the rename makes a chunk finished – no truncated file in the cache
        os.replace(tmp_out, out_path)
    finally:
        for f in (dem_tif, slope_tif):
            if os.path.exists(f):
                os.remove(f)
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbox", required=True, help="west,south,east,north in degrees")
    ap.add_argument("--res", default="auto",
                    help="slope grid in metres, or `auto`")
    ap.add_argument("--out", default="slope-chunks",
                    help="directory of the chunk store (cached)")
    ap.add_argument("--work", default="", help="work directory (default: --out/tmp)")
    ap.add_argument("--dem", default="", help="a local DEM (.vrt/.tif)")
    ap.add_argument("--drive", action="store_true",
                    help="read straight from DMR 5.0 on Drive over HTTP Range")
    ap.add_argument("--jobs", type=int, default=4,
                    help="how many chunks at once; with --drive latency decides, "
                         "not bandwidth, so higher pays off")
    ap.add_argument("--store", default=os.environ.get("SLOPE_STORE", "dem-slope"),
                    help="the Drive store (see workers/drive/store.py)")
    ap.add_argument("--no-store", action="store_true",
                    help="neither use nor fill the store (test run)")
    ap.add_argument("--rebuild", action="store_true",
                    help="recompute chunks even when stored")
    ap.add_argument("--chunk-px", type=int, default=CHUNK_PX)
    ap.add_argument("--dem-cell-m", type=float, default=0.0,
                    help="the source cell in metres (for `--res=auto`); "
                         "1 with --drive")
    # 0 = no time cap (see ROCK_BUDGET_MIN in build-map-region.yml)
    ap.add_argument("--budget-min", type=float, default=0.0)
    ap.add_argument("--chunk-cells", type=float, default=150e6)
    ap.add_argument("--tries", type=int, default=3,
                    help="tries per chunk before the run gives up")
    ap.add_argument("--heartbeat", type=float,
                    default=float(os.environ.get("ROCK_HEARTBEAT_S") or 30),
                    help="how often to say what is running (0 = silent)")
    ap.add_argument("--print-res", action="store_true",
                    help="only print the chosen grid and stop")
    ap.add_argument("--stats", default="", help="where to write the stats (key=value)")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    x0, y0, x1, y1 = rock.to_metric(bbox)

    dem_cell = args.dem_cell_m or (1.0 if args.drive else 0.0)
    if not dem_cell and args.dem:
        dem_cell = rock.dem_cell_metres(args.dem, (bbox[1] + bbox[3]) / 2)[0]
    if str(args.res).strip().lower() in ("auto", "", "0"):
        # the table goes to stderr: `RES=$(… --print-res)` takes stdout
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            res = rock.pick_res(x0, y0, x1, y1, args.chunk_cells, bbox,
                                args.budget_min, dem_cell)
    else:
        res = float(args.res)

    if args.print_res:
        print(f"{res:g}")
        return 0

    chunks = chunk_grid(bbox, res, args.chunk_px)
    if not chunks:
        print(f"::error::Not one chunk reaches the area {args.bbox}.")
        return 2
    # a chunk count guard: a fine grid shrinks the side and the count grows squared
    if len(chunks) > MAX_CHUNKS:
        side_km = args.chunk_px * res / 1000
        print(f"::error::That makes {len(chunks)} chunks of {side_km:g} km "
              f"(grid {res:g} m, {args.chunk_px}² px) and the cap is "
              f"{MAX_CHUNKS}. Raise --chunk-px (e.g. {args.chunk_px * 4}), "
              f"pick a coarser grid (rock_res) or a smaller cut-out (rock_area).")
        return 2

    work = args.work or os.path.join(args.out, "tmp")
    os.makedirs(work, exist_ok=True)
    chunk_store = Store(args.out, args.store, use_store=not args.no_store)

    # the cost before the first gdalwarp, counting what is already stored
    side_km = args.chunk_px * res / 1000
    names = [chunk_name(ix, iy, res) for ix, iy, *_ in chunks]
    have = 0 if args.rebuild else sum(
        1 for n in names if chunk_store.local(n) or n in chunk_store.assets)
    todo = len(chunks) - have
    cells = len(chunks) * args.chunk_px ** 2
    est_s = todo * args.chunk_px ** 2 / rock.SLOPE_CELLS_PER_S

    print("── Slope plan ───────────────────────────────────────")
    print(f"  grid            {res:g} m")
    print(f"  chunks          {len(chunks)} of {side_km:g}×{side_km:g} km "
          f"({args.chunk_px}² px)")
    print(f"  cells           {cells / 1e9:.2f} G")
    print(f"  store           {args.out}"
          + (f" + Drive {args.store}" if chunk_store.use_store
             else " (Drive store off)"))
    print(f"  of them done    {have} → to compute {todo}")
    print(f"  estimate        {rock.hms(est_s)}"
          + ("  (all stored)" if not todo else ""))
    print(f"  mosaic on disk  ~{cells / 1e9 * rock.MOSAIC_MB_PER_GCELL:.0f} MB")
    print("─────────────────────────────────────────────────────", flush=True)

    t0 = time.time()
    env = None
    stats_drive = None
    if args.drive:
        # the Drive shim, file ids and sign-in are in `drive/dmr5.py`
        dd = load("dmr5_drive", os.path.join(os.pardir, "drive", "dmr5.py"))
        base, sizes, stats_drive, creds = dd.serve_drive(0)
        dem = f"/vsicurl/{base}/{dd.TIF_NAME}"
        env = dd.drive.gdal_env()
        print(f"  source: DMR 5.0 on Drive, "
              + ", ".join(f"{n} {s / 2**30:.1f} GiB" for n, s in sizes.items()))
        print(f"  access: {dd.auth.describe(creds)}")
    elif args.dem:
        dem = args.dem
        print(f"  source: {dem}")
    else:
        print("::error::No source – give --dem or --drive.")
        return 2

    done = [0]
    lock = threading.Lock()
    running = {}          # chunk name → computing since
    failed = []           # what failed even on the last try
    tries = max(1, args.tries)

    def compute(name, chunk, path):
        """One chunk – and once more when the connection drops."""
        # a retry costs a minute, a failure the whole job; nothing half-done is left
        for attempt in range(1, tries + 1):
            with lock:
                running[name] = time.time()
            try:
                slope_chunk(dem, chunk, res, path, work, env)
                return
            except Exception as exc:                    # noqa: BLE001
                if attempt >= tries:
                    with lock:
                        failed.append(name)
                    raise
                wait = 5 * attempt
                why = str(exc).strip().splitlines()[-1][:200]
                print(f"::warning::Chunk {name} failed on try {attempt} "
                      f"of {tries}, trying again in {wait} s: {why}", flush=True)
                time.sleep(wait)
            finally:
                with lock:
                    running.pop(name, None)

    def one(chunk):
        ix, iy = chunk[0], chunk[1]
        name = chunk_name(ix, iy, res)
        path = os.path.join(args.out, name)
        got = None if args.rebuild else chunk_store.take(name)
        if got is None:
            compute(name, chunk, path)
            chunk_store.put(name)
        with lock:
            done[0] += 1
            el = time.time() - t0
            eta = el / done[0] * (len(chunks) - done[0])
            print(f"  [{done[0]}/{len(chunks)}] {name} "
                  f"{'from the store' if got else 'computed'} – "
                  f"{rock.hms(el)} elapsed, ~{rock.hms(eta)} left", flush=True)
        return path

    # a heartbeat: a stuck chunk looks just like a slow one; growing Drive requests mean reading
    stop = threading.Event()

    def beat():
        while not stop.wait(args.heartbeat):
            now = time.time()
            with lock:
                live = sorted(running.items(), key=lambda kv: kv[1])
                d = done[0]
            parts = [f"[{d}/{len(chunks)}] running {len(live)}"]
            if live:
                parts.append(", ".join(
                    f"{n.rsplit('-', 1)[-1][:-4]} {rock.hms(now - t)}"
                    for n, t in live[:4]))
            if stats_drive:
                with stats_drive["lock"]:
                    got, req = stats_drive["bytes"], stats_drive["requests"]
                    bad = stats_drive.get("failed", 0)
                parts.append(f"from Drive {got / 1e9:.2f} GB in {req:,} requests"
                             + (f", {bad:,} failed" if bad else ""))
            print("  … " + "  ".join(parts), flush=True)

    if args.heartbeat > 0:
        threading.Thread(target=beat, daemon=True).start()

    def run_pass(batch, jobs):
        """What passed and what failed; one chunk failing doesn't fail the rest."""
        ok, bad = [], []
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            for fut, chunk in [(ex.submit(one, c), c) for c in batch]:
                try:
                    ok.append(fut.result())
                except Exception:               # noqa: BLE001
                    bad.append(chunk)
        return ok, bad

    tiles, rest = run_pass(chunks, args.jobs)
    if rest:
        # Drive's limit holds while other threads push; the second pass goes one by one
        print(f"::warning::Slope: {len(rest)} of {len(chunks)} chunks failed. "
              f"Trying them once more after {RETRY_S} s, one at a time.", flush=True)
        time.sleep(RETRY_S)
        with lock:
            failed.clear()
        again, rest = run_pass(rest, 1)
        tiles += again
    stop.set()
    if rest:
        # the store is this script's point: show that finished work wasn't thrown away
        bad = [chunk_name(c[0], c[1], res) for c in rest]
        have_now = sum(1 for n in names if chunk_store.local(n))
        print(f"::error::Slope failed on {len(bad)} chunks "
              f"({', '.join(bad[:6])}); {have_now} of {len(chunks)} are "
              f"stored – the next run computes only the rest, nothing was "
              f"thrown away.", flush=True)
        return 1
    tiles.sort()

    vrt = os.path.join(args.out, f"slope-r{res:g}.vrt")
    subprocess.run(["gdalbuildvrt", "-q", vrt] + tiles, check=True)
    mb = sum(os.path.getsize(t) for t in tiles) / 1048576
    print(f"Slope mosaic: {len(tiles)} chunks, {mb:.0f} MB → {vrt}")
    print(f"  from the store {chunk_store.hits_local} local + "
          f"{chunk_store.hits_store} from Drive, newly computed "
          f"{chunk_store.made}, total {rock.hms(time.time() - t0)}")
    if stats_drive:
        with stats_drive["lock"]:
            print(f"  from Drive {stats_drive['bytes'] / 1e9:.2f} GB "
                  f"in {stats_drive['requests']:,} requests")

    if args.stats:
        with open(args.stats, "w") as f:
            f.write(f"res={res:g}\nvrt={vrt}\nchunks={len(tiles)}\n"
                    f"from_cache={chunk_store.hits_local}\n"
                    f"from_store={chunk_store.hits_store}\n"
                    f"computed={chunk_store.made}\nmosaic_mb={mb:.0f}\n")
    print(f"slope_vrt={vrt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
