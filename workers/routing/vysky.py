#!/usr/bin/env python3
"""Výška uzla siete z DEM – jedna hodnota na križovatku, nie mriežka.

Stĺpec výšok aj príznak `vyska` sú vo formáte od začiatku a `tiles.py` ich
zapíše, keď ich sieť má; sieť z PBF ich nemá odkiaľ vziať, lebo PBF výšky
nenesie. Toto je ten zdroj.
"""
import math
import os
import subprocess
import tempfile

import numpy as np

E7 = 1e7
# vlastný sentinel warpu; nesmie byť 0 – nula je platná výška
NODATA = -9999.0
# krok mriežky v stupňoch (1″). Nie natívny pixel modelu: výška sa číta ako
# stúpanie po hrane, takže jemnejšie než hrana je šum, a archív má povedať to
# isté nad krajom so Sonnym aj nad krajom s DMR
KROK = 1.0 / 3600.0
# strop mriežky v bunkách; nad ním sa krok zhrubne, nech runner nepadne
STROP_BUNIEK = 120_000_000
# dosah špirály v bunkách pre uzol, ktorému model nedal ani jednu zo štyroch
DOSAH = 16


def _bbox(uzly):
    """Obálka uzlov v stupňoch (západ, juh, východ, sever)."""
    lat = [u[0] for u in uzly.values()]
    lon = [u[1] for u in uzly.values()]
    return (min(lon) / E7, min(lat) / E7, max(lon) / E7, max(lat) / E7)


def _plan(bbox, krok=KROK):
    """Mriežka nad obálkou s rezervou bunky, zhrubnutá po strop."""
    zapad, juh, vychod, sever = bbox
    while True:
        zapad_r, juh_r = zapad - krok, juh - krok
        vychod_r, sever_r = vychod + krok, sever + krok
        w = max(2, math.ceil((vychod_r - zapad_r) / krok))
        h = max(2, math.ceil((sever_r - juh_r) / krok))
        if w * h <= STROP_BUNIEK:
            return zapad_r, sever_r, w, h, krok
        krok *= 2


def mriezka(dem, bbox, krok=KROK):
    """Prevzorkuje DEM do mriežky lat/lon nad obálkou siete."""
    zapad, sever, w, h, krok = _plan(bbox, krok)
    juh, vychod = sever - h * krok, zapad + w * krok
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "uzly.raw")
        subprocess.run(
            ["gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:4326",
             "-te", *map(repr, (zapad, juh, vychod, sever)),
             "-ts", str(w), str(h),
             "-r", "bilinear", "-ot", "Float32", "-dstnodata", str(NODATA),
             "-of", "ENVI", dem, raw],
            check=True,
        )
        grid = np.fromfile(raw, dtype="<f4").reshape(h, w)
    return grid, zapad, sever, krok


def _spirala(grid, r, c, dosah=DOSAH):
    """Najbližšia platná bunka okolo, alebo nič – okraj modelu, nie diera."""
    h, w = grid.shape
    for k in range(1, dosah + 1):
        r0, r1 = max(r - k, 0), min(r + k + 1, h)
        c0, c1 = max(c - k, 0), min(c + k + 1, w)
        vyrez = grid[r0:r1, c0:c1]
        plati = vyrez > NODATA / 2
        if plati.any():
            return float(vyrez[plati].mean())
    return None


def vzorkuj(uzly, grid, zapad, sever, krok):
    """Bilineárna výška na uzol; váhu má len bunka, ktorú model pozná."""
    h, w = grid.shape
    ref = list(uzly)
    lat = np.array([uzly[u][0] for u in ref], dtype=np.float64) / E7
    lon = np.array([uzly[u][1] for u in ref], dtype=np.float64) / E7
    # stred bunky, nie jej roh
    x = (lon - zapad) / krok - 0.5
    y = (sever - lat) / krok - 0.5
    c0 = np.floor(x).astype(np.int64)
    r0 = np.floor(y).astype(np.int64)
    fx, fy = x - c0, y - r0
    sucet = np.zeros(len(ref))
    vaha = np.zeros(len(ref))
    for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
        rr = np.clip(r0 + dr, 0, h - 1)
        cc = np.clip(c0 + dc, 0, w - 1)
        v = grid[rr, cc].astype(np.float64)
        p = (fx if dc else 1.0 - fx) * (fy if dr else 1.0 - fy)
        p = np.where(v > NODATA / 2, p, 0.0)
        sucet += p * v
        vaha += p
    vysky = {}
    for i, osm in enumerate(ref):
        if vaha[i] > 0:
            vysky[osm] = int(round(sucet[i] / vaha[i]))
            continue
        # uzol pod okrajom modelu; bez špirály by dostal nulu, čiže hladinu mora
        blizka = _spirala(grid, int(np.clip(r0[i], 0, h - 1)),
                          int(np.clip(c0[i], 0, w - 1)))
        if blizka is not None:
            vysky[osm] = int(round(blizka))
    return vysky


def doplni(siet, dem):
    """Dosadí výšky uzlov do siete a vráti, koľkým ich model nedal."""
    if not siet.uzly:
        return 0
    grid, zapad, sever, krok = mriezka(dem, _bbox(siet.uzly))
    siet.vysky = vzorkuj(siet.uzly, grid, zapad, sever, krok)
    return len(siet.uzly) - len(siet.vysky)
