#!/usr/bin/env python3
"""Z PBF graf križovatiek – uzly, hrany so značkami a odbočovacie zákazy."""
import math
import os
import sys
from collections import Counter

import osmium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import tags as slovnik_modul                                      # noqa: E402

E7 = 1e7
POLOMER_M = 6371000.0

# `oneway` bez týchto hodnôt je obojsmerná cesta
VPRED = {"yes", "true", "1"}
VZAD = {"-1", "reverse"}


class Siet:
    """Graf križovatiek jedného územia – to, čo ide do dlaždíc aj do poradia."""

    def __init__(self):
        self.uzly = {}          # osm id -> (lat_e7, lon_e7)
        self.hrany = []
        self.zakazy = []
        self.zahodene = Counter()
        self.preskocene = Counter()
        self.ciest = 0

    def susedia(self):
        """Uzol -> susedia, bez smeru; poradie sa počíta nad tvarom siete."""
        out = {u: set() for u in self.uzly}
        for h in self.hrany:
            if h["od"] != h["do"]:
                out[h["od"]].add(h["do"])
                out[h["do"]].add(h["od"])
        return out


class _Zakazy(osmium.SimpleHandler):
    """1. priechod: relácie `type=restriction` – ešte bez hrán."""

    def __init__(self):
        super().__init__()
        self.zakazy = []
        self.uzly = set()
        self.preskocene = Counter()

    def relation(self, r):
        t = {tag.k: tag.v for tag in r.tags}
        if t.get("type") != "restriction":
            return
        druh = (t.get("restriction") or "").strip()
        if druh not in fmt.DRUHY_ZAKAZOV:
            # `restriction:hgv` a `restriction:conditional` sú iná otázka než
            # trvalý zákaz pre všetkých
            iny = next((k for k in t if k.startswith("restriction:")), "")
            self.preskocene[iny or druh or "bez `restriction`"] += 1
            return
        od = [m.ref for m in r.members if m.type == "w" and m.role == "from"]
        na = [m.ref for m in r.members if m.type == "w" and m.role == "to"]
        cez_u = [m.ref for m in r.members if m.type == "n" and m.role == "via"]
        cez_w = [m.ref for m in r.members if m.type == "w" and m.role == "via"]
        if len(od) != 1 or len(na) != 1 or (not cez_u and not cez_w):
            self.preskocene["neúplná relácia"] += 1
            return
        vynimky = 0
        for v in (t.get("except") or "").split(";"):
            v = v.strip()
            if v in fmt.VYNIMKY:
                vynimky |= 1 << fmt.VYNIMKY.index(v)
        self.zakazy.append({"rel": r.id, "druh": fmt.DRUHY_ZAKAZOV.index(druh),
                            "vynimky": vynimky, "od": od[0], "na": na[0],
                            "cez_uzol": cez_u[0] if cez_u else None,
                            "cez_cesty": cez_w})
        self.uzly.update(cez_u)


class _Krizovatky(osmium.SimpleHandler):
    """2. priechod: ktorý uzol je križovatka – bez súradníc, teda bez indexu."""

    def __init__(self, slovnik):
        super().__init__()
        self.slovnik = slovnik
        self.videne = set()
        self.viackrat = set()
        self.konce = set()
        self.ciest = 0

    def way(self, w):
        t = {tag.k: tag.v for tag in w.tags}
        if not self.slovnik.trieda(t) or len(w.nodes) < 2:
            return
        self.ciest += 1
        refs = [n.ref for n in w.nodes]
        for ref in refs:
            if ref in self.videne:
                self.viackrat.add(ref)
            else:
                self.videne.add(ref)
        self.konce.add(refs[0])
        self.konce.add(refs[-1])


class _Hrany(osmium.SimpleHandler):
    """3. priechod: cesta sa reže na križovatkách, medzi nimi je geometria."""

    def __init__(self, slovnik, krizovatky, siet):
        super().__init__()
        self.slovnik = slovnik
        self.krizovatky = krizovatky
        self.siet = siet

    def way(self, w):
        t = {tag.k: tag.v for tag in w.tags}
        if not self.slovnik.trieda(t) or len(w.nodes) < 2:
            return
        vybrane, zahodene = self.slovnik.vyber(t)
        for kluc, hodnota in zahodene:
            self.siet.zahodene[f"{kluc}={hodnota}"] += 1
        try:
            body = [(n.ref, round(n.location.lat * E7), round(n.location.lon * E7))
                    for n in w.nodes]
        except osmium.InvalidLocationError:
            self.siet.preskocene["cesta bez súradníc uzlov"] += 1
            return

        smer = _smer(vybrane)
        zaciatok = 0
        for i in range(1, len(body)):
            if body[i][0] not in self.krizovatky and i != len(body) - 1:
                continue
            usek = body[zaciatok:i + 1]
            zaciatok = i
            if len(usek) < 2 or usek[0][0] == usek[-1][0]:
                # slučka bez druhej križovatky nie je hrana, po ktorej sa dá ísť
                continue
            for ref, lat, lon in (usek[0], usek[-1]):
                self.siet.uzly[ref] = (lat, lon)
            self.siet.hrany.append({
                "cesta": w.id,
                "od": usek[0][0], "do": usek[-1][0],
                "geom": [(lat, lon) for _r, lat, lon in usek[1:-1]],
                "dlzka_cm": _dlzka_cm(usek),
                "smer": smer,
                "tagy": vybrane,
            })


def _smer(tagy):
    """Smerovosť z tagov; predpoklady podľa druhu vozidla patria do telefónu."""
    oneway = tagy.get("oneway", "")
    if oneway in VPRED:
        return fmt.S_VPRED
    if oneway in VZAD:
        return fmt.S_VZAD
    if not oneway and tagy.get("junction") in ("roundabout", "circular"):
        return fmt.S_VPRED
    return fmt.S_VPRED | fmt.S_VZAD


def _dlzka_cm(usek):
    m = 0.0
    for (_r1, lat1, lon1), (_r2, lat2, lon2) in zip(usek, usek[1:]):
        m += _haversine(lat1 / E7, lon1 / E7, lat2 / E7, lon2 / E7)
    return int(round(m * 100))


def _haversine(lat1, lon1, lat2, lon2):
    f1, f2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = (math.sin((f2 - f1) / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2)
    return 2 * POLOMER_M * math.asin(min(1.0, math.sqrt(a)))


def _hrany_cesty(siet):
    out = {}
    for h in siet.hrany:
        out.setdefault(h["cesta"], []).append(h)
    return out


def _hrana_pri(hrany, uzol, ku_uzlu):
    """Hrana danej cesty dotýkajúca sa uzla, v smere jazdy."""
    for h in hrany:
        if h["od"] == uzol:
            return (h["do"], h["od"]) if ku_uzlu else (h["od"], h["do"])
        if h["do"] == uzol:
            return (h["od"], h["do"]) if ku_uzlu else (h["do"], h["od"])
    return None


def _dotiahni_zakazy(siet, surove):
    """Relácie na dvojice uzlov – hrana sa pomenuje `(od, do)` v smere jazdy."""
    podla_cesty = _hrany_cesty(siet)
    for z in surove:
        od_hrany = podla_cesty.get(z["od"], [])
        na_hrany = podla_cesty.get(z["na"], [])
        if not od_hrany or not na_hrany:
            siet.preskocene["zákaz na ceste mimo územia"] += 1
            continue
        if z["cez_uzol"] is not None:
            prve = _hrana_pri(od_hrany, z["cez_uzol"], ku_uzlu=True)
            druhe = _hrana_pri(na_hrany, z["cez_uzol"], ku_uzlu=False)
            if not prve or not druhe:
                siet.preskocene["zákaz sa nedotýka uzla `via`"] += 1
                continue
            retaz = [prve, druhe]
        else:
            retaz = _cez_cesty(podla_cesty, z, siet)
            if not retaz:
                continue
        siet.zakazy.append({"druh": z["druh"], "vynimky": z["vynimky"],
                            "hrany": retaz, "cez": retaz[0][1]})


def _cez_cesty(podla_cesty, z, siet):
    """Zákaz cez cestu: reťaz hrán od `from` cez `via` po `to`."""
    stred = []
    for w in z["cez_cesty"]:
        stred.extend(podla_cesty.get(w, []))
    if not stred:
        siet.preskocene["zákaz cez cestu mimo územia"] += 1
        return None
    for zaciatok in {h["od"] for h in stred} | {h["do"] for h in stred}:
        prve = _hrana_pri(podla_cesty[z["od"]], zaciatok, ku_uzlu=True)
        if not prve:
            continue
        retaz, uzol, zvysok = [prve], zaciatok, list(stred)
        while zvysok:
            dalsia = next((h for h in zvysok if uzol in (h["od"], h["do"])), None)
            if not dalsia:
                break
            zvysok.remove(dalsia)
            uzol = dalsia["do"] if dalsia["od"] == uzol else dalsia["od"]
            retaz.append((retaz[-1][1], uzol))
        posledna = _hrana_pri(podla_cesty[z["na"]], uzol, ku_uzlu=False)
        if posledna and not zvysok:
            return retaz + [posledna]
    siet.preskocene["zákaz cez cestu sa nedá poskladať"] += 1
    return None


def nacitaj(pbf, slovnik=None):
    """PBF → `Siet`; tri priechody, lebo relácie sú v súbore až za cestami."""
    slovnik = slovnik or slovnik_modul.slovnik()
    siet = Siet()

    zak = _Zakazy()
    zak.apply_file(pbf)
    siet.preskocene.update(zak.preskocene)

    kriz = _Krizovatky(slovnik)
    kriz.apply_file(pbf)
    siet.ciest = kriz.ciest
    krizovatky = kriz.viackrat | kriz.konce | zak.uzly
    del kriz

    hrany = _Hrany(slovnik, krizovatky, siet)
    hrany.apply_file(pbf, locations=True, idx="flex_mem")
    _dotiahni_zakazy(siet, zak.zakazy)
    return siet
