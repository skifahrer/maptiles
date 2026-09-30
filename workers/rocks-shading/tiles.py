#!/usr/bin/env python3
"""Rocks from hillshading, 1/3: downloading tiles from freemap.sk.

The tile grid geometry, `Fetcher` (retries, browser profiles, a disk cache) and
`probe_zoom`, plus the shared basics (`WEBMERC`, `R`, `TILE`, `run()`). A module.
"""
import gzip
import http.client
import math
import os
import random
import subprocess
import sys
import threading
import time
import urllib.parse
import zlib

# tiles are Web Mercator and so is the mosaic: one tile pixel = one raster pixel
WEBMERC = "EPSG:3857"
R = 20037508.342789244  # half the world's side in EPSG:3857 metres
TILE = 256

TILES_PER_S = 25.0  # at --jobs=12 and ~25 kB a tile

# gdal_contour cells/s over a darkness mosaic; `probe_zoom` picks by it (a safe 3e5)
CONTOUR_CELLS_PER_S = 3.0e5

# `watch.py` is shared by both ways to rocks, so it lives in `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def lonlat_to_tile(lon, lat, z):
    """Coordinates → tile coordinates (fractional)."""
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(max(-85.05112, min(85.05112, lat)))
    y = (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * n
    return x, y


def tile_range(bbox, z):
    """A bbox in degrees → the tile range [x0, x1) × [y0, y1) at zoom z."""
    w, s, e, n = bbox
    x0f, y0f = lonlat_to_tile(w, n, z)   # north = smaller y
    x1f, y1f = lonlat_to_tile(e, s, z)
    lim = 2 ** z
    x0, y0 = max(0, int(math.floor(x0f))), max(0, int(math.floor(y0f)))
    x1, y1 = min(lim, int(math.ceil(x1f))), min(lim, int(math.ceil(y1f)))
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def tile_res(z):
    """Pixel size in EPSG:3857 metres (not on the ground – see ground_res)."""
    return 2.0 * R / (TILE * 2.0 ** z)


def ground_res(z, lat):
    """The real pixel size on the ground: Mercator stretches by 1/cos(latitude)."""
    return tile_res(z) * math.cos(math.radians(lat))


# each profile is one real browser – UA, `Sec-CH-UA` and platform must agree;
# freemap.sk is a volunteer server, so `jobs` stays low and tiles are cached
BROWSERS = (
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
     '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"', '"Windows"', "sk-SK,sk;q=0.9,en-US;q=0.8,en;q=0.7"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
     '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"', '"macOS"', "sk,cs;q=0.9,en;q=0.8"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
     '"Chromium";v="132", "Not_A Brand";v="8", "Google Chrome";v="132"', '"Linux"', "en-US,en;q=0.9"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
     '"Microsoft Edge";v="134", "Chromium";v="134", "Not:A-Brand";v="24"', '"Windows"', "sk-SK,sk;q=0.9,en;q=0.8"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
     None, None, "sk-SK,sk;q=0.8,en-US;q=0.5,en;q=0.3"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:134.0) Gecko/20100101 Firefox/134.0",
     None, None, "en-US,en;q=0.5"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
     None, None, "sk-SK,sk;q=0.9"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Mobile/15E148 Safari/604.1",
     None, None, "sk-SK,sk;q=0.9,en-US;q=0.8"),
    ("Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36",
     '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"', '"Android"', "sk-SK,sk;q=0.9,en;q=0.8"),
)

PROJECT_UA = "fricomaps/shading-rocks (github.com/skifahrer/fricomaps)"

# first bytes of formats PIL reads – to tell an image from an error page
IMAGE_MAGIC = (b"\xff\xd8\xff",          # JPEG
               b"\x89PNG\r\n\x1a\n",     # PNG
               b"GIF87a", b"GIF89a",     # GIF
               b"RIFF")                  # WebP (RIFF....WEBP)


def looks_like_image(body):
    return bool(body) and body.startswith(IMAGE_MAGIC)


def decode_body(body, encoding):
    """Unpack the body when the server packed it – browser headers ask for gzip, deflate."""
    enc = (encoding or "").strip().lower()
    if not enc or enc == "identity":
        return body
    try:
        if enc == "gzip":
            return gzip.decompress(body)
        if enc == "deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)  # headerless
    except (OSError, zlib.error):
        return b""
    return body


class Fetcher:
    """Tile downloads: a thread-local persistent connection + a disk cache; 404 is no error."""

    def __init__(self, url_tmpl, cache_dir, jobs=12, retries=3, timeout=30,
                 ua="rotate", log_every=25):
        self.tmpl = url_tmpl
        self.cache = cache_dir
        self.jobs, self.retries, self.timeout = jobs, retries, timeout
        self.ua = ua
        self.log_every = log_every
        self.ua_seen = set()
        u = urllib.parse.urlsplit(url_tmpl)
        self.scheme, self.host = u.scheme, u.netloc
        self.local = threading.local()
        self.lock = threading.Lock()
        self.n_ok = self.n_miss = self.n_cached = self.n_fail = 0
        self.n_done = 0
        self.bytes = 0
        # a proxy is tunnelled (CONNECT), or the persistent connection is lost
        self.proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""

    def path(self, z, x, y):
        return os.path.join(self.cache, str(z), str(x), f"{y}.jpg")

    def headers(self):
        """Headers for one request: `rotate` picks a `BROWSERS` profile, `project` names us."""
        # no `br`/`zstd`: `http.client` doesn't unpack and stdlib has only gzip and deflate
        h = {"Accept": "image/avif,image/webp,image/jpeg,image/*,*/*;q=0.8",
             "Accept-Encoding": "gzip, deflate",
             "Connection": "keep-alive"}
        if self.ua == "rotate":
            agent, ch_ua, platform, lang = random.choice(BROWSERS)
            h["Accept-Language"] = lang
            if ch_ua:
                h["Sec-CH-UA"] = ch_ua
                h["Sec-CH-UA-Mobile"] = "?1" if "Mobile" in agent else "?0"
                h["Sec-CH-UA-Platform"] = platform
            h["Sec-Fetch-Dest"] = "image"
            h["Sec-Fetch-Mode"] = "no-cors"
            h["Sec-Fetch-Site"] = "cross-site"
        elif self.ua == "project":
            agent = PROJECT_UA
            h["Accept-Language"] = "sk-SK,sk;q=0.9,en;q=0.8"
        else:
            agent = self.ua
        h["User-Agent"] = agent
        with self.lock:
            self.ua_seen.add(agent)
        return h

    def _conn(self):
        c = getattr(self.local, "conn", None)
        if c is None:
            if self.proxy:
                p = urllib.parse.urlsplit(self.proxy)
                c = http.client.HTTPSConnection(p.hostname, p.port or 8080,
                                                timeout=self.timeout)
                c.set_tunnel(self.host)
            elif self.scheme == "https":
                c = http.client.HTTPSConnection(self.host, timeout=self.timeout)
            else:
                c = http.client.HTTPConnection(self.host, timeout=self.timeout)
            self.local.conn = c
        return c

    def _drop(self):
        c = getattr(self.local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
            self.local.conn = None

    def get(self, z, x, y):
        """True = we have the tile (cached or downloaded)."""
        return self.fetch(z, x, y) in ("cache", "downloaded")

    def fetch(self, z, x, y):
        """Download one tile to the cache: `cache` / `downloaded` / `missing` (404) / `failed`."""
        dst = self.path(z, x, y)
        if os.path.exists(dst):
            with self.lock:
                self.n_cached += 1
            return "cache" if os.path.getsize(dst) > 0 else "missing"
        url = self.tmpl.format(z=z, x=x, y=y)
        rel = urllib.parse.urlsplit(url).path
        body, status = None, 0
        for attempt in range(self.retries):
            try:
                c = self._conn()
                c.request("GET", rel, headers=self.headers())
                resp = c.getresponse()
                status = resp.status
                body = decode_body(resp.read(), resp.getheader("Content-Encoding"))
                if status == 200 and looks_like_image(body):
                    break
                if status == 200:
                    # an error page with 200 is common; saved as .jpg it is a silent hole
                    status, body = 0, None
                    self._drop()
                elif status == 404:
                    body = b""
                    break
                else:
                    self._drop()
            except Exception:
                self._drop()
                body, status = None, 0
            time.sleep(0.5 * (attempt + 1))

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if status == 200 and body:
            tmp = dst + ".part"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, dst)
            with self.lock:
                self.n_ok += 1
                self.bytes += len(body)
            return "downloaded"
        if status == 404:
            open(dst, "wb").close()   # a marker: nothing here
            with self.lock:
                self.n_miss += 1
            return "missing"
        with self.lock:
            self.n_fail += 1
        return "failed"

    def fetch_all(self, z, x0, y0, x1, y1):
        """Download the whole tile rectangle from a shared queue, so a slow tile blocks nothing."""
        jobs = [(x, y) for y in range(y0, y1) for x in range(x0, x1)]
        total = len(jobs)
        idx = [0]
        lock = threading.Lock()
        t0 = time.time()
        last = [t0]

        def worker():
            while True:
                with lock:
                    i = idx[0]
                    idx[0] += 1
                if i >= total:
                    return
                x, y = jobs[i]
                state = self.fetch(z, x, y)
                now = time.time()
                # a line per `--log-every` tiles, and every 15 s so a slow server isn't silent
                with self.lock:
                    self.n_done += 1
                    done = self.n_done
                if (self.log_every and done % self.log_every == 0) or \
                        now - last[0] >= 15:
                    with lock:
                        last[0] = now
                        rate = done / max(1e-6, now - t0)
                        eta = (total - done) / max(1e-6, rate)
                        print(f"  [{done}/{total}] {self.tmpl.format(z=z, x=x, y=y)}"
                              f"  {state}, {total - done} left, "
                              f"{rate:.0f}/s, {hms(eta)} to go, "
                              f"{self.bytes / 1048576:.0f} MB", flush=True)

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(max(1, self.jobs))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        dt = time.time() - t0
        print(f"  tiles: {self.n_ok} downloaded, {self.n_cached} from the cache, "
              f"{self.n_miss} missing (404), {self.n_fail} failed, "
              f"{self.bytes / 1048576:.0f} MB in {hms(dt)}", flush=True)
        # only when something was downloaded – "0 browsers" from the cache looks broken
        if self.ua == "rotate" and self.ua_seen:
            print(f"  headers: {len(self.ua_seen)} different browsers "
                  f"of {len(BROWSERS)} profiles", flush=True)
        if self.n_fail and self.n_fail > total * 0.02:
            print(f"::warning::{self.n_fail} of {total} tiles couldn't be "
                  f"downloaded – the mosaic will have blank spots.")
        return dt


def probe_zoom(fetcher, bbox, zmax, zmin, max_tiles, budget_s):
    """The highest zoom the server really gives and that can be computed in time."""
    # an XYZ template has no metadata, so one tile in the middle is tried top down
    w, s, e, n = bbox
    lon, lat = (w + e) / 2.0, (s + n) / 2.0
    print("── Looking for the highest zoom ─────────────────────")
    for z in range(zmax, zmin - 1, -1):
        x0, y0, x1, y1 = tile_range(bbox, z)
        count = (x1 - x0) * (y1 - y0)
        estimate = count * TILE * TILE / CONTOUR_CELLS_PER_S
        if count > max_tiles:
            print(f"  z{z:<3} {count:>8} tiles  × over the {max_tiles} cap")
            continue
        if budget_s and estimate > budget_s:
            print(f"  z{z:<3} {count:>8} tiles  × outlines ~{hms(estimate)}, "
                  f"budget {hms(budget_s)}")
            continue
        tx, ty = lonlat_to_tile(lon, lat, z)
        ok = fetcher.get(z, int(tx), int(ty))
        print(f"  z{z:<3} {count:>8} tiles  "
              f"{'✓ tile is there' if ok else '× the server gave no tile'}"
              + (f", outlines ~{hms(estimate)}" if ok else ""))
        if ok:
            print(f"  picked          z{z}")
            print("─────────────────────────────────────────────────────", flush=True)
            return z
    print("─────────────────────────────────────────────────────", flush=True)
    print("::error::No zoom passed: either the cut-out is too big for the budget "
          "(raise --budget-min or shrink area), or the server gave not one "
          "probe tile (check --url).")
    return 0
