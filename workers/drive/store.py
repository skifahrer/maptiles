#!/usr/bin/env python3
"""The store of finished data on Google Drive – a stand-in for GitHub releases.

    gh release view          → --names / --index / --latest
    gh release download      → --get
    gh release upload        → --put
    gh release delete-asset  → --rm

File names stay as the assets had them – a name promises an extent. The layout
is `<root>/<store>/<asset name>`; the root appears by itself at the first write,
`DRIVE_STORE_FOLDER` puts it elsewhere. "Clobber" uploads the new first and only
then deletes the old; the newest file of a name wins when reading. Without a
sign-in it fails loudly – "nothing stored" and "no token" must differ.

    python3 workers/drive/store.py --check | --list --store=dem-dmr5
    python3 workers/drive/store.py --get --store=dem-dmr5 --dir=dem/tiles \
        --name=N49E019.tif --missing-ok
    python3 workers/drive/store.py --put --store=dem-terrain --file=/tmp/x.tar.zst
"""
import argparse
import calendar
import importlib.util
import os
import sys
import time

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


# borrowed whole, like `cache.py`, so there is one truth about each
drive = load("drive_serve", "serve.py")     # Pool: Range, redirects
auth = load("drive_auth", "auth.py")        # who am I, token, deleting
folder = load("drive_folder", "folder.py")  # listing, folders, upload

# empty = `STORE_NAME` in the token owner's My Drive root (found by name or made);
# DRIVE_STORE_FOLDER overrides it, an id or a whole link
FOLDER_ID = ""
# the existing Drive folder's name – renaming it would orphan every store
STORE_NAME = "fricomaps-sklad"

# stores the pipeline knows, so a typo isn't mistaken for an empty store;
# `workers/lint/stores.py` checks the list against what the pipeline asks for
KNOWN = {
    "dem-sonny": "Elevation model – Sonny's LiDAR DTM (1°×1° tiles)",
    "dem-sonny1": "Elevation model – Sonny's LiDAR DTM 1″ (.hgt, 1 m height step)",
    "dem-dmr35": "Elevation model – ÚGKK DMR 3.5 (open data, 10 m)",
    # `-v2` carries the resampling fix, since `N49E020.tif` must not be renamed;
    # the old `dem-dmr5` stays until deleted by hand
    "dem-dmr5": "Elevation model – ÚGKK DMR 5.0, tiles (5 m), before the resampling fix",
    "dem-dmr5-v2": "Elevation model – ÚGKK DMR 5.0, tiles (5 m)",
    "dem-ugkk": "Elevation model – ÚGKK DMR 5.0, a full 1 m cut-out",
    "dem-terrain": "Terrain (terrarium) tiles for hillshading and 3D terrain",
    "dem-rocks": "Rock areas computed from the elevation model's slope",
    "dem-rocks-img": "Rock areas from dark spots in hillshading tiles",
    "dem-slope": "The slope raster in chunks (a rock intermediate)",
    "results": "Intermediate build results to look at (contours, rocks, trails)",
    # the former name of `results`, pruned until it is empty
    "vysledky": "Intermediate build results, former store",
}

_ROOT = {}      # the store root's id – found once a run
_STORES = {}    # store name → folder id


def log(msg):
    print(msg, flush=True)


def human(n):
    return folder.human(n)


def creds_or_die(what):
    """Sign-in, or exit with advice; a silent "not stored" is the costliest mistake."""
    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            f"::error::The Drive store needs a sign-in ({what}), but the "
            "environment has no owner token. Add the secret GDRIVE_CREDENTIALS "
            "(or the variable DRIVE_CLIENT and secrets DRIVE_SECRET / "
            "DRIVE_REFRESH) and pass it to the job through `env:` – the "
            "workflow \"Maintenance · Drive sign-in\" makes them.")
    return creds


def root_id(creds, create=False):
    """The store root folder's id; `create=True` makes it when missing."""
    # READING NEVER MAKES A FOLDER: making prints to stdout, and `--latest` is read into a variable
    if "id" in _ROOT:
        return _ROOT["id"]
    want = (os.environ.get("DRIVE_STORE_FOLDER") or FOLDER_ID or "").strip()
    if want:
        _ROOT["id"] = folder.folder_id(want)
        return _ROOT["id"]
    mine = auth.api_get(creds, "/drive/v3/files/root?fields=id")["id"]
    fid = (folder.ensure_folder(creds, mine, STORE_NAME) if create
           else folder.find_folder(creds, mine, STORE_NAME))
    if fid:
        _ROOT["id"] = fid
    return fid


def store_id(creds, store, create=False):
    """A store's folder id, or None while it doesn't exist."""
    if store in _STORES:
        return _STORES[store]
    root = root_id(creds, create=create)
    if not root:
        return None
    fid = (folder.ensure_folder(creds, root, store) if create
           else folder.find_folder(creds, root, store))
    if fid:
        _STORES[store] = fid
    return fid


def known_or_die(store):
    """A typo in a store name is an error, not an empty store."""
    if store in KNOWN:
        return store
    raise SystemExit(
        f"::error::The pipeline doesn't know store \"{store}\". They are: "
        f"{', '.join(sorted(KNOWN))}. To add one, write it into KNOWN in "
        f"workers/drive/store.py – otherwise a typo couldn't be told from an "
        f"empty store and the build would silently compute anew.")


def index(creds, store):
    """{name: {id, size, created}} – the NEWEST wins among duplicate names."""
    # a clobber uploads before deleting; the older winning would return old data
    fid = store_id(creds, store)
    if not fid:
        return {}
    files, _skipped = folder.listing(creds, fid, extra="createdTime")
    out = {}
    for f in files:
        raw = f.get("raw") or {}
        item = {"id": f["id"], "size": f["size"],
                "created": raw.get("createdTime") or ""}
        old = out.get(f["name"])
        if old is None or item["created"] > old["created"]:
            if old is not None:
                item["dupes"] = old.get("dupes", []) + [old["id"]]
            out[f["name"]] = item
        else:
            old.setdefault("dupes", []).append(f["id"])
    return out


def latest(items, prefix="", suffix=""):
    """The newest name matching the prefix and suffix – by upload time, not name."""
    hit = [(v["created"], k) for k, v in items.items()
           if k.startswith(prefix) and k.endswith(suffix)]
    return max(hit)[1] if hit else ""


def download(creds, item, dest):
    """A store file to disk, by blocks with `.part` and a rename (see `folder.py`)."""
    pool = drive.Pool(creds=creds)
    progress = folder.Progress(item["size"])
    t0 = time.time()
    folder.fetch(pool, {"id": item["id"], "name": item["name"],
                        "size": item["size"]}, dest, progress)
    el = max(time.time() - t0, 1e-6)
    log(f"  downloaded {item['name']} ({human(item['size'])}) in {el:.0f} s "
        f"({item['size'] / el / 1e6:.1f} MB/s)")


def upload(creds, store, path, name, note="", clobber=True):
    """A file into a store; the same name is overwritten (only after a good upload)."""
    # `clobber=False` skips the lookup for `slope-chunks.py`'s hundreds of new chunks
    fid = store_id(creds, store, create=True)
    size = os.path.getsize(path)
    was = index(creds, store).get(name) if clobber else None
    old_ids = ([was["id"]] + was.get("dupes", [])) if was else []
    t0 = time.time()
    folder.upload(creds, path, name, fid, note or f"{store}/{name}")
    el = max(time.time() - t0, 1e-6)
    log(f"  uploaded {name} ({human(size)}) in {el:.0f} s "
        f"({size / el / 1e6:.1f} MB/s)")
    for old in old_ids:
        auth.api_delete(creds, old)
    if old_ids:
        log(f"  deleted the old version ({len(old_ids)}×)")


def do_check(args):
    """Can this run read and write the store? Cheap, before an hour of work."""
    creds = creds_or_die("checking access")
    who = auth.whoami(creds)
    root = root_id(creds)
    if root:
        log(f"Store on Google Drive, folder {root}")
        log(f"  {folder.folder_link(root)}")
    else:
        log(f"Store on Google Drive: folder \"{STORE_NAME}\" isn't in My Drive "
            f"yet – made at the first save.")
    log(f"  account {who.get('emailAddress', '?')} (details from {creds.source})")
    write = auth.can_write(creds)
    log("  scope   " + {True: "reads and writes ✓",
                        False: "READ ONLY – nothing will save",
                        None: "can't be told"}[write])
    total = 0
    for store in sorted(KNOWN):
        items = index(creds, store)
        size = sum(v["size"] for v in items.values())
        total += size
        log(f"  {store:<14} {len(items):>5} files  {human(size):>10}"
            + ("" if store_id(creds, store) else "   (not yet)"))
    log(f"  {'total':<14} {'':>5}        {human(total):>10}")
    if write is False:
        log(f"::error::{auth.scope_hint()}")
        return 1
    return 0


def do_list(args):
    creds = creds_or_die("listing the store")
    items = index(creds, args.store)
    size = sum(v["size"] for v in items.values())
    log(f"Store {args.store}: {len(items)} files, {human(size)} "
        f"– {KNOWN[args.store]}")
    for name in sorted(items):
        v = items[name]
        log(f"  {v['created'][:19]}  {human(v['size']):>10}  {name}")
    return 0


def do_names(args):
    """Names, one a line – what `gh release view --json assets` did."""
    creds = creds_or_die("listing the store's names")
    for name in sorted(index(creds, args.store)):
        print(name)
    return 0


def do_index(args):
    """`name:size` a line – `check.sh` fingerprints the store for the cache key."""
    creds = creds_or_die("listing the store's content")
    items = index(creds, args.store)
    for name in sorted(items):
        print(f"{name}:{items[name]['size']}")
    return 0


def do_latest(args):
    creds = creds_or_die("looking for the newest file in the store")
    name = latest(index(creds, args.store), args.prefix, args.suffix)
    if not name:
        return 3
    print(name)
    return 0


def do_get(args):
    """The asked names to disk. Returns 3 when NOT ONE was got."""
    # `--missing-ok` is for tiles: the bbox's corners lie outside the country
    creds = creds_or_die("downloading from the store")
    os.makedirs(args.dir, exist_ok=True)
    items = index(creds, args.store)
    if not items:
        log(f"::warning::Store {args.store} has nothing "
            + ("(the folder doesn't exist yet)." if not store_id(creds, args.store)
               else "."))
    got, missing = [], []
    for name in args.name:
        dest = os.path.join(args.dir, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0 and args.skip_local:
            log(f"  {name} is on disk already – not downloading")
            got.append(name)
            continue
        if name not in items:
            missing.append(name)
            continue
        item = dict(items[name], name=name)
        try:
            download(creds, item, dest)
        except (RuntimeError, OSError) as exc:
            log(f"::warning::{name} couldn't be downloaded from store "
                f"{args.store} ({exc}).")
            missing.append(name)
            continue
        got.append(name)
    if missing:
        log(f"  not in store {args.store}: {' '.join(missing)}")
    log(f"From store {args.store}: {len(got)} of {len(args.name)} files")
    if not got:
        return 3
    return 0 if (not missing or args.missing_ok) else 3


def do_put(args):
    creds = creds_or_die("saving to the store")
    # THE SCOPE IS ASKED BEFORE UPLOADING, or a gigabyte is sent for nothing
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::Nothing was saved to store {args.store}: "
                         f"{auth.scope_hint()}")
    log(f"Store {args.store}: saving {len(args.file)} files")
    for i, path in enumerate(args.file):
        if not os.path.exists(path):
            raise SystemExit(f"::error::{path} doesn't exist – nothing to save.")
        name = args.name[i] if i < len(args.name) else os.path.basename(path)
        upload(creds, args.store, path, name, args.note)
    return 0


def do_rm(args):
    """Delete a file by name (duplicates too), so a rebuild doesn't take the old one."""
    creds = creds_or_die("deleting from the store")
    items = index(creds, args.store)
    n = 0
    for name in args.name:
        v = items.get(name)
        if v is None:
            log(f"  wasn't in store {args.store}: {name}")
            continue
        for fid in [v["id"]] + v.get("dupes", []):
            if args.dry_run:
                log(f"  would delete: {name} ({human(v['size'])})")
            else:
                auth.api_delete(creds, fid)
                log(f"  deleted: {name} ({human(v['size'])})")
            n += 1
    return 0


def do_prune(args):
    """Thin one store by age; no default store, DEM tiles are costly mirrors."""
    creds = creds_or_die("thinning the store")
    items = index(creds, args.store)
    size = sum(v["size"] for v in items.values())
    log(f"Store {args.store}: {len(items)} files, {human(size)}")
    limit = time.time() - args.keep_days * 86400
    doomed = [(n, v) for n, v in sorted(items.items())
              if args.keep_days > 0 and v["created"]
              and _epoch(v["created"]) < limit]
    freed = sum(v["size"] for _, v in doomed)
    log(f"To delete: {len(doomed)} files older than {args.keep_days:g} "
        f"days, {human(freed)}")
    for name, v in doomed:
        log(f"  {v['created'][:19]}  {human(v['size']):>10}  {name}")
    if args.dry_run:
        log("Listing only, nothing deleted.")
    else:
        for _name, v in doomed:
            for fid in [v["id"]] + v.get("dupes", []):
                auth.api_delete(creds, fid)
        log(f"Deleted {len(doomed)} files, freed {human(freed)}")
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(f"### Store `{args.store}` on Drive\n\n")
            f.write("| item | value |\n|---|--:|\n")
            f.write(f"| files before | {len(items)} |\n")
            f.write(f"| size before | {human(size)} |\n")
            f.write(f"| {'to delete' if args.dry_run else 'deleted'} "
                    f"| {len(doomed)} |\n")
            f.write(f"| {'would be freed' if args.dry_run else 'freed'} "
                    f"| {human(freed)} |\n")
            f.write(f"| left | {human(size - freed)} |\n\n")
    return 0


def _epoch(stamp):
    """RFC 3339 from Drive → seconds (UTC, hence `timegm`); unknown = leave it."""
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return time.time()


def lines(values):
    """`--name` and `--file` repeated AND as lines or a space-split list in one value."""
    out = []
    for v in values or []:
        for line in v.splitlines():
            out += line.split()
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--names", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--get", action="store_true")
    ap.add_argument("--put", action="store_true")
    ap.add_argument("--rm", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--store", default="", help="which store (see KNOWN)")
    ap.add_argument("--name", action="append", default=[],
                    help="a file name in the store; repeatable")
    ap.add_argument("--file", action="append", default=[],
                    help="what to upload; repeatable")
    ap.add_argument("--dir", default=".", help="where to download to")
    ap.add_argument("--prefix", default="", help="with --latest")
    ap.add_argument("--suffix", default="", help="with --latest")
    ap.add_argument("--note", default="", help="the file's description on Drive")
    ap.add_argument("--missing-ok", action="store_true",
                    help="with --get: a missing name is a warning, not an error")
    ap.add_argument("--skip-local", action="store_true",
                    help="with --get: don't download what is on disk already")
    ap.add_argument("--keep-days", type=float, default=90,
                    help="with --prune: older goes (0 = never)")
    ap.add_argument("--dry-run", action="store_true",
                    help="only print what would happen")
    ap.add_argument("--summary", default="",
                    help="with --prune: where to append the summary (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()
    args.name = lines(args.name)
    args.file = lines(args.file)

    commands = [k for k in ("check", "list", "names", "index", "latest",
                            "get", "put", "rm", "prune") if getattr(args, k)]
    if len(commands) != 1:
        ap.error("say exactly one thing: --check / --list / --names / "
                 "--index / --latest / --get / --put / --rm / --prune")
    if commands[0] != "check":
        if not args.store:
            ap.error("--store is required")
        known_or_die(args.store)
    if args.get and not args.name:
        ap.error("--get needs at least one --name")
    if args.put and not args.file:
        ap.error("--put needs at least one --file")
    if args.rm and not args.name:
        ap.error("--rm needs at least one --name")

    try:
        return {"check": do_check, "list": do_list, "names": do_names,
                "index": do_index, "latest": do_latest, "get": do_get,
                "put": do_put, "rm": do_rm, "prune": do_prune}[commands[0]](args)
    except auth.AuthError as exc:
        # those messages already say what to do
        print(f"::error::{exc}")
        return 1
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
