#!/usr/bin/env python3
"""DEM → dlaždice `raster-dem` (terrarium) pre tieňovanie a 3D terén.

MapLibre nevie čítať výšky z GeoTIFFu a verejné AWS Terrain Tiles sú povrchový
model, tak sa dlaždice robia z toho istého DEM ako zvyšok pipeline.

    výška [m] = (R * 256 + G + B / 256) − 32768

Zvislý krok sa riadi vodorovným pixelom (`SLOPE_EPS × pixel`, plus rezerva
`FRAC_BITS_MARGIN`) – hrubý krok robí z terénu plošinky a hillshade z ich hrán
mriežku. Resampling volí `resampling()` podľa pomeru pixela a bunky.

Za hranicou kraja sa výška dopĺňa okolím (`pokracuj_okolim`), nie rovinou:
rovina tam robila zvislú stenu. Dlaždica bez jediného pixela kraja sa nezapíše.

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
# aritmetika nad mriežkou a zoomom leží v `lib/cell.py`; `lint/terrain.py` ju
# musí vedieť spustiť a lintovací job nemá numpy
from cell import (SLOPE_EPS, dem_cell_metres, frac_bits,  # noqa: E402
                  resampling, tile_m_per_px)
# práca nad mriežkou výšok leží vo `vyska.py`; tu je plán, warp a kódovanie
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


# minimálny zapisovač PNG: Pillow tu nie je, stačí zlib a pár hlavičiek.
# Filtre sa skúšajú všetky, berie sa riadok s najmenším súčtom odchýlok.
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

    Zaokrúhľuje sa na krok, nereže sa maskou: maskovanie je `floor` a posun
    o celý krok by na hranici zoomov spravil schod.
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
    """Nie je v tejto dlaždici čo tieňovať? (nikde sklon nad `SLOPE_EPS`)"""
    if vysky.shape[0] < 2 or vysky.shape[1] < 2:
        return False
    strop = SLOPE_EPS * px_m
    return (float(np.abs(np.diff(vysky, axis=1)).max()) <= strop
            and float(np.abs(np.diff(vysky, axis=0)).max()) <= strop)


def warp_level(dem, path, minx, miny, maxx, maxy, width, height, resample):
    """Prevzorkuje DEM do mriežky zarovnanej na dlaždice daného zoomu.

    `Float32`, nie `Int16`: zlomok výšky musí prežiť až po kódovanie.
    `-dstnodata` je sentinel, nie nula – nula znamenala hladinu mora a na
    hranici modelu robila stenu.
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

    Tri veci: `mask` je hrubá dlaždicová (zapísať dlaždicu?), `rings` sú
    prstence v Mercatore pre `pixel_mask` (ktoré pixely ležia v kraji).
    """
    if not poly or not os.path.exists(poly):
        return None
    import importlib.util
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "lib", "region-mask.py")
    spec = importlib.util.spec_from_file_location("region_mask", lib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # prevod do Mercatoru je tu, nie v `region-mask.py`: vzorec má byť na jednom mieste
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
    # orez na kraj je dvojdielny: dlaždicový (`mask`) vyhodí dlaždice, čo sa
    # kraja ani nedotknú, pixelový (`rings`) rieši zvyšok – dlaždica je na
    # nízkych zoomoch obrovská, takže sám dlaždicový orez presahoval za kraj
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
    # mriežka sa zmeria z rastra, nie prevezme z číselníka; bez merania `average`
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
    # koľko z plánu naozaj vzniklo – z toho sa počíta rozpočet na ďalší zoom
    kept_ratio = 1.0

    # každý zoom navyše je štvornásobok dlaždíc; nech je plán vidieť dopredu
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
    # ako sa bude počítať – vidieť pred prácou, nie až podľa výsledku
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
        # strop veľkosti: odhad na ďalší zoom z toho, čo vyšlo o zoom nižšie
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
            # najprv „kde model dáta nemá" (výplň priamkou medzi stranami
            # diery), až potom „kde sme za hranicou kraja" (hladké dopĺňanie
            # po pyramíde). Opačne by výplň modelu roznášala vymyslené výšky
            # dovnútra kraja. `chyba` sa drží zvlášť – doplnená mriežka sa už
            # od skutočnej nedá odlíšiť.
            chyba = grid <= NODATA + 1.0
            grid = vypln_nodata(grid, chyba)

            # mimo kraja terén pokračuje okolím, nezrovnáva sa: rovina tam
            # robila zvislú stenu po obvode regiónu. `--edge` pixelov
            # skutočného terénu ostáva za hranicou, nech tieňovanie NA hranici
            # stojí na okolí. `chyba` sa tým nemení – to je otázka o modeli.
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
                    # kontroluje sa tu a nie pred warpom: warp beží na celý pás
                    if mask and not rm.tile_touches(mask, z, tx, ty, args.grow):
                        skipped += 1
                        continue
                    # to isté po pixeloch: dlaždicu bez pixela kraja prekryje
                    # v mape plocha `mimo`, tak sa nezapisuje
                    if keep is not None and not keep[
                            (ty - ry) * TILE:(ty - ry + 1) * TILE,
                            (tx - x0) * TILE:(tx - x0 + 1) * TILE].any():
                        skipped += 1
                        continue
                    # dlaždica bez platného pixela nie je rovina, ale územie,
                    # o ktorom model nič nehovorí – nezapisuje sa ani na minzoome
                    if chyba[(ty - ry) * TILE:(ty - ry + 1) * TILE,
                             (tx - x0) * TILE:(tx - x0 + 1) * TILE].all():
                        bez_modelu += 1
                        continue
                    # po dlaždiciach, nie celý pás: pás má na z15 33 M pixelov
                    vysky = grid[
                        (ty - ry) * TILE : (ty - ry + 1) * TILE,
                        (tx - x0) * TILE : (tx - x0 + 1) * TILE,
                    ]
                    # rovina sa nezapisuje; MapLibre siahne po rodičovi o zoom
                    # nižšie a na rovine je to isté. Minzoom nikdy – je to koreň.
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
        # zoom bez zápisu si podiel neprepíše na nulu, brzda by prestala brzdiť
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

    # prázdna vrstva musí spadnúť, nie zazelenať: výrez môže padnúť mimo kraja
    if made < args.minzoom or not total_tiles:
        print("::error::Nevznikla ani jedna dlaždica tieňovania."
              + (" Výrez behu neleží v kraji, takže v ňom nie je čo "
                 "kresliť – posuň ho dovnútra (`test_at`, `crop_bbox`), "
                 "alebo skontroluj, či je "
                 f"`{args.poly}` naozaj polygónom tohto regiónu."
                 if rings is not None else ""),
              file=sys.stderr)
        return 1
    # skutočne vyrobený maxzoom, nie želaný – berie si ho asset aj štýl
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
