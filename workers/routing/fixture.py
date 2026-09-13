#!/usr/bin/env python3
"""Malý archív `RTIL` na testy čítačky v appke – sieť je písaná ručne, nie z PBF."""
import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import tags as slovnik_modul                                      # noqa: E402
import tiles                                                      # noqa: E402

E7 = 10_000_000
# dlaždica pre hustú časť sa má rozdeliť, kraje nie – rozpočet je preto nízky
ROZPOCET = 900
# mriežka je okolo stredu z9 dlaždice, nech sa pri delení rozpadne na štvrtiny
STRANA = 12
KROK = 0.03
STRED = (21.4453125, 48.6904256)
PORADIE_ID = 0x0A0B0C0D
POLOVICA = 17.578125  # hranica z9 medzi 280 a 281, po nej sa archív reže


def e7(v):
    return round(v * E7)


class Siet:
    """To, čo `tiles.py` čaká od `network.nacitaj` – uzly, hrany a zákazy."""

    def __init__(self):
        self.uzly = {}
        self.hrany = []
        self.zakazy = []

    def uzol(self, osm, lon, lat):
        self.uzly[osm] = (e7(lat), e7(lon))
        return osm

    def hrana(self, od, do, tagy, smer=fmt.S_VPRED | fmt.S_VZAD, body=()):
        # geometria je len tvar medzi uzlami, tak ako ju píše `network.py`
        tvar = [(e7(lat), e7(lon)) for lon, lat in body]
        self.hrany.append({"od": od, "do": do, "tagy": tagy, "smer": smer,
                           "dlzka_cm": _dlzka_cm([self.uzly[od], *tvar,
                                                  self.uzly[do]]),
                           "geom": tvar})

    def zakaz(self, druh, vynimky, retaz):
        self.zakazy.append({"druh": fmt.DRUHY_ZAKAZOV.index(druh),
                            "vynimky": vynimky, "hrany": retaz,
                            "cez": retaz[0][1]})


def _dlzka_cm(geom):
    """Hrubá dĺžka – testy čítačky merajú, či číslo prejde, nie geodéziu."""
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(geom, geom[1:]):
        dy = (lat2 - lat1) / E7 * 111_320
        dx = (lon2 - lon1) / E7 * 111_320 * 0.66
        total += (dx * dx + dy * dy) ** 0.5
    return round(total * 100)


def siet():
    """Dva susedné kraje na hranici z9, križovatka so zákazmi a hustá dlaždica."""
    s = Siet()
    # západ: križovatka n2, z nej jednosmerná diaľnica a chodník
    n1 = s.uzol(1_000_001, 17.00, 48.60)
    n2 = s.uzol(1_000_002, 17.05, 48.60)
    n3 = s.uzol(1_000_003, 17.05, 48.65)
    n4 = s.uzol(1_000_004, 17.10, 48.60)
    # východ: za hranicou dlaždice, spoločný uzol oboch výrezov
    b1 = s.uzol(2_000_001, 17.70, 48.60)
    b2 = s.uzol(2_000_002, 17.80, 48.60)
    b3 = s.uzol(2_000_003, 17.75, 48.65)

    s.hrana(n1, n2, {"highway": "residential", "name": "Hlavná",
                     "surface": "asphalt"})
    s.hrana(n2, n3, {"highway": "motorway", "oneway": "yes", "ref": "D1",
                     "maxspeed": "130"}, smer=fmt.S_VPRED)
    s.hrana(n2, n4, {"highway": "footway", "foot": "yes"},
            body=[(17.07, 48.61), (17.09, 48.605)])
    # cez hranicu dlaždice: hrana je v dlaždici svojho prvého uzla
    s.hrana(n4, b1, {"highway": "primary", "name": "Cesta cez hranicu",
                     "ref": "I/61"})
    s.hrana(b1, b2, {"highway": "primary", "name": "Cesta cez hranicu",
                     "ref": "I/61"})
    s.hrana(b1, b3, {"highway": "track", "surface": "gravel",
                     "maxweight": "3"}, smer=fmt.S_VZAD)

    s.zakaz("no_left_turn", 1 << fmt.VYNIMKY.index("bicycle"),
            [(n1, n2), (n2, n3)])
    s.zakaz("only_straight_on", 0, [(n1, n2), (n2, n4), (n4, b1)])
    return s


def husta(s, n=STRANA):
    """Mriežka s vlastným menom v každej ulici – telo nad rozpočet, nech sa reže."""
    osm = 3_000_000
    rad = {}
    for i in range(n):
        for j in range(n):
            osm += 1
            rad[i, j] = s.uzol(osm, STRED[0] + (i - n / 2) * KROK,
                               STRED[1] + (j - n / 2) * KROK)
    for i in range(n):
        for j in range(n):
            tagy = {"highway": "residential", "name": f"Ulica {i}-{j}",
                    "surface": "paving_stones"}
            if i + 1 < n:
                s.hrana(rad[i, j], rad[i + 1, j], dict(tagy))
            if j + 1 < n:
                s.hrana(rad[i, j], rad[i, j + 1], dict(tagy))
    return s


def vyrez(s, zapad):
    """Kraj rezaný hranicou: hrana ostáva, keď je v ňom aspoň jeden jej koniec."""
    von = Siet()
    von.uzly = dict(s.uzly)
    for h in s.hrany:
        if any(_je_zapad(s.uzly[u]) == zapad for u in (h["od"], h["do"])):
            von.hrany.append(h)
    ostrov = {u for h in von.hrany for u in (h["od"], h["do"])}
    von.uzly = {k: v for k, v in s.uzly.items() if k in ostrov}
    von.zakazy = [z for z in s.zakazy
                  if all(u in ostrov for hr in z["hrany"] for u in hr)]
    return von


def _je_zapad(uzol):
    return uzol[1] < e7(POLOVICA)


class Poradie:
    """Rank pre každý uzol siete, aby mala dlaždica príznak poradia."""

    def __init__(self, s):
        self.id = PORADIE_ID
        self._rank = {osm: i for i, osm in enumerate(sorted(s.uzly))}

    def __bool__(self):
        return True

    def rank(self, osm):
        return self._rank.get(osm, len(self._rank) + osm)


def zapis(cesta, s, slovnik, kluc):
    from pmtiles.tile import (Compression, TileType,                # noqa: PLC0415
                              zxy_to_tileid)
    from pmtiles.writer import Writer                               # noqa: PLC0415

    poradie = Poradie(s)
    telá = tiles.rozdel(s, slovnik, "SK", poradie, rozpocet=ROZPOCET)
    zoom_max = max(z for z, _, _ in telá)
    graf = {
        "rozsah": "region", "kluc": kluc, "name": kluc, "format": "rtil",
        "format_verzia": fmt.VERZIA, "slovnik": f"{slovnik.id:08x}",
        "slovnik_verzia": slovnik.verzia, "poradie": f"{poradie.id:08x}",
        "krajina": "SK", "zoom": tiles.ZOOM, "zoom_max": zoom_max,
        "delenych": sum(1 for z, _, _ in telá if z > tiles.ZOOM),
        "dlazdic": len(telá), "uzlov": len(s.uzly), "hran": len(s.hrany),
        "zakazov": len(s.zakazy), "vyska": False, "multimodal": False,
        "built_at": "2026-09-13T00:00:00Z", "run": "", "run_id": "",
    }
    os.makedirs(os.path.dirname(os.path.abspath(cesta)), exist_ok=True)
    with open(cesta, "wb") as f:
        wr = Writer(f)
        for zxy in sorted(telá, key=lambda t: zxy_to_tileid(*t)):
            wr.write_tile(zxy_to_tileid(*zxy), telá[zxy])
        w = min(tiles.okno(*z)[0] for z in telá)
        j = min(tiles.okno(*z)[1] for z in telá)
        e = max(tiles.okno(*z)[2] for z in telá)
        n = max(tiles.okno(*z)[3] for z in telá)
        wr.finalize(
            {"tile_type": TileType.UNKNOWN, "tile_compression": Compression.GZIP,
             "min_zoom": tiles.ZOOM, "max_zoom": zoom_max,
             "min_lon_e7": w, "min_lat_e7": j, "max_lon_e7": e, "max_lat_e7": n,
             "center_zoom": tiles.ZOOM, "center_lon_e7": (w + e) // 2,
             "center_lat_e7": (j + n) // 2},
            {"name": f"{kluc}-routing", "format": "rtil",
             "description": "Smerovacia sieť so značkami – cenu počíta telefón",
             "graf": graf})
    print(f"{cesta}: {len(telá)} dlaždíc (z{tiles.ZOOM}–z{zoom_max}), "
          f"{os.path.getsize(cesta)} B, {len(s.hrany)} hrán")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="priečinok na archívy")
    args = ap.parse_args()

    slovnik = slovnik_modul.slovnik()
    zapis(os.path.join(args.out, "routing-fixture.pmtiles"), husta(siet()),
          slovnik, "fixture")
    zapis(os.path.join(args.out, "routing-fixture-west.pmtiles"),
          vyrez(siet(), True), slovnik, "fixture-west")
    zapis(os.path.join(args.out, "routing-fixture-east.pmtiles"),
          vyrez(siet(), False), slovnik, "fixture-east")
    print(json.dumps({"slovnik": f"{slovnik.id:08x}",
                      "poradie": f"{PORADIE_ID:08x}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
