#!/usr/bin/env python3
"""Malý archív `RTIL` na testy čítačky v appke – sieť je písaná ručne, nie z PBF."""
import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import order                                                      # noqa: E402
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
# archív, ktorý sa nesmie dať spojiť: appka má odmietnuť iné poradie
PORADIE_INE = 0x0A0B0C0E
POLOVICA = 17.578125  # hranica z9 medzi 280 a 281, po nej sa archív reže


def e7(v):
    return round(v * E7)


class Siet:
    """To, čo `tiles.py` čaká od `network.nacitaj` – uzly, hrany a zákazy."""

    def __init__(self):
        self.uzly = {}
        self.vysky = {}
        self.hrany = []
        self.zakazy = []

    def uzol(self, osm, lon, lat, vyska=None):
        self.uzly[osm] = (e7(lat), e7(lon))
        if vyska is not None:
            self.vysky[osm] = vyska
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


def cesty():
    """Sieť na triedy ciest a na priechod cez vypnutú cestu."""
    s = Siet()
    c = [s.uzol(4_000_000 + i, 18.00 + i * 0.10, 48.50) for i in range(6)]
    for od, do in zip(c, c[1:]):
        s.hrana(od, do, {"highway": "primary", "ref": "I/65",
                         "name": "Hlavný ťah"})
    # obchádzky sú dlhšie, ale hľadanie ich prejde, kým ich trieda neodreže
    for i in range(5):
        d = s.uzol(4_000_100 + i, 18.05 + i * 0.10, 48.52)
        s.hrana(c[i], d, {"highway": "residential", "name": "Obchádzka"})
        s.hrana(d, c[i + 1], {"highway": "residential", "name": "Obchádzka"})
    for osm, lat, dlzka in ((4_000_200, 48.45, 0.002), (4_000_300, 48.40, 0.068)):
        _priechod(s, osm, lat, dlzka)
        s.hrana(c[0], osm, {"highway": "residential", "name": "Prípojka"})
    return s


def _priechod(s, osm, lat, dlzka):
    """Dve ulice spojené jedine poľnou cestou, ktorej dĺžka je tu premenná."""
    r1 = s.uzol(osm, 18.00, lat)
    r2 = s.uzol(osm + 1, 18.02, lat)
    r3 = s.uzol(osm + 2, 18.02 + dlzka, lat)
    r4 = s.uzol(osm + 3, 18.04 + dlzka, lat)
    s.hrana(r1, r2, {"highway": "residential", "name": "Ulica pred"})
    s.hrana(r2, r3, {"highway": "track", "surface": "gravel"})
    s.hrana(r3, r4, {"highway": "residential", "name": "Ulica za"})


def kopce():
    """Sieť s výškami: cesta z doliny cez hrebeň a zase dolu."""
    s = Siet()
    hreben = ((19.00, 420), (19.05, 660), (19.10, 980), (19.15, 540),
              (19.20, 300))
    u = [s.uzol(5_000_000 + i, lon, 49.00, vyska)
         for i, (lon, vyska) in enumerate(hreben)]
    for od, do in zip(u, u[1:]):
        s.hrana(od, do, {"highway": "secondary", "name": "Cez hrebeň",
                         "ref": "II/520"})
    return s


def krizovatky():
    """Sieť na pokyny: výjazd z diaľnice, nájazd, kruhák, vidlica a koniec cesty."""
    s = Siet()
    dialnica(s)
    kruhak(s)
    vidlica(s)
    ulice(s)
    return s


def dialnica(s):
    """D1 s výjazdom na cestu do mesta a s nájazdom naspäť."""
    m = [s.uzol(6_000_000 + i, 20.00 + i * 0.05, 49.20) for i in range(4)]
    for od, do in zip(m, m[1:]):
        s.hrana(od, do, {"highway": "motorway", "oneway": "yes", "ref": "D1"},
                smer=fmt.S_VPRED)
    x0 = s.uzol(6_000_010, 20.07, 49.18)
    x1 = s.uzol(6_000_011, 20.10, 49.16)
    s.hrana(m[1], x0, {"highway": "motorway_link", "oneway": "yes"},
            smer=fmt.S_VPRED)
    s.hrana(x0, x1, {"highway": "primary", "ref": "I/18",
                     "name": "Cesta do mesta"})
    n0 = s.uzol(6_000_020, 20.02, 49.225)
    n1 = s.uzol(6_000_021, 20.06, 49.22)
    s.hrana(n0, n1, {"highway": "primary", "name": "Prístupová"})
    s.hrana(n1, m[2], {"highway": "motorway_link", "oneway": "yes"},
            smer=fmt.S_VPRED)


def kruhak(s):
    """Kruhový objazd proti smeru hodinových ručičiek so štyrmi ramenami."""
    ring = [s.uzol(6_000_030 + i, lon, lat) for i, (lon, lat) in enumerate(
        ((20.200, 49.200), (20.205, 49.197), (20.210, 49.200), (20.205, 49.203)))]
    for od, do in zip(ring, ring[1:] + ring[:1]):
        s.hrana(od, do, {"highway": "tertiary", "junction": "roundabout",
                         "oneway": "yes"}, smer=fmt.S_VPRED)
    ramena = ((20.190, 49.200, "Západná"), (20.205, 49.190, "Južná"),
              (20.220, 49.200, "Východná"), (20.205, 49.210, "Severná"))
    for i, (lon, lat, meno) in enumerate(ramena):
        koniec = s.uzol(6_000_034 + i, lon, lat)
        s.hrana(koniec, ring[i], {"highway": "tertiary", "name": meno})


def vidlica(s):
    """Hlavný ťah, ktorý sa rozdvojuje – ani jedna vetva nie je odbočka."""
    f0 = s.uzol(6_000_040, 20.30, 49.20)
    f1 = s.uzol(6_000_041, 20.33, 49.20)
    f2 = s.uzol(6_000_042, 20.36, 49.21)
    f3 = s.uzol(6_000_043, 20.36, 49.19)
    s.hrana(f0, f1, {"highway": "primary", "ref": "I/18", "name": "Hlavná"})
    s.hrana(f1, f2, {"highway": "primary", "ref": "I/18", "name": "Hlavná"})
    s.hrana(f1, f3, {"highway": "primary", "ref": "I/66", "name": "Odbočka"})


def ulice(s):
    """Zmena mena, slepý koniec s jedinou odbočkou a obyčajná križovatka."""
    c0 = s.uzol(6_000_050, 20.25, 49.20)
    c1 = s.uzol(6_000_051, 20.28, 49.20)
    c2 = s.uzol(6_000_052, 20.31, 49.21)
    s.hrana(c0, c1, {"highway": "residential", "name": "Prvá"})
    s.hrana(c1, c2, {"highway": "residential", "name": "Druhá"})

    e0 = s.uzol(6_000_060, 20.40, 49.20)
    e1 = s.uzol(6_000_061, 20.43, 49.20)
    e2 = s.uzol(6_000_062, 20.43, 49.23)
    s.hrana(e0, e1, {"highway": "residential", "name": "Slepá"})
    s.hrana(e1, e2, {"highway": "residential", "name": "Priečna"})

    t0 = s.uzol(6_000_070, 20.50, 49.20)
    t1 = s.uzol(6_000_071, 20.53, 49.20)
    t2 = s.uzol(6_000_072, 20.53, 49.17)
    t3 = s.uzol(6_000_073, 20.56, 49.20)
    s.hrana(t0, t1, {"highway": "residential", "name": "Rovná"})
    s.hrana(t1, t2, {"highway": "residential", "name": "Kolmá"})
    s.hrana(t1, t3, {"highway": "residential", "name": "Rovná"})


def vyrez(s, zapad):
    """Kraj rezaný hranicou: hrana ostáva, keď je v ňom aspoň jeden jej koniec."""
    von = Siet()
    von.uzly = dict(s.uzly)
    von.vysky = dict(s.vysky)
    for h in s.hrany:
        if any(_je_zapad(s.uzly[u]) == zapad for u in (h["od"], h["do"])):
            von.hrany.append(h)
    ostrov = {u for h in von.hrany for u in (h["od"], h["do"])}
    von.uzly = {k: v for k, v in s.uzly.items() if k in ostrov}
    von.vysky = {k: v for k, v in s.vysky.items() if k in ostrov}
    von.zakazy = [z for z in s.zakazy
                  if all(u in ostrov for hr in z["hrany"] for u in hr)]
    return von


def _je_zapad(uzol):
    return uzol[1] < e7(POLOVICA)


class Susedia:
    """To, čo `order.poradie` čaká od siete: susedia uzla a jeho poloha."""

    def __init__(self, s):
        self.xy = s.uzly
        self._susedia = {osm: set() for osm in s.uzly}
        for h in s.hrany:
            self._susedia[h["od"]].add(h["do"])
            self._susedia[h["do"]].add(h["od"])

    def __getitem__(self, osm):
        return self._susedia.get(osm, ())


class Poradie:
    """Rank pre každý uzol siete, aby mala dlaždica príznak poradia."""

    def __init__(self, s, poradie_id=PORADIE_ID, posun=0):
        self.id = poradie_id
        # to isté nested dissection ako kraj, nie zoradenie podľa OSM id: inak
        # vzorový archív meria najhorší prípad a CCH v appke vyzerá zbytočné
        eliminacia = order.poradie(sorted(s.uzly), Susedia(s))
        self._rank = {osm: i + posun for i, osm in enumerate(eliminacia)}

    def __bool__(self):
        return True

    def rank(self, osm):
        return self._rank.get(osm, len(self._rank) + osm)


def zapis(cesta, s, slovnik, kluc, poradie):
    from pmtiles.tile import (Compression, TileType,                # noqa: PLC0415
                              zxy_to_tileid)
    from pmtiles.writer import Writer                               # noqa: PLC0415

    telá = tiles.rozdel(s, slovnik, "SK", poradie, rozpocet=ROZPOCET)
    zoom_max = max(z for z, _, _ in telá)
    graf = {
        "rozsah": "region", "kluc": kluc, "name": kluc, "format": "rtil",
        "format_verzia": fmt.VERZIA, "slovnik": f"{slovnik.id:08x}",
        "slovnik_verzia": slovnik.verzia, "poradie": f"{poradie.id:08x}",
        "krajina": "SK", "zoom": tiles.ZOOM, "zoom_max": zoom_max,
        "delenych": sum(1 for z, _, _ in telá if z > tiles.ZOOM),
        "dlazdic": len(telá), "uzlov": len(s.uzly), "hran": len(s.hrany),
        "zakazov": len(s.zakazy), "vyska": bool(s.vysky),
        "multimodal": False,
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
    cela = husta(siet())
    vsetky_cesty = cesty()
    hory = kopce()
    uzly_krizovatiek = krizovatky()
    # poradie je nad celým územím, nie nad výrezom – inak by dva „kraje“ dali
    # tomu istému uzlu iný rank a spojiť sa nedajú
    uzemie = Siet()
    uzemie.uzly = {**cela.uzly, **vsetky_cesty.uzly, **hory.uzly,
                   **uzly_krizovatiek.uzly}
    poradie = Poradie(uzemie)
    zapis(os.path.join(args.out, "routing-fixture.pmtiles"), cela, slovnik,
          "fixture", poradie)
    zapis(os.path.join(args.out, "routing-fixture-west.pmtiles"),
          vyrez(siet(), True), slovnik, "fixture-west", poradie)
    zapis(os.path.join(args.out, "routing-fixture-east.pmtiles"),
          vyrez(siet(), False), slovnik, "fixture-east", poradie)
    zapis(os.path.join(args.out, "routing-fixture-roads.pmtiles"), vsetky_cesty,
          slovnik, "fixture-roads", poradie)
    zapis(os.path.join(args.out, "routing-fixture-hills.pmtiles"), hory,
          slovnik, "fixture-hills", poradie)
    zapis(os.path.join(args.out, "routing-fixture-junctions.pmtiles"),
          uzly_krizovatiek, slovnik, "fixture-junctions", poradie)
    # nie je súčasťou behu, preto vedľa: lint sa nad ním nepúšťa
    zapis(os.path.join(args.out, "iny-rank", "routing-fixture-east.pmtiles"),
          vyrez(siet(), False), slovnik, "fixture-east",
          Poradie(uzemie, PORADIE_INE, posun=1))
    print(json.dumps({"slovnik": f"{slovnik.id:08x}",
                      "poradie": f"{PORADIE_ID:08x}",
                      "iny": f"{PORADIE_INE:08x}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
