#!/usr/bin/env python3
"""A small `RTIL` archive for the app's reader tests – the network is hand-written, not from a PBF."""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import order                                                      # noqa: E402
import tags as tags_mod                                           # noqa: E402
import tiles                                                      # noqa: E402

E7 = 10_000_000
STEP_M = fmt.STEP_DM / 10
# the dense part's tile must split, the edges not – hence a low budget
BUDGET = 900
# the grid sits around a z9 tile's centre, so a split quarters it
SIDE = 12
SPACING = 0.03
CENTRE = (21.4453125, 48.6904256)
ORDER_ID = 0x0A0B0C0D
# an archive that must not join: the app must refuse another order
ORDER_OTHER = 0x0A0B0C0E
HALF = 17.578125  # the z9 border between 280 and 281, where the archive is cut


def e7(v):
    return round(v * E7)


class Net:
    """What `tiles.py` expects from `network.load` – nodes, edges and restrictions."""

    def __init__(self):
        self.nodes = {}
        self.heights = {}
        self.edges = []
        self.restrictions = []

    def node(self, osm, lon, lat, height=None):
        self.nodes[osm] = (e7(lat), e7(lon))
        if height is not None:
            self.heights[osm] = height
        return osm

    def edge(self, a, b, tags, direction=fmt.D_FORWARD | fmt.D_BACKWARD, points=()):
        # the geometry is only the shape between nodes, as `network.py` writes it
        shape = [(e7(lat), e7(lon)) for lon, lat in points]
        self.edges.append({"from": a, "to": b, "tags": tags, "direction": direction,
                           "length_cm": _length_cm([self.nodes[a], *shape,
                                                    self.nodes[b]]),
                           "geom": shape})

    def restriction(self, kind, exceptions, chain):
        self.restrictions.append({"kind": fmt.RESTRICTION_KINDS.index(kind),
                                  "exceptions": exceptions, "edges": chain,
                                  "via": chain[0][1]})


def _length_cm(geom):
    """Rough length – the reader tests check the number passes, not geodesy."""
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(geom, geom[1:]):
        dy = (lat2 - lat1) / E7 * 111_320
        dx = (lon2 - lon1) / E7 * 111_320 * 0.66
        total += (dx * dx + dy * dy) ** 0.5
    return round(total * 100)


def base_network():
    """Two neighbouring regions on a z9 border, a junction with restrictions and a dense tile."""
    s = Net()
    # west: junction n2 with a one-way motorway and a footway
    n1 = s.node(1_000_001, 17.00, 48.60)
    n2 = s.node(1_000_002, 17.05, 48.60)
    n3 = s.node(1_000_003, 17.05, 48.65)
    n4 = s.node(1_000_004, 17.10, 48.60)
    # east: past the tile border, a node both cutouts share
    b1 = s.node(2_000_001, 17.70, 48.60)
    b2 = s.node(2_000_002, 17.80, 48.60)
    b3 = s.node(2_000_003, 17.75, 48.65)

    s.edge(n1, n2, {"highway": "residential", "name": "Hlavná",
                    "surface": "asphalt"})
    s.edge(n2, n3, {"highway": "motorway", "oneway": "yes", "ref": "D1",
                    "maxspeed": "130"}, direction=fmt.D_FORWARD)
    s.edge(n2, n4, {"highway": "footway", "foot": "yes"},
           points=[(17.07, 48.61), (17.09, 48.605)])
    # across the tile border: an edge sits in its first node's tile
    s.edge(n4, b1, {"highway": "primary", "name": "Cesta cez hranicu",
                    "ref": "I/61"})
    s.edge(b1, b2, {"highway": "primary", "name": "Cesta cez hranicu",
                    "ref": "I/61"})
    s.edge(b1, b3, {"highway": "track", "surface": "gravel",
                    "maxweight": "3"}, direction=fmt.D_BACKWARD)

    s.restriction("no_left_turn", 1 << fmt.EXCEPTIONS.index("bicycle"),
                  [(n1, n2), (n2, n3)])
    s.restriction("only_straight_on", 0, [(n1, n2), (n2, n4), (n4, b1)])
    return s


def dense(s, n=SIDE):
    """A grid with its own name on every street – a body over budget, so it splits."""
    osm = 3_000_000
    grid = {}
    for i in range(n):
        for j in range(n):
            osm += 1
            grid[i, j] = s.node(osm, CENTRE[0] + (i - n / 2) * SPACING,
                                CENTRE[1] + (j - n / 2) * SPACING)
    for i in range(n):
        for j in range(n):
            tags = {"highway": "residential", "name": f"Ulica {i}-{j}",
                    "surface": "paving_stones"}
            if i + 1 < n:
                s.edge(grid[i, j], grid[i + 1, j], dict(tags))
            if j + 1 < n:
                s.edge(grid[i, j], grid[i, j + 1], dict(tags))
    return s


def roads():
    """A network for road classes and for passing a switched-off road."""
    s = Net()
    c = [s.node(4_000_000 + i, 18.00 + i * 0.10, 48.50) for i in range(6)]
    for a, b in zip(c, c[1:]):
        s.edge(a, b, {"highway": "primary", "ref": "I/65",
                      "name": "Hlavný ťah"})
    # detours are longer, but search takes them until their class is cut
    for i in range(5):
        d = s.node(4_000_100 + i, 18.05 + i * 0.10, 48.52)
        s.edge(c[i], d, {"highway": "residential", "name": "Obchádzka"})
        s.edge(d, c[i + 1], {"highway": "residential", "name": "Obchádzka"})
    for osm, lat, length in ((4_000_200, 48.45, 0.002), (4_000_300, 48.40, 0.068)):
        _passage(s, osm, lat, length)
        s.edge(c[0], osm, {"highway": "residential", "name": "Prípojka"})
    return s


def _passage(s, osm, lat, length):
    """Two streets joined only by a track whose length varies here."""
    r1 = s.node(osm, 18.00, lat)
    r2 = s.node(osm + 1, 18.02, lat)
    r3 = s.node(osm + 2, 18.02 + length, lat)
    r4 = s.node(osm + 3, 18.04 + length, lat)
    s.edge(r1, r2, {"highway": "residential", "name": "Ulica pred"})
    s.edge(r2, r3, {"highway": "track", "surface": "gravel"})
    s.edge(r3, r4, {"highway": "residential", "name": "Ulica za"})


def hills():
    """A network with heights: a road from a valley over a ridge and down again."""
    s = Net()
    ridge = ((19.00, 420), (19.05, 660), (19.10, 980), (19.15, 540),
             (19.20, 300))
    u = [s.node(5_000_000 + i, lon, 49.00, height)
         for i, (lon, height) in enumerate(ridge)]
    for a, b in zip(u, u[1:]):
        s.edge(a, b, {"highway": "secondary", "name": "Cez hrebeň",
                      "ref": "II/520"})
    waves(s)
    return s


def waves(s, step_m=STEP_M, amplitude_m=40):
    """Two waves on an edge – without them the profile climb would equal the ends."""
    for h in s.edges:
        a, b = s.heights.get(h["from"]), s.heights.get(h["to"])
        if a is None or b is None:
            continue
        n = fmt.sample_count(h["length_cm"] / 100, step_m)
        h["profile"] = [
            round((a + (b - a) * i / (n - 1)) * 10
                  + amplitude_m * 10 * math.sin(4 * math.pi * i / (n - 1)))
            for i in range(n)]


def junctions():
    """A network for instructions: motorway exit, entry, roundabout, fork and dead end."""
    s = Net()
    motorway(s)
    roundabout(s)
    fork(s)
    streets(s)
    return s


def motorway(s):
    """D1 with an exit to a road into town and an entry back."""
    m = [s.node(6_000_000 + i, 20.00 + i * 0.05, 49.20) for i in range(4)]
    for a, b in zip(m, m[1:]):
        s.edge(a, b, {"highway": "motorway", "oneway": "yes", "ref": "D1"},
               direction=fmt.D_FORWARD)
    x0 = s.node(6_000_010, 20.07, 49.18)
    x1 = s.node(6_000_011, 20.10, 49.16)
    s.edge(m[1], x0, {"highway": "motorway_link", "oneway": "yes"},
           direction=fmt.D_FORWARD)
    s.edge(x0, x1, {"highway": "primary", "ref": "I/18",
                    "name": "Cesta do mesta"})
    n0 = s.node(6_000_020, 20.02, 49.225)
    n1 = s.node(6_000_021, 20.06, 49.22)
    s.edge(n0, n1, {"highway": "primary", "name": "Prístupová"})
    s.edge(n1, m[2], {"highway": "motorway_link", "oneway": "yes"},
           direction=fmt.D_FORWARD)


def roundabout(s):
    """An anticlockwise roundabout with four arms."""
    ring = [s.node(6_000_030 + i, lon, lat) for i, (lon, lat) in enumerate(
        ((20.200, 49.200), (20.205, 49.197), (20.210, 49.200), (20.205, 49.203)))]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        s.edge(a, b, {"highway": "tertiary", "junction": "roundabout",
                      "oneway": "yes"}, direction=fmt.D_FORWARD)
    arms = ((20.190, 49.200, "Západná"), (20.205, 49.190, "Južná"),
            (20.220, 49.200, "Východná"), (20.205, 49.210, "Severná"))
    for i, (lon, lat, name) in enumerate(arms):
        end = s.node(6_000_034 + i, lon, lat)
        s.edge(end, ring[i], {"highway": "tertiary", "name": name})


def fork(s):
    """A main road that forks – neither branch is a turn."""
    f0 = s.node(6_000_040, 20.30, 49.20)
    f1 = s.node(6_000_041, 20.33, 49.20)
    f2 = s.node(6_000_042, 20.36, 49.21)
    f3 = s.node(6_000_043, 20.36, 49.19)
    s.edge(f0, f1, {"highway": "primary", "ref": "I/18", "name": "Hlavná"})
    s.edge(f1, f2, {"highway": "primary", "ref": "I/18", "name": "Hlavná"})
    s.edge(f1, f3, {"highway": "primary", "ref": "I/66", "name": "Odbočka"})


def streets(s):
    """A name change, a dead end with a single turn and a plain junction."""
    c0 = s.node(6_000_050, 20.25, 49.20)
    c1 = s.node(6_000_051, 20.28, 49.20)
    c2 = s.node(6_000_052, 20.31, 49.21)
    s.edge(c0, c1, {"highway": "residential", "name": "Prvá"})
    s.edge(c1, c2, {"highway": "residential", "name": "Druhá"})

    e0 = s.node(6_000_060, 20.40, 49.20)
    e1 = s.node(6_000_061, 20.43, 49.20)
    e2 = s.node(6_000_062, 20.43, 49.23)
    s.edge(e0, e1, {"highway": "residential", "name": "Slepá"})
    s.edge(e1, e2, {"highway": "residential", "name": "Priečna"})

    t0 = s.node(6_000_070, 20.50, 49.20)
    t1 = s.node(6_000_071, 20.53, 49.20)
    t2 = s.node(6_000_072, 20.53, 49.17)
    t3 = s.node(6_000_073, 20.56, 49.20)
    s.edge(t0, t1, {"highway": "residential", "name": "Rovná"})
    s.edge(t1, t2, {"highway": "residential", "name": "Kolmá"})
    s.edge(t1, t3, {"highway": "residential", "name": "Rovná"})


def cutout(s, west):
    """A region cut at a border: an edge stays when at least one end is inside."""
    out = Net()
    out.nodes = dict(s.nodes)
    out.heights = dict(s.heights)
    for h in s.edges:
        if any(_is_west(s.nodes[u]) == west for u in (h["from"], h["to"])):
            out.edges.append(h)
    island = {u for h in out.edges for u in (h["from"], h["to"])}
    out.nodes = {k: v for k, v in s.nodes.items() if k in island}
    out.heights = {k: v for k, v in s.heights.items() if k in island}
    out.restrictions = [z for z in s.restrictions
                        if all(u in island for pair in z["edges"] for u in pair)]
    return out


def _is_west(node):
    return node[1] < e7(HALF)


class Neighbours:
    """What `order.order` expects of a network: a node's neighbours and position."""

    def __init__(self, s):
        self.xy = s.nodes
        self._neighbours = {osm: set() for osm in s.nodes}
        for h in s.edges:
            self._neighbours[h["from"]].add(h["to"])
            self._neighbours[h["to"]].add(h["from"])

    def __getitem__(self, osm):
        return self._neighbours.get(osm, ())


class Order:
    """A rank for every node, so the tile has the order flag."""

    def __init__(self, s, order_id=ORDER_ID, shift=0):
        self.id = order_id
        # the region's nested dissection, not OSM id order, or CCH looks useless
        elimination = order.order(sorted(s.nodes), Neighbours(s))
        self._rank = {osm: i + shift for i, osm in enumerate(elimination)}

    def __bool__(self):
        return True

    def rank(self, osm):
        return self._rank.get(osm, len(self._rank) + osm)


def write(path, s, dictionary, key, order):
    from pmtiles.tile import (Compression, TileType,                # noqa: PLC0415
                              zxy_to_tileid)
    from pmtiles.writer import Writer                               # noqa: PLC0415

    bodies = tiles.split(s, dictionary, "SK", order, budget=BUDGET)
    zoom_max = max(z for z, _, _ in bodies)
    graph = {
        "scope": "region", "key": key, "name": key, "format": "rtil",
        "format_version": fmt.VERSION, "dictionary": f"{dictionary.id:08x}",
        "dictionary_version": dictionary.version, "order": f"{order.id:08x}",
        "country": "SK", "zoom": tiles.ZOOM, "zoom_max": zoom_max,
        "split": sum(1 for z, _, _ in bodies if z > tiles.ZOOM),
        "tiles": len(bodies), "nodes": len(s.nodes), "edges": len(s.edges),
        "restrictions": len(s.restrictions), "height": bool(s.heights),
        "profile": any(h.get("profile") for h in s.edges),
        "profile_step_m": STEP_M,
        "multimodal": False,
        "built_at": "2026-09-13T00:00:00Z", "run": "", "run_id": "",
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        wr = Writer(f)
        for zxy in sorted(bodies, key=lambda t: zxy_to_tileid(*t)):
            wr.write_tile(zxy_to_tileid(*zxy), bodies[zxy])
        w = min(tiles.window(*z)[0] for z in bodies)
        j = min(tiles.window(*z)[1] for z in bodies)
        e = max(tiles.window(*z)[2] for z in bodies)
        n = max(tiles.window(*z)[3] for z in bodies)
        wr.finalize(
            {"tile_type": TileType.UNKNOWN, "tile_compression": Compression.GZIP,
             "min_zoom": tiles.ZOOM, "max_zoom": zoom_max,
             "min_lon_e7": w, "min_lat_e7": j, "max_lon_e7": e, "max_lat_e7": n,
             "center_zoom": tiles.ZOOM, "center_lon_e7": (w + e) // 2,
             "center_lat_e7": (j + n) // 2},
            {"name": f"{key}-routing", "format": "rtil",
             "description": "Routing network with tags – the phone computes the cost",
             "graph": graph})
    print(f"{path}: {len(bodies)} tiles (z{tiles.ZOOM}–z{zoom_max}), "
          f"{os.path.getsize(path)} B, {len(s.edges)} edges")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder for the archives")
    args = ap.parse_args()

    dictionary = tags_mod.dictionary()
    whole = dense(base_network())
    all_roads = roads()
    hill_net = hills()
    junction_net = junctions()
    # the order covers the whole area, or two cutouts rank a node differently
    area = Net()
    area.nodes = {**whole.nodes, **all_roads.nodes, **hill_net.nodes,
                  **junction_net.nodes}
    node_order = Order(area)
    write(os.path.join(args.out, "routing-fixture.pmtiles"), whole, dictionary,
          "fixture", node_order)
    write(os.path.join(args.out, "routing-fixture-west.pmtiles"),
          cutout(base_network(), True), dictionary, "fixture-west", node_order)
    write(os.path.join(args.out, "routing-fixture-east.pmtiles"),
          cutout(base_network(), False), dictionary, "fixture-east", node_order)
    write(os.path.join(args.out, "routing-fixture-roads.pmtiles"), all_roads,
          dictionary, "fixture-roads", node_order)
    write(os.path.join(args.out, "routing-fixture-hills.pmtiles"), hill_net,
          dictionary, "fixture-hills", node_order)
    write(os.path.join(args.out, "routing-fixture-junctions.pmtiles"),
          junction_net, dictionary, "fixture-junctions", node_order)
    # not part of the run, so beside it: the lint doesn't run over it
    write(os.path.join(args.out, "other-order", "routing-fixture-east.pmtiles"),
          cutout(base_network(), False), dictionary, "fixture-east",
          Order(area, ORDER_OTHER, shift=1))
    print(json.dumps({"dictionary": f"{dictionary.id:08x}",
                      "order": f"{ORDER_ID:08x}",
                      "other": f"{ORDER_OTHER:08x}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
