#!/usr/bin/env python3
"""Marks municipalities whose settlement point carries their name, so the map writes it once."""
import argparse
import os
import sys
from pathlib import Path

import osmium

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from place_twins import bbox, twins  # noqa: E402

MUNICIPALITY = "8"
MARK = "named_by_place"


class Collect(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.points = []
        self.areas = []

    def node(self, n):
        if "place" in n.tags and n.location.valid():
            self.points.append((n.id, n.tags.get("name"), n.tags.get("wikidata"),
                                n.location.lon, n.location.lat))

    def area(self, a):
        t = a.tags
        if t.get("boundary") != "administrative" or t.get("admin_level") != MUNICIPALITY:
            return
        ring = [(n.lon, n.lat) for outer in a.outer_rings() for n in outer if n.location.valid()]
        if ring:
            key = ("w" if a.from_way() else "r", a.orig_id())
            self.areas.append((key, t.get("name"), t.get("wikidata"), bbox(ring)))


class Write(osmium.SimpleHandler):
    def __init__(self, marked, writer):
        super().__init__()
        self.marked = marked
        self.w = writer

    def node(self, n):
        self.w.add_node(n)

    def way(self, w):
        self.w.add_way(w.replace(tags={**dict(w.tags), MARK: "yes"}) if ("w", w.id) in self.marked else w)

    def relation(self, r):
        self.w.add_relation(r.replace(tags={**dict(r.tags), MARK: "yes"}) if ("r", r.id) in self.marked else r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    seen = Collect()
    seen.apply_file(a.pbf, locations=True, idx="flex_mem")
    marked = set(twins(seen.points, seen.areas))
    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    try:
        Write(marked, writer).apply_file(a.pbf)
    finally:
        writer.close()
    print(f"Municipalities: {len(seen.areas)}, {len(marked)} named by their settlement point")


if __name__ == "__main__":
    main()
