#!/usr/bin/env python3
"""Exact region and state border from OSM data, not from osm.fr's widened `.poly`.

Usage as a module (called by `region-poly.py`):
    borders = boundary.borders_from_pbf("data/region.osm.pbf")
    rings, state = boundary.prepare(boundary.pick(borders, "Prešovský kraj", 4),
                                    boundary.pick(borders, "Slovensko", 2))

Or from the command line:
    python3 workers/plan/boundary.py --pbf=data/region.osm.pbf
"""
import json
import os
import subprocess
import sys
import tempfile

# state and region only – municipal borders are thousands of unused areas
ADMIN_LEVELS = (2, 4)

# `osmium extract --polygon` is ~8× slower on the unsimplified border
CUT_TOLERANCE_M = 10

# a stuck `osmium` must fail, not hold the job to its 360 minute cap
TIMEOUT_S = 1800


def log(msg):
    print(msg, flush=True)


# `workers/lib/region-mask.py` keeps its own copy – other folder, dash in name
def rings_from_geojson(data):
    """GeoJSON dict (Polygon/MultiPolygon) → `[(ring, is_hole)]`."""
    out = []
    for feat in data.get("features") or []:
        geom = feat.get("geometry") or {}
        polys = ([geom.get("coordinates")] if geom.get("type") == "Polygon"
                 else geom.get("coordinates") or [])
        for poly in polys:
            for i, ring in enumerate(poly or []):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) >= 3:
                    out.append((pts, i > 0))
    return out


def geojson_from_rings(rings):
    """Rings → GeoJSON; holes go to the last outer ring (`.poly` doesn't say which)."""
    polys, holes = [], []
    for ring, hole in rings:
        closed = ring if ring[0] == ring[-1] else ring + [ring[0]]
        coords = [[round(x, 6), round(y, 6)] for x, y in closed]
        (holes if hole else polys).append(coords)
    if not polys:
        return None
    shapes = [[p] for p in polys]
    for h in holes:
        shapes[-1].append(h)
    geom = ({"type": "Polygon", "coordinates": shapes[0]} if len(shapes) == 1
            else {"type": "MultiPolygon", "coordinates": shapes})
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": geom}]}


def ogr2ogr(args, what, impact):
    """`ogr2ogr` with the given args; `impact` says what is lost when it fails."""
    try:
        subprocess.run(["ogr2ogr", *args], check=True,
                       capture_output=True, text=True, timeout=TIMEOUT_S)
        return True
    except FileNotFoundError:
        log(f"::warning::{what} failed – `ogr2ogr` isn't here. {impact} "
            f"Add `gdal-bin` (and `libsqlite3-mod-spatialite`) to the job.")
        return False
    except subprocess.TimeoutExpired:
        log(f"::warning::{what} didn't finish within {TIMEOUT_S} s. {impact}")
        return False
    except subprocess.CalledProcessError as exc:
        log(f"::warning::{what} failed: {(exc.stderr or '').strip()[-500:]}. "
            f"{impact}")
        return False


def _osmium(args, what):
    """`osmium` with the given args. `True` = it passed."""
    try:
        subprocess.run(["osmium", *args], check=True,
                       capture_output=True, text=True, timeout=TIMEOUT_S)
        return True
    except FileNotFoundError:
        log(f"::warning::{what} failed – `osmium` isn't here.")
        return False
    except subprocess.TimeoutExpired:
        log(f"::warning::{what} didn't finish within {TIMEOUT_S} s.")
        return False
    except subprocess.CalledProcessError as exc:
        log(f"::warning::{what} failed: {(exc.stderr or '').strip()[-500:]}")
        return False


def borders_from_pbf(pbf, levels=ADMIN_LEVELS):
    """PBF → `[{"name", "names", "admin_level", "rings"}]`; empty means "can't", not "none"."""
    if not pbf or not os.path.exists(pbf):
        log(f"::warning::Borders can't be read – {pbf} doesn't exist.")
        return []
    filters = [f"r/admin_level={lvl}" for lvl in levels]
    with tempfile.TemporaryDirectory() as tmp:
        admin = os.path.join(tmp, "admin.osm.pbf")
        geo = os.path.join(tmp, "admin.geojsonseq")
        if not _osmium(["tags-filter", "--overwrite", "-o", admin, pbf,
                        *filters], "Picking border relations from the PBF"):
            return []
        # relations must become areas, not a bundle of lines
        if not _osmium(["export", "--overwrite", "-f", "geojsonseq",
                        "--geometry-types=polygon", "-o", geo, admin],
                       "Assembling borders from relations (`osmium export`)"):
            return []
        return _read_geojsonseq(geo)


def _read_geojsonseq(path):
    """GeoJSON Text Sequence → list of borders."""
    borders = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                # `osmium export` writes RS (0x1E) before every line
                line = raw.strip().lstrip("\x1e").strip()
                if not line:
                    continue
                try:
                    feat = json.loads(line)
                except ValueError:
                    continue
                props = feat.get("properties") or {}
                geom = feat.get("geometry") or {}
                if geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                rings = rings_from_geojson(
                    {"features": [{"geometry": geom}]})
                if not rings:
                    continue
                try:
                    lvl = int(str(props.get("admin_level") or "").strip())
                except ValueError:
                    continue
                # the local name sits in `name` or `name:sk`, states also `int_name`
                names = {str(props.get(k)) for k in
                         ("name", "name:sk", "int_name", "official_name")
                         if props.get(k)}
                borders.append({"name": str(props.get("name") or ""),
                                "names": names,
                                "admin_level": lvl,
                                "rings": rings})
    except OSError as exc:
        log(f"::warning::Assembled borders can't be read ({exc}).")
        return []
    return borders


def pick(borders, name, admin_level):
    """Rings of the border of that name and level (the largest match), or `None`."""
    wanted = (name or "").strip()
    if not wanted:
        return None
    matches = [h for h in borders
               if h["admin_level"] == admin_level
               and (wanted == h["name"] or wanted in h["names"])]
    if not matches:
        return None
    return max(matches, key=lambda h: _area(h["rings"]))["rings"]


def _area(rings):
    """Area of rings in degrees² – only to compare two matches."""
    total = 0.0
    for ring, hole in rings:
        s = 0.0
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            s += x1 * y2 - x2 * y1
        total += (-1 if hole else 1) * abs(s) / 2.0
    return total


def prepare(rings, clip=None, tolerance_m=CUT_TOLERANCE_M, what="the state"):
    """Border for cutting: intersected with `clip` and simplified. `(rings, state)`."""
    state = {"clipped": False, "simplified": False}
    if not rings:
        return rings, state
    a = geojson_from_rings(rings)
    if not a:
        return rings, state
    b = geojson_from_rings(clip) if clip else None
    # degrees, since the geometry is in degrees
    tol = (tolerance_m or 0) / 111320.0
    geom_sql = "a.geom"
    sources = "a"
    if b:
        geom_sql = "ST_Intersection(a.geom, b.geom)"
        sources = "a, b"
    if tol > 0:
        # a self-intersecting ring is refused by `osmium`, so topology-preserving
        geom_sql = f"ST_SimplifyPreserveTopology({geom_sql}, {tol:.8f})"
    with tempfile.TemporaryDirectory() as tmp:
        fa = os.path.join(tmp, "a.geojson")
        fb = os.path.join(tmp, "b.geojson")
        gpkg = os.path.join(tmp, "both.gpkg")
        out = os.path.join(tmp, "cut.geojson")
        with open(fa, "w") as f:
            json.dump(a, f)
        step = "Border for cutting"
        impact = ("The exact relation border is used – the right area, "
                  "only the cut from the parent takes longer"
                  + (" and the region isn't intersected with the state." if b else "."))
        if not ogr2ogr(["-f", "GPKG", "-nln", "a", "-lco", "GEOMETRY_NAME=geom",
                        gpkg, fa], step + " (writing the border)", impact):
            return rings, state
        if b:
            with open(fb, "w") as f:
                json.dump(b, f)
            if not ogr2ogr(["-f", "GPKG", "-update", "-nln", "b",
                            "-lco", "GEOMETRY_NAME=geom", gpkg, fb],
                           step + f" (writing the border of {what})", impact):
                return rings, state
        if not ogr2ogr(["-f", "GeoJSON", "-dialect", "SQLITE", "-sql",
                        f"SELECT {geom_sql} AS geom FROM {sources}",
                        out, gpkg], step + " (SQL)", impact):
            return rings, state
        try:
            with open(out) as f:
                prepared = rings_from_geojson(json.load(f))
        except (OSError, ValueError) as exc:
            log(f"::warning::{step}: the output can't be read ({exc}). "
                f"{impact}")
            return rings, state
    if not prepared:
        log(f"::warning::{step} came out empty – cutting by the exact "
            f"relation border.")
        return rings, state
    state["clipped"] = bool(b)
    state["simplified"] = tol > 0
    return prepared, state


def _cli():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pbf", required=True, help="OSM PBF to read")
    ap.add_argument("--name", default="", help="border name (`osm_name`)")
    ap.add_argument("--level", type=int, default=0, help="admin_level")
    ap.add_argument("--out", default="", help="where to write GeoJSON")
    args = ap.parse_args()

    borders = borders_from_pbf(args.pbf)
    if not borders:
        print("No administrative border found in the PBF.", file=sys.stderr)
        return 1
    if not args.name:
        for h in sorted(borders, key=lambda h: (h["admin_level"], h["name"])):
            print(f"  admin_level={h['admin_level']:<3} {h['name']} "
                  f"({sum(len(r) for r, _ in h['rings'])} points)")
        return 0
    rings = pick(borders, args.name, args.level)
    if not rings:
        print(f"Border “{args.name}” (admin_level={args.level}) isn't in the PBF.",
              file=sys.stderr)
        return 1
    print(f"{args.name}: {len(rings)} rings, "
          f"{sum(len(r) for r, _ in rings)} points")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(geojson_from_rings(rings), f)
        print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
