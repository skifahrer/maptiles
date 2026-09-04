#!/usr/bin/env python3
"""Zistí, či a odkiaľ sa dá stiahnuť 1 m LiDAR od ÚGKK (DMR 5.0).

Hostiteľov `*.skgeodesy.sk` nevidno z každej siete a názvy služieb v ArcGIS
adresári nie sú zdokumentované, tak sa namiesto hádania spustí sonda: stiahne
adresár služieb, pre každého kandidáta z `dem-sources.json` zistí metadáta
a z toho, čo odpovedalo, si vypýta malý výrez a overí, že prišiel GeoTIFF.

Použitie:
    python3 workers/dem/probe.py [--bbox=W,S,E,N] [--summary=SÚBOR]
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

# geoportály za WAF-om bežne zahadzujú požiadavky, ktoré nevyzerajú ako
# prehliadač – a nie chybou, ale tichom, čo vyzerá ako výpadok siete.
# Skúša sa viac profilov: blokuje sa podľa celej sady hlavičiek.
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
    ("ArcGIS klient", {
        # niektoré ArcGIS servery naopak púšťajú len „svojich" klientov
        "User-Agent": "ArcGIS Pro 3.2 (Esri)",
        "Accept": "*/*",
        "Referer": "https://zbgis.skgeodesy.sk/mkzbgis/",
    }),
    ("fricomaps", {
        "User-Agent": "fricomaps-dem/1 (+https://github.com/skifahrer/fricomaps)",
        "Accept": "*/*",
    }),
]

# predvolené hlavičky sú prvý profil; ktorý prešiel, hlási `smart_get`
UA = dict(BROWSERS[0][1])
# malý výrez tam, kde LiDAR určite je – inak by prázdna odpoveď vyzerala
# ako chyba
TEST_BBOX = (20.12, 49.15, 20.16, 49.18)


# krátke timeouty zámerne: keď server neodpovie, chceme to vedieť za sekundy
DEFAULT_TIMEOUT = 12


def host_reachable(url, timeout=8):
    """Odpovie vôbec ten stroj? Rozlišuje „server nie je" od „cesta nie je".

    Testuje sa skutočným HTTPS požiadavkom na koreň, nie TCP spojením: za
    proxy sa TCP otvorí vždy (na proxy) a až CONNECT sa odmietne.
    """
    p = urllib.parse.urlparse(url)
    root = f"{p.scheme}://{p.netloc}/"
    for name, headers in BROWSERS:
        try:
            req = urllib.request.Request(root, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return True, f"HTTP {r.status} ({name})"
        except urllib.error.HTTPError as exc:
            # 403/404 na koreni je v poriadku – server existuje a odpovedá
            return True, f"HTTP {exc.code} ({name})"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
    # ešte curl – iný TLS stack prejde cez niektoré WAF-y tam, kde python nie
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
    """Stiahne URL a skúša pritom vyzerať ako prehliadač.

    Vracia (dáta, čím sa to podarilo) alebo (None, zoznam pokusov): najprv
    profily hlavičiek cez urllib, potom `curl` (iný TLS stack a HTTP/2).
    """
    tried = []
    for name, headers in BROWSERS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), f"urllib / {name}"
        except Exception as exc:
            tried.append(f"urllib/{name}: {type(exc).__name__}")

    # curl má vlastný TLS stack a vie HTTP/2 – tam, kde blokujú podľa odtlačku
    # spojenia, python neprejde a curl áno (alebo naopak)
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
    """Vytiahne URL služieb z metadátového katalógu (RPI / geoportal.gov.sk).

    Hádať názvy služieb je slabé; katalóg ich má v `distributionInfo`. Navyše
    je to iný hostiteľ, takže to môže prejsť aj tam, kde skgeodesy nie.
    """
    import re
    found = []
    for url in urls:
        data, how = smart_get(url, timeout=timeout)
        if data is None:
            print(f"   – katalóg {url}: {how[0] if isinstance(how, list) else how}")
            continue
        text = data.decode("utf-8", "replace")
        hits = re.findall(
            r'https?://[^\s"\'<>\\]+?(?:ImageServer|MapServer|/wcs|/wms|WCSServer|'
            r'WMSServer|\.tif|\.zip)[^\s"\'<>\\]*', text, re.I)
        uniq = list(dict.fromkeys(hits))
        print(f"   ✓ katalóg {url} ({how}) – {len(uniq)} odkazov na služby")
        for u in uniq[:20]:
            print(f"       {u}")
        found += uniq
    return found


def probe_directory(url):
    print(f"\n── Adresár služieb: {url}")
    ok, why = host_reachable(url)
    if not ok:
        print(f"   ✗ hostiteľ neodpovedá ({why})")
        print(f"      → z tohto stroja sa na {urllib.parse.urlparse(url).hostname} "
              f"nedá dostať vôbec; nie je to otázka názvu služby.")
        return []
    try:
        d = fetch(url, {"f": "json"})
    except Exception as exc:
        print(f"   ✗ nedostupný: {type(exc).__name__}: {exc}")
        return []
    folders = d.get("folders", [])
    services = d.get("services", [])
    print(f"   ✓ odpovedal – {len(services)} služieb, {len(folders)} priečinkov")
    for f in folders:
        print(f"     priečinok: {f}")
    found = []
    for s in services:
        line = f"     {s.get('name')} ({s.get('type')})"
        print(line)
        if s.get("type") == "ImageServer":
            found.append(f"{url}/{s['name'].split('/')[-1]}/ImageServer")
    return found


def probe_image_server(url):
    """Metadáta služby: rozlíšenie, rozsah, typ. None = neodpovedala."""
    try:
        d = fetch(url, {"f": "json"})
    except urllib.error.HTTPError as exc:
        return {"ok": False, "why": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}"}
    if "error" in d:
        return {"ok": False, "why": str(d["error"].get("message", "chyba"))[:60]}
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
    """Vypýta si malý výrez a overí, že prišiel GeoTIFF."""
    w, s, e, n = bbox
    # ~1 m mriežka: koľko pixelov je taký výrez v metroch
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
        return {"ok": False, "why": f"bez href: {str(d)[:70]}"}
    try:
        raw = fetch(d["href"], binary=True, timeout=90)
    except Exception as exc:
        return {"ok": False, "why": f"sťahovanie: {type(exc).__name__}"}
    # GeoTIFF začína "II*\0" (little endian) alebo "MM\0*" (big endian)
    if raw[:2] not in (b"II", b"MM"):
        return {"ok": False, "why": f"nie je TIFF ({raw[:12]!r})"}
    return {"ok": True, "bytes": len(raw), "px": f"{px}×{py}"}


def diagnose(sources):
    """Matica hostiteľ × profil prehliadača – odkiaľ sa kam dá dostať.

    Jediný spôsob, ako na otázku „pomôže tváriť sa ako Safari?" odpovedať dátami.
    """
    src = json.load(open(sources))["ugkk"]
    hosts = []
    for u in (src.get("directories", []) + src.get("candidates", [])
              + src.get("wcs", []) + src.get("catalog", [])):
        h = urllib.parse.urlparse(u).netloc
        if h and h not in hosts:
            hosts.append(h)
    # kontrolný hostiteľ: keď neprejde ani ten, problém je v sieti runnera
    hosts.append("pypi.org")

    print("── Dostupnosť hostiteľov (GET na koreň, každý profil zvlášť)")
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
    print("\n   (číslo = HTTP kód, teda server odpovedal; skratka = výnimka)")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnose", action="store_true",
                    help="len matica dostupnosti hostiteľov, nič nesťahuj")
    ap.add_argument("--sources", default="workers/data/dem-sources.json")
    ap.add_argument("--bbox", default=",".join(str(v) for v in TEST_BBOX))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    args = ap.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(","))

    if args.diagnose:
        diagnose(args.sources)
        return 0

    src = json.load(open(args.sources))["ugkk"]
    print(f"Hľadám: {src['label']}")
    print(f"Testovací výrez: {args.bbox} (Vysoké Tatry)")

    # 1. adresár – nech je vidieť, čo tam naozaj je
    discovered = probe_directory(src["directory"])

    # 2. kandidáti zo súboru + čo sa našlo v adresári
    todo, seen = [], set()
    for u in list(src["candidates"]) + discovered:
        if u not in seen:
            seen.add(u)
            todo.append(u)

    print(f"\n── Skúšam {len(todo)} služieb")
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
            print(f"       exportImage zlyhal: {exp['why']}")
            rows.append((u, "~", f"pixel {px} m, metadáta OK", exp["why"]))

    print("\n── Výsledok")
    if winner:
        print(f"✓ POUŽITEĽNÉ: {winner}")
        print("  Zapíš ho ako prvého kandidáta do workers/data/dem-sources.json")
        print("  a `dem_source: ugkk` bude fungovať.")
    else:
        usable = [r for r in rows if r[1] == "✓"]
        if usable:
            print("~ Niečo odpovedalo, ale nič s mriežkou ≤ 2 m – to nie je DMR 5.0.")
        else:
            print("✗ Ani jedna služba neodpovedala tak, aby sa dala použiť.")
        print("  ÚGKK oficiálne dáva DMR 5.0 cez ZBGIS Mapový klient (interaktívny")
        print("  export do 400 km²) a cez vládny cloud. Ak ImageServer neexistuje,")
        print("  jediná cesta je stiahnuť to raz ručne a nazrkadliť do releasu –")
        print("  presne tak, ako to robí workflow *Dáta · výškové modely*")
        print("  pre Sonnyho.")

    if args.summary:
        with open(args.summary, "a") as f:
            f.write("# Sonda: ÚGKK DMR 5.0 (1 m LiDAR)\n\n")
            f.write(f"Testovací výrez `{args.bbox}` (Vysoké Tatry)\n\n")
            f.write("| služba | stav | metadáta | exportImage |\n|---|:-:|---|---|\n")
            for u, st, meta, note in rows:
                f.write(f"| `{u}` | {st} | {meta} | {note} |\n")
            f.write("\n")
            if winner:
                f.write(f"**✓ Použiteľné:** `{winner}`\n\n"
                        "Zapíš ho ako prvého kandidáta do `workers/data/dem-sources.json`"
                        " a `dem_source: ugkk` bude fungovať.\n")
            else:
                f.write("**✗ Nič použiteľné.** ÚGKK oficiálne dáva DMR 5.0 cez ZBGIS "
                        "Mapový klient (interaktívny export do 400 km²) a cez vládny "
                        "cloud. Ak ImageServer neexistuje, jediná cesta je stiahnuť "
                        "to raz ručne a nazrkadliť do releasu – tak, ako to robí "
                        "*Dáta · výškové modely* pre Sonnyho.\n")
    return 0 if winner else 1


if __name__ == "__main__":
    sys.exit(main())
