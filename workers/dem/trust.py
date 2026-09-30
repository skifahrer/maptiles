#!/usr/bin/env python3
"""
Which small tile in a store CAN'T be trusted – and so must be read again.

`check.sh` asked "is the name in the store?" while downloading measures what is
in the files; in run 31781263921 an unsigned empty `N48E016.tif` passed the check
and the build died later. No third truth: it asks `coverage.empty_stamp`, and
opens only suspiciously small files (`tiles.EMPTY_MAX_BYTES`, sizes from the
store listing). Needs `gdalinfo` – installed by the caller only when needed.

Usage (stdin gets `name:size`, the output of `store.py --index`):
    python3 workers/drive/store.py --index --store=dem-dmr5 \\
      | python3 workers/dem/trust.py --store=dem-dmr5 --names="N48E016.tif …"

Stdout gets the untrustworthy names (one a line); explanations go to stderr.
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)


def load(name, filename, where=_HERE):
    """A module with a dash in its name can't be imported – loaded by path."""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(where, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tiles = load("dem_tiles", "tiles.py")
coverage = load("dem_coverage", "coverage.py")


def suspects(index_lines, wanted):
    """Names from `wanted` in the store but suspiciously small (`name:size` lines)."""
    out = []
    for line in index_lines:
        name, _, size = line.strip().rpartition(":")
        if not name or name not in wanted:
            continue
        try:
            if int(size) <= tiles.EMPTY_MAX_BYTES:
                out.append(name)
        except ValueError:
            continue
    return out


def download(store, names, where):
    """Download the suspect tiles into `where`. Returns those that came."""
    subprocess.run(
        [sys.executable, os.path.join(_WORKERS, "drive", "store.py"), "--get",
         "--store", store, "--dir", where, "--missing-ok",
         "--name", " ".join(names)],
        check=False, stdout=sys.stderr, stderr=sys.stderr)
    return [m for m in names if os.path.exists(os.path.join(where, m))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="the store to download from")
    ap.add_argument("--names", default="",
                    help="the tile names in question (space separated)")
    ap.add_argument("--only-suspect", action="store_true",
                    help="only print the suspiciously small ones (no GDAL, no "
                         "download) – so the caller decides whether GDAL is "
                         "worth installing")
    args = ap.parse_args()

    wanted = set(args.names.split())
    if not wanted:
        return 0
    small = suspects(sys.stdin.readlines(), wanted)
    if not small:
        return 0
    if args.only_suspect:
        for name in small:
            print(name)
        return 0

    print(f"Suspiciously small tiles in store {args.store} "
          f"(≤ {tiles.EMPTY_MAX_BYTES // 1024} kB, not an elevation model but "
          f"a \"we looked there\" record): {' '.join(small)}",
          file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        for name in download(args.store, small, tmp):
            info = coverage.tile_info(os.path.join(tmp, name))
            stamp = coverage.empty_stamp(info) if info else None
            if stamp is None:
                # small but no empty tile by its grid – `coverage.py` judges it by extent
                print(f"  ? {name}: small, but not an empty tile – "
                      f"leaving it to coverage.py", file=sys.stderr)
                continue
            if stamp == tiles.EMPTY_CHECK:
                print(f"  ✓ {name}: an empty tile with today's stamp "
                      f"\"{stamp}\" – that degree needn't be read again",
                      file=sys.stderr)
                continue
            print(f"  ✗ {name}: an empty tile from check "
                  f"\"{stamp or 'v1 (unsigned)'}\", today it is "
                  f"\"{tiles.EMPTY_CHECK}\" – it will be refilled", file=sys.stderr)
            print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
