#!/usr/bin/env python3
"""World map sources – water, state borders and download regions, from five files.

    data/world/water.gpkg          seas and oceans   OSM (osmdata.openstreetmap.de)
    data/world/lakes.geojson       lakes             Natural Earth 10m
    data/world/boundaries.geojson  state borders     Natural Earth 10m
    data/world/countries.geojson   states (labels)   Natural Earth 10m
    data/world/downloads.geojson   download regions  Geofabrik index-v1.json

Usage (runs locally too):
    python3 workers/world/sources.py --out=data/world
    python3 workers/world/sources.py --out=data/world --only=downloads
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

# sizes feed the plan's time estimate; a big mismatch is logged after download
NE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master"
      "/geojson")
SOURCES = {
    "countries": {
        "url": f"{NE}/ne_10m_admin_0_countries.geojson",
        "file": "ne_10m_admin_0_countries.geojson",
        "mb": 13.3,
        "what": "states (labels) – Natural Earth 10m",
    },
    "boundaries": {
        "url": f"{NE}/ne_10m_admin_0_boundary_lines_land.geojson",
        "file": "ne_10m_admin_0_boundary_lines_land.geojson",
        "mb": 2.3,
        "what": "state borders – Natural Earth 10m",
    },
    "lakes": {
        "url": f"{NE}/ne_10m_lakes.geojson",
        "file": "ne_10m_lakes.geojson",
        "mb": 5.0,
        "what": "lakes – Natural Earth 10m",
    },
    "water": {
        "url": ("https://osmdata.openstreetmap.de/download/"
                "simplified-water-polygons-split-3857.zip"),
        "file": "simplified-water-polygons-split-3857.zip",
        "mb": 60.0,
        "what": "seas and oceans – from OSM coastlines (simplified, z0–z9)",
    },
    "downloads": {
        "url": "https://download.geofabrik.de/index-v1.json",
        "file": "geofabrik-index-v1.json",
        "mb": 15.0,
        "what": "OSM download regions – Geofabrik index-v1.json",
    },
}

# "obviously broken" floor: an error page must fail here, not as a map without borders
MINIMUM = {
    "countries": 150,
    "boundaries": 200,
    "lakes": 300,
    "downloads": 100,
    "water": 1000,
}

ATTEMPTS = 4        # a foreign server may hiccup without failing the run
TIMEOUT = 120       # s


def log(msg):
    print(msg, flush=True)


def human(bytes_):
    for unit in ("B", "kB", "MB", "GB"):
        if bytes_ < 1024 or unit == "GB":
            return f"{bytes_:.0f} {unit}" if unit == "B" \
                else f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} GB"


def took(sec):
    return f"{sec:.0f} s" if sec < 90 else f"{sec / 60:.1f} min"


def _download_once(url, dest, what, mb):
    """One attempt, with progress so an hour of silence doesn't look stuck."""
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        total = int(r.headers.get("Content-Length") or 0)
        estimate = total or int(mb * 1024 * 1024)
        have = 0
        last = t0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                # at most every 5 s
                if time.time() - last >= 5:
                    last = time.time()
                    done = have / estimate if estimate else 0
                    elapsed = time.time() - t0
                    left = (elapsed / done - elapsed) if done > 0.02 else 0
                    log(f"    {human(have)} of {human(estimate)} "
                        f"({done * 100:.0f} %), ~{took(left)} left")
    return have, time.time() - t0


def download(key, where):
    """Downloads a source into `where` unless there; via `.part` so no half file looks done."""
    z = SOURCES[key]
    dest = os.path.join(where, z["file"])
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log(f"  {z['what']}: already downloaded ✓ ({human(os.path.getsize(dest))})")
        return dest
    for attempt in range(1, ATTEMPTS + 1):
        try:
            size, elapsed = _download_once(z["url"], dest + ".part",
                                           z["what"], z["mb"])
            os.replace(dest + ".part", dest)
            ratio = size / (z["mb"] * 1024 * 1024) if z["mb"] else 1
            log(f"  {z['what']}: {human(size)} in {took(elapsed)}"
                + (f" (estimate was {z['mb']:.1f} MB, so {ratio:.1f}×)"
                   if ratio < 0.5 or ratio > 2 else ""))
            return dest
        except (urllib.error.URLError, OSError, TimeoutError,
                ValueError) as exc:
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            if attempt == ATTEMPTS:
                raise SystemExit(
                    f"::error::{z['what']} couldn't be downloaded in "
                    f"{ATTEMPTS} attempts ({exc}). Try the run again – it's "
                    f"a foreign server ({z['url']}). If it persists, replace "
                    f"the link in SOURCES in `workers/world/sources.py` "
                    f"with a mirror.")
            wait = 5 * 2 ** (attempt - 1)
            log(f"::warning::{z['what']}: attempt {attempt} of {ATTEMPTS} failed "
                f"({exc}) – retrying in {wait} s.")
            time.sleep(wait)
    return dest


def read_geojson(path, what):
    """GeoJSON from a file; a bad shape is a hard error, not an empty layer."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as exc:
        raise SystemExit(
            f"::error::{what}: the downloaded file isn't valid JSON ({exc}). "
            f"It's usually a server error page saved as data – delete "
            f"`{path}` and run again.")
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise SystemExit(
            f"::error::{what}: `{path}` isn't a FeatureCollection with features. "
            f"The source format changed – see `workers/world/sources.py`.")
    return data["features"]


def write_geojson(path, features, key, what):
    """Saves the features and checks there are at least as many as make sense."""
    minimum = MINIMUM[key]
    if len(features) < minimum:
        raise SystemExit(
            f"::error::{what}: {len(features)} features, at least "
            f"{minimum} expected. Such a layer would be silently missing from "
            f"the map, so failing instead. Check whether the source's attribute "
            f"names changed (`workers/world/sources.py`).")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    log(f"  {what}: {len(features)} features → {path} "
        f"({human(os.path.getsize(path))})")


def prop(props, *names, default=""):
    """First filled property of the names, any case (`NAME` × `name` vary by release)."""
    for name in names:
        for candidate in (name, name.upper(), name.lower()):
            value = props.get(candidate)
            if value not in (None, "", -99, "-99"):
                return value
    return default


# Natural Earth field → `name:xx`, app languages only
NE_LANGUAGES = {"AR": "ar", "DE": "de", "EL": "el", "EN": "en", "ES": "es", "FR": "fr",
             "HI": "hi", "HU": "hu", "IT": "it", "JA": "ja", "KO": "ko", "NL": "nl",
             "PL": "pl", "PT": "pt", "RU": "ru", "SV": "sv", "TR": "tr", "UK": "uk",
             "ZH": "zh-Hans", "ZHT": "zh-Hant"}


def names_by_language(props):
    """`name:xx` from `NAME_XX` fields, empty ones skipped."""
    out = {}
    for field, lang in NE_LANGUAGES.items():
        name = prop(props, f"NAME_{field}")
        if name:
            out[f"name:{lang}"] = name
    return out


def prepare_countries(src, out):
    """States → label points; polygons kept so Planetiler computes the centroid."""
    result = []
    for feature in read_geojson(src, "states"):
        p = feature.get("properties") or {}
        if not feature.get("geometry"):
            continue
        rank = prop(p, "LABELRANK", default=6)
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = 6
        result.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                "name": prop(p, "NAME", "NAME_EN"),
                "name_en": prop(p, "NAME_EN", "NAME"),
                **names_by_language(p),
                "iso": prop(p, "ISO_A2_EH", "ISO_A2"),
                "continent": prop(p, "CONTINENT"),
                # a class, since `include_when` compares values, not ranges
                "rank": "major" if rank <= 2 else
                        ("mid" if rank <= 4 else "minor"),
            },
        })
    write_geojson(out, result, "countries", "states (labels)")


def prepare_boundaries(src, out):
    """State borders → lines, certain or disputed (drawn dashed)."""
    result = []
    for feature in read_geojson(src, "state borders"):
        p = feature.get("properties") or {}
        if not feature.get("geometry"):
            continue
        cla = str(prop(p, "FEATURECLA")).lower()
        result.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                "kind": "country" if "international" in cla else "disputed",
            },
        })
    write_geojson(out, result, "boundaries", "state borders")


def prepare_lakes(src, out):
    """Lakes → areas; large ones enter the map before small ones."""
    result = []
    for feature in read_geojson(src, "lakes"):
        p = feature.get("properties") or {}
        if not feature.get("geometry"):
            continue
        rank = prop(p, "SCALERANK", default=8)
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = 8
        result.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                "kind": "lake",
                "name": prop(p, "NAME"),
                "rank": "major" if rank <= 2 else "minor",
            },
        })
    write_geojson(out, result, "lakes", "lakes")


def prepare_downloads(src, out):
    """Geofabrik `index-v1.json` → download regions with their tree level (from the parent chain)."""
    features = read_geojson(src, "download regions")
    parent = {}
    for feature in features:
        p = feature.get("properties") or {}
        if p.get("id"):
            parent[p["id"]] = p.get("parent") or ""

    def depth(ident):
        step, seen = 0, set()
        while parent.get(ident) and ident not in seen:
            seen.add(ident)
            ident = parent[ident]
            step += 1
            if step > 10:      # a cycle in the data
                break
        return step

    LEVELS = ("continent", "country", "subregion")
    result = []
    for feature in features:
        p = feature.get("properties") or {}
        if not feature.get("geometry") or not p.get("id"):
            continue
        urls = p.get("urls") or {}
        result.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                "id": p["id"],
                "name": p.get("name") or p["id"],
                "parent": p.get("parent") or "",
                "level": LEVELS[min(depth(p["id"]), len(LEVELS) - 1)],
                # a link that really downloads – the point of it all
                "pbf": urls.get("pbf") or "",
            },
        })
    no_link = sum(1 for f in result if not f["properties"]["pbf"])
    if no_link:
        log(f"::warning::{no_link} regions have no `.pbf` link in the index – "
            f"they'll be in the map, but without a download link.")
    write_geojson(out, result, "downloads", "download regions")


def prepare_water(zip_path, out):
    """OSM water areas: shapefile in EPSG:3857 → GeoPackage in EPSG:4326 (projection visible in the log)."""
    if shutil.which("ogr2ogr") is None:
        raise SystemExit(
            "::error::`ogr2ogr` isn't here. Water areas are a shapefile "
            "in EPSG:3857 and need projecting – install `gdal-bin` "
            "(in the pipeline `workers/world/build.sh` does it).")
    # the file name inside the ZIP changes between releases
    with zipfile.ZipFile(zip_path) as z:
        shp = [n for n in z.namelist() if n.lower().endswith(".shp")]
    if not shp:
        raise SystemExit(
            f"::error::`{zip_path}` has no `.shp`. Was the whole file "
            f"downloaded? Delete it and run again.")
    source = f"/vsizip/{os.path.abspath(zip_path)}/{shp[0]}"
    log(f"  water areas: {shp[0]} in the ZIP → {out}")
    t0 = time.time()
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(
        ["ogr2ogr", "-f", "GPKG", out, source,
         "-nln", "water", "-t_srs", "EPSG:4326",
         "-nlt", "PROMOTE_TO_MULTI", "-makevalid",
         "-progress"],
        check=True)
    # an empty GeoPackage is valid and would make a map without sea
    info = subprocess.run(
        ["ogrinfo", "-so", out, "water"],
        capture_output=True, text=True, check=False).stdout
    line = [r for r in info.split("\n") if "Feature Count" in r]
    count = int(line[0].split(":")[-1].strip()) if line else 0
    if count < MINIMUM["water"]:
        raise SystemExit(
            f"::error::Water areas: `{out}` has {count} features, at least "
            f"{MINIMUM['water']} expected. The map would have no sea – see the "
            f"`ogr2ogr` log above.")
    log(f"  water areas: {count} areas in {took(time.time() - t0)} "
        f"({human(os.path.getsize(out))})")


STEPS = ("water", "boundaries", "countries", "lakes", "downloads")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/world",
                    help="where the prepared sources go (default data/world)")
    # a list: the `basic` variant wants borders and regions but no water (`variant.py`)
    ap.add_argument("--only", default="",
                    help="only these layers, comma separated: " + ", ".join(STEPS))
    args = ap.parse_args()

    steps = ([k.strip() for k in args.only.split(",") if k.strip()]
             if args.only else list(STEPS))
    for k in steps:
        if k not in STEPS:
            raise SystemExit(f"::error::`--only={k}` is unknown. Layers are: "
                             f"{', '.join(STEPS)}.")
    if not steps:
        raise SystemExit("::error::`--only` got no layer. "
                         f"Layers are: {', '.join(STEPS)}.")

    raw = os.path.join(args.out, "sources")
    os.makedirs(raw, exist_ok=True)

    # the plan before the slow part: the foreign network is what takes time
    total = sum(SOURCES[k]["mb"] for k in steps)
    log(f"World map sources – {len(steps)} sources, ~{total:.0f} MB in all "
        f"to download:")
    for i, k in enumerate(steps, 1):
        log(f"  [{i}/{len(steps)}] {SOURCES[k]['what']} (~{SOURCES[k]['mb']:.0f} MB)")
    if "water" in steps:
        log("Converting water areas (ogr2ogr) is the longest part – expect "
            "a few minutes.")

    t_total = time.time()
    measured = []
    for i, k in enumerate(steps, 1):
        log(f"::group::[{i}/{len(steps)}] {SOURCES[k]['what']}")
        t0 = time.time()
        src = download(k, raw)
        if k == "water":
            prepare_water(src, os.path.join(args.out, "water.gpkg"))
        elif k == "boundaries":
            prepare_boundaries(src, os.path.join(args.out, "boundaries.geojson"))
        elif k == "countries":
            prepare_countries(src, os.path.join(args.out, "countries.geojson"))
        elif k == "lakes":
            prepare_lakes(src, os.path.join(args.out, "lakes.geojson"))
        elif k == "downloads":
            prepare_downloads(src, os.path.join(args.out, "downloads.geojson"))
        measured.append((k, time.time() - t0))
        log("::endgroup::")

    log("Sources are ready:")
    for k, sec in measured:
        log(f"  {k:<11} {took(sec):>8}")
    log(f"  {'total':<11} {took(time.time() - t_total):>8}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"::error::Command `{' '.join(exc.cmd[:2])}` exited with code "
              f"{exc.returncode} – the log above says on what.")
        sys.exit(1)
