#!/usr/bin/env python3
"""A few km² of hand-placed OSM, written as `.osm`; long jittered ways so every prefilter passes 2000 B."""
import argparse
import math
import random
from xml.sax.saxutils import quoteattr

BBOX = (17.10, 48.10, 17.20, 48.16)
OUTLINE = [(17.11, 48.11), (17.19, 48.11), (17.19, 48.15), (17.15, 48.155), (17.11, 48.15)]
# lies outside the outline; nothing of it may reach a tile
FAR = (17.26, 48.20)


class Osm:
    def __init__(self, seed=1):
        self.rnd = random.Random(seed)
        self.nodes, self.ways, self.relations = [], [], []
        self.next_id = {"n": 1000, "w": 1000, "r": 1000}

    def _id(self, kind):
        self.next_id[kind] += 1
        return self.next_id[kind]

    def node(self, lon, lat, **tags):
        nid = self._id("n")
        self.nodes.append((nid, lon, lat, tags))
        return nid

    def line(self, points, every_m=15.0, jitter_m=2.0):
        """Node ids along `points`, a node every `every_m`, each nudged by up to `jitter_m`."""
        out = []
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            mx = 111320 * math.cos(math.radians(y1))
            steps = max(1, int(math.hypot((x2 - x1) * mx, (y2 - y1) * 110540) / every_m))
            for k in range(steps):
                t = k / steps
                jx = self.rnd.uniform(-jitter_m, jitter_m) / mx
                jy = self.rnd.uniform(-jitter_m, jitter_m) / 110540
                out.append(self.node(x1 + t * (x2 - x1) + jx, y1 + t * (y2 - y1) + jy))
        out.append(self.node(*points[-1]))
        return out

    def ring(self, points, **kw):
        ids = self.line(points + [points[0]], **kw)
        return ids[:-1] + ids[:1]

    def way(self, nodes, **tags):
        wid = self._id("w")
        self.ways.append((wid, nodes, tags))
        return wid

    def relation(self, members, **tags):
        rid = self._id("r")
        self.relations.append((rid, members, tags))
        return rid

    def xml(self):
        def tags(t):
            return "".join(f'<tag k={quoteattr(k.replace("__", ":"))} v={quoteattr(str(v))}/>'
                           for k, v in t.items())
        out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="mini_region.py">']
        for nid, lon, lat, t in self.nodes:
            out.append(f'<node id="{nid}" version="1" lat="{lat:.7f}" lon="{lon:.7f}">{tags(t)}</node>')
        for wid, nodes, t in self.ways:
            out.append(f'<way id="{wid}" version="1">' + "".join(f'<nd ref="{n}"/>' for n in nodes)
                       + tags(t) + "</way>")
        for rid, members, t in self.relations:
            out.append(f'<relation id="{rid}" version="1">'
                       + "".join(f'<member type="{k}" ref="{ref}" role="{role}"/>' for k, ref, role in members)
                       + tags(t) + "</relation>")
        out.append("</osm>")
        return "\n".join(out) + "\n"


def square(lon, lat, side_m):
    dx = side_m / (111320 * math.cos(math.radians(lat))) / 2
    dy = side_m / 110540 / 2
    return [(lon - dx, lat - dy), (lon + dx, lat - dy), (lon + dx, lat + dy), (lon - dx, lat + dy)]


def build():
    o = Osm()
    # roads: a numbered main road, a motorway link, a village grid, a road outside
    main_nodes = o.line([(17.105, 48.13), (17.15, 48.132), (17.195, 48.135)])
    main = o.way(main_nodes, highway="primary", ref="I/61", name="Hlavná", maxspeed="90")
    junction = main_nodes[len(main_nodes) // 2]
    jlon, jlat = next((n[1], n[2]) for n in o.nodes if n[0] == junction)
    side = o.way([junction] + o.line([(jlon, jlat), (jlon + 0.002, 48.118)])[1:],
                 highway="tertiary", name="Bočná")
    o.relation([("w", main, "from"), ("n", junction, "via"), ("w", side, "to")],
               type="restriction", restriction="no_left_turn")
    o.way(o.line([(17.17, 48.125), (17.18, 48.12), (17.19, 48.118)]),
          highway="motorway_link", oneway="yes")
    for i in range(6):
        y = 48.135 + i * 0.002
        o.way(o.line([(17.13, y), (17.16, y)]), highway="residential", name=f"Ulica {i + 1}")
    path = o.way(o.line([(17.12, 48.14), (17.14, 48.148), (17.17, 48.145)]), highway="path")
    track = o.way(o.line([(17.17, 48.145), (17.185, 48.12)]), highway="track", tracktype="grade2")
    o.way(o.line([(FAR[0] - 0.01, FAR[1]), (FAR[0] + 0.01, FAR[1])]), highway="secondary", name="Vonku")
    for i in range(30):
        o.node(17.131 + (i % 10) * 0.003, 48.1365 + (i // 10) * 0.002, **{"addr__housenumber": str(i + 1)})

    # hiking route on the path and track
    o.relation([("w", path, ""), ("w", track, "")], type="route", route="hiking",
               network="lwn", name="Okruh", **{"osmc__symbol": "red:white:red_bar"})

    # admin boundaries 2, 4 and 8 on one densified outline
    outline = o.way(o.ring(OUTLINE, every_m=25), boundary="administrative", admin_level="2")
    for level, name in ((2, "Slovensko"), (4, "Bratislavský kraj"), (8, "Malá Obec")):
        o.relation([("w", outline, "outer")], type="boundary", boundary="administrative",
                   admin_level=level, name=name, **{"name__de": name + " (de)"})
    o.node(17.145, 48.138, place="village", name="Malá Obec", population="900", **{"name__de": "Kleindorf"})

    # water: a river, a lake multipolygon, a spring, a lake outside
    o.way(o.line([(17.105, 48.115), (17.15, 48.122), (17.198, 48.126)]),
          waterway="river", name="Mlynský potok", **{"name__en": "Mill Brook"})
    lake = o.way(o.ring(square(17.125, 48.12, 400), every_m=10))
    o.relation([("w", lake, "outer")], type="multipolygon", natural="water", water="lake", name="Jazero")
    o.node(17.135, 48.145, natural="spring", name="Studnička")
    o.way(o.ring(square(*FAR, 300), every_m=10), natural="water", name="Cudzie jazero")

    # rail: a line through a switch onto a branch, a cable car, a train route
    a = o.line([(17.105, 48.112), (17.15, 48.114)], every_m=20)
    switch = a[-1]
    o.nodes[[n[0] for n in o.nodes].index(switch)][3].update(railway="switch")
    b = [switch] + o.line([(17.15, 48.114), (17.195, 48.116)], every_m=20)[1:]
    c = [switch] + o.line([(17.15, 48.114), (17.17, 48.12)], every_m=20)[1:]
    r1 = o.way(a, railway="rail", maxspeed="100", gauge="1435", usage="main")
    r2 = o.way(b, railway="rail", maxspeed="120", gauge="1435", usage="main")
    o.way(c, railway="rail", service="siding")
    o.relation([("w", r1, ""), ("w", r2, "")], type="route", route="train", ref="R 50", colour="#c00000")
    o.way(o.line([(17.16, 48.148), (17.18, 48.153)], every_m=20), aerialway="cable_car", name="Lanovka")

    # history and army
    o.node(17.155, 48.142, historic="castle", name="Hrad", wikipedia="sk:Hrad")
    o.way(o.ring(square(17.175, 48.14, 60), every_m=5), military="bunker", building="bunker")
    o.node(17.16, 48.13, historic="wayside_cross")
    o.way(o.ring(square(17.115, 48.145, 120), every_m=5), historic="ruins", name="Zrúcanina")
    o.way(o.line([(17.11, 48.128), (17.15, 48.126), (17.19, 48.129)], every_m=8),
          man_made="embankment", name="Hrádza")
    o.way(o.line([(17.17, 48.13), (17.18, 48.135)], every_m=5), military="trench")

    # settlement: buildings, a named one, residential land
    for i in range(40):
        lon, lat = 17.131 + (i % 10) * 0.003, 48.1375 + (i // 10) * 0.002
        names = {"name": "Kostol"} if i == 0 else {}
        o.way(o.ring(square(lon, lat, 14 + i % 5), every_m=3), building="house" if i else "church", **names)
    o.way(o.ring([(17.128, 48.134), (17.162, 48.134), (17.162, 48.146), (17.128, 48.146)], every_m=20),
          landuse="residential")

    # landscape features and a peak
    o.node(17.17, 48.15, man_made="tower", **{"tower__type": "observation"}, name="Rozhľadňa")
    o.node(17.12, 48.125, natural="cave_entrance", name="Jaskyňa")
    o.way(o.line([(17.105, 48.153), (17.195, 48.152)], every_m=40), power="line")
    o.way(o.line([(17.13, 48.118), (17.16, 48.119)]), barrier="wall")
    o.way(o.line([(17.11, 48.149), (17.15, 48.147), (17.19, 48.148)], every_m=8), barrier="fence")
    o.way(o.line([(17.12, 48.13), (17.125, 48.14)], every_m=5), natural="tree_row")
    for i, tags in enumerate(({"amenity": "parking"}, {"landuse": "landfill"}, {"landuse": "farmyard"},
                              {"landuse": "brownfield"}, {"natural": "shingle"})):
        o.way(o.ring(square(17.165 + i * 0.004, 48.123, 120), every_m=10), **tags)
    o.way(o.line([(17.175, 48.152), (17.18, 48.13)], every_m=10),
          **{"piste__type": "nordic", "piste__grooming": "classic", "name": "Bežkárska"})
    o.way(o.ring(square(17.185, 48.14, 200), every_m=10),
          **{"piste__type": "downhill", "piste__difficulty": "easy"})
    o.node(17.185, 48.148, natural="peak", ele="512", name="Vrch", wikipedia="sk:Vrch")
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build().xml())


if __name__ == "__main__":
    main()
