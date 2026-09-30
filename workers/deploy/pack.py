#!/usr/bin/env python3
"""How a package is packed – ZIP and Apple Archive, the same contents in both."""
import importlib.util
import json
import os
import subprocess
import shutil
import sys
import tempfile
import time
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_DRIVE = os.path.join(os.path.dirname(_HERE), "drive")


def _load(name, path):
    """workers/*.py can't be imported normally because of the dash in their names."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


folder = _load("drive_folder", os.path.join(_DRIVE, "folder.py"))

# tiles, PNG and fonts are compressed already; a higher level costs minutes for nothing
ZIP_LEVEL = 1
CONTENTS = "contents.json"


def log(*a):
    print(*a, flush=True)


def pack_zip(site, dest, root, files, info=None):
    """Files → one ZIP with everything under the folder `root`, so unpacking doesn't spill."""
    raw = sum(os.path.getsize(f) for f in files)
    log(f"Packing {len(files)} files ({folder.human(raw)}) into {dest}")

    t0 = time.time()
    done = 0
    last = t0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=ZIP_LEVEL) as z:
        if info is not None:
            # first, so it is in sight after unpacking
            z.writestr(os.path.join(root, CONTENTS),
                       json.dumps(info, ensure_ascii=False, indent=2) + "\n")
        for f in sorted(files):
            z.write(f, os.path.join(root, os.path.relpath(f, site)))
            done += os.path.getsize(f)
            # a beat every half minute: silence can't be told from a stuck step
            if time.time() - last >= 30:
                last = time.time()
                log(f"  [{(last - t0) / 60:.1f} min] "
                    f"{folder.human(done)} of {folder.human(raw)}")
    size = os.path.getsize(dest)
    log(f"  done in {time.time() - t0:.0f} s: {folder.human(size)} "
        f"({size * 100 // max(raw, 1)} % of the original size)")
    return size


def has_aa():
    """Is the Apple Archive CLI (`aa`) here? Only on macOS."""
    from shutil import which
    return which("aa") is not None


def pack_aar(site, dest, root, files, info=None):
    """Files → one Apple Archive (`.aar`, LZFSE), staged as a tree of hard links."""
    raw = sum(os.path.getsize(f) for f in files)
    log(f"Packing {len(files)} files ({folder.human(raw)}) into {dest}")
    t0 = time.time()
    stage = tempfile.mkdtemp(prefix="aar-", dir=os.path.dirname(dest) or None)
    try:
        root_dir = os.path.join(stage, root)
        os.makedirs(root_dir, exist_ok=True)
        if info is not None:
            with open(os.path.join(root_dir, CONTENTS), "w") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
                f.write("\n")
        for f in sorted(files):
            target = os.path.join(root_dir, os.path.relpath(f, site))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                os.link(f, target)
            except OSError:
                # another filesystem or too many links – copy then
                shutil.copy2(f, target)
        if os.path.exists(dest):
            os.remove(dest)
        subprocess.run(["aa", "archive", "-a", "lzfse", "-d", stage,
                        "-o", dest], check=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    size = os.path.getsize(dest)
    log(f"  done in {time.time() - t0:.0f} s: {folder.human(size)} "
        f"({size * 100 // max(raw, 1)} % of the original size)")
    return size


# format → its packer; a third format is added here and nowhere else
PACKERS = {"zip": pack_zip, "aar": pack_aar}
