#!/usr/bin/env python3
"""Skaly z tieňovania, 1/3: stiahnutie dlaždíc z freemap.sk.

Geometria dlaždicovej mriežky, `Fetcher` (sťahovanie s opakovaním, viacerými
profilmi prehliadača a diskovou cache) a `probe_zoom`, ktorý zistí, po ktorý
zoom tá služba dlaždice vôbec má.

Sú tu aj spoločné základy (`WEBMERC`, `R`, `TILE`, `run()`) – ostatné moduly
si ich berú odtiaľto. Spúšťa sa ako modul, nie z príkazovej riadky.
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

# dlaždice sú vo Web Mercatore a mozaika sa v ňom aj počíta – žiadne
# prevzorkovanie, jeden pixel dlaždice = jeden pixel rastra
WEBMERC = "EPSG:3857"
R = 20037508.342789244  # polovica strany sveta v metroch EPSG:3857
TILE = 256

TILES_PER_S = 25.0  # pri --jobs=12 a ~25 kB na dlaždicu

# koľko buniek za sekundu zvládne `gdal_contour` nad hotovou mozaikou.
# Je to tu, hoci sa contour počíta až vo `vector.py`: podľa tohto čísla vyberá
# `probe_zoom` zoom, na ktorom beh ešte dobehne. Opačne to nejde – vrstva
# dlaždíc o vektore vedieť nesmie.
#
# Bolo tu 3,5 mil./s prevzatých zo skál z DEM a nebola to pravda: izolínia
# tmavosti nad zrnitým JPEGom má rádovo viac segmentov než izolínia sklonu nad
# hladkým rastrom. 3e5 je bezpečná strana merania.
CONTOUR_CELLS_PER_S = 3.0e5

# `watch.py` je spoločný pre obe cesty ku skalám, tak leží vo `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def lonlat_to_tile(lon, lat, z):
    """Súradnice → dlaždicové súradnice (desatinné)."""
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(max(-85.05112, min(85.05112, lat)))
    y = (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * n
    return x, y


def tile_range(bbox, z):
    """Bbox v stupňoch → rozsah dlaždíc [x0, x1) × [y0, y1) na zoome z."""
    w, s, e, n = bbox
    x0f, y0f = lonlat_to_tile(w, n, z)   # sever = menšie y
    x1f, y1f = lonlat_to_tile(e, s, z)
    lim = 2 ** z
    x0, y0 = max(0, int(math.floor(x0f))), max(0, int(math.floor(y0f)))
    x1, y1 = min(lim, int(math.ceil(x1f))), min(lim, int(math.ceil(y1f)))
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def tile_res(z):
    """Veľkosť pixela v metroch EPSG:3857 (nie na zemi – viď ground_res)."""
    return 2.0 * R / (TILE * 2.0 ** z)


def ground_res(z, lat):
    """Skutočná veľkosť pixela na zemi: Mercator naťahuje mierku 1/cos(šírka),
    takže meter v EPSG:3857 je pri 49° len ~0,65 m terénu."""
    return tile_res(z) * math.cos(math.radians(lat))


# hlavičky, ktorými sa pipeline predstavuje. Každý profil je jeden skutočný
# prehliadač – UA, `Sec-CH-UA` aj platforma musia sedieť dokopy.
# Berie to ale freemap.sk možnosť rozoznať, že ide o dávku, a je to
# dobrovoľnícky server: preto ostáva `jobs` nízke a dlaždice sa cachujú.
# `ua=project` vráti hlavičku, ktorá sa priznáva.
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

# prvé bajty formátov, ktoré vie PIL prečítať – na rozoznanie obrázka od
# chybovej stránky, nie na výber dekodéra
IMAGE_MAGIC = (b"\xff\xd8\xff",          # JPEG
               b"\x89PNG\r\n\x1a\n",     # PNG
               b"GIF87a", b"GIF89a",     # GIF
               b"RIFF")                  # WebP (RIFF....WEBP)


def looks_like_image(body):
    return bool(body) and body.startswith(IMAGE_MAGIC)


def decode_body(body, encoding):
    """Rozbalí telo, keď ho server zabalil – prehliadačovité hlavičky pýtajú
    `gzip, deflate`, takže to treba vedieť aj prijať."""
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
                return zlib.decompress(body, -zlib.MAX_WBITS)  # bez hlavičky
    except (OSError, zlib.error):
        return b""
    return body


class Fetcher:
    """Sťahovanie dlaždíc: thread-local trvalé spojenie + disková cache.

    Pri 12 000 dlaždiciach je TLS handshake väčšina času. 404 nie je chyba.
    """

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
        # proxy sa rieši tunelom (CONNECT), nie prepísaním URL – inak by sa
        # trvalé spojenie zahodilo
        self.proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""

    def path(self, z, x, y):
        return os.path.join(self.cache, str(z), str(x), f"{y}.jpg")

    def headers(self):
        """Hlavičky na jeden request.

        `ua=rotate` (predvolené) vyberie náhodný profil zo `BROWSERS`; ostatné
        hlavičky idú z toho istého profilu, nech si neodporujú. `ua=project`
        sa priznáva menom projektu.

        Trvalé spojenie sa tým nezahadzuje – nie je to dokonalé maskovanie
        a ani sa oň nesnažíme.
        """
        # `Accept-Encoding` bez `br`/`zstd` zámerne: `http.client` telo
        # nerozbaľuje a v stdlib je len gzip a deflate
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
        """True = dlaždicu máme (z cache alebo stiahnutú)."""
        return self.fetch(z, x, y) in ("cache", "stiahnuté")

    def fetch(self, z, x, y):
        """Stiahne jednu dlaždicu do cache a povie, ako to dopadlo:
        `cache` / `stiahnuté` / `chýba` (404) / `zlyhalo`.

        Stav ide von preto, aby sa dalo poznať, či server dáva dáta, alebo len
        rýchlo odpovedá 404."""
        dst = self.path(z, x, y)
        if os.path.exists(dst):
            with self.lock:
                self.n_cached += 1
            return "cache" if os.path.getsize(dst) > 0 else "chýba"
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
                    # chybová stránka s kódom 200 je pri dlaždicových službách
                    # bežná – uložiť ju ako .jpg by bola tichá diera v mozaike
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
            return "stiahnuté"
        if status == 404:
            open(dst, "wb").close()   # značka „tu nič nie je"
            with self.lock:
                self.n_miss += 1
            return "chýba"
        with self.lock:
            self.n_fail += 1
        return "zlyhalo"

    def fetch_all(self, z, x0, y0, x1, y1):
        """Stiahne celý obdĺžnik dlaždíc. Vlákna si berú prácu zo spoločného
        zoznamu, takže pomalá dlaždica nebrzdí celý pás."""
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
                stav = self.fetch(z, x, y)
                now = time.time()
                # riadok na dlaždicu (podľa `--log-every`); časový strop je
                # poistka, nech log nestíchne, keď server spomalí
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
                              f"  {stav}, zostáva {total - done}, "
                              f"{rate:.0f}/s, ešte {hms(eta)}, "
                              f"{self.bytes / 1048576:.0f} MB", flush=True)

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(max(1, self.jobs))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        dt = time.time() - t0
        print(f"  dlaždice: {self.n_ok} stiahnutých, {self.n_cached} z cache, "
              f"{self.n_miss} chýba (404), {self.n_fail} zlyhalo, "
              f"{self.bytes / 1048576:.0f} MB za {hms(dt)}", flush=True)
        # len keď sa naozaj niečo sťahovalo – pri behu celom z cache by
        # „0 rôznych prehliadačov" vyzeralo ako porucha
        if self.ua == "rotate" and self.ua_seen:
            print(f"  hlavičky: {len(self.ua_seen)} rôznych prehliadačov "
                  f"z {len(BROWSERS)} profilov", flush=True)
        if self.n_fail and self.n_fail > total * 0.02:
            print(f"::warning::Nepodarilo sa stiahnuť {self.n_fail} dlaždíc "
                  f"z {total} – v mozaike budú prázdne miesta.")
        return dt


def probe_zoom(fetcher, bbox, zmax, zmin, max_tiles, budget_s):
    """Najvyšší zoom, ktorý server naozaj dá a ktorý sa stihne spočítať.

    Dva stropy: `--max-tiles` chráni dobrovoľnícky server, `--budget-min` chráni
    beh. Zoom sa nedá prečítať z metadát (XYZ šablóna žiadne nemá), tak sa skúša
    jedna dlaždica v strede územia zhora nadol.
    """
    w, s, e, n = bbox
    lon, lat = (w + e) / 2.0, (s + n) / 2.0
    print("── Hľadám najvyšší zoom ─────────────────────────────")
    for z in range(zmax, zmin - 1, -1):
        x0, y0, x1, y1 = tile_range(bbox, z)
        count = (x1 - x0) * (y1 - y0)
        odhad = count * TILE * TILE / CONTOUR_CELLS_PER_S
        if count > max_tiles:
            print(f"  z{z:<3} {count:>8} dlaždíc  × nad strop {max_tiles}")
            continue
        if budget_s and odhad > budget_s:
            print(f"  z{z:<3} {count:>8} dlaždíc  × obrysy ~{hms(odhad)}, "
                  f"rozpočet {hms(budget_s)}")
            continue
        tx, ty = lonlat_to_tile(lon, lat, z)
        ok = fetcher.get(z, int(tx), int(ty))
        print(f"  z{z:<3} {count:>8} dlaždíc  "
              f"{'✓ dlaždica je' if ok else '× server nedal dlaždicu'}"
              + (f", obrysy ~{hms(odhad)}" if ok else ""))
        if ok:
            print(f"  vybrané         z{z}")
            print("─────────────────────────────────────────────────────", flush=True)
            return z
    print("─────────────────────────────────────────────────────", flush=True)
    print("::error::Žiadny zoom neprešiel: buď je výrez privelký na rozpočet "
          "(zdvihni --budget-min alebo zmenši area), alebo server nedal ani "
          "jednu skúšobnú dlaždicu (skontroluj --url).")
    return 0
