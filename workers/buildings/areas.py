#!/usr/bin/env python3
"""Writes the area in m² onto buildings and places as `area_m2`; a place mapped twice keeps its point."""
import argparse
import math
from pathlib import Path

import osmium

R = 6371008.8


def ring_area(points):
    """Ring area in m² – planetiler can't compute it in the schema."""
    if len(points) < 4:
        return 0.0
    lat0 = math.radians(sum(b[1] for b in points) / len(points))
    xy = [(math.radians(x) * R * math.cos(lat0), math.radians(y) * R) for x, y in points]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xy, xy[1:]))) / 2


def points(ring):
    return [(n.lon, n.lat) for n in ring if n.location.valid()]


class Areas(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = {}
        self.relations = {}
        self.place_nodes = []
        self.place_areas = []

    def node(self, n):
        if "place" in n.tags and n.location.valid():
            self.place_nodes.append((n.id, n.tags.get("name"), n.tags.get("wikidata"),
                                     n.location.lon, n.location.lat))

    def area(self, a):
        t = a.tags
        if "building" not in t and "place" not in t:
            return
        m2 = 0.0
        ring = []
        for outer in a.outer_rings():
            ring += points(outer)
            m2 += ring_area(points(outer))
            for inner in a.inner_rings(outer):
                m2 -= ring_area(points(inner))
        if m2 <= 0:
            return
        key = ("w" if a.from_way() else "r", a.orig_id())
        (self.ways if a.from_way() else self.relations)[key[1]] = round(m2)
        if "place" in t and ring:
            box = (min(x for x, _ in ring), min(y for _, y in ring),
                   max(x for x, _ in ring), max(y for _, y in ring))
            self.place_areas.append((key, t.get("name"), t.get("wikidata"), box, round(m2)))

    def twins(self):
        """Place areas that have a place point, and the area each point takes over."""
        by_wikidata = {w: i for i, _, w, _, _ in self.place_nodes if w}
        by_name = {}
        for i, name, _, x, y in self.place_nodes:
            by_name.setdefault(name, []).append((i, x, y))
        dropped, node_m2 = set(), {}
        for key, name, wikidata, (w, s, e, n), m2 in self.place_areas:
            node = by_wikidata.get(wikidata) if wikidata else None
            if node is None and name:
                node = next((i for i, x, y in by_name.get(name, ())
                             if w <= x <= e and s <= y <= n), None)
            if node is not None:
                dropped.add(key)
                node_m2[node] = max(node_m2.get(node, 0), m2)
        return dropped, node_m2


class Write(osmium.SimpleHandler):
    def __init__(self, areas, writer):
        super().__init__()
        self.p = areas
        self.w = writer
        self.dropped, self.node_m2 = areas.twins()

    def node(self, n):
        m2 = self.node_m2.get(n.id)
        self.w.add_node(n if m2 is None else n.replace(tags={**dict(n.tags), "area_m2": str(m2)}))

    def tags(self, o, kind, m2):
        tags = {**dict(o.tags), "area_m2": str(m2)}
        # the point is drawn; the area would draw the name again
        if (kind, o.id) in self.dropped:
            tags.pop("place", None)
        return tags

    def way(self, w):
        m2 = self.p.ways.get(w.id)
        self.w.add_way(w if m2 is None else w.replace(tags=self.tags(w, "w", m2)))

    def relation(self, r):
        m2 = self.p.relations.get(r.id)
        self.w.add_relation(r if m2 is None else r.replace(tags=self.tags(r, "r", m2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    areas = Areas()
    areas.apply_file(a.pbf, locations=True, idx="flex_mem")
    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    write = Write(areas, writer)
    try:
        write.apply_file(a.pbf)
    finally:
        writer.close()
    print(f"Area: {len(areas.ways)} ways and {len(areas.relations)} relations; "
          f"{len(write.dropped)} place areas left to their point")


if __name__ == "__main__":
    main()
