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

Preto sa orezáva aj PO PIXELOCH: čo v dlaždici padne mimo kraj, dostane rovinu
(`region-mask.pixel_mask`). Hillshade kreslí krytím podľa SKLONU, takže
z roviny nenakreslí nič, a 3D terén z nej spraví rovnú plochu – mapa tak končí
tam, kde končí región. Po zmene je pokrytie na každom zoome 1,0–1,07× plochy
kraja (zvyšok je rezerva `--edge`). Dlaždíc je pri tom MENEJ, nie viac: tie
celé mimo kraja sú po vynulovaní rovina a `je_rovina` ich vynechá – na skúšobnom
behu nad bboxom Prešovského kraja (umelý DEM s reliéfom všade, do z11) ich bolo
144 namiesto 172 a 3,5 MB namiesto 4,8 MB.

Rovina je výška 0 – ale POZOR, to už NIE JE to isté, čo dáva `gdalwarp` za
okrajom modelu. Boli to dve odpovede pod jednou hodnotou: „sme za hranicou
kraja" je rozhodnutie, ktoré robíme my a vieme ho posunúť `--edge`-om tam, kde
ho maska schová, kým „model tu nemá dáta" je fakt o modeli a stenu si bral aj
DOVNÚTRA kraja, kde ju neschová nič. `-dstnodata` je preto sentinel `NODATA`
a chýbajúce hodnoty dopĺňa `vypln_nodata` okolím; nula ostala len orezaniu na
kraj.

Hrana medzi terénom a rovinou je pre hillshade zvislá stena, takže NESMIE
stáť presne na hranici kraja – bol by z nej svetlý či tmavý prstenec po jej
vnútornej strane, čiže v mape. `--edge` ju posunie pár pixelov ZA hranicu,
kde ju prekrýva plocha `mimo`.

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


# Hodnota, ktorou `gdalwarp` označí „tu model nie je". Musí byť mimo
# rozsahu skutočných výšok (Zem má −430 m až 8849 m) a NESMIE to byť 0:
# nula je platná výška a v terrariu sa nedá odlíšiť od chýbajúcej hodnoty.
NODATA = -9999.0


def vypln_nodata(grid, chyba):
    """Chýbajúce výšky doplní NAJBLIŽŠOU platnou, nie konštantou.

    PREČO VÔBEC NIEČO. Terrarium je RGB a nemá podobu „hodnota tu nie je" –
    do dlaždice sa teda niečo zapísať MUSÍ. Otázka je len čo, a sú dve
    možnosti: konštanta, alebo okolie.

    KONŠTANTA ROBÍ STENU. Tá stena je presne to, čo bolo v mape vidieť ako
    „divný orez": na hranici modelu spadne výška zo 600 m na konštantu, čo je
    pre hillshade (derivácia výšky) zvislý útes, a nakreslí sa ako ostrá
    čiara cez celú mapu. Za ňou je rovina, teda plocha BEZ tieňovania.

    OKOLIE ŽIADNU NEROBÍ: výška za hranicou plynulo pokračuje tou, ktorá je
    na hranici. Nie je to vymyslený terén – je to jediný spôsob, ako povedať
    „ďalej nevieme" bez toho, aby z toho hillshade nakreslil útvar. Presne to
    isté robí `gdal_fillnodata`; tu je to štyrmi priechodmi indexov (O(n)),
    lebo GDAL by kvôli tomu musel súbor prepísať.

    `chyba` je maska „tu nie je hodnota". Vracia doplnenú mriežku; keď nie je
    z čoho dopĺňať (celý pás je bez dát), vracia ju nezmenenú.
    """
    if not chyba.any() or chyba.all():
        return grid
    g = grid
    plati = ~chyba
    # NAJPRV PO RIADKOCH, POTOM PO STĹPCOCH – nie obe osi naraz a to bližšie
    # z nich. Pixel v rohu, ďaleko od okna s dátami, nemá platného suseda ani
    # vo svojom riadku, ani vo svojom stĺpci, takže by z takého porovnania
    # vyšiel nedoplnený – a v dlaždici by ostal sentinel, čiže −9999 m vedľa
    # 600 m: stena stokrát vyššia než tá, ktorú to má odstrániť. Po riadkovom
    # priechode už každý stĺpec, ktorý dáta pretínajú, platné hodnoty MÁ,
    # takže ich stĺpcový priechod roznesie do zvyšku.
    for axis in (1, 0):
        n = g.shape[axis]
        tvar = [1, 1]
        tvar[axis] = n
        idx = np.broadcast_to(np.arange(n).reshape(tvar), g.shape)
        dopredu = np.maximum.accumulate(np.where(plati, idx, -1), axis=axis)
        spat = np.flip(np.minimum.accumulate(
            np.flip(np.where(plati, idx, n), axis=axis), axis=axis), axis=axis)
        d_dop = np.where(dopredu < 0, n + 1, idx - dopredu)
        d_spat = np.where(spat >= n, n + 1, spat - idx)
        v_dop = np.take_along_axis(g, dopredu.clip(0, n - 1), axis)
        v_spat = np.take_along_axis(g, spat.clip(0, n - 1), axis)
        je_dop, je_spat = d_dop <= n, d_spat <= n
        # KEĎ SÚ PLATNÉ OBE STRANY, PRECHÁDZA SA MEDZI NIMI LINEÁRNE, nie
        # skokom na tú bližšiu. Pri diere V MODELI (nie za jeho okrajom) sa
        # totiž výplne z oboch strán stretnú v jej strede a „tá bližšia" tam
        # spraví šev – teda opäť stenu, len menšiu. Namerané na 70 px diere
        # medzi svahmi, ktoré sa líšia o ~300 m: skokom 298 m (36°),
        # lineárne 0 m. Za okrajom modelu je platná len jedna strana, takže
        # tam z toho vyjde presne to isté, čo predtým – rovné pokračovanie.
        sucet = np.where(je_dop, d_dop, 0) + np.where(je_spat, d_spat, 0)
        podiel = np.divide(np.where(je_spat, d_spat, 0), np.maximum(sucet, 1),
                           dtype=np.float64)
        oboje = je_dop & je_spat
        hodnota = np.where(oboje, v_dop * podiel + v_spat * (1.0 - podiel),
                           np.where(je_dop, v_dop, v_spat))
        naslo = je_dop | je_spat
        g = np.where(plati, g, np.where(naslo, hodnota.astype(g.dtype), g))
        plati = plati | naslo
    return g


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
                         "a v tých, čo prečnievajú, je mimo kraja rovina")
    ap.add_argument("--grow", type=float, default=0.5,
                    help="o koľko svojej strany smie dlaždica prečnievať za kraj")
    ap.add_argument("--edge", type=int, default=2,
                    help="o koľko pixelov presahuje rovina za hranicu kraja")
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
    # 2. PIXELOVÝ (`rings`): v tých, čo vzniknú, dostane všetko mimo kraja
    #    rovinu. Sám dlaždicový orez totiž hrubší byť nemôže, než je dlaždica –
    #    a tá je na nízkych zoomoch obrovská, takže tieňovanie za kraj
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
              f"{args.grow:g} svojej strany a mimo kraja "
              f"(+{args.edge} px) je rovina.", flush=True)
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
    cut_px = 0          # pixelov mimo kraja, ktoré dostali rovinu
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
            # najprv „kde model dáta NEMÁ" (doplní sa okolím), až potom
            # „kde sme za hranicou kraja" (zrovná sa na rovinu). Opačne by
            # výplň roznášala nuly z orezania ďalej do kraja.
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

            # MIMO KRAJA JE ROVINA. Hillshade kreslí krytím podľa SKLONU,
            # takže z roviny nenakreslí nič – tým sa tieňovanie zastaví na
            # hranici kraja aj vnútri dlaždice, ktorá cez ňu prečnieva.
            #
            # NULA JE TU INÁ ODPOVEĎ NEŽ NODATA, a je to zámer: „sme za
            # hranicou kraja" je rozhodnutie, ktoré robíme my, kým „model tu
            # nemá dáta" je fakt o modeli. Kým bola nodata tiež nula, boli to
            # dve odpovede pod jednou hodnotou a tá druhá si brala stenu aj
            # dovnútra kraja, kde ju maska neschová.
            #
            # `--edge` PIXELOV ZA HRANICU. Hrana medzi terénom a rovinou je pre
            # hillshade zvislá stena, čiže najsilnejší sklon v dlaždici; keby
            # stála presne na hranici kraja, bol by z nej svetlý či tmavý
            # prstenec po jej vnútornej strane. S rezervou padne za hranicu,
            # kde ju v štýle prekrýva plocha `mimo` (`deploy/region-mask.py`).
            if rings is not None:
                keep = rm.pixel_mask(rings, (minx, miny, maxx, maxy),
                                     width, height, grow=args.edge)
                cut_px += int(keep.size - keep.sum())
                all_px += keep.size
                grid[~keep] = 0.0
                # Zrovnané na rovinu je odpoveď, nie chýbajúce dáta – inak by
                # sa dlaždica tesne za hranicou zahodila ako „bez modelu"
                # a hillshade by pod ňou siahol po rodičovi s terénom.
                chyba = chyba & keep

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

    # PRÁZDNA VRSTVA MUSÍ SPADNÚŤ, NIE ZAZELENAŤ. Odkedy je mimo kraja rovina,
    # sa dá vyrobiť nula dlaždíc aj z behu, ktorý prebehol celý: keď výrez
    # (`crop_bbox`, štvorec rýchleho testu – ten sa berie zo STREDU bboxu,
    # takže pri členitom kraji môže padnúť mimo neho) neleží v kraji, je celý
    # rovina a `je_rovina` ju vynechá. Bez tejto vetvy by z toho bol prázdny
    # `.pmtiles`, zelený beh a mapa bez tieňovania (pravidlo 8).
    if made < args.minzoom or not total_tiles:
        print("::error::Nevznikla ani jedna dlaždica tieňovania."
              + (" Výrez behu neleží v kraji, takže je celý rovina – posuň ho "
                 "dovnútra (`test_at`, `crop_bbox`), alebo skontroluj, či je "
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
        print(f"Mimo kraja dostalo rovinu {100 * cut_px / all_px:.0f} % "
              f"pixelov – práve tam tieňovanie presahovalo za hranicu.")
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
