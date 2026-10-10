#!/usr/bin/env python3
"""What the mini region's packages must hold: schema layers and zooms, its objects, nothing past the outline."""
import argparse
import glob
import gzip
import json
import math
import os
import subprocess
import sys

import mapbox_vector_tile
import yaml
from pmtiles.reader import MmapSource, Reader, all_tiles
from shapely.geometry import Point, Polygon

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import mini_region  # noqa: E402

SCHEMAS = {"transport": ["transport"], "boundaries": ["boundaries"], "water": ["water"],
           "rail": ["rail"], "history": ["history"], "buildings": ["buildings"],
           "trails": ["trails"], "features": ["features", "points"]}
ARCHIVE = {"points": "points"}
# clip-tiles.py keeps 100 m past the outline
MARGIN_M = 100

# (archive, layer, attributes the fixture gave one of its objects)
EXPECTED = [
    ("transport", "transport", {"class": "primary", "ref": "I/61", "name": "Hlavná"}),
    ("transport", "transport", {"class": "motorway_link"}),
    ("transport", "addresses", {}),
    ("boundaries", "boundary", {"admin_level": 8, "name": "Malá Obec"}),
    ("boundaries", "boundary_line", {}),
    ("boundaries", "place", {"name": "Malá Obec"}),
    ("water", "waterway", {"class": "river", "name": "Mlynský potok", "name_en": "Mill Brook"}),
    ("water", "water", {"name": "Jazero"}),
    ("water", "water_point", {"name": "Studnička"}),
    ("rail", "railway", {}),
    ("rail", "aerialway", {"name": "Lanovka"}),
    ("history", "history", {"name": "Hrad"}),
    ("history", "army", {}),
    ("history", "embankment", {}),
    ("buildings", "building", {"name": "Kostol"}),
    ("buildings", "building_name", {"name": "Kostol"}),
    ("buildings", "settlement_area", {}),
    ("buildings", "settlement", {"name": "Malá Obec"}),
    ("trails", "trail", {"name": "Okruh"}),
    ("features", "feature_line", {}),
    ("points", "feature_point", {"name": "Rozhľadňa"}),
]
OUTSIDE_NAMES = {"Vonku", "Cudzie jazero"}


def schema_layers(name):
    """`{layer id: (lowest min_zoom, geometries)}` from a schema yml."""
    with open(os.path.join(_WORKERS, {"points": "features"}.get(name, name), f"{name}.yml")) as f:
        doc = yaml.safe_load(f)
    out = {}
    for layer in doc["layers"]:
        feats = layer.get("features") or []
        zooms = [f.get("min_zoom", 0) for f in feats]
        out[layer["id"]] = min(zooms) if zooms else 0
    return out


def tile_to_lonlat(z, x, y, px, py, extent):
    n = 2 ** z
    lon = (x + px / extent) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
    return lon, lat


def coords(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        yield from c
    elif t in ("MultiLineString", "Polygon"):
        for part in c:
            yield from part
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring


def read(path):
    """Every feature: (z, layer, geometry type, properties, [lon/lat])."""
    out = []
    with open(path, "r+b") as f:
        reader = Reader(MmapSource(f))
        gz = reader.header()["tile_compression"].value == 2
        for (z, x, y), data in all_tiles(reader.get_bytes):
            raw = gzip.decompress(data) if gz else data
            for name, layer in mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True}).items():
                extent = layer.get("extent", 4096)
                for feat in layer["features"]:
                    pts = [tile_to_lonlat(z, x, y, px, py, extent) for px, py in coords(feat["geometry"])]
                    out.append((z, name, feat["geometry"]["type"], feat["properties"], pts))
    return out


def check_archive(name, features, problems, maxzoom):
    layers = schema_layers(name)
    seen = {}
    for z, layer, _, _, _ in features:
        seen[layer] = min(seen.get(layer, 99), z)
    for layer, z in sorted(seen.items()):
        if layer not in layers:
            problems.append(f"{name}: layer `{layer}` isn't in the schema ({sorted(layers)})")
        elif z < min(layers[layer], maxzoom):
            problems.append(f"{name}: layer `{layer}` appears at z{z}, the schema starts it at z{layers[layer]}")
    # the outline cut, with a tile pixel of rounding at the zoom it was drawn at
    outline = Polygon(mini_region.OUTLINE)
    lat0 = sum(p[1] for p in mini_region.OUTLINE) / len(mini_region.OUTLINE)
    m_per_deg = 111320 * math.cos(math.radians(lat0))
    for z, layer, _, props, pts in features:
        if props.get("name") in OUTSIDE_NAMES:
            problems.append(f"{name}: `{props['name']}` lies outside the region, yet is in {layer} at z{z}")
            continue
        slack_m = MARGIN_M + 2 * 40075016 * math.cos(math.radians(lat0)) / 2 ** z / 4096
        for lon, lat in pts:
            if outline.distance(Point(lon, lat)) * m_per_deg > slack_m:
                problems.append(f"{name}: {layer} at z{z} reaches {lon:.5f},{lat:.5f}, "
                                f"{outline.distance(Point(lon, lat)) * m_per_deg:.0f} m past the outline")
                break


def find(features, layer, attrs):
    return any(lay == layer and all(props.get(k) == v for k, v in attrs.items())
               for _, lay, _, props, _ in features)


def check_style(work, key, by_archive, problems):
    """Each style layer over our packages names a layer the tiles hold, and `fill` gets areas."""
    styles = os.path.join(work, "_site", "styles")
    flags = [f"--{a}=true" for a in by_archive]
    r = subprocess.run(["node", os.path.join(_WORKERS, "styles/build.mjs"), "--base-url=https://x",
                        f"--region={key}", f"--out={styles}", *flags], capture_output=True, text=True)
    if r.returncode:
        problems.append(f"styles/build.mjs failed: {r.stderr[-500:]}")
        return
    found = set()
    for path in sorted(glob.glob(os.path.join(styles, f"{key}-*-*.json"))):
        style = json.load(open(path))
        source_of = {sid: a for sid, s in style["sources"].items() for a in by_archive
                     if str(s.get("url", "")).endswith(f"-{a}.pmtiles")}
        for layer in style["layers"]:
            archive = source_of.get(layer.get("source"))
            if not archive:
                continue
            feats = [f for f in by_archive[archive] if f[1] == layer.get("source-layer")]
            if not feats:
                found.add(f"`{layer['id']}` draws `{archive}/{layer.get('source-layer')}`, "
                          f"which no tile holds")
                continue
            if layer["type"] in ("fill", "fill-extrusion") and "geometry-type" not in json.dumps(layer.get("filter")):
                lines = {f[2] for f in feats} - {"Polygon", "MultiPolygon"}
                if lines:
                    found.add(f"`{layer['id']}` fills `{layer['source-layer']}`, which also holds {sorted(lines)}")
    problems += [f"style: {p}" for p in sorted(found)]


def check_all(work, key, packages):
    problems, by_archive = [], {}
    tiles = os.path.join(work, "_site", "tiles")
    for package in packages:
        for name in SCHEMAS[package]:
            path = os.path.join(tiles, f"{key}-{ARCHIVE.get(name, package)}.pmtiles")
            if not os.path.exists(path):
                problems.append(f"{package}: {os.path.basename(path)} wasn't made")
                continue
            features = read(path)
            maxzoom = max((f[0] for f in features), default=0)
            by_archive[ARCHIVE.get(name, package)] = features
            check_archive(name, features, problems, maxzoom)
    for archive, layer, attrs in EXPECTED:
        if archive in by_archive and not find(by_archive[archive], layer, attrs):
            problems.append(f"{archive}: no {layer} feature with {attrs}")
    check_routing(tiles, key, problems)
    if by_archive:
        check_style(work, key, by_archive, problems)
    return problems


def check_routing(tiles, key, problems):
    path = os.path.join(tiles, f"{key}-routing.pmtiles")
    if not os.path.exists(path):
        return
    sys.path.insert(0, os.path.join(_WORKERS, "routing"))
    import format as fmt  # noqa: PLC0415
    one_way, kinds = 0, []
    with open(path, "r+b") as f:
        reader = Reader(MmapSource(f))
        for _, data in all_tiles(reader.get_bytes):
            tile = fmt.read(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
            one_way += sum(e["direction"] == fmt.D_FORWARD for e in tile["edges"])
            kinds += [fmt.RESTRICTION_KINDS[r["kind"]] for r in tile["restrictions"]]
    if not one_way:
        problems.append("routing: the oneway motorway link lost its direction")
    if "no_left_turn" not in kinds:
        problems.append(f"routing: the no_left_turn restriction is missing (have {kinds})")


def check_dem(work, hole):
    """Contours at the hill's levels; terrain tiles decode to its heights, the hole no sea."""
    from PIL import Image  # noqa: PLC0415
    problems = []
    path = os.path.join(work, "contours-out", "contours.pmtiles")
    if not os.path.exists(path):
        return ["contours: contours.pmtiles wasn't made"]
    eles = {int(p["ele"]) for _, layer, _, p, _ in read(path) if layer == "contour"}
    # the plain is at 200 m, the top at 500; below the 300 m lowland only every 20 m
    want = set(range(220, 300, 20)) | set(range(300, 500, 10))
    if eles != want:
        problems.append(f"contours: levels {sorted(eles ^ want)} differ from the hill's")
    w, s, e, _ = mini_region.BBOX
    cell = (e - w) / 200
    n = s + 120 * cell
    hole_lon = w + (hole[2] + hole[3]) / 2 * cell
    hole_lat = n - (hole[0] + hole[1]) / 2 * cell
    for what, lon, lat, lo, hi in (("hill top", w + 100 * cell, n - 100 * cell, 400, 520),
                                   ("NODATA hole", hole_lon, hole_lat, 190, 520)):
        z = 13
        fx = (lon + 180) / 360 * 2 ** z
        fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z
        png = os.path.join(work, "terrain-png", str(z), str(int(fx)), f"{int(fy)}.png")
        if not os.path.exists(png):
            problems.append(f"terrain: no tile over the {what} ({png})")
            continue
        r, g, b = Image.open(png).convert("RGB").getpixel((int((fx % 1) * 256), int((fy % 1) * 256)))
        height = r * 256 + g + b / 256 - 32768
        if not lo <= height <= hi:
            problems.append(f"terrain: the {what} decodes to {height:.1f} m, expected {lo}–{hi}")
    return problems


def outputs(path):
    with open(path) as f:
        return dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)


def check_rocks(work, failed, key):
    """Rocks from the hill reach the map; a failed computation is marked and stays out of it."""
    problems = []
    if outputs(os.path.join(work, "rocks.out")).get("rocks_enabled") != "true":
        problems.append("rocks: the hill's rocks didn't reach the map")
    elif not [f for f in read(os.path.join(work, "_site", "tiles", f"{key}-rocks.pmtiles")) if f[1] == "rock"]:
        problems.append("rocks: the rocks archive holds no `rock` feature")
    if not os.path.exists(os.path.join(failed, "contours-out", "rock-failed.txt")):
        problems.append("rocks: a failed computation isn't marked in rock-failed.txt, so the cache keeps it")
    if outputs(os.path.join(failed, "rocks.out")).get("rocks_enabled") != "false":
        problems.append("rocks: a failed computation still went to the map")
    if os.path.exists(os.path.join(failed, "_site", "tiles", f"{key}-rocks.pmtiles")):
        problems.append("rocks: a failed computation's empty archive is in _site")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--key", default="mini")
    args = ap.parse_args()
    problems = check_all(args.work, args.key, list(SCHEMAS))
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
