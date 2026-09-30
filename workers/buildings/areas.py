#!/usr/bin/env python3
"""Writes the area in m² onto buildings and places as tag `area_m2`."""
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

    def area(self, a):
        t = a.tags
        if "building" not in t and "place" not in t:
            return
        m2 = 0.0
        for outer in a.outer_rings():
            m2 += ring_area(points(outer))
            for inner in a.inner_rings(outer):
                m2 -= ring_area(points(inner))
        if m2 <= 0:
            return
        (self.ways if a.from_way() else self.relations)[a.orig_id()] = round(m2)


class Write(osmium.SimpleHandler):
    def __init__(self, areas, writer):
        super().__init__()
        self.p = areas
        self.w = writer

    def node(self, n):
        self.w.add_node(n)

    def way(self, w):
        m2 = self.p.ways.get(w.id)
        self.w.add_way(w if m2 is None else w.replace(tags={**dict(w.tags), "area_m2": str(m2)}))

    def relation(self, r):
        m2 = self.p.relations.get(r.id)
        self.w.add_relation(r if m2 is None else r.replace(tags={**dict(r.tags), "area_m2": str(m2)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    areas = Areas()
    areas.apply_file(a.pbf, locations=True, idx="flex_mem")
    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    try:
        Write(areas, writer).apply_file(a.pbf)
    finally:
        writer.close()
    print(f"Area: {len(areas.ways)} ways and {len(areas.relations)} relations")


if __name__ == "__main__":
    main()
