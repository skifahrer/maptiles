#!/usr/bin/env python3
"""What a package is called and where it goes – stable names, so the next build overwrites them."""
import os


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def safe(text):
    """A file name piece: no diacritics, spaces or slashes."""
    fold = {"á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i",
            "ĺ": "l", "ľ": "l", "ň": "n", "ó": "o", "ô": "o", "ŕ": "r",
            "š": "s", "ť": "t", "ú": "u", "ý": "y", "ž": "z"}
    out = []
    for ch in text.strip().lower():
        ch = fold.get(ch, ch)
        out.append(ch if (ch.isalnum() and ch.isascii()) or ch in "._-" else "_")
    return "".join(out).strip("_") or "unnamed"


def strip_test(key):
    """`presovsky_test4` → `presovsky`; the file name says it is a test, the path does not."""
    base = key
    while True:
        cut = base.rfind("_test")
        if cut < 0 or not base[cut + 5:].replace(".", "").isdigit():
            return base
        base = base[:cut]


def country_from_url(url):
    """`…/extracts/europe/austria/tirol-latest.osm.pbf` → `austria`, else `other`."""
    path = url.split("/extracts/", 1)[-1] if "/extracts/" in url else url
    pieces = [k for k in path.split("/") if k]
    if len(pieces) >= 2:
        return safe(pieces[-2])
    return "other"


def drive_path(regions):
    """Folders under the root: [country, region?, area?]."""
    region_key = strip_test(env("REGION_KEY"))
    custom_url = env("CUSTOM_PBF_URL")
    area_key = strip_test(env("AREA_KEY"))

    if custom_url:
        # a custom PBF is not in `regions.json`; the region is what the user named it
        region = safe(env("CUSTOM_NAME") or region_key
                      or custom_url.rsplit("/", 1)[-1].split(".")[0])
        parts = [country_from_url(custom_url), region]
    else:
        r = regions.get(region_key) or {}
        country = safe(r.get("country") or region_key or "other")
        parts = [country]
        # a whole country has no parent region – `admin_level` 2 is a state
        if r.get("admin_level") != 2 and region_key:
            parts.append(safe(region_key))
    # `whole` means no cut-out, so no folder of its own
    if area_key and area_key != "whole":
        parts.append(safe(area_key))
    return parts


def catalog_path(parts):
    """Where it goes in the CATALOG – a quick test gets its own node, never the real map's."""
    test_km2 = env("TEST_KM2", "0")
    if test_km2 in ("", "0"):
        return parts
    return parts[:-1] + [f"{parts[-1]}_test{safe(test_km2)}km2"]


def layers():
    """Name pieces saying what the map holds and from what; an absent layer is named too."""
    own = env("MAP_LAYERS")
    if own:
        return [safe(k) for k in own.split(",") if k.strip()]

    out = []
    if env("CONTOURS_ENABLED") == "true":
        interval = env("CONTOUR_INTERVAL", "10")
        out.append(f"contours_{safe(env('CONTOURS_SOURCE', '?'))}_{safe(interval)}m")
    else:
        out.append("no_contours")

    if env("ROCKS_ENABLED") == "true":
        out.append(f"rocks_{safe(env('ROCKS_SOURCE', '?'))}")
    else:
        out.append("no_rocks")

    if env("TERRAIN_ENABLED") == "true":
        out.append(f"terrain_{safe(env('TERRAIN_SOURCE', '?'))}")
    else:
        out.append("no_terrain")

    # OSM layers are named only when present, or every run grows by "no_" pieces
    if env("TRAILS_ENABLED") == "true":
        out.append("trails")
    if env("FEATURES_ENABLED") == "true":
        out.append("features")
    if env("TRANSPORT_ENABLED") == "true":
        out.append("transport")
    if env("BOUNDARIES_ENABLED") == "true":
        out.append("boundaries")
    if env("WATER_ENABLED") == "true":
        out.append("water")
    if env("RAIL_ENABLED") == "true":
        out.append("rail")
    if env("BUILDINGS_ENABLED") == "true":
        out.append("buildings")
    return out


def stem():
    """Stable name without suffix: `<region>[-<area>][-testNkm2]`; `contents.json` carries the rest."""
    region = strip_test(env("REGION_KEY")) or "map"
    area = strip_test(env("AREA_KEY"))
    pieces = [safe(region)]
    if area and area != "whole":
        pieces.append(safe(area))
    test_km2 = env("TEST_KM2", "0")
    if test_km2 not in ("", "0"):
        # a quick test must never overwrite the real map
        pieces.append(f"test{safe(test_km2)}km2")
    return "-".join(pieces)


# `.aar` unpacks natively on iOS and macOS; ZIP stays for everything else
EXTENSIONS = {"zip": ".zip", "aar": ".aar"}


def file_name(kind="", fmt="zip"):
    """Package file name: stem + kind (`` = the base map) + format extension."""
    return stem() + (f"-{kind}" if kind else "") + EXTENSIONS[fmt]
