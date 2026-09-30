#!/usr/bin/env python3
"""Find out whether and from where ÚGKK's 1 m LiDAR (DMR 5.0) can be downloaded.

`*.skgeodesy.sk` isn't visible from every network and the ArcGIS service names
are undocumented, so a probe lists the service directory, asks each candidate
from `dem-sources.json` for metadata, and asks a responder for a small GeoTIFF.

Usage:
    python3 workers/dem/probe.py [--bbox=W,S,E,N] [--summary=FILE]
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

# geoportals behind a WAF drop non-browser requests silently; several header sets are tried
BROWSERS = [
    ("Safari 17 / macOS", {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.4 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }),
    ("Chrome 124 / Windows", {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "sk-SK,sk;q=0.9,en-US;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }),
    ("ArcGIS client", {
        # some ArcGIS servers let only "their" clients in
        "User-Agent": "ArcGIS Pro 3.2 (Esri)",
        "Accept": "*/*",
        "Referer": "https://zbgis.skgeodesy.sk/mkzbgis/",
    }),
    ("fricomaps", {
        "User-Agent": "fricomaps-dem/1 (+https://github.com/skifahrer/fricomaps)",
        "Accept": "*/*",
    }),
]

# the default headers are the first profile; `smart_get` reports which passed
UA = dict(BROWSERS[0][1])
# a small cut-out where LiDAR surely is – otherwise an empty answer looks like an error
TEST_BBOX = (20.12, 49.15, 20.16, 49.18)


# short timeouts on purpose: a silent server should be known in seconds
DEFAULT_TIMEOUT = 12


def host_reachable(url, timeout=8):
    """Does the machine answer at all? A real HTTPS request (behind a proxy TCP always opens)."""
    p = urllib.parse.urlparse(url)
    root = f"{p.scheme}://{p.netloc}/"
    for name, headers in BROWSERS:
        try:
            req = urllib.request.Request(root, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return True, f"HTTP {r.status} ({name})"
        except urllib.error.HTTPError as exc:
            # 403/404 at the root is fine – the server exists and answers
            return True, f"HTTP {exc.code} ({name})"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
    # curl too – another TLS stack passes some WAFs python doesn't
    try:
        r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                            "--http2", "--max-time", str(timeout), "-A",
                            BROWSERS[0][1]["User-Agent"], root],
                           capture_output=True, timeout=timeout + 5)
        code = r.stdout.decode(errors="replace").strip()
        if code and code != "000":
            return True, f"HTTP {code} (curl)"
        last = "curl: " + r.stderr[:80].decode(errors="replace").strip().replace("\n", " ")
    except Exception as exc:
        last = f"curl: {type(exc).__name__}"
    return False, last


def smart_get(url, timeout=DEFAULT_TIMEOUT, want_binary=True):
    """Download a URL looking like a browser: (data, how) or (None, attempts)."""
    tried = []
    for name, headers in BROWSERS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), f"urllib / {name}"
        except Exception as exc:
            tried.append(f"urllib/{name}: {type(exc).__name__}")

    # curl's own TLS stack and HTTP/2 pass where a connection fingerprint blocks python
    name, headers = BROWSERS[0]
    cmd = ["curl", "-sS", "--fail", "--http2", "--compressed",
           "--max-time", str(int(timeout * 2)), "-L"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout * 3)
        if r.returncode == 0 and r.stdout:
            return r.stdout, f"curl / {name}"
        tried.append(f"curl: rc={r.returncode} {r.stderr[:60].decode(errors='replace')}")
    except Exception as exc:
        tried.append(f"curl: {type(exc).__name__}")
    return None, tried


def fetch(url, params=None, timeout=DEFAULT_TIMEOUT, binary=False):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data, how = smart_get(url, timeout=timeout)
    if data is None:
        raise urllib.error.URLError("; ".join(how))
    return data if binary else json.loads(data.decode("utf-8", "replace"))


def discover_from_catalog(urls, timeout=DEFAULT_TIMEOUT):
    """Service URLs from the metadata catalogue (RPI / geoportal.gov.sk), another host."""
    import re
    found = []
    for url in urls:
        data, how = smart_get(url, timeout=timeout)
        if data is None:
            print(f"   – catalogue {url}: {how[0] if isinstance(how, list) else how}")
            continue
        text = data.decode("utf-8", "replace")
        hits = re.findall(
            r'https?://[^\s"\'<>\\]+?(?:ImageServer|MapServer|/wcs|/wms|WCSServer|'
            r'WMSServer|\.tif|\.zip)[^\s"\'<>\\]*', text, re.I)
        uniq = list(dict.fromkeys(hits))
        print(f"   ✓ catalogue {url} ({how}) – {len(uniq)} service links")
        for u in uniq[:20]:
            print(f"       {u}")
        found += uniq
    return found


def probe_directory(url):
    print(f"\n── Service directory: {url}")
    ok, why = host_reachable(url)
    if not ok:
        print(f"   ✗ the host doesn't answer ({why})")
        print(f"      → {urllib.parse.urlparse(url).hostname} can't be reached "
              f"from this machine at all; it isn't about the service name.")
        return []
    try:
        d = fetch(url, {"f": "json"})
    except Exception as exc:
        print(f"   ✗ unreachable: {type(exc).__name__}: {exc}")
        return []
    folders = d.get("folders", [])
    services = d.get("services", [])
    print(f"   ✓ answered – {len(services)} services, {len(folders)} folders")
    for f in folders:
        print(f"     folder: {f}")
    found = []
    for s in services:
        line = f"     {s.get('name')} ({s.get('type')})"
        print(line)
        if s.get("type") == "ImageServer":
            found.append(f"{url}/{s['name'].split('/')[-1]}/ImageServer")
    return found


def probe_image_server(url):
    """A service's metadata: resolution, extent, type."""
    try:
        d = fetch(url, {"f": "json"})
    except urllib.error.HTTPError as exc:
        return {"ok": False, "why": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}"}
    if "error" in d:
        return {"ok": False, "why": str(d["error"].get("message", "error"))[:60]}
    px = d.get("pixelSizeX")
    ext = d.get("extent", {})
    return {
        "ok": True,
        "pixel_m": px,
        "type": d.get("serviceDataType", "?"),
        "wkid": (ext.get("spatialReference") or {}).get("latestWkid")
                or (ext.get("spatialReference") or {}).get("wkid"),
        "name": d.get("name", ""),
        "desc": (d.get("description") or "")[:80].replace("\n", " "),
    }


def probe_export(url, bbox):
    """Ask for a small cut-out and check a GeoTIFF came."""
    w, s, e, n = bbox
    # a ~1 m grid: how many pixels such a cut-out is in metres
    px = max(1, min(2048, int((e - w) * 111320 * 0.66)))
    py = max(1, min(2048, int((n - s) * 110540)))
    try:
        d = fetch(url + "/exportImage", {
            "f": "json", "bbox": f"{w},{s},{e},{n}",
            "bboxSR": "4326", "imageSR": "4326",
            "format": "tiff", "pixelType": "F32",
            "size": f"{px},{py}",
        })
    except Exception as exc:
        return {"ok": False, "why": f"exportImage: {type(exc).__name__}"}
    if "href" not in d:
        return {"ok": False, "why": f"no href: {str(d)[:70]}"}
    try:
        raw = fetch(d["href"], binary=True, timeout=90)
    except Exception as exc:
        return {"ok": False, "why": f"download: {type(exc).__name__}"}
    # a GeoTIFF starts "II*\0" (little endian) or "MM\0*" (big endian)
    if raw[:2] not in (b"II", b"MM"):
        return {"ok": False, "why": f"not a TIFF ({raw[:12]!r})"}
    return {"ok": True, "bytes": len(raw), "px": f"{px}×{py}"}


def diagnose(sources):
    """A host × browser profile matrix – "would posing as Safari help?" answered with data."""
    src = json.load(open(sources))["ugkk"]
    hosts = []
    for u in (src.get("directories", []) + src.get("candidates", [])
              + src.get("wcs", []) + src.get("catalog", [])):
        h = urllib.parse.urlparse(u).netloc
        if h and h not in hosts:
            hosts.append(h)
    # a control host: if even it fails, the runner's network is the problem
    hosts.append("pypi.org")

    print("── Host reachability (GET on the root, each profile apart)")
    rows = []
    for h in hosts:
        cells = []
        for name, headers in BROWSERS:
            try:
                req = urllib.request.Request(f"https://{h}/", headers=headers)
                with urllib.request.urlopen(req, timeout=10) as r:
                    cells.append(f"{r.status}")
            except urllib.error.HTTPError as exc:
                cells.append(f"{exc.code}")
            except Exception as exc:
                cells.append(type(exc).__name__.replace("Error", "!"))
        try:
            r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                                "--http2", "--max-time", "10", "-A",
                                BROWSERS[0][1]["User-Agent"], f"https://{h}/"],
                               capture_output=True, timeout=15)
            cells.append(r.stdout.decode(errors="replace").strip() or "000")
        except Exception:
            cells.append("000")
        rows.append((h, cells))
        print(f"   {h:<34} " + "  ".join(f"{c:>8}" for c in cells))
    print("   " + " " * 34 + "  ".join(f"{n.split()[0]:>8}" for n, _ in BROWSERS)
          + f"  {'curl':>8}")
    print("\n   (a number = HTTP code, the server answered; a short name = an exception)")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnose", action="store_true",
                    help="only the host reachability matrix, download nothing")
    ap.add_argument("--sources", default="workers/data/dem-sources.json")
    ap.add_argument("--bbox", default=",".join(str(v) for v in TEST_BBOX))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    args = ap.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(","))

    if args.diagnose:
        diagnose(args.sources)
        return 0

    src = json.load(open(args.sources))["ugkk"]
    print(f"Looking for: {src['label']}")
    print(f"Test cut-out: {args.bbox} (Vysoké Tatry)")

    # 1. the directory – so what is really there shows
    discovered = probe_directory(src["directory"])

    # 2. candidates from the file + what the directory had
    todo, seen = [], set()
    for u in list(src["candidates"]) + discovered:
        if u not in seen:
            seen.add(u)
            todo.append(u)

    print(f"\n── Trying {len(todo)} services")
    rows, winner = [], None
    for u in todo:
        meta = probe_image_server(u)
        if not meta["ok"]:
            print(f"   ✗ {u}\n       {meta['why']}")
            rows.append((u, "✗", meta["why"], ""))
            continue
        px = meta.get("pixel_m")
        print(f"   ✓ {u}\n       pixel {px} m, {meta['type']}, EPSG:{meta['wkid']}, {meta['desc']}")
        exp = probe_export(u, bbox)
        if exp["ok"]:
            note = f"{exp['px']} px, {exp['bytes']//1024} kB"
            print(f"       exportImage OK – {note}")
            rows.append((u, "✓", f"pixel {px} m, {meta['type']}", note))
            if winner is None and px and px <= 2:
                winner = u
        else:
            print(f"       exportImage failed: {exp['why']}")
            rows.append((u, "~", f"pixel {px} m, metadata OK", exp["why"]))

    print("\n── Result")
    if winner:
        print(f"✓ USABLE: {winner}")
        print("  Write it as the first candidate into workers/data/dem-sources.json")
        print("  and `dem_source: ugkk` will work.")
    else:
        usable = [r for r in rows if r[1] == "✓"]
        if usable:
            print("~ Something answered, but nothing with a grid ≤ 2 m – that isn't DMR 5.0.")
        else:
            print("✗ Not one service answered usably.")
        print("  ÚGKK officially gives DMR 5.0 through the ZBGIS map client (an")
        print("  interactive export up to 400 km²) and the government cloud. Without")
        print("  an ImageServer, the only way is downloading it once by hand and")
        print("  mirroring it – as the workflow *Data · elevation models* does")
        print("  for Sonny.")

    if args.summary:
        with open(args.summary, "a") as f:
            f.write("# Probe: ÚGKK DMR 5.0 (1 m LiDAR)\n\n")
            f.write(f"Test cut-out `{args.bbox}` (Vysoké Tatry)\n\n")
            f.write("| service | state | metadata | exportImage |\n|---|:-:|---|---|\n")
            for u, st, meta, note in rows:
                f.write(f"| `{u}` | {st} | {meta} | {note} |\n")
            f.write("\n")
            if winner:
                f.write(f"**✓ Usable:** `{winner}`\n\n"
                        "Write it as the first candidate into `workers/data/dem-sources.json`"
                        " and `dem_source: ugkk` will work.\n")
            else:
                f.write("**✗ Nothing usable.** ÚGKK officially gives DMR 5.0 through "
                        "the ZBGIS map client (an interactive export up to 400 km²) and "
                        "the government cloud. Without an ImageServer, the only way is "
                        "downloading it once by hand and mirroring it – as "
                        "*Data · elevation models* does for Sonny.\n")
    return 0 if winner else 1


if __name__ == "__main__":
    sys.exit(main())
