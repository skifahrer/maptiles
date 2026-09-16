#!/usr/bin/env python3
"""Výška na uzol z výškového modelu – bilineárne z mozaiky, po stupňových poliach."""
import json
import math
import os
import re
import subprocess

import numpy as np

E7 = 1e7
# `gdalwarp` sentinel; nesmie byť 0 – nula je platná výška
NODATA = -9999.0
# o toľko pixelov sa pole zväčší, nech má bilineárny odber suseda aj na okraji
OKRAJ_PX = 2


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


def _po_stupnoch(lat, lon):
    """Uzly po stupňových poliach – jedno pole v pamäti naraz."""
    kluc = np.stack([np.floor(lon), np.floor(lat)], axis=1).astype(np.int64)
    polia, kde = np.unique(kluc, axis=0, return_inverse=True)
    for i, (zapad, juh) in enumerate(polia):
        yield int(zapad), int(juh), np.flatnonzero(kde.ravel() == i)


def odober(dem, lat, lon, tmp="/tmp/routing-vysky"):
    """Výška (m) pre každý bod, NaN kde model nič nemá."""
    dx, dy = rozlisenie(dem)
    von = np.full(len(lat), np.nan)
    os.makedirs(tmp, exist_ok=True)
    cesta = os.path.join(tmp, "pole.raw")
    for zapad, juh, idx in _po_stupnoch(lat, lon):
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
