#!/usr/bin/env python3
"""A regenerated package takes from its last copy on Drive what the run didn't rebuild."""
import argparse
import importlib.util
import json
import os
import sys
import tempfile
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_DRIVE = os.path.join(os.path.dirname(_HERE), "drive")
_DATA = os.path.join(os.path.dirname(_HERE), "data")


def _load(name, path):
    """workers/*.py can't be imported normally because of the dash in their names."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


files = _load("deploy_files", os.path.join(_HERE, "files.py"))
folder = _load("drive_folder", os.path.join(_DRIVE, "folder.py"))
catalog = files.catalog
packages = files.packages
names = catalog.names


def carried(rel, package, site_has):
    """Whether a member of the old package comes back: not rebuilt, not the run's own layer."""
    if rel == "contents.json" or site_has(rel):
        return False
    name = os.path.basename(rel)
    cut = f"-omt-{package}.pmtiles"
    own = [s for s in packages.package(package).get("suffixes") or () if s != cut]
    # a layer the run rebuilt without some optional file must not get the old one back
    return not (rel.startswith("tiles/") and files.has_suffix(name, own))


def carry(archive, site, package):
    """Members of the zip `archive` missing in `site`, unpacked there; returns their paths."""
    out = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir() or "/" not in info.filename:
                continue
            # every package zips under one folder of its own name
            rel = info.filename.split("/", 1)[1]
            if not carried(rel, package, lambda r: os.path.exists(os.path.join(site, r))):
                continue
            dest = os.path.join(site, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as dst:
                while block := src.read(1 << 20):
                    dst.write(block)
            out.append(rel)
    return out


def last_copy(maps, package):
    """The `{id, size}` of the package's zip the catalog lists for this run's region, or None."""
    with open(os.path.join(_DATA, "regions.json"), encoding="utf-8") as f:
        regions = json.load(f)
    with open(maps, encoding="utf-8") as f:
        data = json.load(f)
    entry = (catalog.node_at(data, names.catalog_path(names.drive_path(regions)))
             .get("maps") or {}).get(package) or {}
    zip_ = (entry.get("formats") or {}).get("zip") or entry
    fid = folder.id_from_link(zip_.get("download") or zip_.get("link") or "")
    return {"id": fid, "size": int(zip_.get("size") or 0), "name": zip_.get("file") or ""} \
        if fid and zip_.get("size") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="_site")
    ap.add_argument("--maps", default=catalog.CATALOG)
    ap.add_argument("--package", required=True)
    args = ap.parse_args()

    item = last_copy(args.maps, args.package)
    if item is None:
        print(f"Package `{args.package}` isn't in {args.maps} for this region yet – "
              f"nothing to carry over.")
        return 0
    pool = folder.drive.Pool(creds=folder.auth.from_env())
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, item["name"] or "package.zip")
        folder.fetch(pool, item, archive, folder.Progress(item["size"]))
        kept = carry(archive, args.site, args.package)
    print(f"Carried over from {item['name']}: {len(kept)} files the run didn't rebuild")
    for rel in kept:
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
