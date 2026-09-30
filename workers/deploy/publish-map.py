#!/usr/bin/env python3
"""Pack `_site` into stably named packages and upload them to Drive.

The package list is `workers/data/packages.json`. Names are stable so the next
build overwrites the same file and the link in `maps.json` keeps working.
`contents.json` inside says what a package holds.
"""
import argparse
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
_DRIVE = os.path.join(_WORKERS, "drive")


def load(name, path):
    """workers/*.py can't be imported normally because of the dash in their names."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pack = load("deploy_pack", "pack.py")
catalog = load("deploy_catalog", "catalog.py")
files = load("deploy_files", "files.py")
registry = load("deploy_packages", "packages.py")
layer_packages = files.layer_packages
base_parts = files.base_parts
where_glyphs_are = files.where_glyphs_are
manifest_data = files.manifest_data
outside_packages = files.outside_packages
part_sizes = files.part_sizes
all_files = files.all_files
contents_sha = files.contents_sha
base_files = files.base_files
names = load("deploy_names", "names.py")
strip_test = names.strip_test
drive_path = names.drive_path
catalog_path = names.catalog_path
env = names.env
file_name = names.file_name
safe = names.safe
layers = names.layers
PACKERS = pack.PACKERS
has_aa = pack.has_aa
auth = load("drive_auth", os.path.join(_DRIVE, "auth.py"))
folder = load("drive_folder", os.path.join(_DRIVE, "folder.py"))

# a folder id is no secret, the token is
FOLDER_ID = "1pvrw7CGUkQLwg8Ql8xbKA4HhQHvPl8_7"

# retired packages are deleted on Drive, or the catalog keeps a dead link
RETIRED = registry.retired()
LEGACY = registry.legacy()


def log(msg):
    print(msg, flush=True)


def contents(kind, man, fmt="zip", parts=None):
    """`contents.json` for a package – what the file name once carried."""
    reg = catalog.region_entry(man)
    return {
        "package": kind or "base",
        # parts belong to the base map
        **({"parts": part_sizes(parts)} if not kind and parts else {}),
        # with the format extension: an .aar must not claim to be a zip
        "file": file_name(kind, fmt),
        "format": fmt,
        "region": strip_test(env("REGION_KEY")),
        "area": names.area_key() or "whole",
        "test_km2": env("TEST_KM2", "0"),
        "tiles_maxzoom": env("TILES_MAXZOOM"),
        "layers": layers(),
        # glyphs are never packed; the field stays so their absence is visible
        "no_glyphs": True,
        "glyphs": man.get("glyphs") or "",
        "glyphs_where": where_glyphs_are(man),
        "no_viewer": True,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run": env("GITHUB_RUN_NUMBER"),
        "run_id": env("GITHUB_RUN_ID"),
        "manifest": {"dem": man.get("dem"),
                     "dem_maxzoom": man.get("dem_maxzoom"),
                     "dem_source": man.get("dem_source"),
                     # tiles may be there with 3D off, so `dem` alone doesn't say
                     "terrain_3d": man.get("terrain_3d"),
                     "terrain_exaggeration": man.get("terrain_exaggeration"),
                     "region": reg},
    }


def delete_legacy(creds, fid, kind, formats):
    """Old files of a renamed package; the new name never overwrites them."""
    for old in (o for o, new in LEGACY.items() if new == (kind or "base") and kind):
        for fmt in formats:
            name = file_name(old, fmt)
            count = folder.delete_named(creds, fid, name)
            if count:
                log(f"Package `{old}` is `{kind}` now – deleted {count}× old {name}.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default="_site", help="what gets packed")
    # zip always, .aar on top for Apple; formats add up, they don't switch
    ap.add_argument("--format", default="zip",
                    help="formats to build: `zip`, `aar`, `zip,aar`")
    ap.add_argument("--folder", default=FOLDER_ID,
                    help="folder on Drive (URL or id)")
    ap.add_argument("--out", default="", help="where to keep the ZIP (default RUNNER_TEMP)")
    ap.add_argument("--keep-zip", action="store_true",
                    help="keep the ZIP on disk after uploading")
    ap.add_argument("--dry-run", action="store_true",
                    help="say names and path, pack and upload nothing")
    ap.add_argument("--zip-only", action="store_true",
                    help="pack into --out and leave Drive alone (local try)")
    ap.add_argument("--summary", default="", help="where to append the summary")
    ap.add_argument("--wiki", default="",
                    help="folder with Wikipedia articles (package `wikipedia`); "
                         "empty = not published and the old one deleted")
    ap.add_argument("--only", default="",
                    help="publish ONLY this package (e.g. `wikipedia`) and add to "
                         "the catalog, not rewrite it – for pipelines that don't "
                         "build the whole map")
    ap.add_argument("--maps", default=catalog.CATALOG,
                    help="catalog of finished maps in the repository (empty = "
                         "don't write). A quick test turns it into "
                         "`maps-test.json` – `catalog.py` decides.")
    args = ap.parse_args()

    # a test writes its own file (`catalog.catalog_file`)
    args.maps = catalog.catalog_file(args.maps)
    # catalog.sh commits the same file – passed as a step output
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out and args.maps:
        with open(gh_out, "a") as f:
            f.write(f"maps_file={args.maps}\n")
    if args.maps != catalog.CATALOG:
        log(f"Catalog of this run: {args.maps} (quick test – finished maps are "
            f"in {catalog.CATALOG})")

    with open(os.path.join(_DATA, "regions.json")) as f:
        regions = json.load(f)

    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    for f in formats:
        if f not in PACKERS:
            raise SystemExit(f"::error::Unknown format “{f}”. Known: "
                             f"{', '.join(PACKERS)}.")
    if "aar" in formats and not has_aa():
        # skipping silently is not allowed; `aa` exists only on macOS
        raise SystemExit("::error::Apple Archive can't be built – the `aa` tool "
                         "isn't here. It ships with macOS (11+), so a `--format` "
                         "with `aar` belongs in a job on `macos-latest`; on Linux "
                         "keep `--format=zip`.")

    parts = drive_path(regions)
    man = manifest_data(args.site)
    # own packages are counted before the base map – it leaves them out
    own_packages = layer_packages(args.site, man)
    # base map parts: never removed from it (even when another package carries
    # them too) and sized for the catalog; with `--only` the map isn't published
    pieces = base_parts(args.site, man)
    keep = [f for _k, _p, fs in pieces for f in fs]
    if args.only:
        pieces = []
    # viewer and glyphs aren't packed; how much a package leaves out must show
    out_files, out_reasons = outside_packages(args.site, man)
    for description, count, size in out_reasons:
        log(f"Not packed: {description}: {count} files, "
            f"{folder.human(size)}")
    for key, description, fs in pieces:
        log(f"The base map carries part `{key}` – {description}: "
            + (f"{len(fs)} files, "
               f"{folder.human(sum(os.path.getsize(f) for f in fs))}"
               if fs else "THIS BUILD DIDN'T MAKE IT, the map won't have it"))
    # out of the base map: files of own packages + what doesn't belong there
    exclude = [f for _p, fs in own_packages for f in fs] + out_files
    batch = [
        ("", "base map – the whole OSM cartography with waymarked trails, "
             "routing network and search; without layers that have their own "
             "package, glyphs or viewer",
         args.site, base_files(args.site, exclude, keep)),
    ] + [(p["key"], p["description"], args.site, fs)
         for p, fs in own_packages]
    # wikipedia has its own pipeline; without `--wiki` a map run would delete it
    if args.wiki or args.only == "wikipedia":
        batch.append(
            ("wikipedia", registry.package("wikipedia")["description"],
             args.wiki, all_files(args.wiki) if args.wiki else []))
    # `--only`: a separate pipeline makes one package, the rest isn't deleted
    if args.only:
        # the base map is listed under the empty key, but called `base`
        if args.only == "base":
            args.only = ""
        known = [k for k, *_ in batch]
        if args.only not in known:
            raise SystemExit(f"::error::`--only={args.only}` is unknown. Packages "
                             f"are: {', '.join(k or 'base' for k in known)}.")
        batch = [b for b in batch if b[0] == args.only]
        if not batch[0][3]:
            raise SystemExit(
                f"::error::Package `{args.only}` has no files – nothing to "
                f"publish. (Did the step that makes it run?)")
    elif not batch[0][3]:
        raise SystemExit(f"::error::{args.site} has no files – nothing to "
                         f"publish. (Did the `deploy` job get as far as "
                         f"assembling the site?)")
    # what this run decides – one list for deleting and for the catalog
    owns = [kind or "base" for kind, *_ in batch]
    for kind, description, _base, fs in batch:
        state = (f"{len(fs)} files, "
                 f"{folder.human(sum(os.path.getsize(f) for f in fs))}"
                 if fs else "NOT IN THIS BUILD – the old package is deleted")
        for fmt in formats:
            log(f"  {file_name(kind, fmt):<48} {description} – {state}")
    log(f"Folder on Drive: {'/'.join(parts)}")
    if args.dry_run:
        return 0

    if args.zip_only:
        # local try: the same packing, just no Drive
        out = args.out or os.environ.get("RUNNER_TEMP", "/tmp")
        for kind, description, base, fs in batch:
            if not fs:
                log(f"{file_name(kind)}: {description} isn't in this build – skipping.")
                continue
            for fmt in formats:
                name = file_name(kind, fmt)
                PACKERS[fmt](base, os.path.join(out, name), name[:-4], fs,
                             info=contents(kind, man, fmt, pieces))
        return 0

    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            "::error::Publishing the map to Drive needs the owner's token, but "
            "the environment has none. Add the secret GDRIVE_CREDENTIALS (or the "
            "variable DRIVE_CLIENT and secrets DRIVE_SECRET / DRIVE_REFRESH) and "
            "pass it to the job via `env:` – the workflow “Drive · Sign in "
            "(one-off)” makes them.")
    # scope before packing: a readonly token uploads nothing
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::The map wasn't published: {auth.scope_hint()}")

    root = folder.folder_id(args.folder)
    fid = folder.ensure_path(creds, root, parts)
    done = []
    # the same contents in both formats, so hashed once per package
    shas = {}
    for (kind, description, base, fs), fmt in [(b_, f) for b_ in batch
                                               for f in formats]:
        name = file_name(kind, fmt)
        if not fs:
            # the layer isn't in this build: an old package of that name would lie
            count = folder.delete_named(creds, fid, name)
            if count:
                log(f"::warning::{description} isn't in this build – deleted "
                    f"{count}× old {name}, so no package of another run stays "
                    f"in the folder.")
            else:
                log(f"{name}: {description} isn't in this build – not publishing.")
            continue
        dest = os.path.join(args.out or os.environ.get("RUNNER_TEMP", "/tmp"),
                            name)
        size = PACKERS[fmt](base, dest, name[:-4], fs,
                            info=contents(kind, man, fmt, pieces))
        try:
            log(f"Uploading {name} ({folder.human(size)}) …")
            t0 = time.time()
            file_id, overwritten = folder.upload_clobber(
                creds, dest, name, fid, f"{'/'.join(parts)}/{name}")
            el = max(time.time() - t0, 1e-6)
            log(f"  done in {el / 60:.1f} min "
                f"({size / el / 1e6:.1f} MB/s)"
                + (" – old file of that name overwritten" if overwritten else ""))
        finally:
            if not args.keep_zip and os.path.exists(dest):
                os.remove(dest)
        if kind not in shas:
            shas[kind] = contents_sha(base, fs)
        done.append((kind, name, description, size, overwritten, file_id, fmt,
                     shas[kind]))
    log(f"Done: {len(done)} packages in {folder.folder_link(fid)}")

    for kind in {k for k, *_ in done}:
        delete_legacy(creds, fid, kind, formats)

    # names are stable and no new run overwrites them – a retired package is deleted
    if not args.only:
        for kind in RETIRED:
            for fmt in formats:
                name = file_name(kind, fmt)
                count = folder.delete_named(creds, fid, name)
                if count:
                    log(f"::warning::Package `{kind}` no longer exists – its contents "
                        f"are in the base map. Deleted {count}× {name}, so nobody "
                        f"downloads it twice.")

    # what really is in the folder; `None` = unknown, `{}` = empty
    live = None
    try:
        live = folder.ids_in(creds, fid)
        log(f"The map folder holds {len(live)} files – catalog links to files no "
            f"longer there are dropped by them.")
    except Exception as exc:                       # noqa: BLE001
        log(f"::warning::The map folder couldn't be listed ({exc}) – this run "
            f"didn't check catalog links. Writing them as they are.")

    if args.maps:
        # a test is written too, just into its own node
        cat = catalog_path(parts)
        changed = catalog.write_catalog(
            args.maps, parts, regions,
            # every format goes in; `merge` adds, doesn't overwrite
            [(k, n, v, i, f, sh) for k, n, _p, v, _pr, i, f, sh in done],
            man, only=args.only, merge="zip" not in formats, cat=cat,
            layers=layers(), owns=owns,
            # how much of the map is search – nowhere else to read it
            base_parts=None if args.only else part_sizes(pieces),
            # retired packages and dead links out, `--only` too
            retired=RETIRED, live=live)
        if args.summary and changed:
            with open(args.summary, "a") as f:
                f.write(f"Catalog `{args.maps}` in the repository is "
                        f"updated (`{'/'.join(cat)}`).\n\n")

    if args.summary:
        with open(args.summary, "a") as f:
            f.write("## Map on Google Drive\n\n")
            f.write(f"Folder [{'/'.join(parts)}]({folder.folder_link(fid)}) – "
                    f"names are stable, so the next build overwrites these files. "
                    f"`contents.json` inside says what a package holds.\n\n")
            f.write("| package | what it holds | size | old |\n|---|---|--:|---|\n")
            for _kind, name, description, size, overwritten, _fid, _fmt, _sha in done:
                f.write(f"| `{name}` | {description} | {folder.human(size)} | "
                        f"{'overwritten' if overwritten else '–'} |\n")
            f.write("\n")
            # parts separately: the table counts them in the map's size
            if pieces:
                f.write("Of that, the base map carries (no package of their "
                        "own):\n\n")
                f.write("| part | what it is | size |\n|---|---|--:|\n")
                for key, description, fs in pieces:
                    size = sum(os.path.getsize(x) for x in fs)
                    f.write(f"| `{key}` | {description} | "
                            + (folder.human(size) if fs
                               else "**not in this map**") + " |\n")
                f.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except auth.AuthError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
