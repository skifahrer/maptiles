#!/usr/bin/env python3
"""
Ktorý resampling nechá v tieňovaní mriežku – merané, nie odhadnuté.

NIE JE TO ČASŤ PIPELINE. Nevolá to žiadny workflow; je to nástroj, ktorým sa
overuje jediné rozhodnutie: ČÍM sa prevzorkuje výškový model cestou z Drive do
skladu (`workers/drive/dmr5-cut.py`, `workers/dem/tiles.py`). Leží tu preto,
že bez neho sa čísla v tých komentároch nedajú overiť – rovnako ako
`workers/contours-rocks/measure-smoothing.py` pri hladkosti vrstevníc.

PREČO VZNIKOL. Vrstevnice boli zubaté vzorom, ktorý sedel na svetlo-tmavú
mriežku v tieňovaní – čiže obe vrstvy videli TÚ ISTÚ chybu, a teda ju nemala
ani jedna z nich, mal ju model pod nimi. Mriežku v tieňovaní pritom už raz
riešil `terrain/tiles.py` (zvislý krok, `AVERAGE_RATIO`) a opravená bola;
lenže tie opravy sa týkali toho, ako sa z modelu robia DLAŽDICE, kým mriežka
bola zapečená už v tom MODELI.

Vznikala pri čítaní DMR 5.0 z Drive. Cieľ je 5 m, pyramída, z ktorej sa číta,
má 4 m – a `gdal_translate -r average` pri pomere 1,25 nepriemeruje, ale
striedavo berie iné okno zdrojových buniek (GDAL priemeruje cez CELÉ pixely
v okne `[floor, ceil)`, takže pri 1,25 každý štvrtý preskočí). Z toho je
pravidelný rytmus plošiniek a hillshade, ktorý je deriváciou výšky, z neho
spraví mriežku. Je to presne to, čo `workers/lib/cell.py` popisuje pri
`AVERAGE_RATIO` – len o dva kroky skôr v pipeline, než sa to dovtedy hľadalo.

ČO SA MERIA. GDAL tu nie je potreba (a nemá ho ani lintovací job); kernely sa
počítajú priamo, tak ako ich GDAL aplikuje:

  mriežka      … stredná |Laplacián| tieňovania ×10⁻³ na HLADKOM teréne.
                 Hladký terén nemá čo aliasovať, takže všetko, čo v tieňovaní
                 ostane zvlnené, je artefakt prevzorkovania. Je to tá istá
                 miera, akou sú namerané tabuľky vo `workers/lib/cell.py`.
  kolísanie     … na REALISTICKOM teréne: smerodajná odchýlka lokálnej
                 drsnosti tieňovania po blokoch, v % jej priemeru. Toto je tá
                 svetlo-tmavá mriežka, ako ju vidí oko – striedanie miest,
                 kde detail ostal, s miestami, kde ho prevzorkovanie zjedlo.

Použitie:
    python3 workers/dem/measure-resampling.py
    python3 workers/dem/measure-resampling.py --seeds=1,2,3,4,5
"""
import argparse
import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import AVERAGE_RATIO, resampling  # noqa: E402

# pyramídy DMR 5.0 sú 2, 4, 8 … m, takže pri cieli 5 m sa číta zo 4 m –
# tento pomer je celý dôvod, prečo tento súbor existuje
NATIVE_M = 1.0
OVR_M = 4.0
GRID_M = 5.0
# prevod EPSG:3046 → EPSG:4326 mierku prakticky nemení, ale fáza cieľovej
# mriežky voči zdrojovej sa naprieč výrezom plynule posúva
DRIFT = 1.002


def _b3(x):
    """Kubický B-splajn – kernel, ktorý GDAL volá `cubicspline`."""
    x = np.abs(x)
    out = np.zeros_like(x)
    m1, m2 = x < 1, (x >= 1) & (x < 2)
    out[m1] = (4 - 6 * x[m1] ** 2 + 3 * x[m1] ** 3) / 6
    out[m2] = (2 - x[m2]) ** 3 / 6
    return out


def weights(n_src, src_res, n_dst, dst_res, kernel):
    """Matica prevzorkovania pozdĺž jednej osi (n_dst × n_src)."""
    W = np.zeros((n_dst, n_src))
    if kernel == "average":
        # tak, ako to robí GDAL: `GDALResampleChunk_Average` priemeruje celé
        # zdrojové pixely v okne, nie plošným podielom – pri pomere 1,25 sa
        # okná posúvajú nepravidelne a každý štvrtý pixel sa preskočí
        for j in range(n_dst):
            a, b = j * dst_res / src_res, (j + 1) * dst_res / src_res
            i0 = max(0, int(math.floor(a + 1e-9)))
            i1 = min(n_src, max(i0 + 1, int(math.ceil(b - 1e-9))))
            W[j, i0:i1] = 1.0 / (i1 - i0)
        return W
    if kernel == "average-exact":
        # poctivý plošný priemer – referencia „nič sa nepokazilo"
        for j in range(n_dst):
            a, b = j * dst_res, (j + 1) * dst_res
            for i in range(max(0, int(a // src_res)),
                           min(n_src, int(math.ceil(b / src_res)))):
                W[j, i] = max(0.0, min(b, (i + 1) * src_res) - max(a, i * src_res))
            s = W[j].sum()
            if s:
                W[j] /= s
        return W
    # `cubicspline` sa pri zmenšovaní roztiahne v pomere mierok (preto vôbec
    # filtruje); `bilinear` nie, a preto jeho sila závisí od fázy
    scale = min(1.0, src_res / dst_res) if kernel == "cubicspline" else 1.0
    rad = {"bilinear": 1.0, "cubicspline": 2.0, "near": 0.5}[kernel] / scale
    for j in range(n_dst):
        c = (j + 0.5) * dst_res / src_res - 0.5
        idx = np.arange(max(0, int(math.floor(c - rad))),
                        min(n_src - 1, int(math.ceil(c + rad))) + 1)
        t = (idx - c) * scale
        if kernel == "bilinear":
            w = np.maximum(0.0, 1.0 - np.abs(t))
        elif kernel == "cubicspline":
            w = _b3(t)
        else:
            w = (np.abs(t) <= 0.5).astype(float)
        s = w.sum()
        if s:
            W[j, idx] = w / s
    return W


def resample(a, src_res, dst_res, kernel, n_dst=None):
    ny, nx = a.shape
    if n_dst is None:
        n_dst = (int(ny * src_res / dst_res) - 2, int(nx * src_res / dst_res) - 2)
    return (weights(ny, src_res, n_dst[0], dst_res, kernel) @ a
            @ weights(nx, src_res, n_dst[1], dst_res, kernel).T)


def terrain(n, res, seed=3, min_lam=0.0):
    """fBm terén. `min_lam` = najkratšia vlnová dĺžka v metroch.

    Nad dvojnásobkom cieľovej bunky je terén hladký voči cieľovej mriežke,
    takže čo v tieňovaní ostane zvlnené, je artefakt prevzorkovania.
    """
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] * res
    z = 300 + 0.004 * x + 0.002 * y
    for k in range(1, 9):
        lam = 2000.0 / (2 ** k)
        if lam < min_lam:
            continue
        amp = 40.0 * (lam / 2000.0) ** 0.85
        for _ in range(3):
            ang, ph = rng.uniform(0, math.pi), rng.uniform(0, 2 * math.pi)
            z += amp * np.sin(2 * math.pi * (x * math.cos(ang)
                                             + y * math.sin(ang)) / lam + ph)
    return z


def hillshade(z, res, az=315.0, alt=45.0):
    dzdx = (np.roll(z, -1, 1) - np.roll(z, 1, 1)) / (2 * res)
    dzdy = (np.roll(z, -1, 0) - np.roll(z, 1, 0)) / (2 * res)
    slope, aspect = np.arctan(np.hypot(dzdx, dzdy)), np.arctan2(dzdy, -dzdx)
    a, zn = math.radians(alt), math.radians(90 - az)
    hs = (math.sin(a) * np.cos(slope)
          + math.cos(a) * np.sin(slope) * np.cos(zn - aspect))
    return np.clip(hs, 0, 1)[2:-2, 2:-2]


def mriezka(z, res):
    """Stredná |Laplacián| tieňovania ×10⁻³ – miera z `workers/lib/cell.py`."""
    hs = hillshade(z, res)
    lap = (np.roll(hs, 1, 0) + np.roll(hs, -1, 0)
           + np.roll(hs, 1, 1) + np.roll(hs, -1, 1) - 4 * hs)
    return float(np.abs(lap[2:-2, 2:-2]).mean()) * 1e3


def kolisanie(z, res, blok=32):
    """Kolísanie drsnosti po ploche v % priemeru – mriežka, ako ju vidí oko."""
    hs = hillshade(z, res)
    lap = np.abs(hs[1:-1, 1:-1] * 4 - hs[:-2, 1:-1] - hs[2:, 1:-1]
                 - hs[1:-1, :-2] - hs[1:-1, 2:])
    ny, nx = lap.shape
    b = lap[:ny // blok * blok, :nx // blok * blok]
    b = b.reshape(ny // blok, blok, nx // blok, blok).mean((1, 3))
    return 100.0 * float(b.std() / b.mean())


def retazce(z, fine):
    """Kandidátske reťazce prevzorkovania, pomenované tak, ako sú v kóde."""
    ovr = resample(z, fine, OVR_M, "average-exact")     # pyramída .ovr
    avg = resample(ovr, OVR_M, GRID_M, "average")       # čítanie bloku
    cs = resample(ovr, OVR_M, GRID_M, "cubicspline")
    n = (avg.shape[0] - 2, avg.shape[1] - 2)
    warp = lambda a, k: resample(a, GRID_M, GRID_M * DRIFT, k, n_dst=n)
    return {
        "referencia (priamo na cieľovú mriežku)":
            resample(z, fine, GRID_M, "average-exact"),
        "DOTERAZ  average@1,25 + bilinear@1:1": warp(avg, "bilinear"),
        "  keby sa opravil len prvý krok": warp(cs, "bilinear"),
        "  keby sa opravil len druhý krok": warp(avg, "cubicspline"),
        "DNES     cubicspline@1,25 + cubicspline@1:1": warp(cs, "cubicspline"),
        "  (pre porovnanie: druhý krok bez filtra)": warp(cs, "near"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--px", type=int, default=3200, help="strana jemného poľa")
    ap.add_argument("--fine", type=float, default=0.5, help="krok jemného poľa (m)")
    args = ap.parse_args()
    seeds = [int(v) for v in args.seeds.split(",") if v.strip()]

    print(f"Pyramída {OVR_M:g} m → cieľ {GRID_M:g} m (pomer "
          f"{GRID_M / OVR_M:.2f}), potom prevod do WGS84 pri pomere 1,0.")
    print(f"`lib/cell.py` na to hovorí: resampling({GRID_M:g}, {OVR_M:g}) = "
          f"`{resampling(GRID_M, OVR_M)}` – priemerovať sa smie až od "
          f"{AVERAGE_RATIO:g}× hrubšieho pixela.\n")

    hl, re_ = {}, {}
    for seed in seeds:
        for name, z in retazce(terrain(args.px, args.fine, seed, min_lam=60.0),
                               args.fine).items():
            hl.setdefault(name, []).append(mriezka(z, GRID_M))
        for name, z in retazce(terrain(args.px, args.fine, seed, min_lam=3.0),
                               args.fine).items():
            re_.setdefault(name, []).append(kolisanie(z, GRID_M))

    print(f"{'reťazec':48s} {'mriežka':>8s} {'kolísanie':>10s}")
    print(f"{'':48s} {'(hladký)':>8s} {'(reálny)':>10s}")
    for name in hl:
        print(f"{name:48s} {np.mean(hl[name]):8.1f} "
              f"{np.mean(re_[name]):9.1f} %")
    print(f"\n({len(seeds)} terénov, {args.px}² buniek po {args.fine:g} m; "
          f"čím bližšie k referencii, tým menej mriežky)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
