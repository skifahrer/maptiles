#!/usr/bin/env python3
"""Cut a finished vector .pmtiles to the region: lines and areas cut, points beyond dropped."""
import argparse
import gzip
import json
import math
import os
import sys

import mapbox_vector_tile
from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.affinity import affine_transform
from shapely.geometry import box, shape
from shapely.prepared import prep

# beyond the border, so neighbouring regions meet without a seam
MARGIN_M = 100


def region_polygon(path, margin_m):
    """The region polygon, grown by the margin."""
    from shapely.ops import unary_union
    with open(path) as f:
        data = json.load(f)
    if data.get("type") == "FeatureCollection":
        feats = data.get("features") or []
    elif data.get("type") == "Feature":
        feats = [data]
    else:
        feats = [{"geometry": data}]
    # a published region.geojson also holds the outside
    kinds = {(f.get("properties") or {}).get("kind") for f in feats}
    own = [f for f in feats if (f.get("properties") or {}).get("kind") in ("outline", "hranica")]
    if not own:
        own = [f for f in feats if (f.get("properties") or {}).get("kind") not in ("outside", "mimo")]
    if not own:
        raise SystemExit(f"{path}: no region polygon in it (kinds {sorted(map(str, kinds))})")
    polygon = unary_union([shape(f["geometry"]).buffer(0) for f in own])
    lat = polygon.centroid.y
    return polygon.buffer(margin_m / (111_320 * math.cos(math.radians(lat))))


def tile_bounds(z, x, y):
    n = 2 ** z
    lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def to_pixels(region, z, x, y, extent):
    """The region in this tile's pixels, y down."""
    n = 2 ** z

    def project(geom):
        from shapely.ops import transform
        def fn(lons, lats):
            px = [((lon + 180) / 360 * n - x) * extent for lon in lons]
            py = [((1 - math.log(math.tan(math.radians(la)) + 1 / math.cos(math.radians(la)))
                    / math.pi) / 2 * n - y) * extent for la in lats]
            return px, py
        return transform(fn, geom)
    return project(region)


def clip_tile(data, region, z, x, y, compressed):
    raw = gzip.decompress(data) if compressed else data
    layers = mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True})
    out = []
    for name, layer in layers.items():
        extent = layer.get("extent", 4096)
        local = to_pixels(region, z, x, y, extent)
        whole = prep(local)
        kept = []
        for feat in layer["features"]:
            geom = shape(feat["geometry"])
            if geom.is_empty:
                continue
            if not whole.contains(geom):
                if geom.geom_type in ("Point", "MultiPoint"):
                    geom = geom.intersection(local)
                else:
                    geom = geom.buffer(0) if geom.geom_type.endswith("Polygon") else geom
                    geom = geom.intersection(local)
                    # a cut can leave crumbs of a lower dimension
                    geom = _same_kind(geom, feat["geometry"]["type"])
                if geom is None or geom.is_empty:
                    continue
            item = {"geometry": geom, "properties": feat["properties"]}
            if feat.get("id") is not None:
                item["id"] = feat["id"]
            kept.append(item)
        if kept:
            out.append({"name": name, "features": kept, "extent": extent})
    if not out:
        return None
    extent = out[0]["extent"]
    encoded = mapbox_vector_tile.encode(
        [{"name": l["name"], "features": l["features"]} for l in out],
        default_options={"extents": extent, "y_coord_down": True})
    return gzip.compress(encoded) if compressed else encoded


def _same_kind(geom, kind):
    from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon
    want = "Polygon" if "Polygon" in kind else "LineString" if "LineString" in kind else "Point"
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom.geoms if want in g.geom_type]
        flat = []
        for g in parts:
            flat.extend(g.geoms if g.geom_type.startswith("Multi") else [g])
        if not flat:
            return None
        multi = {"Polygon": MultiPolygon, "LineString": MultiLineString, "Point": MultiPoint}[want]
        return flat[0] if len(flat) == 1 else multi(flat)
    return geom if want in geom.geom_type else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--region", default="data/region.geojson")
    ap.add_argument("--margin-m", type=float, default=MARGIN_M)
    args = ap.parse_args()
    if not os.path.exists(args.region):
        print(f"::warning::No region polygon ({args.region}), so {args.archive} is not cut "
              "to the region and draws what lies beyond it.", file=sys.stderr)
        return
    region = region_polygon(args.region, args.margin_m)
    inside = prep(region.buffer(-2 * args.margin_m / 111_320))
    near = prep(region)

    tmp = args.archive + ".clipping"
    cut = dropped = kept = 0
    with open(args.archive, "rb") as src, open(tmp, "wb") as dst:
        reader = Reader(MmapSource(src))
        header, metadata = reader.header(), reader.metadata()
        if header["tile_type"] != TileType.MVT:
            print(f"{args.archive}: not vector tiles, left as it is", file=sys.stderr)
            os.remove(tmp)
            return
        compressed = header["tile_compression"] == Compression.GZIP
        writer = Writer(dst)
        for (z, x, y), data in sorted(all_tiles(reader.get_bytes),
                                      key=lambda t: zxy_to_tileid(*t[0])):
            bounds = box(*tile_bounds(z, x, y))
            if inside.contains(bounds):
                writer.write_tile(zxy_to_tileid(z, x, y), data)
                kept += 1
                continue
            if not near.intersects(bounds):
                dropped += 1
                continue
            clipped = clip_tile(data, region, z, x, y, compressed)
            if clipped is None:
                dropped += 1
                continue
            writer.write_tile(zxy_to_tileid(z, x, y), clipped)
            cut += 1
        writer.finalize(header, metadata)
    before = os.path.getsize(args.archive)
    os.replace(tmp, args.archive)
    print(f"Cut to the region ({args.margin_m:.0f} m beyond): {kept} tiles untouched, "
          f"{cut} cut, {dropped} wholly outside dropped; "
          f"{before / 1048576:.1f} → {os.path.getsize(args.archive) / 1048576:.1f} MB",
          file=sys.stderr)


if __name__ == "__main__":
    main()
