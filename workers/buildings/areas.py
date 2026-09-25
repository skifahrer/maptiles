#!/usr/bin/env python3
"""Výmeru plochy v m² zapíše na budovu a sídlo ako tag `area_m2`."""
import argparse
import math
from pathlib import Path

import osmium

R = 6371008.8


def kruh(body):
    """Plocha prstenca v m² – planetiler výmeru v schéme spočítať nevie."""
    if len(body) < 4:
        return 0.0
    lat0 = math.radians(sum(b[1] for b in body) / len(body))
    xy = [(math.radians(x) * R * math.cos(lat0), math.radians(y) * R) for x, y in body]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xy, xy[1:]))) / 2


def body(ring):
    return [(n.lon, n.lat) for n in ring if n.location.valid()]


class Plochy(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.cesty = {}
        self.relacie = {}

    def area(self, a):
        t = a.tags
        if "building" not in t and "place" not in t:
            return
        m2 = 0.0
        for von in a.outer_rings():
            m2 += kruh(body(von))
            for dnu in a.inner_rings(von):
                m2 -= kruh(body(dnu))
        if m2 <= 0:
            return
        (self.cesty if a.from_way() else self.relacie)[a.orig_id()] = round(m2)


class Zapis(osmium.SimpleHandler):
    def __init__(self, plochy, writer):
        super().__init__()
        self.p = plochy
        self.w = writer

    def node(self, n):
        self.w.add_node(n)

    def way(self, w):
        m2 = self.p.cesty.get(w.id)
        self.w.add_way(w if m2 is None else w.replace(tags={**dict(w.tags), "area_m2": str(m2)}))

    def relation(self, r):
        m2 = self.p.relacie.get(r.id)
        self.w.add_relation(r if m2 is None else r.replace(tags={**dict(r.tags), "area_m2": str(m2)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    plochy = Plochy()
    plochy.apply_file(a.pbf, locations=True, idx="flex_mem")
    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    try:
        Zapis(plochy, writer).apply_file(a.pbf)
    finally:
        writer.close()
    print(f"Výmera: {len(plochy.cesty)} ciest a {len(plochy.relacie)} relácií")


if __name__ == "__main__":
    main()
