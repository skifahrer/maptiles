#!/usr/bin/env python3
"""Farbu a číslo linky z `type=route` relácie prepíše na jej koľaje.

Dopočíta aj body, kde sa mení traťová rýchlosť (`rail_speed`, `rail_speed_prev`),
a smer koľaje pri návestidle (`rail_bearing`), ktorým ukazuje jeho šípka.
"""
import argparse
import math
import re
from pathlib import Path

import osmium

# linky, ktorých farba patrí na koľaj
TRASY = {"tram", "subway", "light_rail", "monorail", "train", "railway", "funicular"}
# mestská linka má na koľaji prednosť pred vlakom, čo po nej ide tiež
PREDNOST = {"tram": 0, "subway": 0, "light_rail": 0, "monorail": 0, "funicular": 1}
# trate, na ktorých sa rýchlosť počíta – vlečky a mestské koľaje nie
RYCHLE = {"rail", "narrow_gauge"}
# koľaje, po ktorých sa berie smer návestidla
KOLAJE = RYCHLE | {"light_rail", "subway", "tram", "monorail", "funicular", "preserved"}
CISLO = re.compile(r"^(\d+(?:\.\d+)?)\s*(mph)?$")


def rychlost(hodnota):
    """`maxspeed` v km/h ako celé číslo; `80;60` berie prvú, `none` a iné nič."""
    if not hodnota:
        return None
    zhoda = CISLO.match(hodnota.split(";")[0].strip())
    if not zhoda:
        return None
    km = float(zhoda.group(1)) * (1.609344 if zhoda.group(2) else 1)
    return int(round(km))


def azimut(a, b):
    """Zemepisný azimut z `a` do `b` v stupňoch, 0 je sever."""
    f1, f2 = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lon - a.lon)
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def zmeny_rychlosti(konce):
    """Uzol, kde sa stretnú presne dve trate s inou rýchlosťou → (predtým, potom).

    Keď jedna trať v uzle končí a druhá začína, poradie je v smere ciest; inak sa
    smer nevie a ide od nižšej k vyššej."""
    zmeny = {}
    for uzol, zaznamy in konce.items():
        if len(zaznamy) != 2:
            continue
        (v1, r1), (v2, r2) = zaznamy
        if v1 == v2:
            continue
        if {r1, r2} == {"koniec", "zaciatok"}:
            pred, po = (v1, v2) if r1 == "koniec" else (v2, v1)
        else:
            pred, po = min(v1, v2), max(v1, v2)
        zmeny[uzol] = (pred, po)
    return zmeny


class Linky(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.farba = {}
        self.cisla = {}
        # uzol → [(rýchlosť, "koniec"|"zaciatok")] z koncov hlavných tratí
        self.konce = {}
        # návestidlo → smer, ktorým platí; a azimut koľaje pri ňom
        self.navestidla = {}
        self.azimut = {}

    def node(self, n):
        if n.tags.get("railway") == "signal":
            self.navestidla[n.id] = n.tags.get("railway:signal:direction", "forward")

    def way(self, w):
        druh = w.tags.get("railway")
        if druh not in KOLAJE:
            return
        uzly = w.nodes
        if druh in RYCHLE and "service" not in w.tags and len(uzly) > 1:
            v = rychlost(w.tags.get("maxspeed"))
            if v:
                self.konce.setdefault(uzly[0].ref, []).append((v, "zaciatok"))
                self.konce.setdefault(uzly[-1].ref, []).append((v, "koniec"))
        for i, nd in enumerate(uzly):
            smer = self.navestidla.get(nd.ref)
            if smer not in ("forward", "backward") or nd.ref in self.azimut:
                continue
            a, b = uzly[max(i - 1, 0)], uzly[min(i + 1, len(uzly) - 1)]
            if a.ref == b.ref or not (a.location.valid() and b.location.valid()):
                continue
            uhol = azimut(a.location, b.location) + (180 if smer == "backward" else 0)
            self.azimut[nd.ref] = int(round(uhol)) % 360

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
    def __init__(self, linky, zmeny, writer):
        super().__init__()
        self.linky = linky
        self.zmeny = zmeny
        self.w = writer
        self.zmenene = 0

    def node(self, n):
        zmena = self.zmeny.get(n.id)
        uhol = self.linky.azimut.get(n.id)
        if zmena is None and uhol is None:
            self.w.add_node(n)
            return
        tagy = dict(n.tags)
        if zmena:
            tagy["rail_speed_prev"], tagy["rail_speed"] = map(str, zmena)
        if uhol is not None:
            tagy["rail_bearing"] = str(uhol)
        self.w.add_node(n.replace(tags=tagy))

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
    linky.apply_file(a.pbf, locations=True, idx="flex_mem")
    zmeny = zmeny_rychlosti(linky.konce)
    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    try:
        prepis = Prepis(linky, zmeny, writer)
        prepis.apply_file(a.pbf)
    finally:
        writer.close()
    print(f"Linky: {prepis.zmenene} koľají dostalo farbu alebo číslo linky")
    print(f"Rýchlosť sa mení v {len(zmeny)} bodoch, {len(linky.azimut)} návestidiel "
          f"má smer")


if __name__ == "__main__":
    main()
