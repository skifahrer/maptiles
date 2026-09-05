#!/usr/bin/env python3
"""Zoženie 1 m LiDAR od ÚGKK (DMR 5.0) pre jeden výrez – s viacerými cestami.

ÚGKK nemá jeden zdokumentovaný spôsob, ako sa k DMR 5.0 dostať programovo, tak
sa skúšajú cesty po poradí a prvá, ktorá dá skutočný výškový raster, vyhráva:
ArcGIS ImageServer (`exportImage`), WCS (`GetCoverage`) a priame URL
(`--direct-urls`) z vládneho cloudu alebo Mapového klienta.

Výsledok je jeden GeoTIFF (COG) na výrez – ten sa zrkadlí do skladu.

Použitie:
    python3 workers/dem/fetch-ugkk.py --bbox=W,S,E,N --out=ugkk.tif
    python3 workers/dem/fetch-ugkk.py --bbox=… --out=… --direct-urls=a.zip,b.zip
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from importlib.machinery import SourceFileLoader

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
_probe = SourceFileLoader("probe", os.path.join(_HERE, "probe.py")).load_module()
UA = _probe.UA


def hms(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def download(url, path, timeout=300):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return os.path.getsize(path)


def is_elevation_raster(path, min_cell_m=2.5):
    """Je to naozaj výškový raster s dostatočne jemnou mriežkou?

    Bez tejto kontroly by ticho prešiel aj 10 m model alebo obrázok.
    """
    try:
        info = json.loads(run(["gdalinfo", "-json", path]).stdout)
    except Exception:
        return None
    gt = info.get("geoTransform")
    if not gt:
        return None
    wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
    dx, dy = abs(gt[1]), abs(gt[5])
    if wkt.startswith("GEOGCRS") or wkt.startswith("GEOGCS"):
        lat = info.get("cornerCoordinates", {}).get("center", [0, 49])[1]
        dx *= 111320 * math.cos(math.radians(lat))
        dy *= 110540
    bands = info.get("bands") or []
    dtype = bands[0].get("type", "") if bands else ""
    ok = max(dx, dy) <= min_cell_m and dtype in ("Float32", "Float64", "Int32", "Int16")
    return {"cell_m": max(dx, dy), "type": dtype, "ok": ok,
            "size": info.get("size")}


# ---------------------------------------------------------------- 1. ArcGIS
def try_arcgis(bbox, tmp, sources, tile_px=4000):
    src = json.load(open(sources))["ugkk"]
    # keď hostiteľ neodpovedá, nemá zmysel skúšať šesť ciest na tom istom stroji
    candidates = list(src["candidates"])

    # katalóg najprv: je to iný hostiteľ a dáva skutočné URL služieb
    if src.get("catalog"):
        print("  hľadám služby v metadátovom katalógu…")
        try:
            found = _probe.discover_from_catalog(src["catalog"])
            candidates = [u for u in found if "ImageServer" in u or "WCS" in u.upper()] + candidates
        except Exception as exc:
            print(f"   – katalóg zlyhal: {type(exc).__name__}")

    for d in src.get("directories", src.get("directory") and [src["directory"]] or []):
        ok, why = _probe.host_reachable(d)
        if not ok:
            print(f"  ✗ {urllib.parse.urlparse(d).hostname} neodpovedá ({why})")
            continue
        try:
            candidates += _probe.probe_directory(d)
        except Exception:
            pass

    if not candidates:
        return None

    service = None
    for url in dict.fromkeys(candidates):
        meta = _probe.probe_image_server(url)
        if meta["ok"] and (meta.get("pixel_m") or 99) <= 2:
            print(f"  ArcGIS: {url} (pixel {meta['pixel_m']} m)")
            service = url
            break
        why = meta.get("why") or f"pixel {meta.get('pixel_m')} m – to nie je 1 m model"
        print(f"  – {url}: {why}")
    if not service:
        return None

    w, s, e, n = bbox
    lat = (s + n) / 2
    mx = 111320 * math.cos(math.radians(lat))
    nx = max(1, math.ceil((e - w) * mx / tile_px))
    ny = max(1, math.ceil((n - s) * 110540 / tile_px))
    dx, dy = (e - w) / nx, (n - s) / ny
    print(f"  sťahujem {nx}×{ny} = {nx*ny} dlaždíc", flush=True)

    tiles, t0 = [], time.time()
    for iy in range(ny):
        for ix in range(nx):
            tw, ts = w + ix * dx, s + iy * dy
            te, tn = tw + dx, ts + dy
            out = os.path.join(tmp, f"ags-{iy:03d}-{ix:03d}.tif")
            try:
                d = _probe.fetch(service + "/exportImage", {
                    "f": "json", "bbox": f"{tw},{ts},{te},{tn}",
                    "bboxSR": "4326", "imageSR": "4326", "format": "tiff",
                    "pixelType": "F32",
                    "size": f"{max(1, round((te-tw)*mx))},{max(1, round((tn-ts)*110540))}",
                })
                if "href" not in d:
                    print(f"    ::warning::dlaždica {iy}/{ix}: {str(d)[:70]}")
                    continue
                download(d["href"], out)
                tiles.append(out)
            except Exception as exc:
                print(f"    ::warning::dlaždica {iy}/{ix}: {type(exc).__name__}")
            done = iy * nx + ix + 1
            el = time.time() - t0
            print(f"    [{done}/{nx*ny}] {hms(el)}, zostáva ~{hms(el/done*(nx*ny-done))}",
                  flush=True)
    return tiles or None


# ------------------------------------------------------------------- 2. WCS
def try_wcs(bbox, tmp, sources):
    src = json.load(open(sources))["ugkk"]
    w, s, e, n = bbox
    for base in src.get("wcs", []):
        ok, why = _probe.host_reachable(base)
        if not ok:
            print(f"  – WCS {base}: hostiteľ neodpovedá ({why})")
            continue
        try:
            caps = urllib.request.urlopen(urllib.request.Request(
                base + ("&" if "?" in base else "?") +
                "service=WCS&request=GetCapabilities", headers=UA),
                timeout=_probe.DEFAULT_TIMEOUT).read()
        except Exception as exc:
            print(f"  – WCS {base}: {type(exc).__name__}")
            continue
        if b"Capabilities" not in caps:
            print(f"  – WCS {base}: odpoveď nie je GetCapabilities")
            continue
        print(f"  WCS odpovedal: {base}")
        for cov in src.get("wcs_coverages", []):
            out = os.path.join(tmp, "wcs.tif")
            url = base + ("&" if "?" in base else "?") + urllib.parse.urlencode({
                "service": "WCS", "version": "2.0.1", "request": "GetCoverage",
                "coverageId": cov, "format": "image/tiff",
                "subset": f"Long({w},{e})",
            }) + f"&subset=Lat({s},{n})"
            try:
                download(url, out)
            except Exception as exc:
                print(f"    – {cov}: {type(exc).__name__}")
                continue
            meta = is_elevation_raster(out)
            if meta and meta["ok"]:
                print(f"    ✓ {cov}: bunka {meta['cell_m']:.1f} m, {meta['type']}")
                return [out]
            print(f"    – {cov}: {meta}")
    return None


# ---------------------------------------------------- 3. priame URL (istota)
def try_direct(urls, tmp):
    """Čo si stiahol ručne z vládneho cloudu alebo z Mapového klienta.

    Jediná cesta, ktorá nezávisí od toho, či ÚGKK nejakú službu zverejnil.
    """
    got = []
    for i, url in enumerate(u.strip() for u in urls if u.strip()):
        name = os.path.basename(urllib.parse.urlparse(url).path) or f"dem-{i}"
        path = os.path.join(tmp, name)
        try:
            mb = download(url, path) / 1048576
            print(f"  ✓ {name} ({mb:.0f} MB)")
        except Exception as exc:
            print(f"  ::warning::{url}: {type(exc).__name__}: {exc}")
            continue
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for m in z.namelist():
                    if m.lower().endswith((".tif", ".tiff", ".asc")):
                        z.extract(m, tmp)
                        got.append(os.path.join(tmp, m))
        else:
            got.append(path)
    return got or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", required=True, help="west,south,east,north")
    ap.add_argument("--out", required=True, help="výstupný GeoTIFF (COG)")
    ap.add_argument("--sources", default=os.path.join(_DATA, "dem-sources.json"))
    ap.add_argument("--direct-urls", default="",
                    help="čiarkami oddelené URL na .tif/.zip (posledná záchrana)")
    ap.add_argument("--max-cells", type=float, default=3e9,
                    help="strop buniek výrezu pri 1 m (0 = bez stropu)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    w, s, e, n = bbox
    lat = (s + n) / 2
    km2 = (e - w) * 111.32 * math.cos(math.radians(lat)) * (n - s) * 110.54
    cells = km2 * 1e6
    print(f"Výrez {args.bbox} = {km2:.0f} km² → {cells/1e9:.2f} mld. buniek pri 1 m")
    if args.max_cells and cells > args.max_cells:
        print(f"::error::To je {cells*4/1e9:.0f} GB vo Float32, strop je "
              f"{args.max_cells/1e9:.1f} mld. buniek. Metrový model má zmysel na "
              f"pohorie, nie na kraj – zvoľ menší výrez (input `area`).")
        return 2

    tmp = tempfile.mkdtemp(prefix="ugkk-", dir=os.path.dirname(args.out) or ".")
    t0 = time.time()
    try:
        tiles, how = None, ""
        if args.direct_urls:
            # priame URL majú prednosť: používateľ vie lepšie, čo chce, než
            # naše hádanie názvov služieb
            print("── 0. priame URL (zadané ručne)")
            tiles, how = try_direct(args.direct_urls.split(","), tmp), "priame URL"

        # dostupnosť hostiteľa najprv, nie až po neúspechu: všetky služby sú
        # na `skgeodesy.sk` a každá by vyčerpala štyri profily plus curl
        host_ok = True
        if not tiles:
            host_ok, why = _probe.host_reachable(
                json.load(open(args.sources))["ugkk"]["directory"])
            if not host_ok:
                print(f"── hostiteľ skgeodesy.sk neodpovedá ({why}) – "
                      f"ImageServer ani WCS nemá zmysel skúšať")
            else:
                print("── 1. ArcGIS ImageServer")
                tiles, how = try_arcgis(bbox, tmp, args.sources), "ArcGIS ImageServer"
                if not tiles:
                    print("── 2. WCS")
                    tiles, how = try_wcs(bbox, tmp, args.sources), "WCS"

        if not tiles:
            print("::error::Ani jedna cesta k ÚGKK DMR 5.0 nevyšla.")
            print()
            if not host_ok:
                # to podstatné zistenie: nie sú to zlé názvy služieb, ale celý
                # hostiteľ je z GitHub runnera nedostupný
                print("PRÍČINA: hostiteľ skgeodesy.sk z GitHub runnera vôbec")
                print("neodpovedá – HTTPS požiadavka na jeho koreň neprejde.")
                print("Nie sú to zle uhádnuté názvy služieb, nedá sa tam dostať.")
                print("Odkazy zo ZBGIS Mapového klienta preto v ugkk_urls tiež")
                print("nepomôžu, sú na tej istej doméne.")
                print()
                print("ČO FUNGUJE: stiahnuť DMR 5.0 raz ručne a nahrať do skladu.")
                print("  1. ZBGIS Mapový klient → Terén → Export údajov → DMR 5.0")
                print(f"     (vyber územie, do 400 km²)")
                print("  2. rozbaľ a zlep do jedného GeoTIFFu, napr.:")
                print("       gdalbuildvrt all.vrt *.tif")
                print("       gdal_translate -of COG -co COMPRESS=DEFLATE \\")
                print("         -co PREDICTOR=3 all.vrt " + os.path.basename(args.out))
                print(f"  3. nahraj do skladu na Drive:")
                print(f"       python3 workers/drive/store.py --put "
                      f"--store=dem-ugkk --file={os.path.basename(args.out)}")
                print("  Odvtedy si to build berie zo skladu a nič nesťahuje.")
                print()
                print("Alebo: ugkk_urls s odkazom, ktorý JE z GitHubu dostupný.")
            else:
                print("Hostiteľ odpovedá, ale ani jedna služba nedala 1 m raster.")
                print("Skús ugkk_urls s priamymi odkazmi zo ZBGIS Mapového klienta")
                print("(Terén → Export údajov → DMR 5.0, do 400 km²).")
            return 1

        # zlepiť a uložiť ako COG – jeden súbor na výrez
        vrt = os.path.join(tmp, "all.vrt")
        run(["gdalbuildvrt", "-q", "-resolution", "highest", vrt] + tiles)
        run(["gdalwarp", "-q", "-overwrite", "-te", repr(w), repr(s), repr(e), repr(n),
             "-t_srs", "EPSG:4326", "-r", "bilinear", "-ot", "Float32",
             "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
             "-co", "BIGTIFF=YES", vrt, args.out])

        meta = is_elevation_raster(args.out)
        mb = os.path.getsize(args.out) / 1048576
        print(f"\n✓ Hotové cez: {how}")
        print(f"  {args.out}: {mb:.0f} MB, bunka ~{meta['cell_m']:.2f} m, "
              f"{meta['type']}, {meta['size']} px, trvalo {hms(time.time()-t0)}")
        if not meta["ok"]:
            print(f"::warning::Bunka {meta['cell_m']:.1f} m nie je 1 m model – "
                  f"skontroluj, či to naozaj je DMR 5.0.")
        return 0
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
