#!/usr/bin/env python3
"""Farbu a číslo linky z `type=route` relácie prepíše na jej koľaje."""
import argparse

import osmium

# linky, ktorých farba patrí na koľaj
TRASY = {"tram", "subway", "light_rail", "monorail", "train", "railway", "funicular"}
# mestská linka má na koľaji prednosť pred vlakom, čo po nej ide tiež
PREDNOST = {"tram": 0, "subway": 0, "light_rail": 0, "monorail": 0, "funicular": 1}


class Linky(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.farba = {}
        self.cisla = {}

    def relation(self, r):
        t = r.tags
        if t.get("type") != "route" or t.get("route") not in TRASY:
            return
        farba = t.get("colour")
        cislo = t.get("ref")
        poradie = PREDNOST.get(t.get("route"), 2)
        for m in r.members:
            if m.type != "w":
                continue
            if farba and poradie < self.farba.get(m.ref, (9, ""))[0]:
                self.farba[m.ref] = (poradie, farba)
            if cislo:
                self.cisla.setdefault(m.ref, set()).add(cislo)


class Prepis(osmium.SimpleHandler):
    def __init__(self, linky, writer):
        super().__init__()
        self.linky = linky
        self.w = writer
        self.zmenene = 0

    def node(self, n):
        self.w.add_node(n)

    def way(self, w):
        farba = self.linky.farba.get(w.id)
        cisla = self.linky.cisla.get(w.id)
        if not farba and not cisla:
            self.w.add_way(w)
            return
        tagy = dict(w.tags)
        if farba and "colour" not in tagy:
            tagy["colour"] = farba[1]
        if cisla:
            tagy["route_ref"] = ";".join(sorted(cisla, key=lambda c: (len(c), c)))
        self.w.add_way(w.replace(tags=tagy))
        self.zmenene += 1

    def relation(self, r):
        self.w.add_relation(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    linky = Linky()
    linky.apply_file(a.pbf)
    writer = osmium.SimpleWriter(a.out, overwrite=True)
    try:
        prepis = Prepis(linky, writer)
        prepis.apply_file(a.pbf)
    finally:
        writer.close()
    print(f"Linky: {prepis.zmenene} koľají dostalo farbu alebo číslo linky")


if __name__ == "__main__":
    main()
