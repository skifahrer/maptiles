#!/usr/bin/env python3
"""Google Drive ako slušný HTTP server pre GDAL.

DMR 5.0 leží na Drive ako holý BigTIFF a Range requesty naň fungujú, ale GDAL
cez `/vsicurl/` čítať nevie: Drive na HEAD vracia `content-length: 0`, takže
si GDAL veľkosť domyslí zle a všetko padá na „after end of file". Tento server
opraví tú jednu hlavičku (veľkosť zistí z `Content-Range` jednobajtového GETu)
a ďalej už len prepája Range requesty.

Dve cesty k tým istým dátam: prihlásený vlastník cez Drive API (vyšší limit)
alebo verejný odkaz, ktorý má denný strop zdieľaný všetkými.

O rýchlosti rozhodujú dve veci:
  1. spojenia sa recyklujú – bez toho je to latencia × počet spojení
     (2 209 dlaždíc 103 s pri 109 MB, čiže ~1 MB/s zo 75 MB/s pásma);
  2. viacnásobný Range (`GDAL_HTTP_MULTIRANGE`) sa musí vedieť – server,
     ktorý pošle len prvý úsek, podstrčí GDALu ticho zlé dáta.

Celý súbor sa nesťahuje: má 145 GiB a runner má voľných ~60 GB.

    python3 workers/drive/serve.py --file=dmr5.tif=<id> --port=8787
"""
import argparse
import http.client
import http.server
import json
import os
import queue
import socket
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (compatible; fricomaps-dem/1.0)"
# verejná cesta: `confirm=t` už obišlo stránku „can't scan this file"
PUBLIC_HOST = "drive.usercontent.google.com"
# Prihlásená cesta: riadne Drive API. Range na `alt=media` funguje rovnako.
API_HOST = "www.googleapis.com"
# koľko úsekov viacnásobného Range sa ťahá naraz – na celý proces, nie na
# požiadavku: pri `--jobs 6` bolo z „12 vlákien" 72. 24 je namerané (48
# výrezov po 400 kB: 1 vlákno 1143 ms/req, 8 vlákien 147, 24 vlákien 68);
# nad ~32 začne Drive odpovedať 403 a čakanie zožerie viac, než sa získa.
FETCH_WORKERS = 24

_FETCH = None
_FETCH_LOCK = threading.Lock()


def fetch_pool():
    """Jeden zdieľaný bazén vlákien na sťahovanie úsekov.

    Zdieľaný, aby `FETCH_WORKERS` naozaj ohraničoval, a jeden, aby sa vlákna
    nevyrábali pri každej z desaťtisícov požiadaviek.
    """
    global _FETCH
    with _FETCH_LOCK:
        if _FETCH is None:
            _FETCH = ThreadPoolExecutor(max_workers=FETCH_WORKERS,
                                        thread_name_prefix="drive-fetch")
    return _FETCH


def quota_hint(authed):
    """Čo robí Drive, keď nechce dať dáta – a čo s tým.

    Na verejnej ceste vráti HTTP 200 a HTML stránku, nie chybový kód. Kým sa
    to bralo ako úspech, job visel 2 h 16 min na `gdalinfo`. Prihlásená cesta
    pošle 403 a JSON s dôvodom.
    """
    if authed:
        return ("prekročený limit sťahovania z Google Drive aj pre prihlásený "
                "účet. Over, či ten súbor prihlásený účet naozaj VLASTNÍ "
                "(`python3 workers/drive/dmr5.py --auth-check`) – na cudzí "
                "zdieľaný súbor platí ten istý denný strop ako na verejný "
                "odkaz. Ak vlastní, počkaj pár hodín; beh medzitým prejde na "
                "hrubší model (sonny), keď je zapnutý ugkk_fallback.")
    return ("prekročený limit sťahovania z Google Drive (verejný odkaz má "
            "denný strop na súbor a ten zdieľajú všetci, kto naň siahnu). "
            "Prihlás beh ako vlastníka dát – secret GDRIVE_CREDENTIALS, "
            "rozpis vo `workers/drive/auth.py --login` – vlastník má strop "
            "oveľa vyšší. Inak počkaj pár hodín, alebo nahraj kópiu modelu do "
            "iného priečinka a prepíš FOLDER_ID vo workers/drive/dmr5.py. Beh "
            "medzitým prejde na hrubší model (sonny), keď je zapnutý "
            "ugkk_fallback.")


def drive_refusal(body, authed=False):
    """Vráti popis odmietnutia, keď je telo HTML stránka namiesto dát."""
    head = body[:2048].lower()
    if b"<html" not in head and b"<!doctype" not in head:
        return None
    if b"quota" in head or b"too many" in head or b"limit" in head:
        return quota_hint(authed)
    return f"Drive vrátil HTML stránku ({len(body)} B), nie dáta"


def api_error(body):
    """`reason` z chybovej JSON odpovede Drive API, alebo None."""
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
        return str(err.get("status") or err.get("message") or "chyba bez dôvodu")
    if isinstance(err, str):
        return err
    return None


def hard_reason(reason, authed):
    """Popis pre dôvody, pri ktorých je opakovanie strata času.

    Limit ani chýbajúce právo sa o dvadsať sekúnd neposunú – prvý taký nález
    zastaví celý `Pool`. `rateLimitExceeded` a 5xx sú prechodné a opakujú sa.
    """
    if reason in ("downloadQuotaExceeded", "quotaExceeded", "dailyLimitExceeded",
                  "userRateLimitExceededUnreg"):
        return quota_hint(authed)
    if reason == "notFound":
        return ("Drive ten súbor nevidí (notFound). Prihlásený beh to hlási "
                "vtedy, keď na súbor nevidí použitý účet – over "
                "`python3 workers/drive/dmr5.py --auth-check`. Inak sa súbor "
                "z priečinka `FOLDER_ID` (workers/drive/dmr5.py) presunul "
                "alebo prestalo platiť zdieľanie.")
    if reason in ("forbidden", "insufficientFilePermissions", "cannotDownloadFile",
                  "insufficientPermissions", "appNotAuthorizedToFile",
                  "fileNotDownloadable", "cannotDownloadAbusiveFile"):
        return (f"Drive odmietol prístup k súboru ({reason}). Prihlás sa účtom, "
                "ktorý dáta vlastní (`python3 workers/drive/auth.py --login`), "
                "alebo súbor nasdieľaj pre kohokoľvek s odkazom.")
    return None


# spojenia

_CTX = None
_CTX_LOCK = threading.Lock()


def _ssl_ctx():
    """Jeden overovací kontext pre celý proces (aj s vlastným CA z prostredia)."""
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
    """HTTPS spojenie na `host`, aj cez firemné proxy (CONNECT tunel).

    `http.client` namiesto `requests`: runner nemá nič doinštalované. Používa
    to aj `drive/auth.py` – proxy a CA sa nemajú riešiť na dvoch miestach.
    """
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
    """Znovupoužiteľné HTTPS spojenia na Drive, po hostoch.

    Ciest k dátam je viac (kanonická adresa a adresa z presmerovania)
    a spojenie na jeden host sa nesmie použiť na druhý.
    """

    def __init__(self, creds=None, size=32):
        self.creds = creds
        self.size = size
        self.free = {}                  # host → LifoQueue voľných spojení
        self.lock = threading.Lock()
        # neprázdne = Drive dáta odmietol a nemá zmysel pýtať sa ďalej
        self.refused = None
        # file id → (host, cesta) z presmerovania: podpísaná adresa platí
        # krátko, ale vypýtať ju znova znamená request na každý blok
        self.redirect = {}
        # súbory, pri ktorých Drive žiada potvrdenie o antivíruse. API to má
        # v `acknowledgeAbuse`, ktoré smie poslať len vlastník – preto sa
        # nepridáva dopredu, len keď si o to Drive povie.
        self.ack = set()

    # spojenia

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

    # kam sa ide po dáta

    def target(self, file_id):
        """Kanonická adresa súboru: s prihlásením API, bez neho verejný odkaz."""
        if self.creds is not None:
            path = (f"/drive/v3/files/{urllib.parse.quote(file_id)}"
                    "?alt=media&supportsAllDrives=true")
            if file_id in self.ack:
                path += "&acknowledgeAbuse=true"
            return API_HOST, path
        return PUBLIC_HOST, (f"/download?id={urllib.parse.quote(file_id)}"
                             "&export=download&confirm=t")

    def _where(self, file_id):
        """(host, cesta, či je to zapamätané presmerovanie)."""
        with self.lock:
            hit = self.redirect.get(file_id)
        if hit:
            return hit[0], hit[1], True
        host, path = self.target(file_id)
        return host, path, False

    def _remember(self, file_id, location):
        """Ulož cieľ presmerovania (absolútny aj relatívny)."""
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

    # čítanie

    def get(self, file_id, rng, tries=6, want=None):
        """GET s hlavičkou Range; vráti (status, headers, telo ako bajty).

        `want` je koľko bajtov sa pýtalo – bez neho sa dá overiť len stavový
        kód, a ten na verejnej ceste pri odmietnutí klame.
        """
        last = None
        attempt = 0
        # presmerovanie a výmena vypršaného tokenu nie sú zlyhania, na ktoré
        # sa čaká – nech nezožerú pokusy určené na chyby siete
        extra, EXTRA_MAX = 0, 6
        renewed = False
        while attempt < tries:
            # limit nepustí ani o dvadsať sekúnd neskôr: stačí naraziť raz za
            # beh, nie raz za blok
            if self.refused:
                raise RuntimeError(self.refused)
            host, path, cached = self._where(file_id)
            headers = {"Range": rng, "User-Agent": UA,
                       "Accept-Encoding": "identity"}
            token = None
            # token ide len na kanonický API host – adresa z presmerovania je
            # podpísaná v query (rovnako to robí `curl -L`)
            if self.creds is not None and host == API_HOST:
                token = self.creds.token()
                headers["Authorization"] = "Bearer " + token
            conn = self._take(host)
            try:
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
                status, hdrs = resp.status, resp.headers
                # 200 na Range znamená, že ho Drive ignoroval; rozhodne dĺžka
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

            # zapamätané presmerovanie mohlo vypršať
            if cached:
                self._forget(file_id)

            if status in (301, 302, 303, 307, 308) and extra < EXTRA_MAX:
                loc = hdrs.get("Location")
                if loc:
                    self._remember(file_id, loc)
                    extra += 1
                    continue

            if status == 401 and token is not None:
                # vypršaný token je okamžitá vec, nie čakanie; `renew` drží,
                # aby ho neobnovovalo každé vlákno. Keď odmietne aj čerstvý,
                # je to zlé prihlásenie, nie prechodná chyba.
                if not renewed:
                    self.creds.renew(token)
                    renewed = True
                    continue
                why = api_error(body)
                hard = (f"Drive odmietol access token aj po obnove (HTTP 401"
                        + (f", {why}" if why else "") + "). Over "
                        "`python3 workers/drive/auth.py --check`: účet mohol "
                        "appke odvolať prístup, alebo secret "
                        "GDRIVE_CREDENTIALS patrí inému projektu, než v ktorom "
                        "bol token vyrobený.")
                self.refused = hard
                raise RuntimeError(hard)

            reason = api_error(body)
            if (reason == "cannotDownloadAbusiveFile" and self.creds is not None
                    and file_id not in self.ack and extra < EXTRA_MAX):
                # Drive súbor nepreveril antivírusom – potvrdenie sa pridá až
                # keď si o to povie
                self.ack.add(file_id)
                extra += 1
                continue

            if reason:
                hard = hard_reason(reason, self.creds is not None)
                if hard:
                    self.refused = hard
                    raise RuntimeError(hard)
                last = f"HTTP {status} ({reason})"
            elif status == 200:
                why = drive_refusal(body, self.creds is not None)
                if why:
                    # toto sa opakovaním nespraví
                    self.refused = why
                    raise RuntimeError(why)
                last = (f"HTTP 200 a {len(body)} B namiesto {want} – "
                        "Drive rozsah ignoroval")
            else:
                last = f"HTTP {status}"
            attempt += 1
            # 403 „rate limit" exponenciálne čakanie spoľahlivo prejde
            time.sleep(min(1.5 ** attempt, 20))
        raise RuntimeError(f"Drive neodpovedal ani na {tries}. pokus: {last}")


def parse_ranges(header, size):
    """`bytes=a-b,c-,-d` → [(start, end), …], konce vrátane, orezané na súbor."""
    out = []
    for spec in header.split("=", 1)[1].split(","):
        spec = spec.strip()
        if not spec:
            continue
        a, _, b = spec.partition("-")
        if a == "":                            # „-500" = posledných 500 bajtov
            start, end = max(0, size - int(b)), size - 1
        else:
            start = int(a)
            end = int(b) if b else size - 1
        end = min(end, size - 1)
        if start <= end:
            out.append((start, end))
    return out


def make_handler(pool, files, stats):
    """`files` je meno v URL → (Drive file id, veľkosť).

    Menami preto, že GDAL si sidecary hľadá podľa mena vedľa hlavného súboru:
    pod `.tif.ovr` nájde pyramídy sám a pri hrubšom cieli číta z nich namiesto
    zo 145 GiB rastra. Preto sa `GDAL_DISABLE_READDIR_ON_OPEN` nenastavuje.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass                  # inak by každá dlaždica bola riadok v logu

        def _entry(self):
            name = urllib.parse.unquote(self.path.lstrip("/"))
            return files.get(name)

        def do_HEAD(self):
            entry = self._entry()
            if not entry:
                # 404 nie je chyba: takto sa GDAL pýta, či sidecar existuje.
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # Presne tá hlavička, ktorú Drive nevie: skutočná dĺžka.
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
                    f"Drive vrátil {len(body)} B namiesto {want} (HTTP {status})")
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
            # rozsah, z ktorého po orezaní nič neostalo, nie je „pošli celý
            # súbor" – to je 145 GB namiesto 32 kB. Podľa RFC 9110 je to 416.
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
                pass              # GDAL zavrel spojenie – bežné a v poriadku
            except Exception as exc:            # noqa: BLE001
                # zlyhania sa aj rátajú: keď GDAL hlási chybu a tu je nula,
                # spojenie sa k shimu nedostalo a hľadať sa má inde než na Drive
                with stats["lock"]:
                    stats["failed"] += 1
                print(f"  drive-serve: {self.path} {hdr} zlyhalo: {exc}",
                      file=sys.stderr, flush=True)
                # odpovedaj aj na chybu – kým sa sem chodilo len vypísať,
                # GDAL čakal na odpoveď, ktorá nikdy neprišla, a job visel
                # 2 h 16 min. 502 vráti GDAL ako chybu a job spadne v sekundách.
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
                    # hlavičky sú vonku – aspoň nenechaj klienta čakať na telo
                    self.close_connection = True

        def _send_stream(self, file_id, size, rng):
            """Celý súbor po kúskoch – GDAL to nerobí, ale `curl` áno."""
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
    # fronta čakajúcich spojení: `socketserver` má predvolene 5 a to je pri
    # šiestich súbežných gdalwarpoch málo. Keď pretečie, jadro SYN ticho zahodí
    # a GDAL to po dvoch minútach vypíše ako `response_code=0`, čo vyzerá ako
    # chyba Drive. Berie sa preto `SOMAXCONN` – prázdna fronta nič nestojí.
    request_queue_size = socket.SOMAXCONN


def probe_size(pool, file_id):
    """Veľkosť z `Content-Range` jednobajtového GETu – HEAD sa nedá veriť."""
    status, headers, _ = pool.get(file_id, "bytes=0-0", want=1)
    cr = headers.get("Content-Range", "")
    if "/" not in cr:
        raise RuntimeError(
            f"Drive nevrátil Content-Range (HTTP {status}, {cr!r}). "
            + ("Vidí prihlásený účet na ten súbor? "
               "`python3 workers/drive/dmr5.py --auth-check`"
               if pool.creds is not None else
               "Je ten súbor zdieľaný pre kohokoľvek s odkazom?"))
    return int(cr.rsplit("/", 1)[1])


def serve(ids, port=8787, creds=None):
    """Spustí server na pozadí.

    `ids` je meno v URL → Drive file id, `creds` z `drive/auth.py` (alebo None
    = verejný odkaz). Vracia (základná url, {meno: veľkosť}, štatistiky).
    """
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
    """Prostredie, v ktorom GDAL cez tento shim číta rozumne.

    `no_proxy` je podstatné: bez neho by GDAL posielal 127.0.0.1 cez proxy.
    `GDAL_DISABLE_READDIR_ON_OPEN` sa zámerne nenastavuje – skryl by `.ovr`
    vedľa `.tif`, a práve pyramídy robia hrubšie výrezy lacnými.
    `GDAL_HTTP_MAX_RETRY` a krátky `CONNECTTIMEOUT`: GDAL predvolene neopakuje
    nič a na spojenie čaká, kým sa nevzdá jadro.
    """
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
    ap.add_argument("--file", action="append", required=True, metavar="MENO=ID",
                    help="meno v URL a Drive file id; dá sa opakovať, aby "
                         "sa .tif a jeho .ovr podávali vedľa seba")
    ap.add_argument("--auth", action="store_true",
                    help="čítať prihlásený ako vlastník (GDRIVE_CREDENTIALS)")
    ap.add_argument("--port", type=int, default=8787, help="0 = vyber voľný")
    ap.add_argument("--print-url", action="store_true")
    args = ap.parse_args()

    ids = {}
    for spec in args.file:
        name, _, file_id = spec.partition("=")
        if not file_id:
            ap.error(f"--file čakalo MENO=ID, dostalo {spec!r}")
        ids[name] = file_id

    creds = None
    if args.auth:
        # až tu: `drive/auth.py` si spojenia berie odtiaľto, bol by to kruh
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "drive_auth", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "drive-auth.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        try:
            creds = mod.from_env()
            if creds is None:
                print("::error::--auth je zapnuté, ale v prostredí nie sú "
                      "prihlasovacie údaje (GDRIVE_CREDENTIALS).",
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
                print(f"  drive-serve: {stats['requests']:,} požiadaviek, "
                      f"{stats['bytes'] / 1e6:,.0f} MB", flush=True)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
