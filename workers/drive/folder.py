#!/usr/bin/env python3
"""A Google Drive folder – what is in it, download from it, upload to it.

Everything signed in through the Drive API: an anonymous `gdown` hit the public
link's daily cap. The cap is tied to the OWNER, so a shared foreign folder
(Sonny) keeps it – hence every file says whether this account owns it. The unit
of work is a FILE: a finished one is skipped, a half one resumed from `.part`.

Usage:
    python3 workers/drive/folder.py --mode
    python3 workers/drive/folder.py --folder=<URL or id> --list
    python3 workers/drive/folder.py --folder=<URL or id> --out=dl
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse

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


# sign-in (`auth.py`) and token-renewing connections (`serve.py`) live elsewhere
drive = load("drive_serve", "serve.py")
auth = load("drive_auth", "auth.py")

FOLDER_MIME = "application/vnd.google-apps.folder"

# a shortcut only points elsewhere; no `size`, and Sonny's folder is all shortcuts
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# big enough for request overhead, small enough to resume a cancelled run
CHUNK = 16 * 1024 * 1024

# a starting estimate until measured; the script prints the measured MB/s
EST_MB_S = 20.0

# endless recursion in someone else's data is a bad idea
MAX_DEPTH = 5


def folder_id(text):
    """A folder id from a URL or a bare id."""
    text = (text or "").strip()
    if not text:
        raise SystemExit("::error::--folder is missing (a folder URL or its id).")
    m = re.search(r"/folders/([-\w]{10,})", text)
    if m:
        return m.group(1)
    parts = urllib.parse.urlsplit(text)
    if parts.query:
        got = urllib.parse.parse_qs(parts.query).get("id")
        if got:
            return got[0]
    if re.fullmatch(r"[-\w]{10,}", text):
        return text
    raise SystemExit(f"::error::No Drive folder id can be read from \"{text}\". "
                     f"Expecting a link like "
                     f"https://drive.google.com/drive/folders/<id> or an id.")


def resolve_shortcut(creds, f, rel):
    """Shortcut → the file it points to. Returns `(item, reason skipped)`."""
    # the shortcut's name stays – a tile name promises an extent, a differing target is said
    det = f.get("shortcutDetails") or {}
    tid = det.get("targetId")
    if not tid:
        return f, (f"{rel} (a shortcut without a target – deleted or "
                   f"inaccessible to this account)")
    if det.get("targetMimeType") == FOLDER_MIME:
        return dict(f, id=tid, mimeType=FOLDER_MIME), ""
    try:
        target = auth.file_info(creds, tid)
    except Exception as exc:                        # noqa: BLE001
        return f, f"{rel} (the shortcut target {tid} can't be asked for: {exc})"
    if target.get("name") and target["name"] != f.get("name"):
        print(f"::warning::Shortcut \"{rel}\" points to a file of another "
              f"name \"{target['name']}\". A tile's name promises which area "
              f"it holds – check it really is that tile, or leave the folder "
              f"out.", flush=True)
    # `size`, `ownedByMe` and id from the target: the cap hangs on the target's owner
    return dict(f, id=tid, size=target.get("size"),
                ownedByMe=target.get("ownedByMe"),
                mimeType=target.get("mimeType", ""), shortcutDetails=det), ""


def listing(creds, fid, depth=0, prefix="", extra=""):
    """Files in a folder (subfolders too) by name, as `{id, name, path, size, owned, raw}`."""
    # Google-native documents are skipped; shortcuts are resolved here; `extra` goes into `raw`
    out, skipped, token = [], [], ""
    while True:
        q = urllib.parse.quote(f"'{fid}' in parents and trashed = false")
        path = (f"/drive/v3/files?q={q}&pageSize=1000&orderBy=folder,name"
                f"&supportsAllDrives=true&includeItemsFromAllDrives=true"
                f"&fields=nextPageToken,files(id,name,size,mimeType,ownedByMe,"
                f"shortcutDetails(targetId,targetMimeType)"
                + (f",{extra}" if extra else "") + ")")
        if token:
            path += "&pageToken=" + urllib.parse.quote(token)
        data = auth.api_get(creds, path)
        for f in data.get("files") or []:
            name = f.get("name") or f["id"]
            rel = f"{prefix}{name}"
            if f.get("mimeType") == SHORTCUT_MIME:
                f, problem = resolve_shortcut(creds, f, rel)
                if problem:
                    skipped.append(problem)
                    continue
            if f.get("mimeType") == FOLDER_MIME:
                if depth >= MAX_DEPTH:
                    skipped.append(f"{rel}/ (nested deeper than {MAX_DEPTH})")
                    continue
                sub, sub_skipped = listing(creds, f["id"], depth + 1, rel + "/",
                                           extra)
                out += sub
                skipped += sub_skipped
                continue
            if f.get("size") is None:
                skipped.append(f"{rel} ({f.get('mimeType', '?')})")
                continue
            out.append({"id": f["id"], "name": name, "path": rel,
                        "size": int(f["size"]), "owned": bool(f.get("ownedByMe")),
                        "raw": f})
        token = data.get("nextPageToken") or ""
        if not token:
            return out, skipped


def human(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


class Progress:
    """A download heartbeat: whole lines every `every` s (Actions hides `\\r`)."""

    def __init__(self, total, every=30):
        self.total = total
        self.every = every
        self.done = 0
        self.t0 = time.time()
        self.last = self.t0

    def add(self, n, label):
        self.done += n
        now = time.time()
        if now - self.last < self.every:
            return
        self.last = now
        rate = self.done / max(now - self.t0, 1e-6)
        line = (f"    [{(now - self.t0) / 60:5.1f} min] {label}: "
                f"{human(self.done)} of {human(self.total)} "
                f"({rate / 1e6:.1f} MB/s)")
        # near-zero speed would give thousands of minutes – worse than nothing
        if rate > 1e5 and self.done < self.total:
            line += f", ~{(self.total - self.done) / rate / 60:.0f} min left"
        print(line, flush=True)


def fetch(pool, item, dest, progress):
    """One file into `dest`; skips a finished one, resumes a half one (via `.part`)."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == item["size"]:
        progress.done += item["size"]
        print(f"    done by an earlier run ({human(item['size'])})", flush=True)
        return 0
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have > item["size"]:                 # a foreign leftover or a changed file
        have = 0
    if have:
        print(f"    resuming from {human(have)}", flush=True)
        progress.done += have
    got = 0
    with open(part, "r+b" if have else "wb") as f:
        f.seek(have)
        f.truncate(have)
        while have < item["size"]:
            end = min(have + CHUNK, item["size"]) - 1
            want = end - have + 1
            _, _, body = pool.get(item["id"], f"bytes={have}-{end}", want=want)
            f.write(body)
            have += len(body)
            got += len(body)
            progress.add(len(body), item["name"])
    os.replace(part, dest)
    return got


# the other way: folders and uploads; Google wants a multiple of 256 KiB
UPLOAD_CHUNK = 32 * 1024 * 1024

# Drive's transient states: retried from where the session stopped
RETRY_STATUS = (408, 429, 500, 502, 503, 504)

UPLOAD_PATH = ("/upload/drive/v3/files?uploadType=resumable"
               "&supportsAllDrives=true&fields=id,name,size")


def find_folder(creds, parent, name):
    """The id of subfolder `name` in `parent`, or None."""
    q = urllib.parse.quote(
        f"'{parent}' in parents and trashed = false and "
        f"mimeType = '{FOLDER_MIME}' and name = '{name}'")
    data = auth.api_get(creds, f"/drive/v3/files?q={q}&pageSize=10"
                               f"&supportsAllDrives=true"
                               f"&includeItemsFromAllDrives=true"
                               f"&fields=files(id,name)")
    files = data.get("files") or []
    return files[0]["id"] if files else None


def files_named(creds, parent, name):
    """Files named `name` in a folder – Drive allows duplicates."""
    q = urllib.parse.quote(
        f"'{parent}' in parents and trashed = false and name = '{name}'")
    data = auth.api_get(creds, f"/drive/v3/files?q={q}&pageSize=100"
                               f"&supportsAllDrives=true"
                               f"&includeItemsFromAllDrives=true"
                               f"&fields=files(id,name,size,mimeType,createdTime)")
    return [f for f in (data.get("files") or [])
            if f.get("mimeType") != FOLDER_MIME]


def ids_in(creds, parent):
    """`{id: name}` of files in a folder now, shallow – does a catalog link still live?"""
    out, token = {}, ""
    while True:
        q = urllib.parse.quote(f"'{parent}' in parents and trashed = false")
        path = (f"/drive/v3/files?q={q}&pageSize=1000"
                f"&supportsAllDrives=true&includeItemsFromAllDrives=true"
                f"&fields=nextPageToken,files(id,name,mimeType)")
        if token:
            path += "&pageToken=" + urllib.parse.quote(token)
        data = auth.api_get(creds, path)
        for f in data.get("files") or []:
            if f.get("mimeType") == FOLDER_MIME:
                continue
            out[f["id"]] = f.get("name") or f["id"]
        token = data.get("nextPageToken") or ""
        if not token:
            return out


def id_from_link(url):
    """A file id from a link as `file_link` / `download_link` write it, else ""."""
    text = (url or "").strip()
    if "/file/d/" in text:
        return text.split("/file/d/", 1)[1].split("/", 1)[0].split("?", 1)[0]
    if "id=" in text:
        return text.split("id=", 1)[1].split("&", 1)[0]
    return ""


def upload_clobber(creds, path, name, parent, description=""):
    """Upload a package as `name`, keeping the id it had (the catalog's link)."""
    # PATCH keeps the id; the oldest is overwritten, duplicates deleted;
    # returns `(file id, how many files of the name were there)`
    old = files_named(creds, parent, name)
    old.sort(key=lambda f: f.get("createdTime") or "")
    if old:
        fid = old[0]["id"]
        update(creds, path, fid, name, description)
        extra = [f["id"] for f in old[1:]]
    else:
        fid = upload(creds, path, name, parent, description)
        extra = []
    for duplicate in extra:
        auth.api_delete(creds, duplicate)
    if extra:
        print(f"    deleted a duplicate of the name ({len(extra)}×)",
              flush=True)
    return fid, len(old)


def file_link(fid):
    """A link to a file – one to send a person (seen by who has access)."""
    return f"https://drive.google.com/file/d/{fid}/view"


def download_link(fid):
    """A link downloading the file directly (Drive asks to confirm big ones)."""
    return f"https://drive.google.com/uc?export=download&id={fid}"


def delete_named(creds, parent, name):
    """Delete files of a name – "this build doesn't have it"."""
    old = files_named(creds, parent, name)
    for f in old:
        auth.api_delete(creds, f["id"])
    return len(old)


def ensure_folder(creds, parent, name):
    """Subfolder `name` in `parent` – found, or made (Drive allows twins). Returns the id."""
    hit = find_folder(creds, parent, name)
    if hit:
        return hit
    data = auth.api_call(creds, "POST",
                         "/drive/v3/files?supportsAllDrives=true&fields=id,name",
                         {"name": name, "mimeType": FOLDER_MIME,
                          "parents": [parent]})
    print(f"    folder \"{name}\" made", flush=True)
    return data["id"]


def ensure_path(creds, root, parts):
    """A folder path under `root` (making what is missing). Returns the last id."""
    fid = root
    for part in parts:
        fid = ensure_folder(creds, fid, part)
    return fid


def folder_link(fid):
    return f"https://drive.google.com/drive/folders/{fid}"


def upload(creds, path, name, parent, description="", tries=4):
    """A file to Drive by resumable upload (survives a network drop). Returns the id."""
    size = os.path.getsize(path)
    meta = json.dumps({"name": name, "parents": [parent], **_meta(description)})
    return _send(creds, path, size, name,
                 _session(creds, meta, size, "POST", UPLOAD_PATH), tries)


def update(creds, path, fid, name="", description="", tries=4):
    """Overwrite an existing file's content – id, name and sharing stay (PATCH)."""
    size = os.path.getsize(path)
    meta = json.dumps(_meta(description))
    return _send(creds, path, size, name or fid,
                 _session(creds, meta, size, "PATCH", _update_path(fid)),
                 tries)


def _meta(description):
    """Metadata a package carries – the same on upload and overwrite."""
    return {
        # `appProperties` cap a value at 124 B, cache keys are longer
        "description": description,
        "appProperties": {
            "repo": os.environ.get("GITHUB_REPOSITORY", ""),
            "run": os.environ.get("GITHUB_RUN_ID", "")},
    }


def _update_path(fid):
    return (f"/upload/drive/v3/files/{urllib.parse.quote(fid)}"
            f"?uploadType=resumable&supportsAllDrives=true"
            f"&fields=id,name,size")


def _session(creds, meta, size, method, path):
    """Open a resumable session and return `(host, path)` for sending blocks."""
    headers = _post_session(creds, meta, size, method, path)
    loc = headers.get("Location")
    if not loc:
        raise RuntimeError("Drive returned no upload address (Location)")
    parts = urllib.parse.urlsplit(loc)
    return parts.netloc, parts.path + (("?" + parts.query) if parts.query else "")


def _send(creds, path, size, name, session, tries):
    """Send a file in blocks into an open session. Returns the id."""
    host, upath = session
    progress = Progress(size)
    sent = 0
    attempt = 0
    with open(path, "rb") as f:
        while sent < size:
            f.seek(sent)
            body = f.read(min(UPLOAD_CHUNK, size - sent))
            end = sent + len(body) - 1
            try:
                status, headers, _ = _put_chunk(host, upath, body, sent, end,
                                                size, creds)
            except Exception as exc:                # noqa: BLE001
                attempt += 1
                if attempt >= tries:
                    raise RuntimeError(
                        f"The Drive upload failed on all {tries} tries "
                        f"({exc}). {human(sent)} of {human(size)} are saved.")
                sent, fid = _after_drop(host, upath, size, creds, sent,
                                        attempt, str(exc))
                if fid:
                    return fid
                continue
            if status in (200, 201):
                progress.add(len(body), name)
                return json.loads(headers["_body"] or b"{}").get("id", "")
            if status == 308:
                sent = _resume_from(headers, sent + len(body))
                progress.add(len(body), name)
                attempt = 0
                continue
            if status in (401, 403) and attempt < tries:
                # replace an expired token and try the same block again
                attempt += 1
                creds.renew(None)
                continue
            if status in RETRY_STATUS:
                attempt += 1
                if attempt >= tries:
                    raise RuntimeError(
                        f"{_upload_error(status, headers, name)} – on all "
                        f"{tries} tries. {human(sent)} of {human(size)} "
                        f"are saved.")
                sent, fid = _after_drop(host, upath, size, creds, sent,
                                        attempt, f"HTTP {status}")
                if fid:
                    return fid
                continue
            raise RuntimeError(_upload_error(status, headers, name))
    raise RuntimeError("Drive didn't finish the upload – the last block got "
                       "no 200/201 answer.")


def _after_drop(host, upath, size, creds, sent, attempt, why):
    """Wait and ask Drive how much it has. Returns `(from where, id if finished)`."""
    print(f"  ({why}) – trying again, try {attempt}", flush=True)
    time.sleep(min(2 ** attempt, 20))
    # only Drive knows how much it has; a repeated block is dropped
    try:
        return _uploaded(host, upath, size, creds)
    except Exception as exc:                        # noqa: BLE001
        print(f"  (Drive didn't say how much it has: {exc})", flush=True)
        return sent, None


def _upload_error(status, headers, where):
    body = headers.get("_body") or b""
    reason = drive.api_error(body)
    if status == 403 and "insufficient" in str(reason or "").lower():
        return auth.scope_hint(str(reason))
    if status == 403:
        return (f"Drive refused the write ({reason or f'HTTP {status}'}) for "
                f"\"{where}\". Most often the account's disk is full or the "
                f"right is read-only.")
    detail = f" ({reason})" if reason else ""
    return f"Drive returned HTTP {status} while uploading{detail}"


def _request(host, method, path, body, headers, timeout=300):
    """One request; the answer body is returned in the headers under `_body`."""
    conn = drive.connect(host, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        head = dict(resp.headers)
        head["_body"] = raw
        return resp.status, head, raw
    finally:
        try:
            conn.close()
        except Exception:                           # noqa: BLE001
            pass


def _post_session(creds, meta, size, method="POST", path=UPLOAD_PATH):
    """Open an upload session; returns the answer headers (with `Location`)."""
    # `POST` makes a new file, `PATCH` overwrites one; a 401 renews the token once
    last = 4
    for attempt in range(last + 1):
        status, head, _ = _request(
            auth.API_HOST, method, path, meta.encode("utf-8"),
            {"Authorization": "Bearer " + creds.token(),
             "Content-Type": "application/json; charset=UTF-8",
             "X-Upload-Content-Type": "application/octet-stream",
             "X-Upload-Content-Length": str(size),
             "User-Agent": drive.UA})
        if status in (200, 201):
            return head
        if status == 401 and attempt == 0:
            creds.renew(None)
            continue
        if status in RETRY_STATUS and attempt < last:
            print(f"  (HTTP {status} opening the session) – trying again",
                  flush=True)
            time.sleep(min(2 ** (attempt + 1), 20))
            continue
        raise RuntimeError(_upload_error(status, head, "?"))
    raise RuntimeError("Drive didn't start the upload")


def _put_chunk(host, path, body, start, end, size, creds):
    return _request(host, "PUT", path, body,
                    {"Authorization": "Bearer " + creds.token(),
                     "Content-Range": f"bytes {start}-{end}/{size}",
                     "Content-Length": str(len(body)),
                     "User-Agent": drive.UA})


def _uploaded(host, path, size, creds):
    """How many bytes Drive has, and the id if it finished meanwhile."""
    status, head, _ = _request(host, "PUT", path, b"",
                               {"Authorization": "Bearer " + creds.token(),
                                "Content-Range": f"bytes */{size}",
                                "Content-Length": "0",
                                "User-Agent": drive.UA})
    if status in (200, 201):
        return size, json.loads(head["_body"] or b"{}").get("id", "")
    if status != 308:
        # 404/410 = the session is gone; resending 127 MB into it is pointless
        raise RuntimeError(f"HTTP {status}")
    return _resume_from(head, 0), None


def _resume_from(headers, default):
    """`Range: bytes=0-<n>` from a 308 answer → where to resume."""
    rng = headers.get("Range") or ""
    if "-" in rng:
        try:
            return int(rng.rsplit("-", 1)[1]) + 1
        except ValueError:
            pass
    return default


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default="",
                    help="a Drive folder URL or its id")
    ap.add_argument("--out", default="dl", help="where to download to")
    ap.add_argument("--mode", action="store_true",
                    help="print `auth` or `public` and stop – the one "
                         "answer to \"can we sign in?\"")
    ap.add_argument("--list", action="store_true",
                    help="print what is in the folder, download nothing")
    args = ap.parse_args()

    # a partial secret pair is an error: silently falling to the public limit is worse
    creds = auth.from_env()

    if args.mode:
        print("auth" if creds is not None else "public")
        return 0

    if creds is None:
        print("::error::A Drive folder can be listed only signed in (the "
              "Drive API serves no anonymous requests), but the environment "
              "has no owner token. Add the variable DRIVE_CLIENT and secrets "
              "DRIVE_SECRET / DRIVE_REFRESH – the workflow \"Maintenance · "
              "Drive sign-in\" (.github/workflows/drive-login.yml) makes them, "
              "from a computer `python3 workers/drive/auth.py --login`.")
        return 3

    fid = folder_id(args.folder)
    who = auth.whoami(creds)
    print(f"Drive read mode: {auth.describe(creds)}")
    print(f"  account  {who.get('emailAddress', '?')} "
          f"({who.get('displayName', '?')})")
    print(f"  details  from {creds.source}")
    print(f"  folder   {fid}")

    files, skipped = listing(creds, fid)
    if not files:
        # what was skipped belongs to the same message
        for f in skipped:
            print(f"  skipped: {f}")
        print(f"::error::Folder {fid} has not one downloadable file "
              f"({len(skipped)} items skipped, see above). Does account "
              f"{who.get('emailAddress', '?')} see it? The folder must be "
              f"shared at least \"anyone with the link – viewer\".")
        return 1
    total = sum(f["size"] for f in files)
    foreign = [f for f in files if not f["owned"]]

    # the plan before the costly part
    print(f"\nPlan: {len(files)} files, {human(total)}, "
          f"~{total / (EST_MB_S * 1e6) / 60:.0f} min estimated "
          f"at {EST_MB_S:.0f} MB/s")
    for f in skipped:
        print(f"  skipping {f}")
    if foreign:
        print(f"  NOTE: this account does NOT own {len(foreign)} of "
              f"{len(files)} files. A shared foreign file has the public "
              f"link's daily download cap – signing in doesn't raise it. So "
              f"they are downloaded here once and stored; the map build "
              f"doesn't reach Drive for them.")
    if args.list:
        for f in files:
            print(f"  {'own    ' if f['owned'] else 'foreign'}  "
                  f"{human(f['size']):>9}  {f['path']}"
                  + ("  (shortcut)" if f["raw"].get("shortcutDetails") else ""))
        return 0

    pool = drive.Pool(creds=creds)
    progress = Progress(total)
    t0 = time.time()
    fresh = 0
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f['path']} – {human(f['size'])}", flush=True)
        fresh += fetch(pool, f, os.path.join(args.out, f["path"]), progress)

    # MEASURED AGAINST THE ESTIMATE, or the estimate above never gets fixed
    el = time.time() - t0
    rate = fresh / max(el, 1e-6) / 1e6
    print(f"\nDone: {len(files)} files, {human(total)} "
          f"({human(fresh)} of them downloaded in this run) "
          f"in {el / 60:.1f} min, {rate:.1f} MB/s "
          f"(the estimate assumed {EST_MB_S:.0f} MB/s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except auth.AuthError as exc:
        # those messages already say what to do
        print(f"::error::{exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
