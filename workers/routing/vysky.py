#!/usr/bin/env python3
"""Výšky z modelu – profil pozdĺž hrany po pevnom kroku, bilineárne z mozaiky."""
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402

E7 = 1e7
# `gdalwarp` sentinel; nesmie byť 0 – nula je platná výška
NODATA = -9999.0
# o toľko pixelov sa pole zväčší, nech má bilineárny odber suseda aj na okraji
OKRAJ_PX = 2
# strana okna odberu v pixeloch; pri 5 m modeli má celý stupeň 22 000 px
# a jeho pole by malo 1,3 GB
OKNO_PX = 4096
STUPEN_M = 111320.0
# vzdialenosť medzi vzorkami profilu
KROK_M = 5.0
# most a tunel nestoja na teréne, tak ich profil vedie priamka medzi koncami
NAD_TERENOM = ("bridge", "tunnel")


def rozlisenie(dem):
    info = json.loads(subprocess.run(["gdalinfo", "-json", dem], check=True,
                                     capture_output=True, text=True).stdout)
    gt = info["geoTransform"]
    return abs(gt[1]), abs(gt[5])


def _rozmer(hdr):
    text = open(hdr, encoding="utf-8").read()
    w = int(re.search(r"^samples\s*=\s*(\d+)", text, re.M).group(1))
    h = int(re.search(r"^lines\s*=\s*(\d+)", text, re.M).group(1))
    return w, h


def _pole(dem, cesta, w, s, e, n, dx, dy):
    """Výrez mozaiky v pôvodnom rozlíšení ako surové Float32."""
    subprocess.run(
        ["gdalwarp", "-q", "-overwrite", "-te", *map(repr, (w, s, e, n)),
         "-tr", repr(dx), repr(dy), "-r", "near", "-ot", "Float32",
         "-dstnodata", str(NODATA), "-of", "ENVI", dem, cesta],
        check=True)
    sirka, vyska = _rozmer(os.path.splitext(cesta)[0] + ".hdr")
    return np.fromfile(cesta, dtype="<f4").reshape(vyska, sirka)


def bilinearne(grid, stlpec, riadok):
    """Výška v bode mriežky; chýbajúci sused váhu nedostane, bez suseda NaN."""
    h, w = grid.shape
    c = np.clip(stlpec, 0, w - 1)
    r = np.clip(riadok, 0, h - 1)
    c0 = np.floor(c).astype(np.int64)
    r0 = np.floor(r).astype(np.int64)
    c1 = np.minimum(c0 + 1, w - 1)
    r1 = np.minimum(r0 + 1, h - 1)
    fc, fr = c - c0, r - r0
    sucet = np.zeros(len(c), dtype=np.float64)
    vahy = np.zeros(len(c), dtype=np.float64)
    for rr, cc, vaha in ((r0, c0, (1 - fr) * (1 - fc)), (r0, c1, (1 - fr) * fc),
                         (r1, c0, fr * (1 - fc)), (r1, c1, fr * fc)):
        v = grid[rr, cc].astype(np.float64)
        plati = v > NODATA + 1.0
        sucet += np.where(plati, v * vaha, 0.0)
        vahy += np.where(plati, vaha, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(vahy > 0, sucet / vahy, np.nan)


def _po_oknach(lat, lon, okno):
    """Body po štvorcoch strany `okno` – jedno pole v pamäti naraz."""
    kluc = np.stack([np.floor(lon / okno), np.floor(lat / okno)],
                    axis=1).astype(np.int64)
    polia, kde = np.unique(kluc, axis=0, return_inverse=True)
    for i, (zapad, juh) in enumerate(polia):
        yield zapad * okno, juh * okno, np.flatnonzero(kde.ravel() == i)


def odober(dem, lat, lon, tmp="/tmp/routing-vysky"):
    """Výška (m) pre každý bod, NaN kde model nič nemá."""
    dx, dy = rozlisenie(dem)
    okno = min(1.0, max(dx, dy) * OKNO_PX)
    von = np.full(len(lat), np.nan)
    os.makedirs(tmp, exist_ok=True)
    cesta = os.path.join(tmp, "pole.raw")
    for zapad, juh, idx in _po_oknach(lat, lon, okno):
        la, lo = lat[idx], lon[idx]
        # výrez sa zarovná na pixely zdroja, aby sa stred pixela neposunul
        w = zapad + math.floor((lo.min() - zapad) / dx - OKRAJ_PX) * dx
        e = zapad + math.ceil((lo.max() - zapad) / dx + OKRAJ_PX) * dx
        s = juh + math.floor((la.min() - juh) / dy - OKRAJ_PX) * dy
        n = juh + math.ceil((la.max() - juh) / dy + OKRAJ_PX) * dy
        grid = _pole(dem, cesta, w, s, e, n, dx, dy)
        von[idx] = bilinearne(grid, (lo - w) / dx - 0.5, (n - la) / dy - 0.5)
        del grid
    return von


def dopln_susedmi(vysky, hrany, uzly):
    """Uzol bez výšky ju vezme od suseda v grafe – kým je od koho."""
    chybaju = set(uzly) - set(vysky)
    while chybaju:
        nove = {}
        for h in hrany:
            a, b = h["od"], h["do"]
            if a in chybaju and b in vysky:
                nove[a] = vysky[b]
            elif b in chybaju and a in vysky:
                nove[b] = vysky[a]
        if not nove:
            break
        vysky.update(nove)
        chybaju -= set(nove)
    return len(chybaju)


def dopln(siet, dem):
    """`siet.vysky` z modelu; vráti (z modelu, od susedov, bez výšky)."""
    ids = list(siet.uzly)
    lat = np.array([siet.uzly[u][0] for u in ids], dtype=np.float64) / E7
    lon = np.array([siet.uzly[u][1] for u in ids], dtype=np.float64) / E7
    v = odober(dem, lat, lon)
    ma = ~np.isnan(v)
    vysky = {u: int(round(float(x))) for u, x, ok in zip(ids, v, ma) if ok}
    z_modelu = len(vysky)
    if not vysky:
        return 0, 0, len(ids)
    bez = dopln_susedmi(vysky, siet.hrany, ids)
    siet.vysky = vysky
    return z_modelu, len(vysky) - z_modelu, bez


def _vzorky(body, krok_m, dlzka_m):
    """Body pozdĺž lomenej čiary po `krok_m`; posledný je vždy koniec hrany."""
    lat = np.array([b[0] for b in body], dtype=np.float64) / E7
    lon = np.array([b[1] for b in body], dtype=np.float64) / E7
    # rovinná aproximácia stačí na umiestnenie vzoriek, nie na dĺžku
    dy = np.diff(lat) * STUPEN_M
    dx = np.diff(lon) * STUPEN_M * math.cos(math.radians(float(lat.mean())))
    kde = np.concatenate([[0.0], np.cumsum(np.hypot(dx, dy))])
    if kde[-1] <= 0 or dlzka_m <= 0:
        return lat[:1], lon[:1]
    # telefón počíta vzorky z `dlzka_cm`, tak sa aj kladú po jej dĺžke
    kde *= dlzka_m / kde[-1]
    n = fmt.pocet_vzoriek(dlzka_m, krok_m)
    poz = np.arange(n - 1) * krok_m
    poz = np.append(poz, dlzka_m)
    return np.interp(poz, kde, lat), np.interp(poz, kde, lon)


def _bez_dier(v):
    """Diery v profile sa preklenú od platných susedov; celý prázdny ostáva."""
    plati = ~np.isnan(v)
    if not plati.any():
        return None
    if plati.all():
        return v
    kde = np.flatnonzero(plati)
    return np.interp(np.arange(len(v)), kde, v[kde])


def _vyhladene(v):
    """Dvakrát [1 2 1] – pri 5 m kroku je šum modelu väčší než sklon cesty."""
    if len(v) < 3:
        return v
    for _ in range(2):
        v = np.concatenate([v[:1], (v[:-2] + 2 * v[1:-1] + v[2:]) / 4, v[-1:]])
    return v


def _priamka(v):
    return np.linspace(v[0], v[-1], len(v))


def profily(siet, dem, krok_m=KROK_M):
    """`hrana["profil"]` – výšky v dm po `krok_m`; vráti (s profilom, bez)."""
    lat, lon, kusy = [], [], []
    for h in siet.hrany:
        la, lo = _vzorky([siet.uzly[h["od"]], *h["geom"], siet.uzly[h["do"]]],
                         krok_m, h["dlzka_cm"] / 100)
        kusy.append(len(la))
        lat.append(la)
        lon.append(lo)
    if not kusy:
        return 0, 0
    v = odober(dem, np.concatenate(lat), np.concatenate(lon))
    del lat, lon

    s_profilom = 0
    for h, kus in zip(siet.hrany, np.split(v, np.cumsum(kusy)[:-1])):
        cely = _bez_dier(kus)
        if cely is None or len(cely) < 2:
            h["profil"] = []
            continue
        if any(h["tagy"].get(k, "no") not in ("no", "") for k in NAD_TERENOM):
            cely = _priamka(cely)
        else:
            cely = _vyhladene(cely)
        h["profil"] = [int(round(x * 10)) for x in cely]
        s_profilom += 1
    return s_profilom, len(siet.hrany) - s_profilom


def _na_uzly(h, od_dm, do_dm):
    """Konce profilu na výšku uzlov; rozdiel sa rozloží pozdĺž hrany, nie skokom."""
    p = h["profil"]
    d0, d1 = od_dm - p[0], do_dm - p[-1]
    if d0 or d1:
        oprava = np.linspace(d0, d1, len(p))
        h["profil"] = [int(round(v + o)) for v, o in zip(p, oprava)]


def dopln_profilmi(siet, dem, krok_m=KROK_M):
    """Profily hrán a z ich koncov výšky uzlov – jeden odber na oboje."""
    s_profilom, bez_profilu = profily(siet, dem, krok_m)
    konce = {}
    for h in siet.hrany:
        p = h.get("profil")
        if p:
            konce.setdefault(h["od"], []).append(p[0])
            konce.setdefault(h["do"], []).append(p[-1])
    uzol_dm = {u: int(round(sum(v) / len(v))) for u, v in konce.items()}
    for h in siet.hrany:
        if h.get("profil"):
            _na_uzly(h, uzol_dm[h["od"]], uzol_dm[h["do"]])
    vysky = {u: int(round(dm / 10)) for u, dm in uzol_dm.items()}
    z_modelu = len(vysky)
    if not vysky:
        return 0, 0, len(siet.uzly), s_profilom, bez_profilu
    bez = dopln_susedmi(vysky, siet.hrany, list(siet.uzly))
    siet.vysky = vysky
    return (z_modelu, len(vysky) - z_modelu, bez, s_profilom, bez_profilu)
