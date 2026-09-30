#!/usr/bin/env python3
"""DMR 5.0 (ETRS89) from Google Drive → an elevation model for the store.

Two BigTIFFs in folder `FOLDER_ID`, read over HTTP Range signed in as the owner.
Latency is the cost, so the window is cut into blocks read in parallel; heights
are ellipsoidal, so the EGM2008 geoid is subtracted.

Stages (`--stage`): `plan`, `read` (the only one on the network), `finish`, `all`.
With `--tiles` the window widens to whole degrees – a name promises a tile.

Usage:
    python3 workers/drive/dmr5.py --area=vysoke_tatry --grid-m=1 \\
        --out=out --asset=ugkk-vysoke_tatry.tif
    python3 workers/drive/dmr5.py --area=20,49,21,50 --grid-m=5 --tiles --out=out
    python3 workers/drive/dmr5.py --auth-check
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

# where DMR 5.0 lies – a folder, what really moves and is shared; the token is the secret
FOLDER_ID = "1H62op_LMUYDqKeFf-_sXS-46PLEmxDyd"
TIF_NAME = "dmr5_etrs89.tif"
OVR_NAME = TIF_NAME + ".ovr"


# state between stages; `--work` survives between the job's steps
STATE = "dmr5-drive-state.json"

# a reading cost estimate per SOURCE pixel (coarser grids read from overviews)
PX_PER_MIN = 24e6         # at --jobs=12
BYTES_PER_PX = 3.8


def load(name, path):
    """workers/*.py can't be imported normally; `sys.modules` keeps one connection pool."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


drive = load("drive_serve", "serve.py")
auth = load("drive_auth", "auth.py")
folder = load("drive_folder", "folder.py")
raster = load("dmr5_raster", "dmr5-raster.py")

# cutting is in `dmr5-cut.py`; this file asks how to reach the data, at what cost, in
# which stages; `LOG` is one journal, so it comes from there
cut = load("dmr5_cut", "dmr5-cut.py")
LOG, log, run = cut.LOG, cut.log, cut.run
src_window, blocks, read_blocks = cut.src_window, cut.blocks, cut.read_blocks
pyramid_level = cut.pyramid_level
to_wgs84, country_tiles = cut.to_wgs84, cut.country_tiles
SRC_EPSG = cut.SRC_EPSG


def state_path(work):
    return os.path.join(work, STATE)


# stages are separate processes – otherwise the summary keeps only the last log
_LOG_SAVED = 0


def save_state(work, state):
    global _LOG_SAVED
    state["log"] = state.get("log", []) + LOG[_LOG_SAVED:]
    _LOG_SAVED = len(LOG)
    os.makedirs(work, exist_ok=True)
    with open(state_path(work), "w") as f:
        json.dump(state, f, indent=1)


def load_state(work):
    """The state from the `plan` stage; missing means stages ran out of order."""
    p = state_path(work)
    if not os.path.exists(p):
        raise SystemExit(
            f"::error::{p} is missing – this stage runs only after `--stage=plan`.")
    with open(p) as f:
        return json.load(f)


def credentials():
    """The Drive sign-in from the environment, or None; an error fails loudly."""
    try:
        creds = auth.from_env()
        if creds is None:
            return None
        # the token now: when Drive won't give it, it is said here, not after an hour
        creds.token()
    except auth.AuthError as exc:
        raise SystemExit(f"::error::{exc}")
    try:
        auth.whoami(creds)
    except auth.AuthError as exc:
        # only for "which account reads"; reading goes on
        log(f"::warning::The account couldn't be found out ({exc}). Reading "
            f"runs signed in, the log just won't say which account.")
    return creds


# ids resolved once aren't looked up again in the process
_IDS = None


def resolve_ids(creds):
    """The Drive folder → (model id, overview id), by name, else the largest `.tif`."""
    global _IDS
    if _IDS is not None:
        return _IDS
    if creds is None:
        raise SystemExit(
            "::error::DMR 5.0 lies in a Drive folder "
            f"({FOLDER_ID}) only a signed-in run can list – the Drive API "
            "serves no anonymous requests. Add the secret GDRIVE_CREDENTIALS "
            "(or the variable DRIVE_CLIENT and secrets DRIVE_SECRET / "
            "DRIVE_REFRESH): the workflow \"Maintenance · Drive sign-in\" "
            "makes them, from a computer `python3 workers/drive/auth.py --login`.")
    files, _skipped = folder.listing(creds, FOLDER_ID)
    tifs = [f for f in files if f["name"].lower().endswith(".tif")]
    ovrs = [f for f in files if f["name"].lower().endswith(".ovr")]
    if not tifs:
        raise SystemExit(
            f"::error::Drive folder {FOLDER_ID} has not one "
            f".tif (I saw: "
            + (", ".join(f["name"] for f in files[:8]) or "nothing")
            + "). Does the signed-in account see it, and is DMR 5.0 in it?")
    tif = next((f for f in tifs if f["name"] == TIF_NAME),
               max(tifs, key=lambda f: f["size"]))
    ovr = next((f for f in ovrs if f["name"] == tif["name"] + ".ovr"),
               max(ovrs, key=lambda f: f["size"]) if ovrs else None)
    log(f"  folder {FOLDER_ID}: {len(files)} files")
    for f in (tif, ovr):
        if f is not None:
            log(f"    {f['name']}  {f['size'] / 2**30:.2f} GiB"
                + ("" if f["owned"] else "  (this account does NOT own it – the "
                                         "daily download limit applies)"))
    if ovr is None:
        # no error, but costly: coarser grids from the full 1 m raster
        log(f"::warning::The folder has no `{OVR_NAME}` (overviews). Coarser "
            f"grids will be read from the full 1 m raster, several times longer.")
    _IDS = (tif["id"], ovr["id"] if ovr else None)
    return _IDS


def serve_drive(port=0):
    """A shim over both DMR 5.0 files under canonical names (GDAL finds the sidecar)."""
    creds = credentials()
    tif_id, ovr_id = resolve_ids(creds)
    ids = {TIF_NAME: tif_id}
    if ovr_id:
        ids[OVR_NAME] = ovr_id
    base, sizes, stats = drive.serve(ids, port, creds=creds)
    return base, sizes, stats, creds


def auth_check():
    """Say which account reads, and whether it sees both files."""
    print("Access to DMR 5.0 on Google Drive:")
    try:
        creds = auth.from_env()
        ids = [i for i in resolve_ids(creds) if i]
        return auth.do_check(argparse.Namespace(file=ids))
    except auth.AuthError as exc:
        print(f"::error::{exc}")
        return 2


def open_source(args):
    """The Drive shim + the opened raster: (src, env, info, native_m, stats, creds)."""
    log("Opening DMR 5.0 (ETRS89) on Drive through a local shim…")
    base, sizes, stats, creds = serve_drive(args.port)
    log(f"  access: {auth.describe(creds)}")
    for name, size in sizes.items():
        log(f"  {name}: {size / 2**30:.2f} GiB")
    src = f"/vsicurl/{base}/{TIF_NAME}"
    env = drive.gdal_env()
    if args.geoid == "egm2008":
        # PROJ downloads the geoid grid from its CDN when it hasn't one locally
        env["PROJ_NETWORK"] = "ON"

    t0 = time.time()
    info = json.loads(run(["gdalinfo", "-json", "-nomd", src], env).stdout)
    ov = [o["size"] for o in info["bands"][0].get("overviews", [])]
    log(f"  opened in {time.time() - t0:.1f} s: "
        f"{info['size'][0]:,} × {info['size'][1]:,} px, "
        f"grid {abs(info['geoTransform'][1]):g} m, {len(ov)} overview levels")
    if not ov:
        log("::warning::No overviews found – coarser grids will be computed "
            "from the full 1 m raster, several times longer.")
    return src, env, info, abs(info["geoTransform"][1]), stats, creds


def drive_totals(state, stats):
    """Add what came from Drive in this stage to the earlier ones."""
    if stats is None:
        return state.get("drive_bytes", 0), state.get("drive_requests", 0)
    with stats["lock"]:
        req, got = stats["requests"], stats["bytes"]
    state["drive_bytes"] = state.get("drive_bytes", 0) + got
    state["drive_requests"] = state.get("drive_requests", 0) + req
    return state["drive_bytes"], state["drive_requests"]


def stage_plan(args):
    """Open the source, compute the window and blocks, and say what it will cost."""
    src, env, info, native_m, stats, creds = open_source(args)
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)
    wkt_file = os.path.join(args.work, "src.wkt")
    with open(wkt_file, "w") as f:
        f.write((info.get("coordinateSystem") or {}).get("wkt", ""))

    area_name, bbox = raster.resolve_area(args.area, os.path.join(_DATA, "areas.json"))

    # `--tiles` widens to whole degrees: `N49E020.tif` promises a whole one
    tiles_out = bbox is None or args.tiles
    if bbox is not None and args.tiles:
        w, s, e, n = bbox
        bbox = (float(math.floor(w)), float(math.floor(s)),
                float(math.ceil(e)), float(math.ceil(n)))
        deg = int((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        area_name += (f" → whole degrees {bbox[0]:g},{bbox[1]:g}…{bbox[2]:g},"
                      f"{bbox[3]:g} ({deg} tiles)")

    log(f"Area: {area_name}, target grid {args.grid_m:g} m")

    if bbox is None:
        box = (info["geoTransform"][0], info["geoTransform"][3]
               + info["geoTransform"][5] * info["size"][1],
               info["geoTransform"][0] + info["geoTransform"][1] * info["size"][0],
               info["geoTransform"][3])
    else:
        box = src_window(bbox, wkt_file, info, env)
    parts, (nx, ny) = blocks(box, args.grid_m, args.jobs)

    km_x, km_y = (box[2] - box[0]) / 1000, (box[3] - box[1]) / 1000
    area_m2 = (box[2] - box[0]) * (box[3] - box[1])
    cells = area_m2 / args.grid_m ** 2

    # the cost is pixels coming from Drive, from the coarsest overview still finer (`cut.pyramid_level`)
    ovr_level, read_m = pyramid_level(info, native_m, args.grid_m)
    src_px = area_m2 / read_m ** 2

    # measured at `--jobs=12`; over ~16 threads Drive answers 403
    rate = PX_PER_MIN * min(args.jobs, 16) / 12.0
    est_min = src_px / max(rate, 1.0)
    est_gb = src_px * BYTES_PER_PX / 1e9
    asset = args.asset or f"ugkk-{args.area}.tif"

    print("── Reading plan from Drive ──────────────────────────")
    print(f"  area            {area_name}")
    print(f"  window          {km_x:.1f} × {km_y:.1f} km "
          f"({km_x * km_y:.0f} km²) in EPSG:{SRC_EPSG}")
    print(f"  target grid     {args.grid_m:g} m → {cells / 1e6:.1f} M cells")
    print(f"  read from       {read_m:g} m "
          + ("(full resolution)" if read_m == native_m else
             f"(overview, level {ovr_level})")
          + f" → {src_px / 1e6:.1f} M px")
    # the resampling: the difference between a grid in the shading and smooth relief
    print(f"  resampling      {cut.read_args(args.grid_m, read_m, ovr_level)[1]}")
    print(f"  blocks          {len(parts)} ({nx}×{ny}), {args.jobs} at once")
    print(f"  estimate        ~{est_min:.0f} min, ~{est_gb:.2f} GB from Drive")
    print("  output          " + (f"1° tiles into {args.out}/" if tiles_out
                                  else f"{args.out}/{asset}"))
    print("  heights         " + ("EGM2008 (≈ Bpv)" if args.geoid == "egm2008"
                                  else "ellipsoidal ETRS89"))
    print("─────────────────────────────────────────────────────", flush=True)
    if est_min > 120:
        print(f"::warning::Reading is estimated at ~{est_min / 60:.1f} h. It "
              f"goes faster with a smaller area or a coarser grid (--grid-m).")

    state = {
        "area": args.area,
        "area_name": area_name,
        # how the data was reached – what was really used
        "drive_auth": auth.describe(creds),
        "bbox": list(bbox) if bbox is not None else None,
        "box": list(box),
        "blocks": [list(p) for p in parts],
        "grid_m": args.grid_m,
        "native_m": native_m,
        # read from: computed in the plan, used in the `read` stage
        "read_m": read_m,
        "ovr_level": ovr_level,
        "tiles": tiles_out,
        "geoid": args.geoid,
        "asset": asset,
        "src_px": list(info["size"]),
        "cells": cells,
        "est_min": est_min,
    }

    # half-read blocks fit only the same plan: a block is known by its number
    old = None
    if os.path.exists(state_path(args.work)):
        with open(state_path(args.work)) as f:
            old = json.load(f)
    same = old is not None and all(old.get(k) == state[k]
                                   for k in ("box", "blocks", "grid_m", "geoid"))
    stale = [f for f in os.listdir(args.work)
             if f.startswith(("block-", "blok-")) and f.endswith((".tif", ".part"))]
    if stale and not same:
        for f in stale:
            os.remove(os.path.join(args.work, f))
        log(f"  the plan changed – {len(stale)} earlier blocks dropped")
    elif stale:
        log(f"  {len(stale)} blocks from an earlier try fit this plan "
            f"and won't be read again")

    if same and old.get("t_start"):
        state["t_start"] = old["t_start"]
        state["drive_bytes"] = old.get("drive_bytes", 0)
        state["drive_requests"] = old.get("drive_requests", 0)
        state["log"] = old.get("log", [])
    else:
        state["t_start"] = time.time()
    drive_totals(state, stats)
    save_state(args.work, state)
    return state


def stage_read(args, state):
    """Blocks from Drive to disk – the only stage on the network, and the long one."""
    src, env, _info, _native, stats, creds = open_source(args)
    state["drive_auth"] = auth.describe(creds)
    parts = [tuple(p) for p in state["blocks"]]
    log(f"  {len(parts)} blocks, {args.jobs} at once, target grid "
        f"{state['grid_m']:g} m")
    read_blocks(src, parts, state["grid_m"], args.work, args.jobs, env,
                state["native_m"], state.get("read_m"), state.get("ovr_level"))
    got, req = drive_totals(state, stats)
    log(f"From Drive so far {got / 1e9:.2f} GB in {req:,} requests")
    save_state(args.work, state)
    return state


def stage_finish(args, state):
    """Blocks on disk → a COG or 1° tiles, off the network."""
    env = drive.gdal_env()
    if state["geoid"] == "egm2008":
        env["PROJ_NETWORK"] = "ON"
    parts = sorted(os.path.join(args.work, f)
                   for f in os.listdir(args.work)
                   if f.startswith(("block-", "blok-")) and f.endswith(".tif"))
    if not parts:
        raise SystemExit(f"::error::{args.work} has not one block – "
                         f"the `read` stage didn't run or failed.")
    if len(parts) != len(state["blocks"]):
        raise SystemExit(
            f"::error::There are {len(parts)} blocks on disk, the plan has "
            f"{len(state['blocks'])}. A mosaic with a hole would be filled "
            f"with zeros, and zero is sea on the map – run `read` again.")
    log(f"Assembling {len(parts)} blocks, "
        f"{sum(os.path.getsize(p) for p in parts) / 1048576:.0f} MB on disk")

    if state["tiles"]:
        # the window widened to whole degrees; `None` = the whole country
        country_tiles(parts, args.out, args.work, env, state["geoid"],
                      window=state["bbox"], grid_m=state["grid_m"])
        made = sorted(f for f in os.listdir(args.out) if f.endswith(".tif"))
        log(f"Done: {len(made)} tiles in {args.out}")
    else:
        dest = to_wgs84(parts, os.path.join(args.out, state["asset"]),
                        state["bbox"], state["grid_m"], args.work, env,
                        state["geoid"])
        made = [os.path.basename(dest)]

    # blocks only now: until then they are the only data read
    for p in parts:
        os.remove(p)
    state["made"] = made
    save_state(args.work, state)
    return state


def write_summary(path, state):
    got = state.get("drive_bytes", 0)
    req = state.get("drive_requests", 0)
    made = state.get("made", [])
    with open(path, "w") as f:
        f.write("## DMR 5.0 (ETRS89) from Drive\n\n")
        f.write("| item | value |\n|---|---|\n")
        f.write(f"| area | {state['area_name']} |\n")
        f.write(f"| grid | {state['grid_m']:g} m |\n")
        f.write(f"| window | {(state['box'][2] - state['box'][0]) / 1000:.1f} × "
                f"{(state['box'][3] - state['box'][1]) / 1000:.1f} km, "
                f"{len(state['blocks'])} blocks |\n")
        f.write(f"| source | {state['src_px'][0]:,}×{state['src_px'][1]:,} px "
                f"@ {state['native_m']:g} m, EPSG:{SRC_EPSG} |\n")
        f.write(f"| heights | {'EGM2008 (≈ Bpv)' if state['geoid'] == 'egm2008' else 'ellipsoidal ETRS89'} |\n")
        f.write(f"| from Drive | {got / 1e9:.2f} GB / {req:,} requests |\n")
        f.write(f"| access | {state.get('drive_auth', '?')} |\n")
        f.write(f"| duration | {(time.time() - state['t_start']) / 60:.1f} min "
                f"(estimated {state['est_min']:.0f} min) |\n")
        f.write(f"| output | {', '.join(f'`{m}`' for m in made[:12]) or '–'} |\n")
        f.write("\n<details><summary>Log</summary>\n\n```\n"
                + "\n".join(state.get("log", []) + LOG[_LOG_SAVED:])
                + "\n```\n\n</details>\n")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", default="whole_country",
                    help="a key from workers/data/areas.json, `whole_country`, or a bbox W,S,E,N")
    ap.add_argument("--grid-m", type=float, default=1.0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--work", default="drive-work")
    ap.add_argument("--asset", default=None,
                    help="the result's name for a cut-out; default ugkk-<area>.tif. "
                         "Required with a bbox in --area – the build can't ask "
                         "for `ugkk-20,49,21,50.tif`.")
    ap.add_argument("--jobs", type=int, default=12,
                    help="how many blocks are read at once; over ~16 Drive "
                         "answers 403 and waiting costs more than it gains")
    ap.add_argument("--geoid", choices=("egm2008", "ellipsoid", "elipsoid"), default="egm2008")
    ap.add_argument("--tiles", action="store_true",
                    help="output 1° tiles (dem-dmr5) for a cut-out too – the "
                         "window widens to whole degrees. Otherwise a cut-out "
                         "is one COG (dem-ugkk).")
    ap.add_argument("--stage", choices=("all", "plan", "read", "finish"),
                    default="all",
                    help="which stage to run; they share state through --work")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--probe-only", action="store_true",
                    help="only open the source and print what is in it")
    ap.add_argument("--auth-check", action="store_true",
                    help="say which account reads from Drive and whether it "
                         "sees both files; nothing is read")
    ap.add_argument("--summary", default=None)
    args = ap.parse_args()

    if args.auth_check:
        return auth_check()

    if args.probe_only:
        _src, _env, info, native_m, _stats, _creds = open_source(args)
        log(f"  CRS: {(info.get('coordinateSystem') or {}).get('wkt', '')[:80]}…")
        log(f"  origin: {info['geoTransform'][0]}, {info['geoTransform'][3]}")
        for i, o in enumerate(info["bands"][0].get("overviews", [])):
            w, h = o["size"]
            log(f"    level {i}: {w:,} × {h:,} px = "
                f"{native_m * info['size'][0] / w:.0f} m")
        return 0

    # stages chain top down; `all` is all three in one process
    state = None
    if args.stage in ("all", "plan"):
        state = stage_plan(args)
    if args.stage in ("all", "read"):
        state = stage_read(args, state or load_state(args.work))
    if args.stage in ("all", "finish"):
        state = stage_finish(args, state or load_state(args.work))
        got, req = state.get("drive_bytes", 0), state.get("drive_requests", 0)
        log(f"From Drive came {got / 1e9:.2f} GB in {req:,} requests, "
            f"the whole run {(time.time() - state['t_start']) / 60:.1f} min")

    if args.summary:
        write_summary(args.summary, state or load_state(args.work))
    return 0


if __name__ == "__main__":
    sys.exit(main())
