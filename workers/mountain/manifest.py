#!/usr/bin/env python3
"""`_site/tiles/manifest.json` of a mountain package – what the packer and the catalog read.

The values come through the environment, from what the DEM layers really made.
"""
import glob
import json
import os
import sys
import time

# the style's own number (`poc/web/themes.js`), so the client never invents another
TERRAIN_EXAGGERATION = 1.3
OUTLINES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "outlines")


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def pmtiles_zooms(path):
    """(min, max) zoom from a PMTiles v3 header."""
    with open(path, "rb") as f:
        head = f.read(102)
    return (head[100], head[101]) if head[:7] == b"PMTiles" and len(head) == 102 else None


def number(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def outline(key):
    """The range's outline as MultiPolygon coordinates, or None for its box."""
    path = os.path.join(OUTLINES, f"{key}.geojson")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        geoms = [feat["geometry"] for feat in json.load(f)["features"]]
    return [poly for g in geoms
            for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"])]


def manifest(site):
    key = env("REGION_KEY")
    tiles = os.path.join(site, "tiles")
    has = {kind: os.path.isfile(os.path.join(tiles, f"{key}-{kind}.pmtiles"))
           for kind in ("contours", "rocks", "terrain", "transport", "paths", "water",
                        "points", "range-boundaries", "aerial_summer", "aerial_winter")}
    region = {"name": env("MOUNTAIN_NAME", key),
              "bbox": [float(v) for v in env("AREA_BBOX").split(",")],
              "mountain": True}
    # the app stands the range in for its regions inside this line, not the box
    if outline(key):
        region["outline"] = outline(key)
    if has["contours"]:
        region.update(contours=f"tiles/{key}-contours.pmtiles",
                      contours_maxzoom=int(env("CONTOURS_MAXZOOM", "16")),
                      contour_interval=number(env("CONTOUR_INTERVAL", "2.5")))
    if has["rocks"]:
        region.update(rocks=f"tiles/{key}-rocks.pmtiles",
                      rocks_maxzoom=int(env("ROCKS_MAXZOOM", "16")))
        if env("ROCK_SLOPE").isdigit():
            region["rock_slope"] = int(env("ROCK_SLOPE"))
        if env("ROCKS_SOURCE"):
            region["rock_source"] = env("ROCKS_SOURCE")
    if has["contours"] or has["rocks"]:
        region["dem_source"] = env("CONTOURS_SOURCE", "dmr5")
    if env("COUNTRIES"):
        region["countries"] = env("COUNTRIES").split(",")
    for kind in ("transport", "paths"):
        if has[kind]:
            region[kind] = f"tiles/{key}-{kind}.pmtiles"
            region[f"{kind}_maxzoom"] = int(env("TRANSPORT_MAXZOOM", "14"))
    for kind, default in (("water", "14"), ("points", "15")):
        if has[kind]:
            region[kind] = f"tiles/{key}-{kind}.pmtiles"
            region[f"{kind}_maxzoom"] = int(env(f"{kind.upper()}_MAXZOOM", default))
    # the range's own schema, so its file is no region's `boundaries` to the app's atlas
    if has["range-boundaries"]:
        region["boundaries"] = f"tiles/{key}-range-boundaries.pmtiles"
        region["boundaries_maxzoom"] = int(env("BOUNDARIES_MAXZOOM", "14"))
    sprite = sorted(os.path.join("tiles", os.path.basename(p))
                    for p in glob.glob(os.path.join(tiles, f"{key}-roadsigns*")))
    if has["transport"] and sprite:
        region["road_sign_sprite"] = sprite
    for kind in ("aerial_summer", "aerial_winter"):
        zooms = has[kind] and pmtiles_zooms(os.path.join(tiles, f"{key}-{kind}.pmtiles"))
        if zooms:
            region[kind] = f"tiles/{key}-{kind}.pmtiles"
            region[f"{kind}_maxzoom"] = zooms[1]
    out = {"default_region": key,
           "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "regions": {key: region}}
    if has["terrain"]:
        out.update(dem=f"tiles/{key}-terrain.pmtiles",
                   dem_maxzoom=int(env("TERRAIN_MAXZOOM", "16")),
                   dem_source=env("TERRAIN_SOURCE", "dmr5"),
                   terrain_3d=True,
                   terrain_exaggeration=TERRAIN_EXAGGERATION)
    return out


def main(args):
    site = args[0] if args else "_site"
    data = manifest(site)
    held = ("contours", "rocks", "transport", "paths", "water", "points", "boundaries",
            "aerial_summer", "aerial_winter")
    if not any(k in data["regions"][data["default_region"]] for k in held) \
            and "dem" not in data:
        raise SystemExit(f"::error::{site}/tiles holds none of the mountain's layers – "
                         f"nothing to package. (Did the DEM layers run?)")
    os.makedirs(os.path.join(site, "tiles"), exist_ok=True)
    with open(os.path.join(site, "tiles", "manifest.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
