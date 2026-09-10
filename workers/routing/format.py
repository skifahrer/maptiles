#!/usr/bin/env python3
"""Telo smerovacej dlaždice `RTIL` – zápis aj čítanie na jednom mieste."""
import struct

MAGIC = b"RTIL"
VERZIA = 1

# `priznaky` v hlavičke: pole, ktoré v archíve nie je, sa nekóduje vôbec
P_VYSKA = 1
P_PORADIE = 2

# hrana je prejazdná v smere uzlov way, proti nemu, alebo oboma
S_VPRED = 1
S_VZAD = 2

# index = to, čo je v dlaždici; poradie sa nesmie preskladať bez verzie formátu
DRUHY_ZAKAZOV = [
    "no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn",
    "no_entry", "no_exit",
    "only_left_turn", "only_right_turn", "only_straight_on", "only_u_turn",
]

# `except=bicycle;psv` – bit na vozidlo, ktorého sa zákaz netýka
VYNIMKY = ["foot", "bicycle", "psv", "hgv", "motorcar", "moped",
           "motorcycle", "emergency"]

# strop na jednu dlaždicu; nad ním sa archív sťahuje po kusoch, ktoré sa
# v telefóne nedajú rozumne držať v pamäti
ROZPOCET_KB = 1024


def zigzag(n):
    return (n << 1) ^ (n >> 63) if n < 0 else n << 1


class Zapis:
    def __init__(self):
        self.b = bytearray()

    def u(self, n):
        if n < 0:
            raise ValueError(f"varint nie je pre záporné číslo: {n}")
        while True:
            b = n & 0x7F
            n >>= 7
            self.b.append(b | 0x80 if n else b)
            if not n:
                return

    def z(self, n):
        self.u((n << 1) ^ (n >> 63) if n < 0 else n << 1)

    def bajt(self, n):
        self.b.append(n & 0xFF)

    def text(self, s):
        raw = s.encode("utf-8")
        self.u(len(raw))
        self.b += raw


class Citanie:
    def __init__(self, b):
        self.b, self.i = b, 0

    def u(self):
        n, posun = 0, 0
        while True:
            x = self.b[self.i]
            self.i += 1
            n |= (x & 0x7F) << posun
            if not x & 0x80:
                return n
            posun += 7

    def z(self):
        n = self.u()
        return -(n + 1) // 2 if n & 1 else n // 2

    def bajt(self):
        self.i += 1
        return self.b[self.i - 1]

    def text(self):
        n = self.u()
        self.i += n
        return self.b[self.i - n:self.i].decode("utf-8")


def zapis(dlazdica):
    """Dlaždica ako slovník polí → bajty tela (ešte nezabalené gzipom)."""
    w = Zapis()
    w.b += MAGIC
    w.bajt(VERZIA)
    priznaky = ((P_VYSKA if dlazdica["vyska"] else 0)
                | (P_PORADIE if dlazdica["poradie"] else 0))
    w.bajt(priznaky)
    w.b += struct.pack(">II", dlazdica["slovnik_id"], dlazdica["poradie_id"])
    for v in dlazdica["zxy"]:
        w.u(v)
    for v in dlazdica["bbox"]:
        w.z(v)

    uzly = dlazdica["uzly"]
    w.u(len(uzly))
    _stlpec_z(w, [u[0] for u in uzly], delta=True)
    _stlpec_z(w, [u[1] for u in uzly], delta=True)
    _stlpec_z(w, [u[2] for u in uzly], delta=True)
    if dlazdica["vyska"]:
        _stlpec_z(w, [u[3] for u in uzly], delta=True)
    if dlazdica["poradie"]:
        for u in uzly:
            w.u(u[4])

    hrany = dlazdica["hrany"]
    w.u(len(hrany))
    for h in hrany:
        w.u(h["od"])
    for h in hrany:
        w.u(h["do"])
    for h in hrany:
        w.u(h["tagset"])
    for h in hrany:
        w.u(h["dlzka_cm"])
    for h in hrany:
        w.bajt(h["smer"])
    for h in hrany:
        w.u(len(h["geom"]))
    for h in hrany:
        lat, lon = uzly[h["od"]][1], uzly[h["od"]][2]
        for glat, glon in h["geom"]:
            w.z(glat - lat)
            w.z(glon - lon)
            lat, lon = glat, glon

    w.u(len(dlazdica["tagsety"]))
    for ts in dlazdica["tagsety"]:
        w.u(len(ts))
        for kluc_idx, hodnota in ts:
            w.u(kluc_idx)
            w.u(hodnota)

    w.u(len(dlazdica["retazce"]))
    for s in dlazdica["retazce"]:
        w.text(s)

    w.u(len(dlazdica["zakazy"]))
    for z in dlazdica["zakazy"]:
        w.u(z["druh"])
        w.u(z["vynimky"])
        w.u(len(z["hrany"]))
        for od, do in z["hrany"]:
            w.u(od)
            w.u(do)

    w.u(len(dlazdica["okraj"]))
    for i in dlazdica["okraj"]:
        w.u(i)
    return bytes(w.b)


def citaj(raw):
    """Bajty tela → ten istý slovník, aký zobral `zapis`."""
    if raw[:4] != MAGIC:
        raise ValueError("telo dlaždice nezačína `RTIL` – toto nie je "
                         "smerovacia dlaždica")
    r = Citanie(raw)
    r.i = 4
    verzia = r.bajt()
    if verzia != VERZIA:
        raise ValueError(f"dlaždica je vo formáte v{verzia}, tento kód číta "
                         f"v{VERZIA}")
    priznaky = r.bajt()
    slovnik_id, poradie_id = struct.unpack(">II", raw[r.i:r.i + 8])
    r.i += 8
    zxy = [r.u() for _ in range(3)]
    bbox = [r.z() for _ in range(4)]

    n = r.u()
    ids = _citaj_stlpec(r, n, delta=True)
    lats = _citaj_stlpec(r, n, delta=True)
    lons = _citaj_stlpec(r, n, delta=True)
    vysky = (_citaj_stlpec(r, n, delta=True) if priznaky & P_VYSKA
             else [0] * n)
    rank = [r.u() for _ in range(n)] if priznaky & P_PORADIE else [0] * n
    uzly = list(zip(ids, lats, lons, vysky, rank))

    m = r.u()
    od = [r.u() for _ in range(m)]
    do = [r.u() for _ in range(m)]
    tagset = [r.u() for _ in range(m)]
    dlzka = [r.u() for _ in range(m)]
    smer = [r.bajt() for _ in range(m)]
    pocty = [r.u() for _ in range(m)]
    hrany = []
    for i in range(m):
        lat, lon = uzly[od[i]][1], uzly[od[i]][2]
        geom = []
        for _ in range(pocty[i]):
            lat += r.z()
            lon += r.z()
            geom.append((lat, lon))
        hrany.append({"od": od[i], "do": do[i], "tagset": tagset[i],
                      "dlzka_cm": dlzka[i], "smer": smer[i], "geom": geom})

    tagsety = []
    for _ in range(r.u()):
        tagsety.append([(r.u(), r.u()) for _ in range(r.u())])
    retazce = [r.text() for _ in range(r.u())]

    zakazy = []
    for _ in range(r.u()):
        druh, vynimky = r.u(), r.u()
        zakazy.append({"druh": druh, "vynimky": vynimky,
                       "hrany": [(r.u(), r.u()) for _ in range(r.u())]})
    okraj = [r.u() for _ in range(r.u())]

    return {"verzia": verzia, "vyska": bool(priznaky & P_VYSKA),
            "poradie": bool(priznaky & P_PORADIE),
            "slovnik_id": slovnik_id, "poradie_id": poradie_id,
            "zxy": zxy, "bbox": bbox, "uzly": uzly, "hrany": hrany,
            "tagsety": tagsety, "retazce": retazce, "zakazy": zakazy,
            "okraj": okraj}


def _stlpec_z(w, hodnoty, delta):
    prev = 0
    for v in hodnoty:
        w.z(v - prev if delta else v)
        if delta:
            prev = v


def _citaj_stlpec(r, n, delta):
    out, prev = [], 0
    for _ in range(n):
        v = r.z() + (prev if delta else 0)
        out.append(v)
        prev = v
    return out

