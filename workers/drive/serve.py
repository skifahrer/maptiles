#!/usr/bin/env python3
"""Google Drive as a decent HTTP server for GDAL.

DMR 5.0 lies on Drive as a bare BigTIFF and Range requests work, but GDAL can't
read it through `/vsicurl/`: Drive answers HEAD with `content-length: 0`. This
server fixes that one header (the size from a one-byte GET's `Content-Range`)
and passes Range requests through, reusing connections and serving multi-range
requests properly. Signed in through the Drive API, or the public link.

    python3 workers/drive/serve.py --file=dmr5.tif=<id> --port=8787
"""
import argparse
import http.client
import http.server
import json
import os
import queue
import random
import socket
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (compatible; fricomaps-dem/1.0)"
# the public way: `confirm=t` skips the "can't scan this file" page
PUBLIC_HOST = "drive.usercontent.google.com"
# the signed-in way: the Drive API; Range on `alt=media` works the same
API_HOST = "www.googleapis.com"
# multi-range parts fetched at once per process (measured best at 24; over ~32 Drive 403s)
FETCH_WORKERS = 24

_FETCH = None
_FETCH_LOCK = threading.Lock()


def fetch_pool():
    """One shared thread pool fetching parts, so `FETCH_WORKERS` really bounds it."""
    global _FETCH
    with _FETCH_LOCK:
        if _FETCH is None:
            _FETCH = ThreadPoolExecutor(max_workers=FETCH_WORKERS,
                                        thread_name_prefix="drive-fetch")
    return _FETCH


def quota_hint(authed):
    """What Drive does when it won't give data – and what to do about it."""
    # the public way answers 200 with an HTML page; taken as success, a job hung 2 h 16 min
    if authed:
        return ("the Google Drive download limit is exceeded even for the "
                "signed-in account. Check the account really OWNS the file "
                "(`python3 workers/drive/dmr5.py --auth-check`) – someone "
                "else's shared file has the public link's daily cap. If it "
                "owns it, wait a few hours; meanwhile the run falls back to a "
                "coarser model (sonny) when ugkk_fallback is on.")
    return ("the Google Drive download limit is exceeded (a public link has a "
            "daily per-file cap shared by everyone reaching it). Sign the run "
            "in as the data owner – secret GDRIVE_CREDENTIALS, steps in "
            "`workers/drive/auth.py --login` – the owner's cap is much higher. "
            "Otherwise wait a few hours, or upload a copy of the model to "
            "another folder and rewrite FOLDER_ID in workers/drive/dmr5.py. "
            "Meanwhile the run falls back to a coarser model (sonny) when "
            "ugkk_fallback is on.")


def drive_refusal(body, authed=False):
    """A refusal description when the body is an HTML page instead of data."""
    head = body[:2048].lower()
    if b"<html" not in head and b"<!doctype" not in head:
        return None
    if b"quota" in head or b"too many" in head or b"limit" in head:
        return quota_hint(authed)
    return f"Drive returned an HTML page ({len(body)} B), not data"


def api_error(body):
    """`reason` from a Drive API JSON error answer, or None."""
    if not body[:64].lstrip().startswith(b"{"):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        for e in err.get("errors") or []:
            if e.get("reason"):
                return e["reason"]
        return str(err.get("status") or err.get("message") or "an error without a reason")
    if isinstance(err, str):
        return err
    return None


def hard_reason(reason, authed):
    """A description for reasons where retrying wastes time; the first stops the `Pool`."""
    if reason in ("downloadQuotaExceeded", "quotaExceeded", "dailyLimitExceeded",
                  "userRateLimitExceededUnreg"):
        return quota_hint(authed)
    if reason == "notFound":
        return ("Drive doesn't see the file (notFound). A signed-in run says "
                "so when the account doesn't see it – check "
                "`python3 workers/drive/dmr5.py --auth-check`. Otherwise the "
                "file moved out of folder `FOLDER_ID` (workers/drive/dmr5.py) "
                "or its sharing stopped.")
    if reason in ("forbidden", "insufficientFilePermissions", "cannotDownloadFile",
                  "insufficientPermissions", "appNotAuthorizedToFile",
                  "fileNotDownloadable", "cannotDownloadAbusiveFile"):
        return (f"Drive refused access to the file ({reason}). Sign in with the "
                "account owning the data (`python3 workers/drive/auth.py "
                "--login`), or share the file with anyone with the link.")
    return None


_CTX = None
_CTX_LOCK = threading.Lock()


def _ssl_ctx():
    """One verifying context for the process (with an own CA from the environment)."""
    global _CTX
    with _CTX_LOCK:
        if _CTX is None:
            ctx = ssl.create_default_context()
            ca = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
            if ca and os.path.exists(ca):
                ctx.load_verify_locations(ca)
            _CTX = ctx
    return _CTX


def connect(host, timeout=180):
    """An HTTPS connection to `host`, through a proxy too (a CONNECT tunnel)."""
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy:
        p = urllib.parse.urlsplit(proxy)
        conn = http.client.HTTPSConnection(p.hostname, p.port or 8080,
                                           timeout=timeout, context=_ssl_ctx())
        conn.set_tunnel(host, 443)
        return conn
    return http.client.HTTPSConnection(host, 443, timeout=timeout,
                                       context=_ssl_ctx())


class Pool:
    """Reusable HTTPS connections to Drive, per host (canonical and redirect)."""

    def __init__(self, creds=None, size=32):
        self.creds = creds
        self.size = size
        self.free = {}                  # host → LifoQueue of free connections
        self.lock = threading.Lock()
        # non-empty = Drive refused the data, asking on is pointless
        self.refused = None
        # until when nobody asks: Drive's limit is a window other threads keep open
        self.cooldown = 0.0
        # file id → (host, path) from a redirect, instead of a request per block
        self.redirect = {}
        # files Drive wants an antivirus acknowledgement for (only when it asks)
        self.ack = set()

    def _pipe(self, host):
        with self.lock:
            q = self.free.get(host)
            if q is None:
                q = self.free[host] = queue.LifoQueue()
        return q

    def _take(self, host):
        try:
            return self._pipe(host).get_nowait()
        except queue.Empty:
            return connect(host)

    def _put(self, host, conn):
        q = self._pipe(host)
        if q.qsize() < self.size:
            q.put(conn)
        else:
            conn.close()

    def target(self, file_id):
        """A file's canonical address: the API when signed in, else the public link."""
        if self.creds is not None:
            path = (f"/drive/v3/files/{urllib.parse.quote(file_id)}"
                    "?alt=media&supportsAllDrives=true")
            if file_id in self.ack:
                path += "&acknowledgeAbuse=true"
            return API_HOST, path
        return PUBLIC_HOST, (f"/download?id={urllib.parse.quote(file_id)}"
                             "&export=download&confirm=t")

    def _where(self, file_id):
        """(host, path, whether it is a remembered redirect)."""
        with self.lock:
            hit = self.redirect.get(file_id)
        if hit:
            return hit[0], hit[1], True
        host, path = self.target(file_id)
        return host, path, False

    def _remember(self, file_id, location):
        """Remember a redirect target (absolute or relative)."""
        parts = urllib.parse.urlsplit(location)
        host = parts.netloc or self.target(file_id)[0]
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        with self.lock:
            self.redirect[file_id] = (host, path)

    def _forget(self, file_id):
        with self.lock:
            self.redirect.pop(file_id, None)

    def _slow_down(self, retry_after, n):
        """Drive's limit stops the whole Pool, not just the thread that hit it."""
        wait = min(2.0 ** n, 60.0)
        try:
            wait = max(wait, float(retry_after))
        except (TypeError, ValueError):
            pass
        with self.lock:
            new = max(self.cooldown, time.time() + wait)
            loud = new > self.cooldown + 1
            self.cooldown = new
        if loud:
            print(f"  drive-serve: Drive limit – waiting {wait:.0f} s "
                  f"(all threads)", file=sys.stderr, flush=True)

    def _wait_out(self):
        while True:
            with self.lock:
                left = self.cooldown - time.time()
            if left <= 0:
                return
            # jitter, so threads don't all start at once when the window ends
            time.sleep(min(left, 5.0) + random.random() / 2)

    def get(self, file_id, rng, tries=6, want=None):
        """A GET with a Range header; returns (status, headers, body bytes)."""
        # `want` is the bytes asked; the public way's status code lies on refusal
        last = None
        attempt = 0
        # redirects and token renewals aren't failures – they don't eat network retries
        extra, EXTRA_MAX = 0, 6
        slow, SLOW_MAX = 0, 8
        renewed = False
        while attempt < tries:
            # a limit won't lift in twenty seconds: hitting it once a run is enough
            if self.refused:
                raise RuntimeError(self.refused)
            self._wait_out()
            host, path, cached = self._where(file_id)
            headers = {"Range": rng, "User-Agent": UA,
                       "Accept-Encoding": "identity"}
            token = None
            # the token only to the canonical API host; a redirect is signed in its query
            if self.creds is not None and host == API_HOST:
                token = self.creds.token()
                headers["Authorization"] = "Bearer " + token
            conn = self._take(host)
            try:
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
                status, hdrs = resp.status, resp.headers
                # 200 on a Range means Drive ignored it; the length decides
                if status == 206 or (status == 200
                                     and (want is None or len(body) == want)):
                    self._put(host, conn)
                    return status, hdrs, body
                conn.close()
            except Exception as exc:                # noqa: BLE001
                last = exc
                try:
                    conn.close()
                except Exception:                   # noqa: BLE001
                    pass
                attempt += 1
                time.sleep(min(1.5 ** attempt, 20))
                continue

            # a remembered redirect may have expired
            if cached:
                self._forget(file_id)

            if status in (301, 302, 303, 307, 308) and extra < EXTRA_MAX:
                loc = hdrs.get("Location")
                if loc:
                    self._remember(file_id, loc)
                    extra += 1
                    continue

            if status == 401 and token is not None:
                # renew once; refusing a fresh token too is a bad sign-in, not transient
                if not renewed:
                    self.creds.renew(token)
                    renewed = True
                    continue
                why = api_error(body)
                hard = ("Drive refused the access token even after renewal (HTTP 401"
                        + (f", {why}" if why else "") + "). Check "
                        "`python3 workers/drive/auth.py --check`: the account "
                        "may have revoked the app's access, or the secret "
                        "GDRIVE_CREDENTIALS belongs to another project than "
                        "the token was made in.")
                self.refused = hard
                raise RuntimeError(hard)

            reason = api_error(body)
            if (reason == "cannotDownloadAbusiveFile" and self.creds is not None
                    and file_id not in self.ack and extra < EXTRA_MAX):
                # Drive didn't virus-scan the file – acknowledge only when asked
                self.ack.add(file_id)
                extra += 1
                continue

            if reason:
                hard = hard_reason(reason, self.creds is not None)
                if hard:
                    self.refused = hard
                    raise RuntimeError(hard)
            # the limit has its own budget, or it uses up the network retries
            if status == 429 or reason in ("rateLimitExceeded",
                                           "userRateLimitExceeded"):
                if slow < SLOW_MAX:
                    slow += 1
                    self._slow_down(hdrs.get("Retry-After"), slow)
                    continue
            if reason:
                last = f"HTTP {status} ({reason})"
            elif status == 200:
                why = drive_refusal(body, self.creds is not None)
                if why:
                    # retrying won't fix this
                    self.refused = why
                    raise RuntimeError(why)
                last = (f"HTTP 200 and {len(body)} B instead of {want} – "
                        "Drive ignored the range")
            else:
                last = f"HTTP {status}"
            attempt += 1
            # an exponential wait reliably gets past a 403 "rate limit"
            time.sleep(min(1.5 ** attempt, 20))
        raise RuntimeError(f"Drive didn't answer in {tries} tries: {last}")


def parse_ranges(header, size):
    """`bytes=a-b,c-,-d` → [(start, end), …], ends inclusive, clipped to the file."""
    out = []
    for spec in header.split("=", 1)[1].split(","):
        spec = spec.strip()
        if not spec:
            continue
        a, _, b = spec.partition("-")
        if a == "":                            # "-500" = the last 500 bytes
            start, end = max(0, size - int(b)), size - 1
        else:
            start = int(a)
            end = int(b) if b else size - 1
        end = min(end, size - 1)
        if start <= end:
            out.append((start, end))
    return out


def make_handler(pool, files, stats):
    """`files` is URL name → (Drive file id, size); names let GDAL find `.tif.ovr` itself."""

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass                  # otherwise every tile would be a log line

        def _entry(self):
            name = urllib.parse.unquote(self.path.lstrip("/"))
            return files.get(name)

        def do_HEAD(self):
            entry = self._entry()
            if not entry:
                # 404 isn't an error: that is how GDAL asks whether a sidecar exists
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # exactly the header Drive gets wrong: the real length
            self.send_response(200)
            self.send_header("Content-Length", str(entry[1]))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()

        def _fetch(self, file_id, start, end):
            want = end - start + 1
            status, _, body = pool.get(file_id, f"bytes={start}-{end}", want=want)
            if len(body) != want:
                raise RuntimeError(
                    f"Drive returned {len(body)} B instead of {want} (HTTP {status})")
            with stats["lock"]:
                stats["requests"] += 1
                stats["bytes"] += len(body)
            return body

        def send_response(self, *a, **kw):
            self.responded = True
            super().send_response(*a, **kw)

        def do_GET(self):
            self.responded = False
            entry = self._entry()
            if not entry:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            file_id, size = entry
            hdr = self.headers.get("Range")
            asked = bool(hdr and hdr.startswith("bytes="))
            ranges = parse_ranges(hdr, size) if asked else []
            # a range empty after clipping isn't "send the whole file" (145 GB) – RFC 9110 says 416
            if asked and not ranges:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            whole = not ranges
            if whole:
                ranges = [(0, size - 1)]

            try:
                if whole:
                    self._send_stream(file_id, size, ranges[0])
                elif len(ranges) == 1:
                    self._send_single(file_id, size, *ranges[0])
                else:
                    self._send_multipart(file_id, size, ranges)
            except (BrokenPipeError, ConnectionResetError):
                pass              # GDAL closed the connection – common and fine
            except Exception as exc:            # noqa: BLE001
                # counted: GDAL errors with zero here never reached the shim
                with stats["lock"]:
                    stats["failed"] += 1
                print(f"  drive-serve: {self.path} {hdr} failed: {exc}",
                      file=sys.stderr, flush=True)
                # answer an error too: unanswered, a job hung 2 h 16 min; a 502 fails it in seconds
                if not self.responded:
                    try:
                        msg = str(exc).encode("utf-8")
                        self.send_response(502)
                        self.send_header("Content-Length", str(len(msg)))
                        self.send_header("Content-Type",
                                         "text/plain; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(msg)
                    except Exception:           # noqa: BLE001
                        pass
                else:
                    # headers are out – at least don't keep the client waiting for a body
                    self.close_connection = True

        def _send_stream(self, file_id, size, rng):
            """The whole file in pieces – GDAL doesn't, but `curl` does."""
            start, end = rng
            self.send_response(200)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            step = 32 << 20
            for a in range(start, end + 1, step):
                self.wfile.write(self._fetch(file_id, a, min(a + step - 1, end)))

        def _send_single(self, file_id, size, start, end):
            body = self._fetch(file_id, start, end)
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(body)

        def _send_multipart(self, file_id, size, ranges):
            bodies = list(fetch_pool().map(
                lambda r: self._fetch(file_id, *r), ranges))
            boundary = "fricomaps_%d" % time.time_ns()
            parts, total = [], 0
            for (start, end), body in zip(ranges, bodies):
                head = (f"\r\n--{boundary}\r\n"
                        "Content-Type: application/octet-stream\r\n"
                        f"Content-Range: bytes {start}-{end}/{size}\r\n\r\n"
                        ).encode("ascii")
                parts.append((head, body))
                total += len(head) + len(body)
            tail = f"\r\n--{boundary}--\r\n".encode("ascii")
            total += len(tail)
            self.send_response(206)
            self.send_header("Content-Type",
                             f"multipart/byteranges; boundary={boundary}")
            self.send_header("Content-Length", str(total))
            self.end_headers()
            for head, body in parts:
                self.wfile.write(head)
                self.wfile.write(body)
            self.wfile.write(tail)

    return Handler


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    # the backlog: 5 by default drops SYNs under six gdalwarps (`response_code=0`)
    request_queue_size = socket.SOMAXCONN


def probe_size(pool, file_id):
    """The size from a one-byte GET's `Content-Range` – HEAD can't be trusted."""
    status, headers, _ = pool.get(file_id, "bytes=0-0", want=1)
    cr = headers.get("Content-Range", "")
    if "/" not in cr:
        raise RuntimeError(
            f"Drive returned no Content-Range (HTTP {status}, {cr!r}). "
            + ("Does the signed-in account see the file? "
               "`python3 workers/drive/dmr5.py --auth-check`"
               if pool.creds is not None else
               "Is the file shared with anyone with the link?"))
    return int(cr.rsplit("/", 1)[1])


def serve(ids, port=8787, creds=None):
    """Start the server in the background; returns (base url, {name: size}, stats)."""
    # `ids` is URL name → Drive file id, `creds` from `auth.py` (None = public link)
    pool = Pool(creds=creds)
    files, sizes = {}, {}
    for name, file_id in ids.items():
        files[name] = (file_id, probe_size(pool, file_id))
        sizes[name] = files[name][1]
    stats = {"requests": 0, "bytes": 0, "failed": 0, "lock": threading.Lock()}
    httpd = Server(("127.0.0.1", port), make_handler(pool, files, stats))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", sizes, stats


def gdal_env(extra=None):
    """An environment where GDAL reads through this shim sensibly."""
    # `no_proxy` keeps 127.0.0.1 off the proxy; no READDIR switch, it would hide `.ovr`
    env = {
        **os.environ,
        "GDAL_HTTP_MULTIRANGE": "YES",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "GDAL_HTTP_VERSION": "1.1",
        "GDAL_HTTP_MAX_RETRY": os.environ.get("GDAL_HTTP_MAX_RETRY", "5"),
        "GDAL_HTTP_RETRY_DELAY": os.environ.get("GDAL_HTTP_RETRY_DELAY", "1"),
        "GDAL_HTTP_CONNECTTIMEOUT": os.environ.get(
            "GDAL_HTTP_CONNECTTIMEOUT", "20"),
        "GDAL_NUM_THREADS": "ALL_CPUS",
        "GDAL_CACHEMAX": os.environ.get("GDAL_CACHEMAX", "2048"),
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": os.environ.get("VSI_CACHE_SIZE", str(512 * 1024 * 1024)),
        "GDAL_PAM_ENABLED": "NO",
        "no_proxy": "127.0.0.1,localhost",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    env.update(extra or {})
    return env


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", action="append", required=True, metavar="NAME=ID",
                    help="a URL name and a Drive file id; repeatable, so a "
                         ".tif and its .ovr are served side by side")
    ap.add_argument("--auth", action="store_true",
                    help="read signed in as the owner (GDRIVE_CREDENTIALS)")
    ap.add_argument("--port", type=int, default=8787, help="0 = pick a free one")
    ap.add_argument("--print-url", action="store_true")
    args = ap.parse_args()

    ids = {}
    for spec in args.file:
        name, _, file_id = spec.partition("=")
        if not file_id:
            ap.error(f"--file expected NAME=ID, got {spec!r}")
        ids[name] = file_id

    creds = None
    if args.auth:
        # only here: `auth.py` takes its connections from this file
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "drive_auth", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "auth.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        try:
            creds = mod.from_env()
            if creds is None:
                print("::error::--auth is on, but the environment has no "
                      "sign-in details (GDRIVE_CREDENTIALS).",
                      file=sys.stderr)
                return 2
            mod.whoami(creds)
        except mod.AuthError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        print(f"drive-serve: {mod.describe(creds)}", flush=True)

    base, sizes, stats = serve(ids, args.port, creds=creds)
    for name, size in sizes.items():
        print(f"drive-serve: {base}/{name}  "
              f"({size:,} B = {size / 2**30:.2f} GiB)", flush=True)
    if args.print_url:
        print(base)
    try:
        while True:
            time.sleep(60)
            with stats["lock"]:
                print(f"  drive-serve: {stats['requests']:,} requests, "
                      f"{stats['bytes'] / 1e6:,.0f} MB", flush=True)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
