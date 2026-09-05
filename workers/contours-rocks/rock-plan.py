#!/usr/bin/env python3
"""Plán skál: na akej mriežke, koľko buniek a ako dlho to potrvá.

Oddelené od `rock-areas.py`: `slope-chunks.py` sa pýta pred výpočtom („akú
mriežku zvoliť"), `rock-areas.py` až pri ňom („koľko to ešte potrvá").

Sú tu aj namerané rýchlosti, z ktorých odhady vychádzajú. Keď sa beh s nimi
rozíde viac než 3×, povie to sám na konci a číslo sa má prepísať.
"""
import json
import math
import os
import subprocess
import sys

# `watch.py` je spoločný pre obe cesty ku skalám, tak leží vo `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms  # noqa: E402
import cell  # noqa: E402

# mriežku rastra sa pýta aj tieňovanie, tak je prevod v `lib/cell.py`;
# `rock-areas.py` aj `slope-chunks.py` si ho berú odtiaľto
dem_cell_metres = cell.dem_cell_metres

METRIC = "EPSG:3035"  # LAEA Európa – pre naše šírky skresľuje plochy minimálne
# sklon sa ukladá ako Int16 v stotinách stupňa: Byte s krokom 0,5° robil
# v poli sklonu plošiny a izolínia po nich chodila schodíkmi
SCALE = 100

# namerané na GitHub runneri – slúžia len na odhad dopredu.
# Slope: 170 častí / 23,1 mld. buniek za 75 min.
#
# Contour: cena `gdal_contour -p` ide so ZDROJOVÝMI bunkami, nie s mriežkou,
# na ktorú sa trasuje – obrys sa nezlacní hrubším trasovaním, ale hrubším
# skladom. Preto `pick_res` účtuje vektorizáciu mriežke skladu.
#
# Číslo platí pre počítanie PO BLOKOCH (`ROCK_BLOCK_PX`): pri jednom priechode
# `gdal_contour -p` nad veľkým územím spomaľuje, ako pribúdajú rozpracované
# prstence, a nikdy nedobehol. Prvé číslo z behu, ktorý dobehol, je
# 12,1 mil. buniek/s na rovine – na skalnatom výreze bude nižšia.
CONTOUR_SRC_CELLS_PER_S = 1.2e7
# ten istý beh na OOM nespadol, takže pri 23,1 mld. buniek bol pod 16 GB:
# zadanie sa zabije o čas, nie o pamäť


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def to_metric(bbox):
    """Bbox v stupňoch → rozsah v metroch (EPSG:3035)."""
    w, s, e, n = bbox
    pts = "\n".join(f"{x} {y}" for x, y in
                    [(w, s), (e, s), (w, n), (e, n), ((w + e) / 2, s), ((w + e) / 2, n)])
    out = run(["gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", METRIC],
              input=pts).stdout.split()
    xs = [float(v) for v in out[0::3]]
    ys = [float(v) for v in out[1::3]]
    return min(xs), min(ys), max(xs), max(ys)


def chunk_plan(x0, y0, x1, y1, res, chunk_cells, bbox, side_m=0):
    """Rozdelenie na časti + zoznam tých, ktoré naozaj ležia v území.

    EPSG:3035 je pootočená voči poludníkom, takže obdĺžnik opísaný bboxu je
    v metroch výrazne väčší než región – časti mimo bboxu sa preskočia.

    `side_m` prebije veľkosť časti; používa to `pick_res`, ktorý potrebuje len
    zistiť, koľko plochy naozaj leží v území.
    """
    snap = lambda v, up: (math.ceil(v / res) if up else math.floor(v / res)) * res
    x0, y0, x1, y1 = snap(x0, False), snap(y0, False), snap(x1, True), snap(y1, True)
    width_m, height_m = x1 - x0, y1 - y0

    side = side_m or math.sqrt(chunk_cells) * res
    nx = max(1, math.ceil(width_m / side))
    ny = max(1, math.ceil(height_m / side))
    step_x = math.ceil(width_m / nx / res) * res
    step_y = math.ceil(height_m / ny / res) * res

    chunks = []
    for iy in range(ny):
        for ix in range(nx):
            cx0, cy0 = x0 + ix * step_x, y0 + iy * step_y
            cx1, cy1 = min(cx0 + step_x, x1), min(cy0 + step_y, y1)
            if cx1 <= cx0 or cy1 <= cy0:
                continue
            chunks.append((iy, ix, cx0, cy0, cx1, cy1))

    keep = [c for c in chunks if intersects_bbox(c[2], c[3], c[4], c[5], bbox)]
    cells = sum(((c[4] - c[2]) / res) * ((c[5] - c[3]) / res) for c in keep)
    return keep, len(chunks), cells, (nx, ny, step_x, step_y, width_m, height_m)


def intersects_bbox(cx0, cy0, cx1, cy1, bbox):
    """Zasahuje časť (v metroch) do bboxu územia (v stupňoch)?"""
    pts = "\n".join(f"{x} {y}" for x, y in
                     [(cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1),
                      ((cx0 + cx1) / 2, cy0), ((cx0 + cx1) / 2, cy1),
                      (cx0, (cy0 + cy1) / 2), (cx1, (cy0 + cy1) / 2)])
    try:
        out = run(["gdaltransform", "-s_srs", METRIC, "-t_srs", "EPSG:4326"],
                  input=pts).stdout.split()
    except subprocess.CalledProcessError:
        return True  # keď sa to nedá zistiť, radšej počítať než vynechať
    xs = [float(v) for v in out[0::3]]
    ys = [float(v) for v in out[1::3]]
    return not (max(xs) < bbox[0] or min(xs) > bbox[2]
                or max(ys) < bbox[1] or min(ys) > bbox[3])


# z čoho `--res=auto` vyberá. Najjemnejšie je 1 m: ani 1 m LiDAR pod to nedá
# nový detail a pixel dlaždice má pri z16 aj tak 1,57 m.
RES_LADDER = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 15.0, 20.0)

# podlaha mriežky, na ktorej sa vektorizuje: obrys trasovaný jemnejšie než
# pixel dlaždice pri z16 sa v mape nemá ako zobraziť. Čas to neušetrí (zmerané),
# ale výstup je menší a pamäť nižšia.
VEC_FLOOR_M = 1.6


def pick_vec_res(res, floor=VEC_FLOOR_M):
    """Mriežka vektorizácie: najjemnejšia, ktorú je ešte vidieť – ale nikdy
    jemnejšia než uložený sklon.

    Čas tým neušetríš (zmerané); je to o menšom výstupe a nižšej pamäti.
    Na čas je jediná páka hrubší sklad (`rock_res`).
    """
    for r in RES_LADDER:
        if r < res or r < floor:
            continue
        return r
    return max(res, RES_LADDER[-1])


def pick_res(x0, y0, x1, y1, chunk_cells, bbox, budget_min, dem_cell_m):
    """Najjemnejšia mriežka, ktorá má ešte zmysel (a zmestí sa do rozpočtu).

    Rozpočet je predvolene žiadny (`budget_min=0`), takže rozhodujú len dva
    stropy zdola: desatina bunky zdrojového DEM (jemnejšie sa už len
    interpoluje) a 1 m absolútne.

    Absolútny strop bol 0,5 m a pri DMR 5.0 to bola chyba: štvornásobok buniek,
    ktoré nenesú ani o meter terénu viac – pri z16 má pixel dlaždice 1,57 m.
    Hladší obrys robia `--simplify` a `--smooth` za zlomok ceny.
    """
    # koľko plochy naozaj leží v území, zistené na hrubom rastri častí –
    # nezávisí to od mriežky, tak sa to počíta raz a lacno
    side = max(2000.0, math.sqrt((x1 - x0) * (y1 - y0) / 50.0))
    probe, _, _, _ = chunk_plan(x0, y0, x1, y1, 10.0, chunk_cells, bbox,
                                side_m=side)
    area_m2 = sum((c[4] - c[2]) * (c[5] - c[3]) for c in probe)
    if not area_m2:
        return RES_LADDER[3]  # nič sa netrafilo – nech to povie až chunk_plan

    # podlaha mriežky skladu, oba dôvody o tom, čo je vidieť – nie o čase:
    # desatina bunky zdrojového DEM a pixel dlaždice pri z16 (`VEC_FLOOR_M`).
    # To druhé tu dlho nebolo a `auto` preto pri DMR 5.0 siahalo na 1 m sklad –
    # pri 2 m je buniek štvrtina a detail v mape rovnaký.
    floor = max(VEC_FLOOR_M, round((dem_cell_m or 0) / 10.0, 1))
    budget_s = budget_min * 60 if budget_min else float("inf")

    print("── Výber mriežky (rock_res=auto) ────────────────────")
    print(f"  plocha územia   {area_m2/1e6:.0f} km²")
    print("  rozpočet        " + ("bez stropu – berie sa najjemnejšia, "
                                  "ktorá má zmysel"
                                  if budget_s == float("inf")
                                  else f"{budget_min:g} min"))
    if dem_cell_m:
        print(f"  bunka DEM       {dem_cell_m:.0f} m → jemnejšie než "
              f"{floor:g} m nemá zmysel")
    else:
        print(f"  bunka DEM       neznáma → dolný strop {floor:g} m")
    # dve polovice, dva riadky: jedno číslo za obe skrývalo, že drahšia je tá
    # druhá – pri 1 m stojí sklon dve minúty a vektorizácia hodinu a pol
    chosen = None
    for res in RES_LADDER:
        if res < floor:
            continue
        vec = pick_vec_res(res)
        cells = area_m2 / (res * res)
        s_slope = cells / SLOPE_CELLS_PER_S
        # vektorizácia sa účtuje tejto mriežke, nie tej, na ktorú sa trasuje:
        # `gdal_contour` prečíta zdrojové bunky tak či tak
        s_vec = cells / CONTOUR_SRC_CELLS_PER_S
        est = s_slope + s_vec
        fits = est <= budget_s
        # bez rozpočtu je stĺpec len odhad času, nie súd nad ním
        znak = "" if budget_s == float("inf") else (
            "  ✓" if fits else "  × nad rozpočet")
        print(f"  {res:>4g} m  {cells/1e9:5.2f} mld.  sklon ~{hms(s_slope)}"
              f"  + vektory ~{hms(s_vec)} (trasuje sa na {vec:g} m)"
              f"  = ~{hms(est)}{znak}")
        if fits and chosen is None:
            chosen = res
    if chosen is None:
        chosen = RES_LADDER[-1]
        print(f"::warning::Ani najhrubšia mriežka {chosen:g} m sa do rozpočtu "
              f"{hms(budget_s)} nezmestí – skús menší výrez (input „area“).")
    print(f"  vybrané         {chosen:g} m")
    print("─────────────────────────────────────────────────────", flush=True)
    return chosen


def mosaic_cells(vrt):
    """Koľko buniek má hotová mozaika sklonu – na odhad času vektorizácie."""
    try:
        info = json.loads(run(["gdalinfo", "-json", vrt]).stdout)
        w, h = info["size"]
        return float(w) * float(h)
    except Exception:
        return 0.0


def mosaic_info(vrt):
    """(šírka, výška, rozsah v metroch, počet zdrojov) hotovej mozaiky."""
    try:
        info = json.loads(run(["gdalinfo", "-json", vrt]).stdout)
        w, h = info["size"]
        gt = info["geoTransform"]
        x0, y1 = gt[0], gt[3]
        x1, y0 = x0 + gt[1] * w, y1 + gt[5] * h
        try:
            zdroje = open(vrt).read().count("<SourceFilename")
        except OSError:
            zdroje = 0
        return int(w), int(h), (x0, y0, x1, y1), zdroje
    except Exception:
        return 0, 0, None, 0


def clip_vrt(vrt, box, res, tmp, src_res=0.0):
    """Mozaika orezaná presne na územie, ktoré si beh vypýtal – a keď treba,
    rovno na hrubšej mriežke.

    Sklad má absolútnu mriežku častí (to je jeho zmysel), takže mozaika je
    zjednotenie celých častí, nie územia: 2 km² štvorec môže pretínať štyri
    z nich. Bez orezu sa vektorizuje osemnásobok a plochy navyše skončia v mape
    mimo územia.

    Orezáva sa VRT, nie dáta – zápis do XML, takže to stojí milisekundy.
    Hranice sa prichytávajú na mriežku `res`, nech sa bunky neposunú o pol bunky.

    Zhrubnutie ide tou istou cestou: VRT si rovno vypýta hrubšie bunky
    a priemeruje. `average`, nie `nearest` – ten by z 1 m poľa vybral každú
    štvrtú bunku aj s jej zrnom.
    """
    x0 = math.floor(box[0] / res) * res
    y0 = math.floor(box[1] / res) * res
    x1 = math.ceil(box[2] / res) * res
    y1 = math.ceil(box[3] / res) * res
    out = os.path.join(tmp, "slope-clip.vrt")
    hrubsie = ["-r", "average"] if src_res and res > src_res else []
    run(["gdalbuildvrt", "-q", "-te", repr(x0), repr(y0), repr(x1), repr(y1),
         "-tr", repr(res), repr(res)] + hrubsie + [out, vrt])
    return out
