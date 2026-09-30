#!/usr/bin/env python3
"""Region polygon (not its rectangle) into `data/region.geojson`.

The border is read from OSM (`boundary.py`); osm.fr's `.poly` is a loud fallback.

Usage:
    python3 workers/plan/region-poly.py --region=presovsky \
        --from-pbf=data/region.osm.pbf --out=data/region.geojson \
        --poly-out=data/region.poly --summary=$GITHUB_STEP_SUMMARY
"""
import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

sys.path.insert(0, _HERE)
from area import BORDER_BUFFER_M  # noqa: E402
import boundary  # noqa: E402
import seam  # noqa: E402

# polygons sit beside the extracts, in another folder and without `-latest`
POLY_BASE = os.environ.get("OSMFR_POLYGONS",
                           "https://download.openstreetmap.fr/polygons")


def regions(path=None):
    with open(path or os.path.join(_DATA, "regions.json")) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def poly_url(reg):
    """`.poly` URL of the region's first slug, or `None` (a whole country)."""
    osmfr = reg.get("osmfr") or {}
    slugs = osmfr.get("slugs") or []
    if not slugs:
        return None
    slug = slugs[0].removesuffix("-latest")
    return f"{POLY_BASE}/{osmfr.get('dir', '')}/{slug}.poly"


def parse_poly(text):
    """`.poly` → `[(ring, is_hole)]`, a ring is a list of `(lon, lat)`."""
    rings, ring, hole = [], None, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "polygon":
            continue
        if line == "END":
            if ring is not None:
                if len(ring) >= 3:
                    rings.append((ring, hole))
                ring = None
            continue
        parts = line.split()
        if len(parts) == 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            if ring is None:
                ring, hole = [], False
            ring.append((lon, lat))
        else:
            # ring name – `!` means a hole
            ring, hole = [], line.startswith("!")
    return rings


def ring_bbox(rings):
    xs = [x for ring, _ in rings for x, _ in ring]
    ys = [y for ring, _ in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def ring_area_km2(ring):
    """Ring area in km² – a planar approximation, enough for a ratio."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(y for _, y in ring) / len(ring)
    kx = 111.32 * math.cos(math.radians(lat0))
    ky = 110.57
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(s) / 2.0


def geojson(rings):
    """Rings → GeoJSON."""
    return boundary.geojson_from_rings(rings)


def bbox_rect(bbox):
    """Fallback without a polygon: the bbox rectangle."""
    w, s, e, n = bbox
    ring = [(w, s), (e, s), (e, n), (w, n), (w, s)]
    return [(list(ring), False)]


def rings_to_poly_text(rings, name="region"):
    """`[(ring, is_hole)]` → `.poly` text."""
    lines = [name or "region"]
    for i, (ring, hole) in enumerate(rings, start=1):
        closed = ring if ring[0] == ring[-1] else list(ring) + [ring[0]]
        lines.append(f"!{i}" if hole else str(i))
        lines += [f"\t{lon:.6f}\t{lat:.6f}" for lon, lat in closed]
        lines.append("END")
    lines.append("END")
    return "\n".join(lines) + "\n"


def download_rings(reg, timeout=20):
    """The region's `.poly` from the server → rings, or `None` (quietly: neighbours only)."""
    url = poly_url(reg)
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse_poly(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def osm_name(reg, key=""):
    """The region's name in OSM – `osm_name`, else its `name`."""
    return (reg.get("osm_name") or reg.get("name") or key or "").strip()


def exact_rings(reg, borders, key=""):
    """The region's rings from the assembled PBF borders, or `None`."""
    if not borders:
        return None
    return boundary.pick(borders, osm_name(reg, key),
                         int(reg.get("admin_level") or 4))


def neighbour_rings(regs, key, borders=None):
    """Siblings (same `osmfr.parent`, touching bbox) and parent, all from one source.

    Returns `({key: rings}, parent_rings, [missing keys])`.
    """
    reg = regs.get(key) or {}
    parent = ((reg.get("osmfr") or {}).get("parent") or "")
    if not parent:
        return {}, None, []
    w, s, e, n = reg["bbox"]
    neighbours, missing = {}, []
    for k, r in regs.items():
        if k == key or not isinstance(r, dict):
            continue
        if ((r.get("osmfr") or {}).get("parent") or "") != parent:
            continue
        bw, bs, be, bn = r.get("bbox") or (0, 0, 0, 0)
        if bw > e or be < w or bs > n or bn < s:
            continue            # bboxes don't even touch
        rings = (exact_rings(r, borders, k) if borders
                 else download_rings(r))
        if rings:
            neighbours[k] = rings
        else:
            missing.append(k)
    parent_reg = regs.get(parent) or {}
    parent_rings = (exact_rings(parent_reg, borders, parent) if borders
                    else download_rings(parent_reg))
    return neighbours, parent_rings, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True, help="key from data/regions.json")
    ap.add_argument("--regions", default="", help="path to regions.json")
    ap.add_argument("--from-pbf", default="",
                    help="OSM PBF to read the EXACT border from "
                         "(`boundary=administrative` relation); without it "
                         "osm.fr's fallback `.poly` is used")
    ap.add_argument("--out", default="data/region.geojson")
    ap.add_argument("--poly-out", default="",
                    help="where to save the .poly (for Planetiler --polygon "
                         "and `osmium extract --polygon`)")
    ap.add_argument("--summary", default="", help="where to append the summary")
    ap.add_argument("--no-seam", action="store_true",
                    help="don't measure the seam with neighbouring regions")
    args = ap.parse_args()

    regs = regions(args.regions or None)
    reg = regs.get(args.region)
    if not reg:
        print(f"::error::Unknown region '{args.region}'. Known: "
              f"{', '.join(sorted(regs))}", file=sys.stderr)
        return 1
    bbox = tuple(reg["bbox"])

    rings, source, exact = None, "", False
    borders, state, has_state = [], {}, False
    if args.from_pbf:
        borders = boundary.borders_from_pbf(args.from_pbf)
        raw_rings = exact_rings(reg, borders, args.region)
        if raw_rings:
            # a broken OSM relation must not stick out beyond the state border
            parent = ((reg.get("osmfr") or {}).get("parent") or "")
            country = (exact_rings(regs[parent], borders, parent)
                       if parent and parent in regs else None)
            # a region without a parent is the country itself
            has_state = bool(parent)
            before = sum(ring_area_km2(r) for r, hole in raw_rings if not hole)
            rings, state = boundary.prepare(raw_rings, country)
            after = sum(ring_area_km2(r) for r, hole in rings if not hole)
            exact = True
            source = (f"OSM relation `{osm_name(reg, args.region)}` "
                      f"(admin_level={reg.get('admin_level') or 4}) "
                      f"from {args.from_pbf}")
            if state.get("clipped") and before - after > 1.0:
                print(f"::warning::The region relation reached {before - after:,.0f} km² "
                      f"beyond the state border; clipped by the state.")
        else:
            print(f"::warning::{args.from_pbf} has no border "
                  f"`{osm_name(reg, args.region)}` "
                  f"(admin_level={reg.get('admin_level') or 4}), so cutting "
                  f"uses osm.fr's FALLBACK `.poly` – rounded to ~550 m and "
                  f"widened around the border, so the map reaches into the "
                  f"neighbouring region and beyond the state border. Check "
                  f"`osm_name` and `admin_level` in workers/data/regions.json.")

    raw = ""
    url = poly_url(reg)
    if rings is None and url:
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            rings = parse_poly(raw)
            source = f"{url} (fallback – not the region border)"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"::warning::The region polygon couldn't be downloaded "
                  f"({url}: {exc}) – DEM layers are computed on the WHOLE BBOX "
                  f"of the region, beyond it too. Try the run again.")
    # a rectangle would only pretend to cut
    has_border = exact or bool(raw)
    if not rings:
        rings, source = bbox_rect(bbox), "region bbox (no border)"

    data = geojson(rings)
    if not data:
        print("::error::The region polygon has no outer ring.",
              file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f)
    if args.poly_out and has_border:
        os.makedirs(os.path.dirname(args.poly_out) or ".", exist_ok=True)
        with open(args.poly_out, "w") as f:
            f.write(rings_to_poly_text(rings, args.region))

    # measured only once the polygon is on disk: a measurement, not output
    seam_result = None
    if has_border and not args.no_seam:
        try:
            neighbours, parent_rings, missing = neighbour_rings(
                regs, args.region, borders)
            if missing:
                print(f"::warning::The borders of neighbours {', '.join(sorted(missing))} "
                      f"couldn't be obtained from the same source as ours, "
                      f"so the seam with them was NOT measured – the numbers below "
                      f"cover only the rest. For a region it means their relation "
                      f"isn't in the PBF; check `osm_name` and `admin_level` "
                      f"in workers/data/regions.json and that the parent cut has "
                      f"`-s smart -S types=multipolygon,boundary`.")
            if neighbours:
                seam_result = seam.measure_seam(rings, neighbours, parent_rings,
                                                BORDER_BUFFER_M)
        except Exception as exc:                        # noqa: BLE001
            print(f"::warning::The seam with the neighbours couldn't be measured ({exc}). "
                  f"The map is done, only whether the neighbour joins it is unknown.")

    pw, ps, pe, pn = ring_bbox(rings)
    area = sum(ring_area_km2(r) for r, hole in rings if not hole) \
        - sum(ring_area_km2(r) for r, hole in rings if hole)
    bw, bs, be, bn = bbox
    bbox_km2 = ring_area_km2([(bw, bs), (be, bs), (be, bn), (bw, bn)])
    share = 100 * area / bbox_km2 if bbox_km2 else 0
    outer = sum(1 for _, hole in rings if not hole)
    holes = sum(1 for _, hole in rings if hole)

    print(f"Region polygon: {args.out}")
    print(f"  source               {source}")
    if exact:
        print("  clipped by state     "
              + ("yes (region relation intersected with the state border)"
                 if state.get("clipped") else
                 "not needed – this region IS the country"
                 if not has_state else
                 "NO – the state border couldn't be used (see ::warning:: "
                 "above)"))
        print("  simplification       "
              + (f"{boundary.CUT_TOLERANCE_M:g} m (for the cut's speed)"
                 if state.get("simplified") else
                 "NO – cutting with full geometry, the parent cut takes longer"))
    if args.poly_out:
        print(f"  .poly for cutting    "
              f"{args.poly_out if has_border else 'NONE (tiles cover the whole bbox)'}")
    print(f"  rings                {outer} (+{holes} holes), "
          f"{sum(len(r) for r, _ in rings)} points")
    print(f"  polygon bbox         {pw:.3f},{ps:.3f},{pe:.3f},{pn:.3f}")
    print(f"  region bbox          {bw},{bs},{be},{bn}")
    print(f"  region area          {area:,.0f} km² of {bbox_km2:,.0f} km² "
          f"bbox = {share:.0f} %")
    print(f"  outside the region   {bbox_km2 - area:,.0f} km² "
          f"({100 - share:.0f} % of bbox) no longer computed")
    if seam_result:
        for line in seam.report(seam_result, BORDER_BUFFER_M):
            print(line)
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(f"- **Cut to region**: {area:,.0f} km² of "
                    f"{bbox_km2:,.0f} km² bbox ({share:.0f} %), "
                    f"{outer} ring(s), border: "
                    + ("**exact from OSM**" if exact
                       else "osm.fr fallback `.poly` (widened!)") + "\n")
            if seam_result and seam_result["points"]:
                f.write(f"- **Seam with neighbours**: {seam.summary(seam_result)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
