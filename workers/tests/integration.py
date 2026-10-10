#!/usr/bin/env python3
"""The mini region through every package build, then `check-packages.py` over the result."""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
from load import worker  # noqa: E402
import mini_region  # noqa: E402

PACKAGES = ("transport", "boundaries", "water", "rail", "history", "buildings", "trails", "features")
REGION_KEY = "mini"
# apt is the job's business; the builds only ask for what is already there
SUDO = '#!/bin/sh\n[ "$1" = apt-get ] && exit 0\nexec "$@"\n'


def prepare(work, jar):
    """`work/` as a build sees the repository root: workers, data, planetiler.jar."""
    os.makedirs(os.path.join(work, "data"), exist_ok=True)
    link = os.path.join(work, "workers")
    if not os.path.exists(link):
        os.symlink(_WORKERS, link)
    if not os.path.exists(os.path.join(work, "planetiler.jar")):
        os.symlink(os.path.abspath(jar), os.path.join(work, "planetiler.jar"))
    osm = os.path.join(work, "data", "mini-region.osm")
    with open(osm, "w", encoding="utf-8") as f:
        f.write(mini_region.build().xml())
    subprocess.run(["osmium", "cat", "--overwrite", osm, "-o",
                    os.path.join(work, "data", "region.osm.pbf")], check=True)
    poly = worker("plan/region-poly.py")
    rings = [(list(mini_region.OUTLINE), False)]
    with open(os.path.join(work, "data", "region.poly"), "w") as f:
        f.write(poly.rings_to_poly_text(rings, name=REGION_KEY))
    with open(os.path.join(work, "data", "region.geojson"), "w") as f:
        f.write(json.dumps(poly.geojson(rings)))
    stubs = os.path.join(work, "stubs")
    os.makedirs(stubs, exist_ok=True)
    with open(os.path.join(stubs, "sudo"), "w") as f:
        f.write(SUDO)
    os.chmod(os.path.join(stubs, "sudo"), 0o755)
    return stubs


def run_build(work, stubs, package):
    """One `build.sh`; returns (ok, its GITHUB_OUTPUT as a dict, log)."""
    out = os.path.join(work, f"{package}.out")
    open(out, "w").close()
    env = {**os.environ, "PATH": stubs + os.pathsep + os.environ["PATH"],
           "GITHUB_OUTPUT": out, "REGION_KEY": REGION_KEY, "REGION_NAME": "Mini",
           "REGION_BBOX": ",".join(str(v) for v in mini_region.BBOX),
           "OPT_REGION_CLIP": "true", "SIZE_LIMIT_MB": "900"}
    env.update({f"BUDGET_{p.upper()}_PCT": "100" for p in PACKAGES})
    # empty = the build's own default zoom
    env.update({f"OPT_{p.upper()}_MAXZOOM": "" for p in PACKAGES})
    t0 = time.time()
    r = subprocess.run(["bash", f"workers/{package}/build.sh"], cwd=work, env=env,
                       capture_output=True, text=True)
    with open(out) as f:
        outputs = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)
    print(f"{'✓' if r.returncode == 0 else '✗'} {package}: {time.time() - t0:.0f} s, "
          f"outputs {outputs}", flush=True)
    return r.returncode == 0, outputs, r.stdout + r.stderr


def routing(work):
    """The road routing archive from the mini region, as the rail build makes its own."""
    data = os.path.join(work, "data")
    with open(os.path.join(data, "routing-filter.txt"), "w") as f:
        subprocess.run([sys.executable, os.path.join(_WORKERS, "routing/tags.py"), "--filter"],
                       stdout=f, check=True)
    subprocess.run(["osmium", "tags-filter", "--overwrite", "-o", os.path.join(data, "routing.osm.pbf"),
                    os.path.join(data, "region.osm.pbf"),
                    f"--expressions={os.path.join(data, 'routing-filter.txt')}"], check=True)
    out = os.path.join(work, "_site", "tiles", f"{REGION_KEY}-routing.pmtiles")
    r = subprocess.run([sys.executable, os.path.join(_WORKERS, "routing/tiles.py"),
                        f"--pbf={os.path.join(data, 'routing.osm.pbf')}", f"--out={out}",
                        f"--region-key={REGION_KEY}", "--profile-step=0"],
                       capture_output=True, text=True)
    print(f"{'✓' if r.returncode == 0 else '✗'} routing", flush=True)
    return r.returncode == 0, r.stdout + r.stderr


# what dem-layers.yml gives the contours step (its `env:` and the form's defaults)
CONTOUR_ENV = {
    "ONLY": "contours", "AREA_KEY_IN": "whole", "AREA_NAME_IN": "", "AREA_BBOX_IN": "", "AREA_KM2": "",
    "CONTOUR_INTERVAL": "10", "OPT_CONTOUR_LINES": "true", "OPT_CONTOUR_SOURCE": "sonny",
    "OPT_CONTOUR_SMOOTHING": "0", "OPT_CONTOUR_MAXZOOM": "14", "OPT_CONTOUR_MAXZOOM_CAP": "14",
    "OPT_CONTOUR_LOWLAND_M": "300", "OPT_ROCK_MAXZOOM": "16", "OPT_ROCK_SOLID": "0",
    "OPT_ROCK_FILL_HOLES": "0", "ROCK_SLOPE_IN": "50", "ROCK_RES_IN": "auto", "OPT_ROCKS": "false",
    "OPT_ROCK_DEM": "", "OPT_ROCK_SOURCE": "sonny", "OPT_ROCK_IMG_ASSET": "", "OPT_ROCKS_REBUILD": "false",
    "OPT_SIZE_LIMIT_MB": "900", "OPT_UGKK_FALLBACK": "", "OPT_TEST_KM2": "0", "SLOPE_DIR": "slope-chunks",
    "CONTOUR_DEM_LOWPASS": "2", "CONTOUR_SIMPLIFY": "-1", "CONTOUR_SMOOTH": "2",
    "BUDGET_CONTOURS_PCT": "20", "BUDGET_ROCKS_PCT": "20", "BUDGET_TERRAIN_PCT": "12",
    "ROCK_RES": "auto", "ROCK_VEC_RES": "auto", "ROCK_SIMPLIFY": "-1", "ROCK_SMOOTH": "2",
    "ROCK_ALGO": "v5", "ROCK_CLIFF_PLUS": "15", "ROCK_CHUNK_CELLS": "150000000", "ROCK_BUDGET_MIN": "0",
    "ROCK_BLOCK_PX": "4096", "ROCK_MAX_RSS_GB": "12", "ROCK_HEARTBEAT_S": "30",
    "DEM_STORE": "dem-sonny", "ROCK_STORE": "dem-rocks", "SLOPE_STORE": "dem-slope",
}
# rows and columns of the hill's NODATA hole, inside the region
HOLE = (50, 60, 60, 75)


def dem_side(work, stubs):
    """A synthetic hill as the `sonny` mosaic: contours through build.sh, terrain tiles over a hole."""
    from geo import hill, write_dem  # noqa: PLC0415
    w, s, e, _ = mini_region.BBOX
    box = (w, s, e, s + 120 * (e - w) / 200)
    os.makedirs(os.path.join(work, "dem", "sonny"), exist_ok=True)
    write_dem(os.path.join(work, "dem", "sonny", "hill.tif"), hill(200)[:120], box)
    subprocess.run(["gdalbuildvrt", "-q", os.path.join(work, "dem", "sonny", "all.vrt"),
                    os.path.join(work, "dem", "sonny", "hill.tif")], check=True)
    write_dem(os.path.join(work, "dem", "hole.tif"), hill(200, hole=HOLE)[:120], box)
    env = {**os.environ, "PATH": stubs + os.pathsep + os.environ["PATH"], **CONTOUR_ENV,
           "GITHUB_OUTPUT": os.path.join(work, "contours.out"), "REGION_KEY": REGION_KEY,
           "REGION_BBOX": ",".join(str(v) for v in mini_region.BBOX)}
    logs, ok = [], True
    for cmd in (["bash", "workers/contours-rocks/build.sh"],
                [sys.executable, "workers/terrain/tiles.py", "--dem=dem/hole.tif",
                 f"--bbox={env['REGION_BBOX']}", "--poly=data/region.geojson",
                 "--minzoom=10", "--maxzoom=13", "--out=terrain-png", "--format=png"]):
        r = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True)
        print(f"{'✓' if r.returncode == 0 else '✗'} {cmd[1]}", flush=True)
        ok &= r.returncode == 0
        logs.append(r.stdout + r.stderr)
    return ok, "\n".join(logs)


ROCK_ENV = {"ONLY": "rocks", "OPT_ROCKS": "true", "OPT_ROCK_DEM": "sonny", "OPT_ROCK_SOURCE": "sonny",
            "AREA_NAME_IN": "the whole region", "ROCK_SLOPE_IN": "3", "ROCK_RES_IN": "10"}


def failing_workers(work):
    """`workers/` of symlinks, but `rock-areas.py` fails when run (still importable)."""
    shadow = os.path.join(work, "shadow")
    os.makedirs(os.path.join(shadow, "contours-rocks"), exist_ok=True)
    for name in os.listdir(_WORKERS):
        if name != "contours-rocks" and not os.path.exists(os.path.join(shadow, name)):
            os.symlink(os.path.join(_WORKERS, name), os.path.join(shadow, name))
    src = os.path.join(_WORKERS, "contours-rocks")
    for name in os.listdir(src):
        dst = os.path.join(shadow, "contours-rocks", name)
        if name == "rock-areas.py":
            with open(os.path.join(src, name)) as f:
                body = f.read().replace("    sys.exit(main())", "    sys.exit(1)")
            with open(dst, "w") as f:
                f.write(body)
        elif not os.path.exists(dst):
            os.symlink(os.path.join(src, name), dst)
    return shadow


def rocks_side(work, stubs):
    """Rocks from the hill, then the same with a failing computation in a copy of `work`."""
    fail = os.path.join(work, "rocks-failed")
    os.makedirs(fail, exist_ok=True)
    for name in ("data", "dem", "stubs", "planetiler.jar"):
        if not os.path.exists(os.path.join(fail, name)):
            os.symlink(os.path.join(work, name), os.path.join(fail, name))
    if not os.path.exists(os.path.join(fail, "workers")):
        os.symlink(failing_workers(work), os.path.join(fail, "workers"))
    bbox = ",".join(str(v) for v in mini_region.BBOX)
    logs, ok = [], True
    for where in (work, fail):
        os.makedirs(os.path.join(where, "steps-out"), exist_ok=True)
        env = {**os.environ, "PATH": stubs + os.pathsep + os.environ["PATH"], **CONTOUR_ENV, **ROCK_ENV,
               "GITHUB_OUTPUT": os.path.join(where, "rocks.out"), "REGION_KEY": REGION_KEY,
               "REGION_BBOX": bbox, "AREA_BBOX_IN": bbox, "CACHE_HIT": "false"}
        for script in ("build.sh", "site.sh"):
            r = subprocess.run(["bash", f"workers/contours-rocks/{script}"], cwd=where, env=env,
                               capture_output=True, text=True)
            print(f"{'✓' if r.returncode == 0 else '✗'} rocks {script}"
                  f"{' (failing computation)' if where == fail else ''}", flush=True)
            ok &= r.returncode == 0
            logs.append(r.stdout + r.stderr)
    return ok, "\n".join(logs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", default="planetiler.jar")
    ap.add_argument("--work", default="", help="kept for a look afterwards; default a temp folder")
    ap.add_argument("--only", default="", help="comma-separated packages")
    ap.add_argument("--dem", action="store_true", help="the DEM side too (contours, terrain)")
    args = ap.parse_args()
    if not os.path.exists(args.jar):
        print(f"::error::{args.jar} is missing – workers/lib/planetiler.sh downloads it.")
        return 2
    work = args.work or tempfile.mkdtemp(prefix="mini-region-")
    stubs = prepare(work, args.jar)
    print(f"Mini region in {work}")

    failed = []
    packages = args.only.split(",") if args.only else list(PACKAGES)
    for package in packages:
        ok, outputs, log = run_build(work, stubs, package)
        if not ok or outputs.get("enabled") != "true":
            failed.append(package)
            print(f"::error::{package}: build.sh {'failed' if not ok else 'made no package'}:\n"
                  + "\n".join(log.splitlines()[-30:]))
    if not args.only:
        ok, log = routing(work)
        if not ok:
            failed.append("routing")
            print("::error::routing:\n" + "\n".join(log.splitlines()[-30:]))

    if args.dem:
        for name, side in (("dem", dem_side), ("rocks", rocks_side)):
            ok, log = side(work, stubs)
            if not ok:
                failed.append(name)
                print(f"::error::{name}:\n" + "\n".join(log.splitlines()[-40:]))

    spec = importlib.util.spec_from_file_location("check_packages", os.path.join(_HERE, "check-packages.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    problems = check.check_all(work, REGION_KEY, [p for p in packages if p not in failed])
    if args.dem and "dem" not in failed:
        problems += check.check_dem(work, HOLE)
    if args.dem and "rocks" not in failed:
        problems += check.check_rocks(work, os.path.join(work, "rocks-failed"), REGION_KEY)
    for p in problems:
        print(f"::error::{p}")
    print(f"Mini region: {len(failed)} builds failed, {len(problems)} problems in the packages")
    if not args.work:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed or problems else 0


if __name__ == "__main__":
    sys.exit(main())
