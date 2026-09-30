#!/usr/bin/env python3
"""Marked trails from OSM `type=route` relations: hiking, cycling, ski and horse routes.

One line per (way, route) pair, each in its own lane (`side` + `off`), ways chained
so lanes keep their side (`orient_ways`), sharp turns eased (`ease_corners`).

    python3 workers/trails/routes.py --pbf=data/trails.osm.pbf \\
        --out=data/trails.geojson --stats=trail-stats.txt
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict, deque

import osmium

# what a route's tags say (colour, network, mark) is in `tags.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tags import (  # noqa: E402
    TIER_ORDER,
    resolve_colour,
    resolve_mark,
    resolve_tier,
)

# `route` value of the relation → our kind
ROUTE_TYPES = {
    "hiking": "hiking",
    "foot": "hiking",
    "walking": "hiking",
    "bicycle": "bicycle",
    "mtb": "mtb",
    "ski": "ski",
    "nordic": "ski",
    "skitour": "ski",
    "horse": "horse",
    # a via ferrata runs on rock, not a path
    "via_ferrata": "ferrata",
}

# lane order – walking marks nearest the way
ROUTE_ORDER = {"hiking": 0, "ferrata": 1, "bicycle": 2, "mtb": 3, "ski": 4,
               "horse": 5}

# wheeled routes on the other side than walking ones; +1 right of the line, −1 left
SIDE_BY_ROUTE = {"hiking": 1, "ferrata": 1, "ski": 1, "horse": 1,
                 "bicycle": -1, "mtb": -1}

# a road is drawn much wider than a path, so the style keeps an offset for each
PATH_HIGHWAYS = {
    "path", "footway", "bridleway", "steps", "track", "cycleway", "corridor",
}


def way_class(tags):
    """What the route runs on: `path` (footpath, forest track) or `road`."""
    return "path" if (tags.get("highway") or "").strip().lower() \
        in PATH_HIGHWAYS else "road"

# MapLibre can't stitch a `miter` above 120°, so such a turn becomes 60° steps
EASE_ABOVE_DEG = 120.0
MAX_TURN_DEG = 60.0
CUT_M = 2.0
# closer points are one place – two vertices on each other have no direction
MIN_STEP_M = 0.2


def ease_corners(coords, above_deg=EASE_ABOVE_DEG, max_turn_deg=MAX_TURN_DEG,
                 cut_m=CUT_M):
    """Rounds turns sharper than `above_deg` in metres; ends stay put. `(points, count)`."""
    if len(coords) < 3:
        return coords, 0
    lat_mid = sum(c[1] for c in coords) / len(coords)
    mx = 111320.0 * math.cos(math.radians(lat_mid))
    my = 110540.0
    pts = [((lon - coords[0][0]) * mx, (lat - coords[0][1]) * my)
           for lon, lat in coords]
    max_turn = math.radians(max_turn_deg)
    above = math.radians(above_deg)

    out = [pts[0]]
    eased = 0
    for i in range(1, len(pts) - 1):
        (px, py), (x, y), (nx, ny) = pts[i - 1], pts[i], pts[i + 1]
        ax, ay, bx, by = x - px, y - py, nx - x, ny - y
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        if la == 0 or lb == 0:
            continue
        dot = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        turn = math.acos(dot)
        if turn <= above:
            out.append((x, y))
            continue
        eased += 1
        cut = min(cut_m, la * 0.45, lb * 0.45)
        a = (x - ax / la * cut, y - ay / la * cut)
        b = (x + bx / lb * cut, y + by / lb * cut)
        # a quadratic Bezier on the original vertex; one step extra, it splits unevenly
        n = max(2, math.ceil(turn / max_turn) + 1)
        out.append(a)
        for k in range(1, n):
            t = k / n
            s = 1 - t
            out.append((s * s * a[0] + 2 * s * t * x + t * t * b[0],
                        s * s * a[1] + 2 * s * t * y + t * t * b[1]))
        out.append(b)
    out.append(pts[-1])

    # a moved shared end node would stop Planetiler joining neighbours
    lon0, lat0 = coords[0]
    res = []
    for j, (x, y) in enumerate(out):
        last = j == len(out) - 1
        if res and not last and \
                math.hypot(x - res[-1][1], y - res[-1][2]) < MIN_STEP_M:
            continue
        if j == 0:
            res.append((list(coords[0]), x, y))
        elif last:
            res.append((list(coords[-1]), x, y))
        else:
            res.append(([round(lon0 + x / mx, 7),
                         round(lat0 + y / my, 7)], x, y))
    return [ll for ll, _, _ in res], eased


# member roles that aren't the route itself
SKIP_ROLES = {
    "guidepost", "marker", "sign", "signpost", "stop", "platform",
    "site", "label", "map", "fixme", "shelter", "info",
}

# routes that don't exist yet stay out
SKIP_STATES = {"proposed", "planned", "abandoned", "removed", "disused"}


def orient_ways(ends):
    """Which ways to reverse so lanes continue: `(ways to flip, conflicts, chains)`.

    `ends` is `{way id: (first node, last node)}`; breadth-first, one ends where the next starts.
    """
    at = defaultdict(list)
    for wid, (first, last) in ends.items():
        at[first].append(wid)
        # a closed loop touches its node twice, but neighbours it once
        if last != first:
            at[last].append(wid)

    flip = {}
    chains = 0
    for seed in sorted(ends):
        if seed in flip:
            continue
        chains += 1
        first, last = ends[seed]
        flip[seed] = first > last
        queue = deque([seed])
        while queue:
            wid = queue.popleft()
            first, last = ends[wid]
            tail, head = (last, first) if flip[wid] else (first, last)
            # forward from the head and back from the tail
            for node, starts_there in ((head, True), (tail, False)):
                for nxt in at.get(node, ()):
                    if nxt in flip:
                        continue
                    nfirst, nlast = ends[nxt]
                    flip[nxt] = nfirst != node if starts_there else nlast != node
                    queue.append(nxt)

    # conflicts only count where exactly two ways meet
    conflicts = 0
    for node, wids in at.items():
        if len(wids) != 2:
            continue
        heads = 0
        for wid in wids:
            first, last = ends[wid]
            head = first if flip[wid] else last
            heads += head == node
        if heads != 1:
            conflicts += 1

    return {wid for wid, rev in flip.items() if rev}, conflicts, chains


class Ends(osmium.SimpleHandler):
    """Pass 2: end nodes of ways a route runs on, without coordinates."""

    def __init__(self, by_way):
        super().__init__()
        self.by_way = by_way
        self.ends = {}

    def way(self, w):
        if w.id not in self.by_way or len(w.nodes) < 2:
            return
        self.ends[w.id] = (w.nodes[0].ref, w.nodes[-1].ref)


class Routes(osmium.SimpleHandler):
    """Pass 1: the list of routes on every way, from relations."""

    def __init__(self):
        super().__init__()
        self.by_way = defaultdict(list)
        self.routes = 0
        self.skipped = Counter()

    def relation(self, r):
        tags = {t.k: t.v for t in r.tags}
        if tags.get("type") != "route":
            return
        route = ROUTE_TYPES.get((tags.get("route") or "").strip().lower())
        if not route:
            self.skipped[(tags.get("route") or "?")] += 1
            return
        if (tags.get("state") or "").strip().lower() in SKIP_STATES:
            self.skipped["state"] += 1
            return

        colour, hexcolour = resolve_colour(tags)
        tier, network = resolve_tier(tags)
        # the mark as painted on the tree, not the lane colour
        mark, mark_bg, mark_fg = resolve_mark(tags, route, colour)
        info = {
            "route": route,
            "colour": colour,
            "hex": hexcolour,
            "mark": mark or "",
            "mark_bg": mark_bg or "",
            "mark_fg": mark_fg or "",
            "network": network,
            "tier": tier,
            "name": (tags.get("name:sk") or tags.get("name") or "").strip(),
            "ref": (tags.get("ref") or "").strip(),
            "rel": r.id,
        }
        self.routes += 1
        for m in r.members:
            if m.type != "w" or (m.role or "").strip().lower() in SKIP_ROLES:
                continue
            self.by_way[m.ref].append(info)


class Ways(osmium.SimpleHandler):
    """Pass 3: geometry of ways with routes, one copy per route in its lane."""

    def __init__(self, by_way, out, flipped=frozenset()):
        super().__init__()
        self.by_way = by_way
        self.out = out
        # ways drawn reversed so the lane keeps its side
        self.flipped = flipped
        self.features = 0
        self.ways = 0
        self.no_geometry = 0
        self.by_type = Counter()
        self.by_colour = Counter()
        self.by_mark = Counter()
        self.by_tier = Counter()
        self.by_way_class = Counter()
        self.lanes = Counter()
        self.named = set()
        self.eased = 0
        self.points_in = 0
        self.points_out = 0

    def way(self, w):
        routes = self.by_way.get(w.id)
        if not routes:
            return

        coords = []
        for n in w.nodes:
            if n.location.valid():
                coords.append([round(n.lon, 7), round(n.lat, 7)])
        if len(coords) < 2:
            self.no_geometry += 1
            return

        # the direction decides the `line-offset` side (`orient_ways`)
        if w.id in self.flipped:
            coords.reverse()

        # once per way: all its lanes draw the same line
        self.points_in += len(coords)
        coords, eased = ease_corners(coords)
        self.points_out += len(coords)
        self.eased += eased

        lanes = self.lane_order(routes)
        way = way_class({t.k: t.v for t in w.tags})
        self.ways += 1
        self.lanes[len(lanes)] += 1
        self.by_way_class[way] += 1
        # lanes are numbered per side
        taken = Counter()
        for info in lanes:
            side = SIDE_BY_ROUTE.get(info["route"], 1)
            idx = taken[side]
            taken[side] += 1
            self.by_type[info["route"]] += 1
            self.by_colour[info["colour"] or "no colour"] += 1
            self.by_mark[
                f'{info["mark_bg"]}-{info["mark_fg"]}-{info["mark"]}'
                if info["mark"] else "no mark"
            ] += 1
            self.by_tier[info["tier"]] += 1
            if info["name"]:
                self.named.add(info["rel"])
            props = {
                "route": info["route"],
                "tier": info["tier"],
                # numbered outwards, so one route ending doesn't shift the others
                "side": side,
                "off": idx,
                "way": way,
                "cnt": len(lanes),
                "rel": info["rel"],
            }
            for key in ("colour", "hex", "network", "name", "ref",
                        "mark", "mark_bg", "mark_fg"):
                if info[key]:
                    props[key] = info[key]
            self.write(coords, props)
            self.features += 1

    @staticmethod
    def lane_order(routes):
        """Lane order from route properties only; a parent and its part collapse into one."""
        seen = {}
        for info in routes:
            key = (info["route"], info["colour"], info["hex"],
                   info["ref"] or info["name"])
            # of equal routes keep the named one
            old = seen.get(key)
            if old is None or (not old["name"] and info["name"]):
                seen[key] = info
        return sorted(
            seen.values(),
            key=lambda i: (
                TIER_ORDER.get(i["tier"], 9),
                ROUTE_ORDER.get(i["route"], 9),
                i["colour"],
                i["ref"],
                i["name"],
                i["rel"],
            ),
        )

    def write(self, coords, props):
        """Features are written as they go – a whole region would not fit in memory."""
        self.out.write("," if self.features else "")
        json.dump(
            {"type": "Feature", "properties": props,
             "geometry": {"type": "LineString", "coordinates": coords}},
            self.out, ensure_ascii=False, separators=(",", ":"),
        )
        self.out.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True, help="PBF prefiltered to route relations")
    ap.add_argument("--out", required=True, help="output .geojson for Planetiler")
    ap.add_argument("--stats", default="", help="where to write numbers for the build summary")
    args = ap.parse_args()

    if not os.path.exists(args.pbf):
        print(f"::error::Input {args.pbf} doesn't exist.", file=sys.stderr)
        return 1

    print(f"1/3 – looking for route relations in {args.pbf} …", flush=True)
    routes = Routes()
    routes.apply_file(args.pbf)
    print(f"    routes: {routes.routes}, ways with a route: {len(routes.by_way)}")
    if routes.skipped:
        top = ", ".join(f"{k}={v}" for k, v in routes.skipped.most_common(6))
        print(f"    skipped relations (other kind or state): {top}")

    if not routes.routes:
        print("::warning::This area has no marked trail – "
              "the map goes without them.")

    # cheap: end nodes only
    print("2/3 – who neighbours whom (lane direction) …", flush=True)
    ends = Ends(routes.by_way)
    ends.apply_file(args.pbf)
    flipped, conflicts, chains = orient_ways(ends.ends)
    print(f"    {len(ends.ends)} ways in {chains} chains, "
          f"{len(flipped)} reversed")
    # never zero, but a jump means the orientation broke
    pct = 100.0 * conflicts / max(1, len(ends.ends))
    print(f"    places where a lane still switches side: {conflicts} "
          f"({pct:.1f} % of ways)")
    if pct > 5:
        print("::warning::Trail lanes switch side on "
              f"{pct:.0f} % of ways – that's a lot. See `orient_ways` in "
              "workers/trails/routes.py; it should be under 5 %.")

    print("3/3 – assembling way geometry …", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write('{"type":"FeatureCollection","features":[\n')
        ways = Ways(routes.by_way, fh, flipped)
        # `locations=True` fills node coordinates
        ways.apply_file(args.pbf, locations=True, idx="flex_mem")
        fh.write("]}\n")

    size_mb = os.path.getsize(args.out) / 1048576
    print(f"✓ {args.out}: {ways.features} sections on {ways.ways} ways "
          f"({size_mb:.1f} MB)")
    if ways.no_geometry:
        print(f"::warning::{ways.no_geometry} ways have no coordinates in the PBF "
              "(member outside the area) – those sections won't be in the map.")
    order = sorted(ways.by_type.items(), key=lambda kv: -kv[1])
    print("  kinds:   " + ", ".join(f"{k} {v}" for k, v in order))
    print("  colours: " + ", ".join(f"{k} {v}" for k, v in ways.by_colour.most_common()))
    print("  marks:   " + ", ".join(
        f"{k} {v}" for k, v in ways.by_mark.most_common(8))
        + "  (base-colour-shape; “no mark” draws the route kind icon)")
    print("  networks: " + ", ".join(f"{k} {v}" for k, v in ways.by_tier.most_common()))
    print("  run on:  " + ", ".join(
        f"{k} {v}" for k, v in ways.by_way_class.most_common())
        + "  (`path` = footpath and forest track, `road` = the rest; the style "
          "picks the lane offset by it)")
    multi = sum(n for lanes, n in ways.lanes.items() if lanes > 1)
    print(f"  ways with more than one route: {multi} "
          f"(most at once: {max(ways.lanes, default=0)})")
    grew = 100.0 * (ways.points_out - ways.points_in) / max(1, ways.points_in)
    print(f"  turns above {EASE_ABOVE_DEG:.0f}° split: {ways.eased} "
          f"(points {ways.points_in} → {ways.points_out}, {grew:+.1f} %) – above "
          "them a `miter` join can't stitch the lane and it narrows in the bend")

    if args.stats:
        with open(args.stats, "w", encoding="utf-8") as fh:
            fh.write(f"routes={routes.routes}\n")
            fh.write(f"named={len(ways.named)}\n")
            fh.write(f"ways={ways.ways}\n")
            fh.write(f"features={ways.features}\n")
            fh.write(f"multi={multi}\n")
            fh.write(f"chains={chains}\n")
            fh.write(f"side_flips={conflicts}\n")
            fh.write(f"eased={ways.eased}\n")
            fh.write(f"max_lanes={max(ways.lanes, default=0)}\n")
            for key, count in ways.by_type.items():
                fh.write(f"type_{key}={count}\n")
            for key, count in ways.by_tier.items():
                fh.write(f"tier_{key}={count}\n")
            # the summary sources this file with `.`, so quote
            fh.write('colours="' + ", ".join(
                f"{k} {v}" for k, v in ways.by_colour.most_common()) + '"\n')
            # shows whether `osmc:symbol` is used in this region at all
            fh.write(f"marked={sum(v for k, v in ways.by_mark.items() if k != 'no mark')}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
