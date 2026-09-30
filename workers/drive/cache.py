#!/usr/bin/env python3
"""The build cache on Google Drive – a stand-in for `actions/cache`.

GitHub's cache holds 10 GB a repository and silently drops the oldest; this
pipeline stores tens of GB a cut-out. The semantics stay: `cache-hit` only on
an exact key, `restore-keys` are prefixes taking the newest, an existing key
isn't overwritten.

One entry = one `.tar.zst` in `FOLDER_ID` named by its key; the whole key is in
`description` too, since the name replaces characters outside `[A-Za-z0-9._-]`.
Nothing deletes itself – the weekly `--prune` thins it at two speeds.

    python3 workers/drive/cache.py --check | --list
    python3 workers/drive/cache.py --restore --key=abc --path=dem
    python3 workers/drive/cache.py --lookup --key=abc --restore-keys=ab
    python3 workers/drive/cache.py --save --key=abc --path=dem
    python3 workers/drive/cache.py --prune --keep-days=30 --keep-gb=100
"""
import argparse
import calendar
import importlib.util
import os
import shutil
import subprocess
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


# sign-in, the HTTP pool and folder listing/download are borrowed whole
drive = load("drive_serve", "serve.py")
auth = load("drive_auth", "auth.py")
folder = load("drive_folder", "folder.py")

# the cache folder on Drive; the id is no secret, the owner's token is
FOLDER_ID = "15-Z37buVADUk9_-RMWAQp6arqqjPdRaV"

# FINISHED LAYERS FROM THE ELEVATION MODEL are hours of work a region and asked for
# months later (`workers/plan/cache-keys.sh`), so they live longer and go LAST
LAYERS = ("contours-", "rocks-", "terrain-")


def is_layer(key):
    """Is it a finished layer (the expensive kind worth keeping longer)?"""
    return key.startswith(LAYERS)


# two suffixes: `zstd` may be missing somewhere, unpacked by what the name says
ZSTD = ".tar.zst"
GZIP = ".tar.gz"
SUFFIXES = (ZSTD, GZIP)


def human(n):
    return folder.human(n)


def log(msg):
    print(msg, flush=True)


def safe(key):
    """Key → file name, character for character so a prefix stays a prefix."""
    return "".join(c if (c.isalnum() and c.isascii()) or c in "._-" else "_"
                   for c in key)


def entry_key(name):
    """File name → key (without suffix), or None when it isn't an entry."""
    for suf in SUFFIXES:
        if name.endswith(suf):
            return name[:-len(suf)]
    return None


def creds_or_die(what):
    """Sign-in, or exit with advice; a silent cache miss is the costliest mistake."""
    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            f"::error::The Drive cache needs a sign-in ({what}), but the "
            "environment has no owner token. Add the secret GDRIVE_CREDENTIALS "
            "(or the variable DRIVE_CLIENT and secrets DRIVE_SECRET / "
            "DRIVE_REFRESH) and pass it to the job through `env:` – the "
            "workflow \"Maintenance · Drive sign-in\" makes them.")
    return creds


def entries(creds):
    """Cache entries in the folder, newest first; files without a suffix are left alone."""
    files, _skipped = folder.listing(creds, FOLDER_ID,
                                     extra="createdTime,description")
    out = []
    for f in files:
        key = entry_key(f["name"])
        if key is None:
            continue
        raw = f.get("raw") or {}
        out.append({"id": f["id"], "name": f["name"], "key": key,
                    "full_key": raw.get("description") or key,
                    "size": f["size"], "created": raw.get("createdTime") or ""})
    out.sort(key=lambda e: e["created"], reverse=True)
    return out


def find(items, key, restore_keys):
    """(entry, exact match?) by the `actions/cache` rules, on the FULL key."""
    # the exact key first, then prefixes in order, the newest per prefix
    exact = [e for e in items if e["full_key"] == key]
    if exact:
        return exact[0], True
    for prefix in restore_keys:
        hit = [e for e in items if e["full_key"].startswith(prefix)]
        if hit:
            return hit[0], False
    return None, False


def have(cmd):
    return shutil.which(cmd) is not None


def pack(paths, dest):
    """Pack paths (relative to the work dir) into one archive; missing ones are said."""
    present = [p for p in paths if os.path.exists(p)]
    for p in paths:
        if p not in present:
            log(f"  ({p} isn't in the work dir – leaving it out)")
    if not present:
        raise SystemExit("::error::Not one of the paths exists – nothing to "
                         "save. (The calling step should guard it with `hashFiles`.)")
    cmd = ["tar", "--zstd" if dest.endswith(ZSTD) else "-z", "-cf", dest, *present]
    t0 = time.time()
    subprocess.run(cmd, check=True)
    log(f"  packed {', '.join(present)} → {human(os.path.getsize(dest))} "
        f"in {time.time() - t0:.0f} s")
    return present


def unpack(src):
    """Unpack an archive into the work dir."""
    t0 = time.time()
    subprocess.run(["tar", "--zstd" if src.endswith(ZSTD) else "-z", "-xf", src],
                   check=True)
    log(f"  unpacked in {time.time() - t0:.0f} s")


def download(creds, item, dest):
    """An entry from Drive to disk, by blocks through `folder.py`."""
    pool = drive.Pool(creds=creds)
    progress = folder.Progress(item["size"])
    t0 = time.time()
    folder.fetch(pool, {"id": item["id"], "name": item["name"],
                        "size": item["size"]}, dest, progress)
    el = max(time.time() - t0, 1e-6)
    log(f"  downloaded {human(item['size'])} in {el / 60:.1f} min "
        f"({item['size'] / el / 1e6:.1f} MB/s)")


def out(name, value):
    """A step output – the same names as `actions/cache`."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")
    log(f"  {name}={value}")


def do_restore(args):
    creds = creds_or_die("looking for a cache entry")
    items = entries(creds)
    hit, exact = find(items, args.key, args.restore_keys)
    out("cache-primary-key", args.key)
    if hit is None:
        log(f"Drive cache: nothing for `{args.key}`"
            + (f" nor for prefixes {args.restore_keys}" if args.restore_keys
               else "")
            + f" ({len(items)} entries in the folder)")
        out("cache-hit", "false")
        out("cache-matched-key", "")
        return 0
    # a prefix match takes something not made with today's key – a `::notice::`
    if exact:
        log(f"Drive cache: exact match – {hit['name']} "
            f"({human(hit['size'])}, {hit['created'][:19]})")
    else:
        log(f"::notice::Drive cache: prefix match – taking "
            f"`{hit['full_key']}` ({human(hit['size'])}, "
            f"{hit['created'][:19]}) instead of `{args.key}`.")
    tmp = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"),
                       "drive-cache-" + os.path.basename(hit["name"]))
    # AN UNUSABLE ENTRY MUST NOT BLOCK THE BUILD: warn, recompute, delete a broken one
    try:
        download(creds, hit, tmp)
    except (RuntimeError, OSError) as exc:
        print(f"::warning::Entry `{hit['name']}` couldn't be downloaded "
              f"({exc}) – computing anew.")
        _clean(tmp)
        out("cache-hit", "false")
        out("cache-matched-key", "")
        return 0
    try:
        unpack(tmp)
    except subprocess.CalledProcessError as exc:
        print(f"::warning::Entry `{hit['name']}` can't be unpacked ({exc}) – "
              f"deleting it and computing anew.")
        auth.api_delete(creds, hit["id"])
        _clean(tmp)
        out("cache-hit", "false")
        out("cache-matched-key", "")
        return 0
    _clean(tmp)
    out("cache-hit", "true" if exact else "false")
    out("cache-matched-key", hit["full_key"])
    return 0


def do_lookup(args):
    """Is there an entry for the key or a prefix? Downloads nothing."""
    creds = creds_or_die("looking for a cache entry")
    hit, exact = find(entries(creds), args.key, args.restore_keys)
    out("cache-hit", "true" if exact else "false")
    out("cache-matched-key", hit["full_key"] if hit else "")
    log(f"Drive cache: {hit['full_key'] if hit else 'nothing'} for `{args.key}`")
    return 0


def _clean(tmp):
    """The downloaded archive after itself – a half-done `.part` too."""
    for p in (tmp, tmp + ".part"):
        if os.path.exists(p):
            os.remove(p)


def do_save(args):
    creds = creds_or_die("saving the cache")
    # THE SCOPE IS ASKED BEFORE PACKING: a readonly token would fail only after packing 500 MB
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::Saving cache `{args.key}` to Drive wasn't "
                         f"even tried: {auth.scope_hint()}")
    items = entries(creds)
    hit, exact = find(items, args.key, [])
    if exact:
        # as on GitHub, an existing key isn't overwritten; refillable keys carry a run number
        log(f"Drive cache: `{args.key}` is already there "
            f"({human(hit['size'])}, {hit['created'][:19]}) – not saving.")
        return 0
    name = safe(args.key) + (ZSTD if have("zstd") else GZIP)
    tmp = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), name)
    log(f"Drive cache: saving `{args.key}`")
    try:
        pack(args.path, tmp)
        size = os.path.getsize(tmp)
        t0 = time.time()
        folder.upload(creds, tmp, name, FOLDER_ID, args.key)
        el = max(time.time() - t0, 1e-6)
        log(f"  uploaded {human(size)} in {el / 60:.1f} min "
            f"({size / el / 1e6:.1f} MB/s)")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        # loud: an unsaved cache costs the next run hours; the step has `continue-on-error`
        raise SystemExit(f"::error::Saving cache `{args.key}` to Drive "
                         f"failed: {exc}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return 0


def do_delete(args):
    """Delete an entry by exact key (duplicates too), so a rebuild can save anew."""
    creds = creds_or_die("deleting a cache entry")
    doomed = [e for e in entries(creds) if e["full_key"] == args.key]
    if not doomed:
        log(f"wasn't in the cache: {args.key}")
        return 0
    for e in doomed:
        if args.dry_run:
            log(f"would delete: {e['name']} ({human(e['size'])})")
            continue
        auth.api_delete(creds, e["id"])
        log(f"deleted: {e['name']} ({human(e['size'])})")
    return 0


def do_list(args):
    creds = creds_or_die("listing the cache")
    items = entries(creds)
    total = sum(e["size"] for e in items)
    log(f"Drive cache ({FOLDER_ID}): {len(items)} entries, {human(total)}")
    for e in items:
        log(f"  {e['created'][:19]}  {human(e['size']):>9}  {e['full_key']}")
    return 0


def do_prune(args):
    """Thinning: duplicates first, then age, the cap last, oldest first."""
    creds = creds_or_die("thinning the cache")
    items = entries(creds)
    total = sum(e["size"] for e in items)
    log(f"Drive cache ({FOLDER_ID}): {len(items)} entries, {human(total)}")

    doomed, reason = [], {}

    def mark(e, why):
        if e["id"] not in reason:
            doomed.append(e)
            reason[e["id"]] = why

    seen = set()
    for e in items:                      # newest first
        if e["key"] in seen:
            mark(e, "duplicate (a newer entry with the same key exists)")
        seen.add(e["key"])

    # AGE: finished layers have a longer limit of their own
    for e in items:
        days = args.keep_days_layers if is_layer(e["full_key"]) else args.keep_days
        if days <= 0 or not e["created"]:
            continue
        if _epoch(e["created"]) < time.time() - days * 86400:
            mark(e, f"older than {days:g} days"
                    + (" (finished layer)" if is_layer(e["full_key"]) else ""))

    if args.keep_gb > 0:
        cap = args.keep_gb * 1e9
        kept = 0
        # keeping order: finished layers first, what can be fetched again is sacrificed
        by_cost = ([e for e in items if is_layer(e["full_key"])]
                   + [e for e in items if not is_layer(e["full_key"])])
        for e in by_cost:
            if e["id"] in reason:
                continue
            kept += e["size"]
            if kept > cap:
                mark(e, f"over the {args.keep_gb:g} GB cap")

    freed = sum(e["size"] for e in doomed)
    log(f"To delete: {len(doomed)} entries, {human(freed)}")
    for e in doomed:
        log(f"  {e['created'][:19]}  {human(e['size']):>9}  {e['full_key']} "
            f"– {reason[e['id']]}")
    if args.dry_run:
        log("Listing only, nothing deleted.")
    else:
        for e in doomed:
            auth.api_delete(creds, e["id"])
        log(f"Deleted {len(doomed)} entries, freed {human(freed)}")

    if args.summary:
        with open(args.summary, "a") as f:
            f.write("### Drive cache\n\n")
            f.write(f"Finished layers (contours, rocks, hillshading) are kept "
                    f"{args.keep_days_layers:g} days, the rest "
                    f"{args.keep_days:g}.\n\n")
            f.write("| item | value |\n|---|--:|\n")
            f.write(f"| entries before | {len(items)} |\n")
            f.write(f"| size before | {human(total)} |\n")
            f.write(f"| {'to delete' if args.dry_run else 'deleted'} "
                    f"| {len(doomed)} |\n")
            f.write(f"| {'would be freed' if args.dry_run else 'freed'} "
                    f"| {human(freed)} |\n")
            f.write(f"| left | {human(total - freed)} |\n\n")
    return 0


def _epoch(stamp):
    """RFC 3339 from Drive → seconds (UTC, hence `timegm`); unknown = leave it."""
    try:
        return calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return time.time()


def do_check(args):
    """Can this run read and write the cache? Cheap, before an hour of work."""
    creds = creds_or_die("checking access")
    who = auth.whoami(creds)
    print(f"Cache on Google Drive, folder {FOLDER_ID}")
    print(f"  account {who.get('emailAddress', '?')} (details from {creds.source})")
    write = auth.can_write(creds)
    print("  scope   " + {True: "reads and writes ✓",
                          False: "READ ONLY – nothing will save",
                          None: "can't be told"}[write])
    info = auth.api_get(creds, f"/drive/v3/files/{FOLDER_ID}"
                               "?fields=id,name,ownedByMe,capabilities("
                               "canAddChildren,canListChildren)"
                               "&supportsAllDrives=true")
    caps = info.get("capabilities") or {}
    print(f"  folder  \"{info.get('name', '?')}\" – "
          f"{'own' if info.get('ownedByMe') else 'someone else’s'}, "
          f"adding {'yes' if caps.get('canAddChildren') else 'NO'}")
    items = entries(creds)
    print(f"  content {len(items)} entries, "
          f"{human(sum(e['size'] for e in items))}")
    quota = auth.api_get(creds, "/drive/v3/about?fields=storageQuota(limit,usage)")
    q = quota.get("storageQuota") or {}
    if q.get("limit"):
        print(f"  account {human(int(q.get('usage', 0)))} of "
              f"{human(int(q['limit']))}")
    if write is False or not caps.get("canAddChildren"):
        print(f"::error::{auth.scope_hint()}")
        return 1
    return 0


def lines(values):
    """`--path` repeated AND as several lines in one value (`path: |` passes through)."""
    out_ = []
    for v in values or []:
        out_ += [line.strip() for line in v.splitlines() if line.strip()]
    return out_


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--lookup", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--key", default="", help="the entry key")
    ap.add_argument("--path", action="append", default=[],
                    help="what is packed; repeatable, or one per line")
    ap.add_argument("--restore-keys", action="append", default=[],
                    help="prefixes searched when the key doesn't match")
    ap.add_argument("--keep-days", type=float, default=30,
                    help="with --prune: older goes (0 = never)")
    ap.add_argument("--keep-days-layers", type=float, default=180,
                    help="with --prune: the same for finished layers (contours, "
                         "rocks, hillshading) – hours of work, asked for months later")
    ap.add_argument("--keep-gb", type=float, default=100,
                    help="with --prune: a cap on the whole folder (0 = none)")
    ap.add_argument("--dry-run", action="store_true",
                    help="only print what would happen")
    ap.add_argument("--summary", default="",
                    help="with --prune: where to append the summary (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()
    args.path = lines(args.path)
    args.restore_keys = lines(args.restore_keys)

    if (args.restore or args.lookup or args.save or args.delete) and not args.key:
        ap.error("--key is required")
    if args.save and not args.path:
        ap.error("--save needs at least one --path")

    try:
        if args.check:
            return do_check(args)
        if args.list:
            return do_list(args)
        if args.prune:
            return do_prune(args)
        if args.restore:
            return do_restore(args)
        if args.lookup:
            return do_lookup(args)
        if args.save:
            return do_save(args)
        if args.delete:
            return do_delete(args)
    except auth.AuthError as exc:
        # those messages already say what to do
        print(f"::error::{exc}")
        return 1
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return 1
    ap.error("say what to do: --restore / --lookup / --save / --delete / --list / "
             "--prune / --check")


if __name__ == "__main__":
    sys.exit(main())
