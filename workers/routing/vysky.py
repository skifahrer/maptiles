#!/usr/bin/env python3
"""Výška na uzol z výškového modelu – bilineárne, po poliach mriežky."""
import importlib.util
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)

E7 = 1e7
# `gdalwarp` sentinel; nesmie byť 0 – nula je platná výška
NODATA = -9999.0
# o toľko pixelov sa pole zväčší, nech má bilineárny odber suseda aj na okraji
OKRAJ_PX = 2
# Aké veľké pole sa berie naraz. Stupeň je v 20 m modeli 5500 px (120 MB) a to
# je práve tak akurát; v 5 m modeli by to bolo 1,9 GB, tak sa číta po kusoch.
KROK_MOZAIKA = 1.0
KROK_DRIVE = 0.1


def _modul(meno, cesta):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if meno in sys.modules:
        return sys.modules[meno]
    spec = importlib.util.spec_from_file_location(meno, os.path.join(_WORKERS, cesta))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[meno] = mod
    spec.loader.exec_module(mod)
    return mod


def z_drive(port=0):
    """DMR 5.0 na Drive: `(dem, env, srs, krok_stupnov, stats)`.

    Nič sa nezrkadlí ani nesťahuje celé – GDAL číta okno cez HTTP Range, ako to
    robí sklon pre skaly. Výšky zdroja sú elipsoidické, geoid odčíta `gdalwarp`.
    """
    dd = _modul("dmr5_drive", os.path.join("drive", "dmr5.py"))
    cut = _modul("dmr5_cut", os.path.join("drive", "dmr5-cut.py"))
    base, _sizes, stats, _creds = dd.serve_drive(port)
    env = dd.drive.gdal_env()
    # mriežku geoidu si PROJ stiahne z CDN, keď ju nemá lokálne
    env["PROJ_NETWORK"] = "ON"
    srs = ["-s_srs", f"EPSG:{cut.SRC_EPSG}+{cut.SRC_VERT}",
           "-t_srs", f"EPSG:4326+{cut.DST_VERT}",
           # bez poistky by GDAL pri chýbajúcej mriežke ticho nechal
           # elipsoidické výšky, čo je o ~42 m vedľa
           "-to", "ERROR_ON_MISSING_VERT_SHIFT=YES"]
    return f"/vsicurl/{base}/{dd.TIF_NAME}", env, srs, stats


def rozlisenie(dem, env=None):
    info = json.loads(subprocess.run(["gdalinfo", "-json", dem], check=True,
                                     capture_output=True, text=True, env=env).stdout)
    gt = info["geoTransform"]
    return abs(gt[1]), abs(gt[5])


def rozlisenie_v_stupnoch(dem, lat, env=None):
    """To isté pre model v metroch: jeho bunka prepočítaná na stupne."""
    raster = _modul("dmr5_raster", os.path.join("drive", "dmr5-raster.py"))
    m, _ = rozlisenie(dem, env)
    dx, dy = raster.degrees_per_metre(lat)
    return m * dx, m * dy


def _rozmer(hdr):
    text = open(hdr, encoding="utf-8").read()
    w = int(re.search(r"^samples\s*=\s*(\d+)", text, re.M).group(1))
    h = int(re.search(r"^lines\s*=\s*(\d+)", text, re.M).group(1))
    return w, h


def _pole(dem, cesta, w, s, e, n, dx, dy, env=None, srs=()):
    """Výrez mozaiky v pôvodnom rozlíšení ako surové Float32."""
    subprocess.run(
        ["gdalwarp", "-q", "-overwrite", *srs, "-te", *map(repr, (w, s, e, n)),
         "-tr", repr(dx), repr(dy), "-r", "near", "-ot", "Float32",
         "-dstnodata", str(NODATA), "-of", "ENVI", dem, cesta],
        check=True, env=env)
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


def _po_poliach(lat, lon, krok=KROK_MOZAIKA):
    """Uzly po poliach mriežky – jedno pole v pamäti naraz.

    Mriežka je ukotvená v nule, nie v bboxe: tá istá zem padne vždy do toho
    istého poľa, nech sa kraj rozšíri, ako chce.
    """
    kluc = np.stack([np.floor(lon / krok), np.floor(lat / krok)],
                    axis=1).astype(np.int64)
    polia, kde = np.unique(kluc, axis=0, return_inverse=True)
    for i, (zapad, juh) in enumerate(polia):
        # `float()`, nie numpy skalár: `repr` numpy 2 píše `np.float64(17.1)`
        # a to je argument, ktorý gdalwarp odmietne
        yield float(zapad * krok), float(juh * krok), np.flatnonzero(kde.ravel() == i)


def odober(dem, lat, lon, tmp="/tmp/routing-vysky", env=None, srs=(),
           krok=KROK_MOZAIKA, dxdy=None):
    """Výška (m) pre každý bod, NaN kde model nič nemá."""
    dx, dy = dxdy or rozlisenie(dem, env)
    von = np.full(len(lat), np.nan)
    os.makedirs(tmp, exist_ok=True)
    cesta = os.path.join(tmp, "pole.raw")
    for zapad, juh, idx in _po_poliach(lat, lon, krok):
        la, lo = lat[idx], lon[idx]
        # výrez sa zarovná na pixely zdroja, aby sa stred pixela neposunul
        w = zapad + math.floor((lo.min() - zapad) / dx - OKRAJ_PX) * dx
        e = zapad + math.ceil((lo.max() - zapad) / dx + OKRAJ_PX) * dx
        s = juh + math.floor((la.min() - juh) / dy - OKRAJ_PX) * dy
        n = juh + math.ceil((la.max() - juh) / dy + OKRAJ_PX) * dy
        grid = _pole(dem, cesta, w, s, e, n, dx, dy, env, srs)
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
    """`siet.vysky` z modelu; vráti (z modelu, od susedov, bez výšky).

    `dem` je cesta k mozaike, alebo `drive` pre DMR 5.0 čítané z Drive.
    """
    ids = list(siet.uzly)
    lat = np.array([siet.uzly[u][0] for u in ids], dtype=np.float64) / E7
    lon = np.array([siet.uzly[u][1] for u in ids], dtype=np.float64) / E7
    if dem == "drive":
        dem, env, srs, _stats = z_drive()
        stred = float(np.median(lat))
        v = odober(dem, lat, lon, env=env, srs=srs, krok=KROK_DRIVE,
                   dxdy=rozlisenie_v_stupnoch(dem, stred, env))
    else:
        v = odober(dem, lat, lon)
    ma = ~np.isnan(v)
    vysky = {u: int(round(float(x))) for u, x, ok in zip(ids, v, ma) if ok}
    z_modelu = len(vysky)
    if not vysky:
        return 0, 0, len(ids)
    bez = dopln_susedmi(vysky, siet.hrany, ids)
    siet.vysky = vysky
    return z_modelu, len(vysky) - z_modelu, bez
