#!/usr/bin/env python3
"""
DEM → dlaždice `raster-dem` (kódovanie terrarium) pre tieňovanie reliéfu
a 3D terén.

PREČO VLASTNÉ DLAŽDICE: MapLibre nevie čítať výšky z GeoTIFFu – potrebuje
pyramídu PNG dlaždíc, kde je nadmorská výška zakódovaná do farby. Verejné
AWS Terrain Tiles sú *povrchový* model (Copernicus/SRTM vrátane stromov),
takže by 3D terén a tieňovanie hovorili niečo iné než vrstevnice a skaly,
ktoré počítame z LiDAR terénu. Tento skript preto vyrobí dlaždice z toho
istého DEM ako zvyšok pipeline.

Kódovanie terrarium (rovnaké, aké čakal doterajší zdroj):
    výška [m] = (R * 256 + G + B / 256) − 32768

ZVISLÝ KROK SA RIADI VODOROVNÝM PIXELOM, a to je oprava tkanej mriežky
v tieňovaní. Kým bolo `B = 0`, výška bola zaokrúhlená na celé metre – teda
terén rozrezaný na metrové plošinky. Hillshade je DERIVÁCIA výšky, takže
z hrany každej plošinky spraví čiaru, a keď je plošinka široká pár pixelov,
tie čiary vyjdú pravidelné a v mape je vidieť tkaninu. Je to tá istá chyba,
akú už raz spravil sklon skál uložený po 0,5° (viď hlavičku
`contours-rocks/rock-plan.py`): hrubý krok → plošinky → obrys po hranách.

Pôvodné meranie („rozdiel je priemerne 0,5 z 255 odtieňov, okom neviditeľný")
bolo správne spočítané a viedlo k zlému záveru: merala sa VEĽKOSŤ odchýlky,
nie jej TVAR. Oko odchýlku 0,5/255 nevidí, ale pravidelnú mriežku z nej áno.

Krok sa preto volí tak, aby falošný sklon z kvantizácie ostal pod `SLOPE_EPS`
– a keďže sklon je krok delený pixelom, znamená to `krok ≤ SLOPE_EPS × pixel`.

LENŽE NIE TESNE POD ŇOU, ALE S ODSTUPOM. Krok postavený presne na tú hranicu
posadí falošný sklon na KAŽDOM zoome tesne pod hranicu viditeľnosti a nechá ho
tam – a keďže je pravidelný, oko ho aj tak číta ako mriežku (na hranách
schodíkov ju druhá derivácia ešte zvýrazní). Je to presne tá chyba, ktorú
popisuje odsek vyššie, len spravená druhýkrát: krok sa vybral podľa VEĽKOSTI
odchýlky a nie podľa toho, že jej TVAR je mriežka. Preto `FRAC_BITS_MARGIN`
(`workers/lib/cell.py`) posúva krok ešte o tri bity nižšie.

Namerané celou touto cestou na hladkom umelom teréne (mriežka v hillshade ako
stredná |Δ| Laplaciánu ×10⁻³; hladký povrch = 0,0). Kvantizácia pridáva na
každom zoome to isté, lebo krok ide s pixelom:

    bity navyše   z12 krok  mriežka  kB/dl.   z13 krok  mriežka  kB/dl.
    +0 (doteraz)    1/2      10,47    20,3     1/4        9,12    21,2
    +1              1/4       6,39    26,6     1/8        4,62    30,8
    +2              1/8       4,68    35,3     1/16       2,33    38,7
    +3 (dnes)       1/16      4,07    43,7     1/32       1,17    47,4

Každý bit stojí ~30 % veľkosti dlaždice. Na z13 je po mriežke (7,8×), na z12
sa to zastaví na 4,07 – tam už nedrží kvantizácia, ale prevzorkovanie pri
pomere pixel/bunka 1,25, čo je blízko Nyquista a bitmi sa to nekúpi.
Dlaždice sú ~2,2× väčšie a to je celá cena – platí sa len tam, kde je pixel
jemný (do z8 vyjde krok na celý meter, čiže presne to, čo bolo doteraz)
a `--budget-mb` sa oň postará sám.

RESAMPLING SA RIADI POMEROM PIXELA A BUNKY. Dlaždice sa nekreslia zmenšovaním
hotových dlaždíc, ale pre každý zoom sa DEM prevzorkuje nanovo – priemerovať sa
totiž musí *výška*, nie zakódovaná farba (priemer bajtov R/G je nezmysel).

`average` je box filter cez tie bunky, ktoré cieľový pixel prekryje, takže
priemerovať má čo až vtedy, keď ich prekryje aspoň dve. Pri ZVÄČŠOVANÍ
zdegeneruje na najbližšieho suseda – z každej bunky DEM vypadne štvorček
rovnakých pixelov a hillshade z jeho hrán spraví mriežku. A TESNE NAD BUNKOU
je to to isté, len slabšie: raz jedna bunka, raz dve, čiže rytmus plošiniek.
Preto hranica nie je „pixel hrubší než bunka", ale jej DVOJNÁSOBOK
(`AVERAGE_RATIO` vo `workers/lib/cell.py`); pod ním ide `-r cubicspline` –
B-spline, teda hladký aj v prvej derivácii a bez prestrelov na okrajoch dát.

Namerané na tom istom teréne (bunka 20 m, mriežka ×10⁻³):

    zoom   pixel    pomer   average   cubicspline
    z11    50,1 m    2,51     0,65       0,58     ← tu sú si rovné
    z12    25,1 m    1,25     5,36       0,53     ← toto ostalo vidieť
    z13    12,5 m    0,63    34,34       0,04

Prvá oprava riešila len zväčšovanie (z13 a vyššie), takže na z12 ostal
`average` – a mriežku bolo na mape stále vidieť.

TIEŇOVANIE KONČÍ NA HRANICI REGIÓNU, NIE NA HRANICI DLAŽDICE. Dlaždice sa
robia na OBDĹŽNIKU bboxu a `--poly` z nich vyhodí tie, čo sa kraja ani
nedotknú – lenže hrubšie než dlaždica sa to orezať nedá a dlaždica je na
nízkych zoomoch obrovská. Namerané na Prešovskom kraji (10 184 km²) ako plocha
vyrobených dlaždíc proti ploche kraja:

    zoom      z8     z9    z10    z11    z12    z13    z14
    pokrytie 6,2×   3,8×   2,2×   1,7×   1,4×   1,2×   1,11×

Tieňovaný reliéf teda pokračoval ďaleko za hranicu stiahnutého regiónu – na
z10 na dvojnásobku jeho plochy. V mape to zakrývala až plocha `mimo` zo štýlu
(`workers/deploy/region-mask.py`), takže stačilo pozrieť sa na vrstvu bez nej
a mapa „pokračovala" tam, kde už žiadna nie je.

Preto sa orezáva aj PO PIXELOCH (`region-mask.pixel_mask`). Otázka je, ČO
v dlaždici dostanú pixely mimo kraja – a odpoveď je tá istá, akú si už raz
vypýtala hranica modelu o pár odsekov nižšie: POKRAČOVANIE OKOLÍM, nie
konštanta.

ROVINA NA HRANICI KRAJA ROBILA STENU. Kým tam bola výška 0, spadol terén
medzi dvoma pixelmi zo 600 m na nulu – a to je pre hillshade (derivácia
výšky) zvislý útes, teda najsilnejší sklon, aký v dlaždici môže byť, a v 3D
teréne doslova stena po obvode regiónu. `--edge` ju posúval pár pixelov ZA
hranicu, kde ju v štýle prekrýva plocha `mimo`, lenže to je schovávanie, nie
odstránenie: v 3D pod uhlom, pri prevýšení a všade, kde sa maska nekreslí,
bola stena vidieť. Namerané celým týmto skriptom na umelom teréne (z13,
12,5 m/px, členitý polygón kraja; terén sám má v kraji najväčší sklon medzi
susednými pixelmi 17,9° a stredný 8,0°):

    orez              najväčší sklon za hranicou    stredný sklon za hranicou
                      1–4 px   5–12 px   ďalej      1–8 px  9–32 px  33–128 px
    rovina 0 m         89,4°    89,4°    89,3°      79,2°     2,6°      0,0°
    pokračovanie       30,6°    22,8°    21,8°       7,0°     6,8°      5,5°

Rovina teda za hranicou postavila stenu (79,2° V PRIEMERE cez celý pás
1–8 px) a za ňou nechala plochu bez tieňovania. Pokračovanie nemá stenu
nikde: sklon za hranicou je terénny a von z regiónu pomaly slabne
(8,0° v kraji → 5,5° stotridsať pixelov za hranicou).

AKO SA POKRAČUJE: `pokracuj_okolim` nižšie, pyramída priemerov. Nie po
riadkoch a stĺpcoch ako `vypln_nodata` – tá je stavaná na ROVNÝ okraj modelu
a na členitej hranici kraja spraví vlastnú stenu (namerané 825 m medzi dvoma
susednými riadkami dva pixely za hranicou, čiže 89°: stena preč a hneď vedľa
vyrástla iná).

ČO SA TÝM STRATILO A PREČO TO NEVADÍ. Rovina za hranicou nekreslila NIČ,
pokračovanie kreslí slabnúci reliéf. Ten je ale celý ZA hranicou, kde ho
v štýle prekrýva plocha `mimo` (`workers/deploy/region-mask.py`) – a ďalej
ako o kúsok za hranicu sa nedostane: dlaždica, v ktorej NIE JE ANI JEDEN
pixel kraja, sa nezapíše vôbec. To je to isté, čo predtým robila rovina cez
`je_rovina` (celá dlaždica mimo = rovina = vynechaná), len sa to pýta priamo
masky, a nie naokolo cez výšku. Dlaždíc je preto rovnako veľa ako s rovinou
a pokrytie ostáva na 1,0–1,07× plochy kraja (zvyšok je rezerva `--edge`).
Namerané na tom istom umelom teréne, dva tvary kraja:

    kraj                     rovina 0 m          pokračovanie
    12 % bboxu           67 dlaždíc, 1,9 MB   65 dlaždíc, 2,2 MB
    54 % bboxu (ako kraj) 203 dlaždíc, 8,2 MB 202 dlaždíc, 8,7 MB

Tých pár percent navyše sú zlomkové bity doplnenej výšky; drží ich pri zemi
zaokrúhlenie na `SLOPE_EPS × pixel` (rozpis pri `pokracuj_okolim`).

`--edge` OSTÁVA, ale s inou úlohou: nie „kam schovať stenu", ale koľko pixelov
SKUTOČNÉHO terénu sa nechá ešte za hranicou, nech je tieňovanie NA hranici
počítané z okolia a nie z pokračovania (hillshade berie susedné pixely a klient
si dlaždicu ešte prevzorkuje).

Použitie:
    python3 workers/terrain/tiles.py --dem=dem/all.vrt \\
        --bbox=16.8,47.7,22.6,49.6 --maxzoom=12 --out=terrain-out
"""
import argparse
import math
import os
import struct
import subprocess
import sys
import zlib

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
# `SLOPE_EPS`, `frac_bits` a `resampling` sú čistá aritmetika nad mriežkou
# a zoomom, tak bývajú vo `lib/cell.py` vedľa `terrain_zoom_for` – je to tá
# istá otázka z troch strán. A hlavne: `lint/terrain.py` ich musí vedieť
# spustiť, a lintovací job nemá numpy (viď hlavičku `lib/cell.py`).
from cell import (SLOPE_EPS, dem_cell_metres, frac_bits,  # noqa: E402
                  resampling, tile_m_per_px)
# Čo sa zapíše tam, kde výšku nemáme – sentinel `NODATA`, výplň dier v modeli
# a pokračovanie za hranicou kraja. Je to práca nad mriežkou výšok a leží
# vedľa, vo `vyska.py`: `tiles.py` je plán, warp a kódovanie do dlaždíc, a nad
# 800 riadkov sa v jednom súbore nedá rýchlo nájsť, čo sa zmenilo (pravidlo 5).
sys.path.insert(0, _HERE)
from vyska import NODATA, pokracuj_okolim, vypln_nodata  # noqa: E402

R_EARTH = 6378137.0
ORIGIN = math.pi * R_EARTH  # 20037508.342789244
TILE = 256


def merc_x(lon):
    return math.radians(lon) * R_EARTH


def merc_y(lat):
    lat = max(min(lat, 85.05112878), -85.05112878)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH


def tile_range(z, w, s, e, n):
    """Rozsah dlaždíc XYZ, ktoré pokrývajú bbox na danom zoome."""
    count = 2**z
    size = 2 * ORIGIN / count
    x0 = int((merc_x(w) + ORIGIN) // size)
    x1 = int((merc_x(e) + ORIGIN) // size)
    y0 = int((ORIGIN - merc_y(n)) // size)
    y1 = int((ORIGIN - merc_y(s)) // size)
    clamp = lambda v: max(0, min(count - 1, v))
    return clamp(x0), clamp(x1), clamp(y0), clamp(y1)


# ---------- minimálny zapisovač PNG ----------
# Pillow tu nie je: jediné, čo potrebujeme, je bezstratový RGB PNG, a to je
# zlib + pár hlavičiek. Filtre skúšame všetky a pre každý riadok berieme ten
# s najmenším súčtom absolútnych odchýlok (štandardná heuristika) – bez nich
# by boli dlaždice zbytočne veľké.
def _filter_rows(raw):
    h, stride = raw.shape
    bpp = 3
    out = np.empty((h, stride + 1), np.uint8)
    prev = np.zeros(stride, np.uint8)
    for i in range(h):
        line = raw[i].astype(np.int16)
        left = np.zeros(stride, np.int16)
        left[bpp:] = line[:-bpp]
        up = prev.astype(np.int16)
        upleft = np.zeros(stride, np.int16)
        upleft[bpp:] = up[:-bpp]

        cands = [
            (0, line),
            (1, line - left),
            (2, line - up),
            (3, line - ((left + up) // 2)),
        ]
        # Paeth
        p = left + up - upleft
        pa, pb, pc = np.abs(p - left), np.abs(p - up), np.abs(p - upleft)
        pred = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, up, upleft))
        cands.append((4, line - pred))

        best = min(cands, key=lambda c: int(np.abs(c[1].astype(np.int8)).sum()))
        out[i, 0] = best[0]
        out[i, 1:] = best[1].astype(np.uint8)
        prev = raw[i]
    return out


def png_rgb(arr):
    h, w, _ = arr.shape
    raw = np.ascontiguousarray(arr).reshape(h, w * 3)
    data = _filter_rows(raw).tobytes()

    def chunk(kind, payload):
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(data, 9))
        + chunk(b"IEND", b"")
    )


def terrarium(vysky, bits):
    """Výška v metroch → RGB terrarium so zlomkom na `bits` bitov.

    ZAOKRÚHĽUJE SA NA KROK, nereže sa maskou. Maskovanie spodných bitov je
    o riadok kratšie a je to `floor`: každá výška by klesla až o celý krok
    a pri `bits = 0` (nízke zoomy) by to bol posun až o meter oproti tomu, čo
    zapisoval `-ot Int16` doteraz. Systematický, takže by sa neprejavil ako
    šum, ale ako schod na hranici zoomov – v 3D teréne by terén pri
    priblížení nadskočil. Takto je `bits = 0` presne to, čo bolo doteraz,
    a bajt B má aj tak len 2^bits rôznych hodnôt (to je to, čo z neho spraví
    stlačiteľný bajt).
    """
    krok = 1 << (8 - bits)               # krok kódovania v 1/256 m
    v = np.rint((vysky.astype(np.float64) + 32768.0) * 256.0 / krok) * krok
    v = np.clip(v, 0, (16777215 // krok) * krok).astype(np.uint32)
    rgb = np.empty(vysky.shape + (3,), np.uint8)
    rgb[..., 0] = (v >> 16) & 255
    rgb[..., 1] = (v >> 8) & 255
    rgb[..., 2] = v & 255
    return rgb


def je_rovina(vysky, px_m):
    """Nie je v tejto dlaždici čo tieňovať?

    Najväčší rozdiel výšky medzi susednými pixelmi proti `SLOPE_EPS`. Keď
    nikde v dlaždici nie je sklon nad ním, je to hladina alebo rovina –
    hillshade by z nej nakreslil rovnú plochu a 3D terén rovinu, čiže presne
    to, čo klient dostane aj z rodičovskej dlaždice o zoom nižšie.
    """
    if vysky.shape[0] < 2 or vysky.shape[1] < 2:
        return False
    strop = SLOPE_EPS * px_m
    return (float(np.abs(np.diff(vysky, axis=1)).max()) <= strop
            and float(np.abs(np.diff(vysky, axis=0)).max()) <= strop)


def warp_level(dem, path, minx, miny, maxx, maxy, width, height, resample):
    """Prevzorkuje DEM do mriežky presne zarovnanej na dlaždice daného zoomu.

    `Float32`, nie `Int16`: zlomok výšky musí prežiť až po kódovanie, inak
    je krok metrový bez ohľadu na to, koľko bitov mu potom dáme.

    `-dstnodata` JE SENTINEL, NIE NULA. Kým tu stála nula, znamenalo „model tu
    nemáme" to isté, čo „hladina mora" – a terrarium nemá ako povedať, že
    hodnota nie je. Mimo modelu tým vznikla vyrobená rovina v nulovej výške
    a na jej hranici stena. Namerané na publikovanom
    `bratislavsky_test4-terrain.pmtiles`: dlaždica z5 mala 99,6 % plochy
    presne 0 m, z9 43 %, z10 35 %, a najväčší skok medzi susednými pixelmi
    bol 668 m na 407 m/px, čo je sklon 59° – hillshade z toho nakreslí ostrú
    svetlo-tmavú čiaru tam, kde končia dáta, a za ňou nekreslí nič. Odteraz
    je nodata rozoznateľná a `vypln_nodata` ju doplní okolím.
    """
    subprocess.run(
        ["gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:3857",
         "-te", *map(repr, (minx, miny, maxx, maxy)),
         "-ts", str(width), str(height),
         "-r", resample, "-ot", "Float32", "-dstnodata", str(NODATA),
         "-of", "ENVI", dem, path],
        check=True,
    )


def load_mask(poly, bbox):
    """Maska kraja z `workers/lib/region-mask.py`, alebo `None` bez polygónu.

    Vracia TRI veci, lebo kraj sa pýta dvakrát a na dve rôzne otázky:
    `mask` je hrubá dlaždicová („má sa táto dlaždica vôbec zapísať?")
    a `rings` sú prstence kraja vo Web Mercatore pre `pixel_mask`
    („ktoré pixely v nej ležia v kraji?"). Obe sú z TOHO ISTÉHO polygónu.

    Modul má v mene pomlčku, takže `import` naň nefunguje – naťahuje sa cez
    `importlib` presne tak, ako to robí zvyšok pipeline (`load("rock_plan", …)`).
    """
    if not poly or not os.path.exists(poly):
        return None
    import importlib.util
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "lib", "region-mask.py")
    spec = importlib.util.spec_from_file_location("region_mask", lib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Prevod do Mercatoru je TU a nie v `region-mask.py`: vzorec projekcie je
    # v pipeline na jednom mieste (`merc_x`/`merc_y` o kus vyššie, tie isté,
    # ktorými sa počítajú okná dlaždíc). Druhá kópia by bola druhá pravda
    # o jednej projekcii – a rozišla by sa ticho, o pár metrov.
    rings = [([(merc_x(x), merc_y(y)) for x, y in ring], hole)
             for ring, hole in mod.rings_from_geojson(poly)]
    return mod, mod.mask_from_file(poly, bbox), rings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", required=True, help="vstupný DEM (.vrt/.tif)")
    ap.add_argument("--bbox", required=True, help="west,south,east,north")
    ap.add_argument("--poly", default="",
                    help="GeoJSON kraja – dlaždice mimo neho sa nekreslia "
                         "a v tých, čo prečnievajú, terén za hranicou "
                         "pokračuje okolím (žiadna stena)")
    ap.add_argument("--grow", type=float, default=0.5,
                    help="o koľko svojej strany smie dlaždica prečnievať za kraj")
    ap.add_argument("--edge", type=int, default=2,
                    help="koľko pixelov skutočného terénu ostáva ešte za "
                         "hranicou kraja, než sa začne pokračovanie okolím")
    ap.add_argument("--maxzoom", type=int, default=12)
    ap.add_argument("--minzoom", type=int, default=0)
    ap.add_argument("--out", required=True, help="adresár s dlaždicami {z}/{x}/{y}.png")
    ap.add_argument("--budget-mb", type=float, default=0,
                    help="koľko MB smú dlaždice zabrať (0 = bez stropu)")
    ap.add_argument("--keep-flat", action="store_true",
                    help="zapisovať aj dlaždice bez reliéfu (inak sa vynechajú "
                         "a klient si na ich mieste vezme rodiča)")
    args = ap.parse_args()

    w, s, e, n = (float(v) for v in args.bbox.split(","))
    lat = (s + n) / 2
    # OREZ NA KRAJ, A JE DVOJDIELNY. Bbox kraja je oveľa väčší než kraj sám (pri
    # Prešovskom 16 107 km² proti 10 184 km², teda 37 % mimo), takže bez tohto
    # sa tretina dlaždíc kreslila do susedných krajov a za hranicu – a práve
    # tam je DMR 5.0 prázdne, takže z nich boli biele dlaždice s rovnou hranou.
    #
    # 1. DLAŽDICOVÝ (`mask`): dlaždica, ktorá sa kraja ani nedotkne, nevznikne.
    # 2. PIXELOVÝ (`rings`): v tých, čo vzniknú, terén za hranicou kraja
    #    nepokračuje sám sebou, ale pokračovaním okolia (a dlaždica bez
    #    jediného pixela kraja sa nezapíše). Sám dlaždicový orez totiž hrubší
    #    byť nemôže, než je dlaždica – a tá je na nízkych zoomoch obrovská,
    #    takže tieňovanie za kraj
    #    PRESAHOVALO. Namerané na Prešovskom kraji, plocha vyrobených dlaždíc
    #    proti ploche kraja: z8 6,2×, z10 2,2×, z12 1,4×, z14 1,11×. To je ten
    #    „dvakrát väčší tieň než kraj", ktorý bolo v mape vidieť: mimo
    #    stiahnutého regiónu ho zakrýva až plocha `mimo` zo štýlu, takže
    #    stačilo, aby si vrstvu niekto pozrel bez nej (alebo v 3D pod iným
    #    uhlom), a reliéf pokračoval ďaleko za hranicu.
    maska = load_mask(args.poly, (w, s, e, n))
    rm, mask, rings = maska if maska else (None, None, None)
    if mask:
        print(f"Orez na kraj: v kraji je {mask.pct:.0f} % bboxu "
              f"(maska {mask.nx}×{mask.ny}); dlaždica smie prečnievať "
              f"{args.grow:g} svojej strany a za hranicou (+{args.edge} px "
              f"terénu) sa výška dopĺňa okolím, nie rovinou.", flush=True)
    else:
        print("::warning::Polygón kraja nie je – kreslí sa celý bbox regiónu, "
              "teda aj mimo kraj. (`--poly` nedostal súbor.)", flush=True)
    # Mriežka modelu sa ZMERIA z rastra, nie prevezme z `data/dem-sources.json`:
    # tam je hodnota zo zadania (`dmr5` je 5 m na región a 1 m na výrez) a to,
    # či sa prevzorkúva nahor alebo nadol, musí vyjsť z toho, čo naozaj leží
    # na disku. Keď sa raster nedá prečítať, ostáva `average` ako doteraz.
    cell_dx, cell_dy = dem_cell_metres(args.dem, lat)
    cell_m = max(cell_dx, cell_dy) if cell_dx and cell_dy else 0.0
    if cell_m:
        print(f"Mriežka modelu: {cell_dx:.1f} × {cell_dy:.1f} m "
              f"(rozhoduje {cell_m:.1f} m).", flush=True)
    else:
        print("::warning::Mriežka modelu sa nedá prečítať z "
              f"{args.dem} – prevzorkuje sa priemerom ako doteraz. "
              "Na maxzoome to môže dať mriežku v tieňovaní.", flush=True)

    total_bytes = 0
    total_tiles = 0
    skipped = 0
    rovin = 0
    cut_px = 0          # pixelov za hranicou kraja (výška z okolia)
    all_px = 0
    bez_modelu = 0      # dlaždíc, kde model nemá ANI JEDEN platný pixel
    made = args.minzoom - 1
    # Koľko z naplánovaných dlaždíc naozaj vzniklo. Rovina ostáva rovinou aj
    # o zoom vyššie, takže je to jediný podložený odhad toho, koľko ich
    # v ďalšom zoome pribudne – a rozpočet sa počíta z neho, nie z plánu.
    kept_ratio = 1.0

    # ---------- plán ----------
    # Každý zoom navyše je ŠTVORNÁSOBOK dlaždíc, takže rozdiel medzi z13
    # a z15 nie je „o kúsok viac", ale šestnásťnásobok. Bez tohto výpisu to
    # bolo vidieť až podľa toho, že job bežal hodinu a stránka sa nezmestila
    # do rozpočtu – teda po celej práci.
    plan = []
    for z in range(args.minzoom, args.maxzoom + 1):
        x0, x1, y0, y1 = tile_range(z, w, s, e, n)
        vsetkych = (x1 - x0 + 1) * (y1 - y0 + 1)
        if mask:
            v_kraji = sum(1 for tx in range(x0, x1 + 1) for ty in range(y0, y1 + 1)
                          if rm.tile_touches(mask, z, tx, ty, args.grow))
        else:
            v_kraji = vsetkych
        plan.append((z, v_kraji, vsetkych))
    mimo = sum(v - k for _, k, v in plan)
    print("Plán: " + ", ".join(f"z{z} {k} dl." for z, k, _ in plan)
          + f"  (spolu {sum(k for _, k, _ in plan)} dlaždíc"
          + (f", {mimo} mimo kraja sa vynechá" if mimo else "")
          + ")"
          + (f", strop {args.budget_mb:.0f} MB" if args.budget_mb else ""),
          flush=True)
    # Ako sa bude na každom zoome počítať – nech je to vidieť PRED prácou
    # a nie až podľa toho, ako výsledok vyzerá (pravidlo 4).
    print("Prevzorkovanie a zvislý krok: " + ", ".join(
        f"z{z} {tile_m_per_px(z, lat):.1f} m/px "
        f"{resampling(tile_m_per_px(z, lat), cell_m)}"
        f" 1/{2 ** frac_bits(tile_m_per_px(z, lat))} m"
        for z, _, _ in plan), flush=True)

    for z in range(args.minzoom, args.maxzoom + 1):
        x0, x1, y0, y1 = tile_range(z, w, s, e, n)
        px_m = tile_m_per_px(z, lat)
        bits = frac_bits(px_m)
        resample = resampling(px_m, cell_m)
        # ---------- strop veľkosti ----------
        # Odhad na ďalší zoom sa NEBERIE z konštanty, ale z toho, čo práve
        # vyšlo o zoom nižšie: dlaždica z toho istého územia a modelu má na
        # každom zoome podobnú veľkosť. Zoom, ktorý by sa nezmestil, sa preto
        # ani nezačne počítať – inak by sa hodina práce vyhodila.
        if args.budget_mb and total_tiles:
            per_tile = total_bytes / total_tiles
            want = next(k for zz, k, _ in plan if zz == z) * kept_ratio * per_tile
            if (total_bytes + want) / 1048576 > args.budget_mb:
                print(f"::warning::Výškové dlaždice končia na z{made}: z{z} by "
                      f"pridal ~{want / 1048576:.0f} MB a rozpočet na "
                      f"tieňovanie je {args.budget_mb:.0f} MB. Pre jemnejší "
                      f"reliéf zmenši územie (input `area`, voľba "
                      f"`crop_bbox`), alebo zdvihni `size_limit_mb` "
                      f"či podiel BUDGET_TERRAIN_PCT.")
                break
        size = 2 * ORIGIN / (2**z)
        nx, ny = x1 - x0 + 1, y1 - y0 + 1
        skipped_before = skipped
        rovin_before = rovin
        bez_modelu_before = bez_modelu
        zapisanych = 0

        # Po pásoch, nech pamäť nerastie s veľkosťou územia.
        rows_per_strip = max(1, 512 // max(1, nx))
        zbytes = 0
        for ry in range(y0, y1 + 1, rows_per_strip):
            ry_end = min(ry + rows_per_strip - 1, y1)
            minx = -ORIGIN + x0 * size
            maxx = -ORIGIN + (x1 + 1) * size
            maxy = ORIGIN - ry * size
            miny = ORIGIN - (ry_end + 1) * size
            width = nx * TILE
            height = (ry_end - ry + 1) * TILE
            warp_level(args.dem, "/tmp/level.raw", minx, miny, maxx, maxy,
                       width, height, resample)
            grid = np.fromfile("/tmp/level.raw", dtype="<f4").reshape(height, width)
            # DVE RÔZNE OTÁZKY NAD JEDNOU MRIEŽKOU, A V TOMTO PORADÍ:
            # najprv „kde model dáta NEMÁ" (doplní sa okolím), až potom „kde
            # sme za hranicou kraja" (tam terén pokračuje `pokracuj_okolim`).
            # Obe odpovede sú dnes pokračovanie okolia, ale nie tým istým
            # priechodom: diera V MODELI má dve strany a patrí do nej priamka
            # medzi nimi, kým za hranicou kraja niet čo pretínať a treba
            # hladké dopĺňanie po pyramíde. Opačne by navyše výplň modelu
            # roznášala dovnútra kraja to, čo sme si vymysleli za hranicou.
            #
            # KDE MODEL NIE JE, SA NEVYMÝŠĽA VÝŠKA. `-dstnodata` je preto
            # sentinel mimo rozsahu skutočných výšok, nie nula: nula je platná
            # výška a v terrariu sa od chýbajúcej hodnoty neodlíši. Kým ňou
            # bola, robila na hranici modelu stenu – namerané na publikovanom
            # `bratislavsky_test4-terrain.pmtiles` 668 m na 407 m/px, čiže
            # sklon 59°, a za ňou plochu bez tieňovania (z5 mala 99,6 %
            # dlaždice presne 0 m). Maska sa drží zvlášť: doplnená mriežka sa
            # už od skutočnej nedá odlíšiť, a pritom treba vedieť, ktorá
            # dlaždica nemá ani jeden platný pixel.
            chyba = grid <= NODATA + 1.0
            grid = vypln_nodata(grid, chyba)

            # MIMO KRAJA SA TERÉN NEZROVNÁ, ALE POKRAČUJE. Rovina (výška 0)
            # tam robila zvislú stenu po celom obvode regiónu – najsilnejší
            # sklon, aký v dlaždici môže byť (namerané 89,4° proti 17,9°,
            # ktoré má terén sám), a v 3D doslova múr. Pokračovanie okolím
            # nepridá sklon, ktorý by terén nemal (najväčší za hranicou 30,6°
            # proti 17,9°, ktoré má terén sám, a stredný 7,0° proti 8,0°),
            # a von z regiónu pomaly slabne.
            #
            # `--edge` PIXELOV SKUTOČNÉHO TERÉNU sa nechá ešte za hranicou:
            # hillshade počíta zo susedných pixelov a klient si dlaždicu ešte
            # prevzorkuje, takže tieňovanie NA hranici má stáť na okolí a nie
            # na pokračovaní.
            #
            # `chyba` sa tým NEMENÍ: ostáva otázkou o MODELI (podľa nej sa
            # nižšie zahodí dlaždica, o ktorej model nič nehovorí). Orez na
            # kraj do nej nepatrí – pixel za hranicou model má, len ho
            # nechceme ukázať.
            keep = None
            if rings is not None:
                keep = rm.pixel_mask(rings, (minx, miny, maxx, maxy),
                                     width, height, grow=args.edge)
                cut_px += int(keep.size - keep.sum())
                all_px += keep.size
                if keep.any() and not chyba.all():
                    grid = pokracuj_okolim(grid, keep, SLOPE_EPS * px_m)

            for ty in range(ry, ry_end + 1):
                for tx in range(x0, x1 + 1):
                    # MIMO KRAJA SA NEZAPISUJE. Kontroluje sa tu a nie pred
                    # warpom zámerne: warp beží na celý pás naraz a v tom páse
                    # sú aj dlaždice v kraji, takže sa celý vynechať nedá.
                    # Ušetrí sa zápis, veľkosť stránky a hlavne biele dlaždice
                    # z prázdneho DEM za hranicou.
                    if mask and not rm.tile_touches(mask, z, tx, ty, args.grow):
                        skipped += 1
                        continue
                    # A TO ISTÉ PRESNE, PO PIXELOCH: dlaždica, v ktorej nie je
                    # ani jeden pixel kraja (ani v rezerve `--edge`), neukáže
                    # nikomu nič – v mape ju celú prekrýva plocha `mimo`.
                    # Predtým to isté robila rovina cez `je_rovina`: celá
                    # dlaždica mimo = samá nula = vynechaná. Odkedy sa terén za
                    # hranicou nezrovnáva, ale pokračuje, rovina tam nie je –
                    # tak sa to pýta priamo masky. Bez tohto by pokračovanie
                    # rástlo do dlaždíc, ktoré s krajom nemajú spoločné nič.
                    if keep is not None and not keep[
                            (ty - ry) * TILE:(ty - ry + 1) * TILE,
                            (tx - x0) * TILE:(tx - x0 + 1) * TILE].any():
                        skipped += 1
                        continue
                    # DLAŽDICA BEZ JEDINÉHO PLATNÉHO PIXELA SA NEZAPÍŠE, a to
                    # ani na minzoome. Nie je to rovina – je to územie, o ktorom
                    # model nič nehovorí, a zapísať doň čokoľvek znamená tvrdiť,
                    # že tam terén je (pravidlo 2: rozsah je sľub). Kým sa
                    # nodata kódovala ako nula, vznikala z nej hladina mora –
                    # v archíve teda ležali dlaždice na pol Európy a hlavička
                    # `.pmtiles` sa nimi vykázala ako rozsah tieňovania.
                    if chyba[(ty - ry) * TILE:(ty - ry + 1) * TILE,
                             (tx - x0) * TILE:(tx - x0 + 1) * TILE].all():
                        bez_modelu += 1
                        continue
                    # Kóduje sa PO DLAŽDICIACH, nie celý pás naraz: pás má na
                    # z15 aj 33 miliónov pixelov a medzikroky kódovania by
                    # z neho spravili stovky MB v pamäti. Takto je v pamäti
                    # naraz jedna dlaždica.
                    vysky = grid[
                        (ty - ry) * TILE : (ty - ry + 1) * TILE,
                        (tx - x0) * TILE : (tx - x0 + 1) * TILE,
                    ]
                    # ROVINA SA NEZAPISUJE, a nie je to diera v mape: keď
                    # dlaždica chýba, MapLibre siahne po rodičovi o zoom nižšie
                    # (`TerrainSourceCache.getSourceTile` ho hľadá až po
                    # minzoom, a v 3D ho `SourceCache.update` dosadí rovno).
                    # Na rovine je rodič to isté, čo by tu vzniklo – len sa zaň
                    # neplatí štvornásobkom dlaždíc na každom ďalšom zoome.
                    # Minzoom sa nevynecháva NIKDY: je to koreň tej pyramídy,
                    # po ktorom sa rodič hľadá.
                    if (not args.keep_flat and z > args.minzoom
                            and je_rovina(vysky, px_m)):
                        rovin += 1
                        continue
                    d = os.path.join(args.out, str(z), str(tx))
                    os.makedirs(d, exist_ok=True)
                    data = png_rgb(terrarium(vysky, bits))
                    with open(os.path.join(d, f"{ty}.png"), "wb") as f:
                        f.write(data)
                    zbytes += len(data)
                    total_tiles += 1
                    zapisanych += 1
        total_bytes += zbytes
        made = z
        v_plane = next(k for zz, k, _ in plan if zz == z)
        # Zoom, ktorý nezapísal nič, si podiel NEPREPÍŠE na nulu: z nuly by
        # vyšiel nulový odhad na ďalší zoom a rozpočet by prestal brzdiť čokoľvek.
        if v_plane and zapisanych:
            kept_ratio = zapisanych / v_plane
        print(f"z{z}: {nx}×{ny} dlaždíc, {zapisanych} zapísaných, "
              f"{zbytes / 1048576:.1f} MB ({resample}, krok 1/{2 ** bits} m)"
              + (f", mimo kraja {skipped - skipped_before}"
                 if mask and skipped > skipped_before else "")
              + (f", bez reliéfu {rovin - rovin_before}"
                 if rovin > rovin_before else "")
              + (f", bez modelu {bez_modelu - bez_modelu_before}"
                 if bez_modelu > bez_modelu_before else ""), flush=True)

    # PRÁZDNA VRSTVA MUSÍ SPADNÚŤ, NIE ZAZELENAŤ. Odkedy sa orezáva na kraj,
    # sa dá vyrobiť nula dlaždíc aj z behu, ktorý prebehol celý: keď výrez
    # (`crop_bbox`, štvorec rýchleho testu – ten sa berie zo STREDU bboxu,
    # takže pri členitom kraji môže padnúť mimo neho) neleží v kraji, nemá ani
    # jedna dlaždica pixel kraja a všetky sa vynechajú. Bez tejto vetvy by
    # z toho bol prázdny `.pmtiles`, zelený beh a mapa bez tieňovania
    # (pravidlo 8).
    if made < args.minzoom or not total_tiles:
        print("::error::Nevznikla ani jedna dlaždica tieňovania."
              + (" Výrez behu neleží v kraji, takže v ňom nie je čo "
                 "kresliť – posuň ho dovnútra (`test_at`, `crop_bbox`), "
                 "alebo skontroluj, či je "
                 f"`{args.poly}` naozaj polygónom tohto regiónu."
                 if rings is not None else ""),
              file=sys.stderr)
        return 1
    # Skutočne vyrobený maxzoom, nie ten želaný. Píše ho ten, kto dlaždice
    # naozaj vyrobil – meno assetu v sklade aj štýl si ho odtiaľto berú, takže
    # sa nemá ako stať, že mapa pýta z15 a na Pages je z13.
    with open(os.path.join(args.out, "maxzoom.txt"), "w") as f:
        f.write(f"{made}\n")
    if all_px:
        print(f"Za hranicou kraja bolo {100 * cut_px / all_px:.0f} % "
              f"pixelov – tam výška pokračuje okolím, takže hranica nie je "
              f"stena a tieňovanie za ňou slabne.")
    print(f"Spolu: {total_tiles} dlaždíc, {total_bytes / 1048576:.1f} MB, "
          f"maxzoom z{made}"
          + (f"; mimo kraja vynechaných {skipped} dlaždíc "
             f"({100 * skipped / (total_tiles + skipped):.0f} %)"
             if skipped else "")
          + (f"; bez reliéfu vynechaných {rovin} dlaždíc "
             f"({100 * rovin / (total_tiles + rovin):.0f} %) – na ich mieste "
             f"kreslí klient rodiča"
             if rovin else "")
          + (f"; bez modelu vynechaných {bez_modelu} dlaždíc – tam výškový "
             f"model nemá dáta, takže sa tam tieňovanie nekreslí"
             if bez_modelu else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
