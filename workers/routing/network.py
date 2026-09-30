#!/usr/bin/env python3
"""From a PBF, the junction graph – nodes, tagged edges and turn restrictions."""
import math
import os
import sys
from collections import Counter

import osmium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import tags as tags_mod                                           # noqa: E402

E7 = 1e7
RADIUS_M = 6371000.0

# `oneway` without these values is a two-way road
FORWARD = {"yes", "true", "1"}
BACKWARD = {"-1", "reverse"}


class Network:
    """One area's junction graph – what goes into tiles and into the node order."""

    def __init__(self):
        self.nodes = {}         # osm id -> (lat_e7, lon_e7)
        self.edges = []
        self.restrictions = []
        self.dropped = Counter()
        self.skipped = Counter()
        self.ways = 0

    def neighbours(self):
        """Node -> neighbours, undirected; the order is computed over the shape."""
        out = {u: set() for u in self.nodes}
        for h in self.edges:
            if h["from"] != h["to"]:
                out[h["from"]].add(h["to"])
                out[h["to"]].add(h["from"])
        return out


class _Restrictions(osmium.SimpleHandler):
    """Pass 1: `type=restriction` relations – no edges yet."""

    def __init__(self):
        super().__init__()
        self.restrictions = []
        self.nodes = set()
        self.skipped = Counter()

    def relation(self, r):
        t = {tag.k: tag.v for tag in r.tags}
        if t.get("type") != "restriction":
            return
        kind = (t.get("restriction") or "").strip()
        if kind not in fmt.RESTRICTION_KINDS:
            # `restriction:hgv` and `:conditional` aren't a permanent ban for all
            other = next((k for k in t if k.startswith("restriction:")), "")
            self.skipped[other or kind or "no `restriction`"] += 1
            return
        frm = [m.ref for m in r.members if m.type == "w" and m.role == "from"]
        to = [m.ref for m in r.members if m.type == "w" and m.role == "to"]
        via_n = [m.ref for m in r.members if m.type == "n" and m.role == "via"]
        via_w = [m.ref for m in r.members if m.type == "w" and m.role == "via"]
        if len(frm) != 1 or len(to) != 1 or (not via_n and not via_w):
            self.skipped["incomplete relation"] += 1
            return
        exceptions = 0
        for v in (t.get("except") or "").split(";"):
            v = v.strip()
            if v in fmt.EXCEPTIONS:
                exceptions |= 1 << fmt.EXCEPTIONS.index(v)
        self.restrictions.append({"rel": r.id, "kind": fmt.RESTRICTION_KINDS.index(kind),
                                  "exceptions": exceptions, "from": frm[0], "to": to[0],
                                  "via_node": via_n[0] if via_n else None,
                                  "via_ways": via_w})
        self.nodes.update(via_n)


class _Junctions(osmium.SimpleHandler):
    """Pass 2: which node is a junction – without coordinates, so without an index."""

    def __init__(self, dictionary):
        super().__init__()
        self.dictionary = dictionary
        self.seen = set()
        self.repeated = set()
        self.ends = set()
        self.ways = 0

    def way(self, w):
        t = {tag.k: tag.v for tag in w.tags}
        if not self.dictionary.road_class(t) or len(w.nodes) < 2:
            return
        self.ways += 1
        refs = [n.ref for n in w.nodes]
        for ref in refs:
            if ref in self.seen:
                self.repeated.add(ref)
            else:
                self.seen.add(ref)
        self.ends.add(refs[0])
        self.ends.add(refs[-1])


class _Edges(osmium.SimpleHandler):
    """Pass 3: a way is cut at junctions, the geometry lies between."""

    def __init__(self, dictionary, junctions, network):
        super().__init__()
        self.dictionary = dictionary
        self.junctions = junctions
        self.network = network

    def way(self, w):
        t = {tag.k: tag.v for tag in w.tags}
        if not self.dictionary.road_class(t) or len(w.nodes) < 2:
            return
        picked, dropped = self.dictionary.pick(t)
        for key, value in dropped:
            self.network.dropped[f"{key}={value}"] += 1
        try:
            points = [(n.ref, round(n.location.lat * E7), round(n.location.lon * E7))
                      for n in w.nodes]
        except osmium.InvalidLocationError:
            self.network.skipped["way without node coordinates"] += 1
            return

        direction = _direction(picked)
        start = 0
        for i in range(1, len(points)):
            if points[i][0] not in self.junctions and i != len(points) - 1:
                continue
            piece = points[start:i + 1]
            start = i
            if len(piece) < 2 or piece[0][0] == piece[-1][0]:
                # a loop without a second junction isn't an edge one can take
                continue
            for ref, lat, lon in (piece[0], piece[-1]):
                self.network.nodes[ref] = (lat, lon)
            self.network.edges.append({
                "way": w.id,
                "from": piece[0][0], "to": piece[-1][0],
                "geom": [(lat, lon) for _r, lat, lon in piece[1:-1]],
                "length_cm": _length_cm(piece),
                "direction": direction,
                "tags": picked,
            })


def _direction(tags):
    """Direction from tags; per-vehicle assumptions belong on the phone."""
    oneway = tags.get("oneway", "")
    if oneway in FORWARD:
        return fmt.D_FORWARD
    if oneway in BACKWARD:
        return fmt.D_BACKWARD
    if not oneway and tags.get("junction") in ("roundabout", "circular"):
        return fmt.D_FORWARD
    return fmt.D_FORWARD | fmt.D_BACKWARD


def _length_cm(piece):
    m = 0.0
    for (_r1, lat1, lon1), (_r2, lat2, lon2) in zip(piece, piece[1:]):
        m += _haversine(lat1 / E7, lon1 / E7, lat2 / E7, lon2 / E7)
    return int(round(m * 100))


def _haversine(lat1, lon1, lat2, lon2):
    f1, f2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = (math.sin((f2 - f1) / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2)
    return 2 * RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _way_edges(network):
    out = {}
    for h in network.edges:
        out.setdefault(h["way"], []).append(h)
    return out


def _edge_at(edges, node, towards):
    """The way's edge touching the node, in the direction of travel."""
    for h in edges:
        if h["from"] == node:
            return (h["to"], h["from"]) if towards else (h["from"], h["to"])
        if h["to"] == node:
            return (h["from"], h["to"]) if towards else (h["to"], h["from"])
    return None


def _resolve_restrictions(network, raw):
    """Relations into node pairs – an edge is named `(from, to)` in travel direction."""
    by_way = _way_edges(network)
    for z in raw:
        from_edges = by_way.get(z["from"], [])
        to_edges = by_way.get(z["to"], [])
        if not from_edges or not to_edges:
            network.skipped["restriction on a way outside the area"] += 1
            continue
        if z["via_node"] is not None:
            first = _edge_at(from_edges, z["via_node"], towards=True)
            second = _edge_at(to_edges, z["via_node"], towards=False)
            if not first or not second:
                network.skipped["restriction doesn't touch its `via` node"] += 1
                continue
            chain = [first, second]
        else:
            chain = _via_ways(by_way, z, network)
            if not chain:
                continue
        network.restrictions.append({"kind": z["kind"], "exceptions": z["exceptions"],
                                     "edges": chain, "via": chain[0][1]})


def _via_ways(by_way, z, network):
    """A restriction via ways: the edge chain from `from` via `via` to `to`."""
    middle = []
    for w in z["via_ways"]:
        middle.extend(by_way.get(w, []))
    if not middle:
        network.skipped["restriction via a way outside the area"] += 1
        return None
    for start in {h["from"] for h in middle} | {h["to"] for h in middle}:
        first = _edge_at(by_way[z["from"]], start, towards=True)
        if not first:
            continue
        chain, node, left = [first], start, list(middle)
        while left:
            nxt = next((h for h in left if node in (h["from"], h["to"])), None)
            if not nxt:
                break
            left.remove(nxt)
            node = nxt["to"] if nxt["from"] == node else nxt["from"]
            chain.append((chain[-1][1], node))
        last = _edge_at(by_way[z["to"]], node, towards=False)
        if last and not left:
            return chain + [last]
    network.skipped["restriction via a way can't be assembled"] += 1
    return None


def load(pbf, dictionary=None):
    """PBF → `Network`; three passes, since relations come after ways in the file."""
    dictionary = dictionary or tags_mod.dictionary()
    network = Network()

    rs = _Restrictions()
    rs.apply_file(pbf)
    network.skipped.update(rs.skipped)

    js = _Junctions(dictionary)
    js.apply_file(pbf)
    network.ways = js.ways
    junctions = js.repeated | js.ends | rs.nodes
    del js

    edges = _Edges(dictionary, junctions, network)
    edges.apply_file(pbf, locations=True, idx="flex_mem")
    _resolve_restrictions(network, rs.restrictions)
    return network
