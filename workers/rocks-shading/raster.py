#!/usr/bin/env python3
"""Skaly z tieňovania, 2/3: z dlaždíc raster tmavosti.

Mozaika dlaždíc → pole „ako tmavé je to tu oproti okoliu": pásové čítanie,
pole osvetlenia na zmenšenej mriežke, prahy a zápis rastra po pásoch.
Spúšťa sa ako modul: `load("shading_raster", "raster.py")`.
"""
import importlib.util
import math
import os
import sys
import time

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# mriežka, run() a Heartbeat sú zo spodnej vrstvy
tiles = load("shading_tiles", "tiles.py")
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
run = tiles.run
tile_res, ground_res = tiles.tile_res, tiles.ground_res

# watch.py je spoločný pre oba druhy skál, preto vo workers/lib/
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb, Heartbeat  # noqa: E402

# zmenšenie, na ktorom sa počíta pole osvetlenia – je to hladká funkcia
BG_DOWN = 8


# raster

def block_mean(gray, k, chunk_rows=4096):
    """Priemer v blokoch k×k → k-krát menší obraz vo float32.

    Po pásoch riadkov, nech float medzivýsledok nie je veľký ako celý pás.
    """
    h, w = gray.shape
    h2, w2 = h // k, w // k
    out = np.empty((h2, w2), np.float32)
    step = max(1, (chunk_rows // k)) * k
    for r in range(0, h2 * k, step):
        r1 = min(r + step, h2 * k)
        blk = gray[r:r1, :w2 * k].reshape((r1 - r) // k, k, w2, k)
        out[r // k:r1 // k] = blk.mean(axis=(1, 3), dtype=np.float32)
    return out


def box_mean(a, r):
    """Priemer v okne (2r+1)² cez integrálny obraz; okraje sa doplnia hranou."""
    if r <= 0:
        return a.astype(np.float32)
    h, w = a.shape
    r = min(r, max(h, w))
    pad = np.pad(a.astype(np.float64), ((r, r), (r, r)), mode="edge")
    ii = np.zeros((pad.shape[0] + 1, pad.shape[1] + 1), np.float64)
    np.cumsum(np.cumsum(pad, axis=0), axis=1, out=ii[1:, 1:])
    win = 2 * r + 1
    s = (ii[win:win + h, win:win + w] - ii[0:h, win:win + w]
         - ii[win:win + h, 0:w] + ii[0:h, 0:w])
    return (s / (win * win)).astype(np.float32)


def box_blur_u8(a, r):
    """Priemer v malom okne priamo na šedej – zmaže zrno JPEGu.

    Inak by izolínia okolo prahu vyrábala tisíce odrobiniek.
    """
    if r <= 0:
        return a
    h, w = a.shape
    ap = np.pad(a, r, mode="edge")
    acc = np.zeros((h, w), np.uint16)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            acc += ap[dy:dy + h, dx:dx + w]
    acc //= (2 * r + 1) ** 2
    return acc.astype(np.uint8)


def load_band(fetcher, z, x0, x1, ty0, ty1, every=30):
    """Dlaždicové riadky [ty0, ty1) ako jeden obraz odtieňov šedej.

    Chýbajúca dlaždica ostane 255 (svetlá), nie 0 – nula by bola najtmavšie
    miesto mozaiky. Dekódovanie JPEGov je najdlhšia tichá časť behu, preto
    sa hlási dlaždicový riadok.
    """
    w = (x1 - x0) * TILE
    h = (ty1 - ty0) * TILE
    band = np.full((h, w), 255, np.uint8)
    t0 = last = time.time()
    n = 0
    for ty in range(ty0, ty1):
        now = time.time()
        if every and now - last >= every:
            last = now
            hotovo = ty - ty0
            eta = (now - t0) / max(1, hotovo) * (ty1 - ty - 0) if hotovo else 0
            print(f"  … dekódovanie: riadok {hotovo + 1}/{ty1 - ty0}, "
                  f"{n} dlaždíc, beží {hms(now - t0)}"
                  + (f", ostáva {hms(eta)}" if hotovo else ""), flush=True)
        for tx in range(x0, x1):
            n += 1
            p = fetcher.path(z, tx, ty)
            try:
                if not os.path.exists(p) or os.path.getsize(p) == 0:
                    continue
                with Image.open(p) as im:
                    a = np.asarray(im.convert("L"), np.uint8)
            except Exception:
                continue
            if a.shape != (TILE, TILE):
                continue
            ry, rx = (ty - ty0) * TILE, (tx - x0) * TILE
            band[ry:ry + TILE, rx:rx + TILE] = a
    return band


def upsample(small, h, w, k=BG_DOWN):
    """Zmenšené pole späť na plné rozlíšenie; okraj sa doplní hranou."""
    full = np.repeat(np.repeat(small, k, axis=0), k, axis=1)
    if full.shape[0] < h or full.shape[1] < w:
        full = np.pad(full, ((0, max(0, h - full.shape[0])),
                             (0, max(0, w - full.shape[1]))), mode="edge")
    return full[:h, :w]


def bright_background(small, r):
    """Ako svetlý je tu osvetlený terén – priemer svetlejšej polovice okna.

    Obyčajný priemer by si veľká tmavá plocha stiahla k sebe a našiel by sa
    len jej okraj; druhý prechod počíta len z pixelov nad hrubým priemerom.
    """
    m1 = box_mean(small, r)
    lit = (small >= m1).astype(np.float32)
    s = box_mean(small * lit, r)
    c = box_mean(lit, r)
    return np.where(c > 0.05, s / np.maximum(c, 1e-6), m1).astype(np.float32)


def _rank_box(a, r, ufunc):
    """Bežiace min/max v okne (2r+1)² – separovateľne, po osiach."""
    if r <= 0:
        return a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        ap = np.pad(a, pad, mode="edge")
        acc = None
        for d in range(2 * r + 1):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(d, d + a.shape[axis])
            v = ap[tuple(sl)]
            acc = v if acc is None else ufunc(acc, v)
        a = acc
    return a


def open_mask(score, r):
    """Morfologické otvorenie masky tmavosti: erózia, potom dilatácia.

    Prah nájde aj hustú sieť vlásočnicových rýh, z ktorej je pri nízkom zoome
    rovnomerná sivá deka. Erózia zmaže všetko užšie než 2r+1, dilatácia vráti
    prežitým jadrám rozsah – triedi sa teda podľa šírky, nie plochy.
    Polomer je v metroch na zemi (`--open`), rovnako na každom zoome.
    """
    if r <= 0:
        return score
    keep = (score > 0).astype(np.uint8)
    keep = _rank_box(keep, r, np.minimum)   # erózia
    keep = _rank_box(keep, r, np.maximum)   # dilatácia
    score = score.copy()
    score[keep == 0] = 0
    return score


def score_band(gray, dark, always, local_px, rel, blur, fill_px=0, every=0,
               open_px=0):
    """Šedá → „tmavosť" (Byte): o koľko je pixel pod referenciou.

    ref   = clip(pozadie − rel, always, dark)   (bez pozadia rovno `dark`)
    score = clip(ref − šedá, 0, 255)

    `open_px` vyhodí všetko užšie než 2×open_px (viď `open_mask`), `fill_px`
    (default vypnuté) spriemeruje tmavosť v okolí.
    """
    def faza(text, t0):
        if every:
            print(f"  … tmavosť: {text} ({hms(time.time() - t0)})", flush=True)

    t_f = time.time()
    gray = box_blur_u8(gray, blur)
    h, w = gray.shape
    if local_px > 0:
        faza("miestne pozadie", t_f)
        small = block_mean(gray, BG_DOWN)
        bg = bright_background(small, max(1, int(round(local_px / BG_DOWN / 2))))
        np.subtract(bg, float(rel), out=bg)
        np.clip(bg, float(always), float(dark), out=bg)
    else:
        bg = None

    faza("prah tmavosti", t_f)
    out = np.empty((h, w), np.uint8)
    step = 2048
    for r in range(0, h, step):
        r1 = min(r + step, h)
        g = gray[r:r1].astype(np.int16)
        if bg is None:
            np.subtract(np.int16(dark), g, out=g)
        else:
            rows = bg[r // BG_DOWN:(r1 + BG_DOWN - 1) // BG_DOWN]
            full = upsample(rows, r1 - r, w)
            np.subtract(full, g.astype(np.float32), out=full)
            g = full.astype(np.int16)
        np.clip(g, 0, 255, out=g)
        out[r:r1] = g.astype(np.uint8)

    if fill_px > 0:
        faza("vyplnenie", t_f)
        # priemerná tmavosť v okolí; na tom istom zmenšení ako pozadie
        out = upsample(box_mean(block_mean(out, BG_DOWN),
                                max(1, int(round(fill_px / BG_DOWN / 2)))),
                       h, w).astype(np.uint8)

    if open_px > 0:
        # až na hotovej maske: pred prahom by sa `dark_always` nemal ako
        # uplatniť, po vektorizácii už je sieť jeden polygón
        faza(f"otvorenie {open_px} px", t_f)
        out = open_mask(out, open_px)
    return out, gray


VRT_RAW = """<VRTDataset rasterXSize="{w}" rasterYSize="{h}">
  <SRS>EPSG:3857</SRS>
  <GeoTransform>{ox}, {res}, 0.0, {oy}, 0.0, -{res}</GeoTransform>
  <VRTRasterBand dataType="Byte" band="1" subClass="VRTRawRasterBand">
    <SourceFilename relativeToVRT="1">{raw}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>1</PixelOffset>
    <LineOffset>{w}</LineOffset>
  </VRTRasterBand>
</VRTDataset>
"""


def write_chunk(arr, ox, oy, res, out_tif):
    """numpy → georeferencovaný komprimovaný GTiff, bez python bindings GDALu.

    Raw súbor + VRTRawRasterBand + `gdal_translate`; raw sa hneď maže.
    """
    h, w = arr.shape
    # cez `.part`: existencia súboru znamená „pás je spočítaný", takže by
    # polovičný TIFF zamkol dieru v mozaike navždy
    final_tif, out_tif = out_tif, out_tif + ".part"
    raw = out_tif + ".raw"
    arr.tofile(raw)
    vrt = out_tif + ".vrt"
    with open(vrt, "w") as f:
        f.write(VRT_RAW.format(w=w, h=h, ox=repr(ox), oy=repr(oy),
                               res=repr(res), raw=os.path.basename(raw)))
    try:
        run(["gdal_translate", "-q", "-of", "GTiff",
             "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=2",
             "-co", "TILED=YES", "-co", "BIGTIFF=IF_SAFER",
             vrt, out_tif])
    finally:
        for f in (raw, vrt):
            if os.path.exists(f):
                os.remove(f)
    os.replace(out_tif, final_tif)


def build_score_raster(fetcher, z, x0, y0, x1, y1, args, tmp, preview_rows):
    """Mozaika tmavosti po pásoch dlaždicových riadkov → zoznam GTiffov.

    Pás sa načíta s PRESAHOM niekoľkých dlaždicových riadkov hore aj dole,
    aby okno pozadia na jeho okraji nebolo zrezané, a zapíše sa až orezaný
    presne na svoje riadky. Presahové dlaždice sú už v cache, takže sa
    nesťahujú druhýkrát.
    """
    res = tile_res(z)
    w_px = (x1 - x0) * TILE
    local_px = args.local_px
    pad_tiles = (int(math.ceil(max(local_px, args.fill_px, 2 * args.open_px)
                               / 2.0 / TILE))
                 + (1 if args.blur else 0))
    rows_per_band = max(1, int(args.band_cells // max(1, w_px * TILE)))
    tifs = []
    t0 = time.time()
    n_bands = int(math.ceil((y1 - y0) / rows_per_band))
    print(f"  pás = {rows_per_band} dlaždicových riadkov "
          f"({rows_per_band * TILE} px), presah {pad_tiles}, "
          f"{n_bands} pásov", flush=True)

    for bi, ty in enumerate(range(y0, y1, rows_per_band)):
        ty1 = min(ty + rows_per_band, y1)
        py0, py1 = max(y0, ty - pad_tiles), min(y1, ty1 + pad_tiles)
        tif = os.path.join(tmp, f"score{bi:04d}.tif")
        # hotový pás z predošlého behu sa nepočíta znova
        if os.path.exists(tif) and os.path.getsize(tif) > 0:
            tifs.append(tif)
            print(f"  … tmavosť: pás {bi + 1}/{n_bands} už je "
                  f"({dir_mb(tif):.0f} MB) – preskakujem", flush=True)
            continue
        # tep okolo celého pásu – inak z logu nepoznáš „počíta" od „zaseklo sa"
        hb = Heartbeat(f"pás {bi + 1}/{n_bands}", every=args.heartbeat)
        hb.start()
        try:
            gray = load_band(fetcher, z, x0, x1, py0, py1,
                             every=args.heartbeat)
            score, blurred = score_band(gray, args.dark, args.dark_always,
                                        local_px, args.rel, args.blur,
                                        args.fill_px, every=args.heartbeat,
                                        open_px=args.open_px)
        finally:
            hb.stop()
        del gray
        top = (ty - py0) * TILE
        bot = top + (ty1 - ty) * TILE
        cut = score[top:bot]
        ox = -R + x0 * TILE * res
        oy = R - ty * TILE * res
        write_chunk(np.ascontiguousarray(cut), ox, oy, res, tif)
        tifs.append(tif)
        # náhľad sa skladá priebežne, celá mozaika sa nikdy nedrží v pamäti
        if preview_rows is not None:
            k = max(1, args.preview_down)
            vis = blurred[top:bot]
            vh = (vis.shape[0] // k) * k
            if vh:
                preview_rows.append((
                    block_mean(vis[:vh], k).astype(np.uint8),
                    block_mean(cut[:vh], k).astype(np.uint8)))
        del score, blurred, cut
        done = ty1 - y0
        el = time.time() - t0
        eta = el / max(1, done) * (y1 - y0 - done)
        print(f"  … tmavosť: pás {bi + 1}/{n_bands}, "
              f"{done}/{y1 - y0} riadkov, beží {hms(el)}, ostáva {hms(eta)}, "
              f"na disku {dir_mb(tmp):.0f} MB", flush=True)
    return tifs, time.time() - t0
