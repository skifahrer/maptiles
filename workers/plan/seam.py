#!/usr/bin/env python3
"""Does the neighbouring region's map continue where ours ends – without overlapping it?

Usage:
    from seam import measure_seam
    python3 workers/plan/seam.py --region=trnavsky
"""
import math

from boundary import CUT_TOLERANCE_M   # sibling file, no dash in its name

M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# distance is to neighbour segments, so denser sampling adds nothing
STEP_M = 250.0

# a point must lie this deep inside the parent to count as an inner border
INSIDE_PARENT_M = 5000.0

# how far a sibling may be to still share the seam; also a prefilter
REACH_M = 5000.0

# two simplifications, one on each side of the seam
TOLERANCE_M = 2 * CUT_TOLERANCE_M


def to_metric(rings, lat0):
    """`[(ring, is_hole)]` in degrees → the same in metres around `lat0`."""
    kx = M_PER_DEG_LON * math.cos(math.radians(lat0))
    return [([(x * kx, y * M_PER_DEG_LAT) for x, y in ring], hole)
            for ring, hole in rings]


def _inside(rings_m, x, y):
    """Is the point in the polygon? Ray casting, holes subtracted."""
    ok = False
    for ring, hole in rings_m:
        c = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    c = not c
        if c:
            if hole:
                return False
            ok = True
    return ok


def _dist_to_segment(x, y, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def dist_to_boundary(rings_m, x, y):
    """Distance of a point to the OUTLINE, also from inside."""
    best = math.inf
    for ring, _ in rings_m:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            d = _dist_to_segment(x, y, x1, y1, x2, y2)
            if d < best:
                best = d
    return best


def dist_to_polygon(rings_m, bbox_m, x, y, limit=None):
    """Distance of a point to the polygon in metres; 0 inside, `inf` beyond `limit` of bbox."""
    w, s, e, n = bbox_m
    if limit is not None:
        dx = w - x if x < w else x - e if x > e else 0.0
        dy = s - y if y < s else y - n if y > n else 0.0
        if math.hypot(dx, dy) > limit:
            return math.inf
    if _inside(rings_m, x, y):
        return 0.0
    return dist_to_boundary(rings_m, x, y)


def bbox_of(rings_m):
    xs = [x for ring, _ in rings_m for x, _ in ring]
    ys = [y for ring, _ in rings_m for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def sample_boundary(rings_m, step_m=STEP_M):
    """Points along the outer outline every `step_m` (an enclave isn't a neighbour border)."""
    out = []
    for ring, hole in rings_m:
        if hole:
            continue
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            d = math.hypot(x2 - x1, y2 - y1)
            steps = max(1, int(d // step_m))
            for k in range(steps):
                t = k / steps
                out.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
    return out


def measure_seam(own, neighbours, parent, buffer_m, lat0=None, step_m=STEP_M):
    """Gap and overlap between our border and the neighbours' (all rings from one source)."""
    if not own:
        return None
    ys = [y for ring, _ in own for _, y in ring]
    lat0 = lat0 if lat0 is not None else (min(ys) + max(ys)) / 2
    kx = M_PER_DEG_LON * math.cos(math.radians(lat0))

    own_m = to_metric(own, lat0)
    parent_m = to_metric(parent, lat0) if parent else None
    nb_m = {k: to_metric(v, lat0) for k, v in neighbours.items() if v}
    nb_bbox = {k: bbox_of(v) for k, v in nb_m.items()}

    limit = 2.0 * buffer_m + TOLERANCE_M
    # measured past the limit too, so "missing 300 m" and "missing 12 km" differ
    reach = REACH_M

    worst_gap, where, who = -1.0, None, None
    worst_overlap, where_o, who_o = -1.0, None, None
    points, lonely = 0, 0
    per = {k: [-1.0, -1.0, 0] for k in nb_m}
    for x, y in sample_boundary(own_m, step_m):
        # without a parent the state border can't be told apart, so no missing neighbour
        deep = False
        if parent_m is not None:
            if not _inside(parent_m, x, y):
                continue
            d_parent = dist_to_boundary(parent_m, x, y)
            if d_parent < INSIDE_PARENT_M:
                continue
            deep = d_parent >= 3 * INSIDE_PARENT_M
        points += 1
        best_d, best_k = math.inf, None
        for k, rings in nb_m.items():
            d = dist_to_polygon(rings, nb_bbox[k], x, y, limit=reach)
            if d < best_d:
                best_d, best_k = d, k
        # the bbox prefilter isn't a cap on the result
        if best_d > reach:
            best_k = None
        if best_k is None:
            # deep inside the country no sibling means a missing region
            if deep:
                lonely += 1
            continue
        overlap = (dist_to_boundary(nb_m[best_k], x, y)
                   if best_d == 0.0 and _inside(nb_m[best_k], x, y) else 0.0)
        if per[best_k][0] < best_d:
            per[best_k][0] = best_d
        if per[best_k][1] < overlap:
            per[best_k][1] = overlap
        per[best_k][2] += 1
        if best_d > worst_gap:
            worst_gap, where, who = best_d, (x / kx, y / M_PER_DEG_LAT), best_k
        if overlap > worst_overlap:
            worst_overlap, where_o, who_o = (overlap,
                                             (x / kx, y / M_PER_DEG_LAT), best_k)
    gap = max(worst_gap, 0.0) if points else 0.0
    overlap = max(worst_overlap, 0.0) if points else 0.0
    return {
        "limit_m": limit,
        "points": points,
        "gap_m": gap,
        "overlap_m": overlap,
        "where": where,
        "neighbour": who,
        "where_overlap": where_o,
        "neighbour_overlap": who_o,
        "fits": points == 0 or (lonely == 0 and gap <= limit
                                and overlap <= limit),
        "per_neighbour": {k: (max(v[0], 0.0), max(v[1], 0.0), v[2])
                          for k, v in per.items() if v[2]},
        "no_neighbour": lonely,
    }


def summary(result):
    """One sentence for the run summary: does the seam fit, and with what numbers?"""
    if not result or not result["points"]:
        return "no inner border (all of it is the state border) – nothing to join"
    v = result
    numbers = (f"gap {v['gap_m']:.0f} m, overlap {v['overlap_m']:.0f} m, "
               f"tolerance {v['limit_m']:.0f} m")
    if v["fits"]:
        return f"fits ✓ ({numbers})"
    if v["no_neighbour"]:
        return f"**a whole neighbour is missing** ({numbers})"
    if v["gap_m"] > v["limit_m"]:
        return (f"**GAP {v['gap_m']:.0f} m** at neighbour "
                f"`{v['neighbour']}` ({numbers})")
    return (f"**OVERLAP {v['overlap_m']:.0f} m** into neighbour "
            f"`{v['neighbour_overlap']}` ({numbers})")


def report(result, buffer_m):
    """Measurement → log lines (the first is the summary)."""
    if not result:
        return ["The seam with the neighbours can't be measured – the border is missing."]
    v = result
    if not v["points"]:
        return ["Seam with the neighbours: no inner border (all of it is the "
                "state border) – nothing to join."]
    lim = v["limit_m"]
    lines = []
    if v["fits"]:
        lines.append(
            f"Seam with the neighbours FITS ✓ – the largest gap to a neighbouring "
            f"region is {v['gap_m']:.0f} m, the deepest overlap into one "
            f"{v['overlap_m']:.0f} m; tolerance is {lim:.0f} m "
            f"(2 × buffer {buffer_m:g} m + 2 × border simplification "
            f"{CUT_TOLERANCE_M:g} m).")
    if v["gap_m"] > lim:
        where = (f" at {v['where'][0]:.4f},{v['where'][1]:.4f}" if v["where"] else "")
        lines.append(
            f"::warning::GAP BETWEEN MAPS: the inner border has a place"
            f"{where} where the nearest region ({v['neighbour']}) is "
            f"{v['gap_m']:.0f} m away, while {lim:.0f} m is tolerated. "
            f"A strip without a map stays between the downloaded maps there. "
            f"Either the two regions' borders really differ in OSM, or one "
            f"of them is from the fallback `.poly` – see `source` above.")
    if v["overlap_m"] > lim:
        where = (f" at {v['where_overlap'][0]:.4f},{v['where_overlap'][1]:.4f}"
                 if v["where_overlap"] else "")
        lines.append(
            f"::warning::MAP REACHES INTO THE NEIGHBOUR: the border runs{where} "
            f"{v['overlap_m']:.0f} m inside region {v['neighbour_overlap']}, "
            f"while {lim:.0f} m is tolerated. A piece of the neighbouring region "
            f"rides in this map and in the elevation layers – exactly what the "
            f"exact border is meant to prevent.")
    if v["no_neighbour"]:
        lines.append(
            f"::warning::{v['no_neighbour']} inner border points have no "
            f"sibling in sight – a whole region is missing from the country "
            f"map there (or its border wasn't obtained).")
    for k, (m, p, n) in sorted(v["per_neighbour"].items(),
                               key=lambda kv: -kv[1][0]):
        lines.append(f"  {k:<18} gap {m:6.0f} m, overlap {p:6.0f} m "
                     f"({n} points of shared border)")
    return lines


def _cli():
    import argparse
    import importlib.util
    import os
    import sys

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--region", required=True, help="key from data/regions.json")
    ap.add_argument("--regions", default="", help="path to regions.json")
    ap.add_argument("--step-m", type=float, default=STEP_M)
    ap.add_argument("--from-pbf", default="",
                    help="PBF with exact borders (without it osm.fr's fallback "
                         "`.poly` are used and overlap numbers describe THEM)")
    args = ap.parse_args()

    # dash in the name; at run time `region-poly.py` calls this file instead
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "region_poly", os.path.join(here, "region-poly.py"))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)

    regs = rp.regions(args.regions or None)
    if args.region not in regs:
        print(f"Unknown region '{args.region}'. Known: {', '.join(sorted(regs))}",
              file=sys.stderr)
        return 1
    import boundary as b
    borders = b.borders_from_pbf(args.from_pbf) if args.from_pbf else []
    own = (rp.exact_rings(regs[args.region], borders, args.region)
           or rp.download_rings(regs[args.region]))
    if not own:
        print("The region border couldn't be obtained.", file=sys.stderr)
        return 1
    neighbours, parent, missing = rp.neighbour_rings(regs, args.region, borders)
    if missing:
        print(f"Neighbour borders {', '.join(sorted(missing))} aren't from the "
              f"same source – not measured against them.")
    for r in report(measure_seam(own, neighbours, parent, rp.BORDER_BUFFER_M,
                                 step_m=args.step_m), rp.BORDER_BUFFER_M):
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
