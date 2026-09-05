#!/usr/bin/env python3
"""Koľko metrov je jedna bunka – a čo z toho plynie.

Bunka modelu a pixel dlaždice rozhodujú o troch veciach naraz: ktorý maxzoom
má zmysel počítať, ktorým resamplingom sa naň ide a aký zvislý krok znesie
kódovanie výšky. Odpoveď na všetky stojí na tom istom prevode stupňov na
metre, tak sú tu spolu. Pýtajú sa ich `plan/options.py`,
`contours-rocks/rock-plan.py`, `terrain/tiles.py` a `smooth-shapes.py`.

Bez numpy zámerne: `lint/terrain.py` to musí vedieť spustiť a lintovací job má
len holý python3. Práca nad poliami ostáva v `terrain/tiles.py`.
"""
import json
import math
import subprocess

# stred Slovenska: mriežka Web Mercatora je v metroch na rovníku, tak sa
# rozmer musí prepočítať na našu šírku (rozdiel 47,7° a 49,6° sú ~4 %)
DEFAULT_LAT = 49.0

# Zoom 0 má na rovníku 156 543,03 m na pixel (256 px na 40 075 km).
EQUATOR_M_PER_PX = 156543.03

# šírka je takmer konštantná, dĺžka sa krátí s kosínusom. Kto prepočítava
# toleranciu z metrov na stupne, delí tou dlhšou – na zemi tak nevyjde väčšia.
M_PER_DEG_LAT = 110540
M_PER_DEG_LON_EQ = 111320


def tile_m_per_px(z, lat=DEFAULT_LAT):
    """Koľko metrov v teréne je jeden pixel dlaždice na danom zoome."""
    return EQUATOR_M_PER_PX * math.cos(math.radians(lat)) / (2 ** z)


# súradnicová mriežka vektorovej dlaždice: `extent` 4096 na 256 pixelov, teda
# 16 krokov na pixel. Zaokrúhli sa do nej každý bod geometrie, takže sa podľa
# nej riadi aj hustota vzorkovania vyhladenej vrstevnice.
TILE_EXTENT = 4096
TILE_PX = 256


def tile_grid_m(z, lat=DEFAULT_LAT):
    """Krok súradnicovej mriežky dlaždice v metroch na danom zoome."""
    return tile_m_per_px(z, lat) * TILE_PX / TILE_EXTENT


def terrain_zoom_for(cell_m, lo=8, hi=16):
    """Najnižší zoom, na ktorom je pixel dlaždice jemnejší než bunka modelu.

    Vyššie už dlaždice nesú detail, ktorý v modeli nie je. Sonny (20 m) → z13,
    DMR 3.5 (10 m) → z14, DMR 5.0 (5 m) → z15.
    """
    for z in range(lo, hi + 1):
        if tile_m_per_px(z) <= cell_m:
            return z
    return hi


# sklon, ktorý sa v tieňovaní už nedá odlíšiť od roviny (2 % je ~3,6 z 255
# odtieňov, a v štýle ešte cez `hillshade-exaggeration`). Jedno číslo, dve
# použitia: vyberá zvislý krok kódovania a rozhoduje, ktorá dlaždica je rovina.
SLOPE_EPS = 0.02

# jemnejšie než 1/64 m je pod šumom každého modelu a v PNG len bajt navyše
MAX_FRAC_BITS = 6

# o koľko pod hranicu viditeľnosti. `SLOPE_EPS` je sklon, ktorý sa stratí
# v jednom mieste – kvantizácia ho ale robí pravidelne cez celú dlaždicu, tak
# ho oko číta ako mriežku. Namerané celou cestou cez `terrain/tiles.py`: každý
# bit navyše stojí ~30 % veľkosti dlaždice a tri bity zrazia mriežku na z13
# 7,8×. Na z12 sa zastaví na prevzorkovaní pri pomere 1,25 (blízko Nyquista),
# ktoré sa bitmi kúpiť nedá.
FRAC_BITS_MARGIN = 3


def frac_bits(px_m):
    """Koľko zlomkových bitov výšky (bajt B) treba pri pixeli `px_m` metrov.

    Krok kódovania má ostať `FRAC_BITS_MARGIN` bitov pod `SLOPE_EPS × pixel`.
    Nula znamená celé metre – na najhrubších zoomoch dlaždice nerastú vôbec.
    """
    want = SLOPE_EPS * px_m
    if not (want > 0):
        return 0
    # strop `MAX_FRAC_BITS` platí ďalej: na najvyšších zoomoch vyjde margin
    # menší, a je to v poriadku (1/64 m je pri pixeli 3 m len 0,5 % sklonu)
    target = want / (2 ** FRAC_BITS_MARGIN)
    return max(0, min(MAX_FRAC_BITS, int(math.ceil(-math.log2(target)))))


# od akého násobku bunky sa smie priemerovať. `average` je box filter cez
# prekryté bunky, takže priemerovať má čo až od dvoch. Hneď nad bunkou mu
# padne raz jedna, raz dve – rytmus plošiniek a z neho tá istá mriežka ako pri
# zväčšovaní. Namerané (bunka 20 m, mriežka = stredná |Laplacián| ×10⁻³):
# pri pomere 2,51 sú `average` a `cubicspline` rovné, pri 1,25 je `average`
# 10× horší. Nad pomerom 2 sa nelíšia a `average` je tam lacnejší.
AVERAGE_RATIO = 2.0


def resampling(px_m, cell_m):
    """`average` až keď je pixel aspoň `AVERAGE_RATIO`× hrubší než bunka.

    Pri zväčšovaní zdegeneruje na najbližšieho suseda; v pásme tesne nad
    bunkou je to to isté, len slabšie. Bez známej bunky ostáva `average` –
    doterajšie správanie, pri poctivom zmenšovaní správne.
    """
    if not cell_m or px_m >= AVERAGE_RATIO * cell_m:
        return "average"
    return "cubicspline"


def dem_cell_metres(dem, lat=DEFAULT_LAT):
    """Rozmer bunky zdrojového DEM v metroch – zmeraný z rastra, nie z mena.

    `cell_m` v `dem-sources.json` je hodnota zo zadania: `dmr5` je 5 m na
    región a 1 m na výrez, `sonny1` má mriežku nesúmernú (20,3 × 30,9 m).

    Vracia `(dx, dy)`, alebo `(None, None)`, keď sa raster nedá prečítať.
    """
    try:
        out = subprocess.run(["gdalinfo", "-json", dem], check=True,
                             capture_output=True, text=True).stdout
        info = json.loads(out)
        gt = info["geoTransform"]
        wkt = info.get("coordinateSystem", {}).get("wkt", "")
        dx, dy = abs(gt[1]), abs(gt[5])
        if wkt.startswith("GEOGCRS") or wkt.startswith("GEOGCS"):
            return (dx * M_PER_DEG_LON_EQ * math.cos(math.radians(lat)),
                    dy * M_PER_DEG_LAT)
        return dx, dy
    except Exception:
        return None, None
