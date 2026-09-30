#!/usr/bin/env python3
"""Rocks from hillshading, 2/3: the darkness raster from tiles.

The tile mosaic → a field of "how dark it is here against the surroundings", in
bands. Used as a module: `load("shading_raster", "raster.py")`.
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
    """workers/*.py can't be imported normally because of the dash in the name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# grid, run() and Heartbeat come from the layer below
tiles = load("shading_tiles", "tiles.py")
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
run = tiles.run
tile_res, ground_res = tiles.tile_res, tiles.ground_res

# watch.py is shared by both kinds of rocks, so it lives in workers/lib/
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb, Heartbeat  # noqa: E402

# the downscale the lighting field is computed on – it is a smooth function
BG_DOWN = 8



def block_mean(gray, k, chunk_rows=4096):
    """A mean over k×k blocks → a k times smaller float32 image, in row strips."""
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
    """A mean over a (2r+1)² window via an integral image; edges padded."""
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
    """A mean over a small window on the grey itself – erases JPEG grain."""
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
    """Tile rows [ty0, ty1) as one greyscale image; a missing tile stays 255 (light)."""
    # decoding JPEGs is the run's longest silent part, so each tile row reports
    w = (x1 - x0) * TILE
    h = (ty1 - ty0) * TILE
    band = np.full((h, w), 255, np.uint8)
    t0 = last = time.time()
    n = 0
    for ty in range(ty0, ty1):
        now = time.time()
        if every and now - last >= every:
            last = now
            finished = ty - ty0
            eta = (now - t0) / max(1, finished) * (ty1 - ty - 0) if finished else 0
            print(f"  … decoding: row {finished + 1}/{ty1 - ty0}, "
                  f"{n} tiles, running {hms(now - t0)}"
                  + (f", {hms(eta)} left" if finished else ""), flush=True)
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
    """A downscaled field back to full resolution; the edge padded."""
    full = np.repeat(np.repeat(small, k, axis=0), k, axis=1)
    if full.shape[0] < h or full.shape[1] < w:
        full = np.pad(full, ((0, max(0, h - full.shape[0])),
                             (0, max(0, w - full.shape[1]))), mode="edge")
    return full[:h, :w]


def bright_background(small, r):
    """How light lit terrain is here – the mean of the window's lighter half."""
    # a plain mean would be pulled down by a big dark area, finding only its edge
    m1 = box_mean(small, r)
    lit = (small >= m1).astype(np.float32)
    s = box_mean(small * lit, r)
    c = box_mean(lit, r)
    return np.where(c > 0.05, s / np.maximum(c, 1e-6), m1).astype(np.float32)


def _rank_box(a, r, ufunc):
    """A running min/max over a (2r+1)² window – separably, per axis."""
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
    """Morphological opening of the darkness mask: erosion, then dilation."""
    # sorts by width, not area: a hairline gully network is a grey blanket at low zoom
    if r <= 0:
        return score
    keep = (score > 0).astype(np.uint8)
    keep = _rank_box(keep, r, np.minimum)   # erosion
    keep = _rank_box(keep, r, np.maximum)   # dilation
    score = score.copy()
    score[keep == 0] = 0
    return score


def score_band(gray, dark, always, local_px, rel, blur, fill_px=0, every=0,
               open_px=0):
    """Grey → "darkness" (Byte): how far a pixel is under the reference."""
    # ref = clip(background − rel, always, dark); score = clip(ref − grey, 0, 255)
    def phase(text, t0):
        if every:
            print(f"  … darkness: {text} ({hms(time.time() - t0)})", flush=True)

    t_f = time.time()
    gray = box_blur_u8(gray, blur)
    h, w = gray.shape
    if local_px > 0:
        phase("local background", t_f)
        small = block_mean(gray, BG_DOWN)
        bg = bright_background(small, max(1, int(round(local_px / BG_DOWN / 2))))
        np.subtract(bg, float(rel), out=bg)
        np.clip(bg, float(always), float(dark), out=bg)
    else:
        bg = None

    phase("darkness threshold", t_f)
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
        phase("fill", t_f)
        # the mean darkness around, on the same downscale as the background
        out = upsample(box_mean(block_mean(out, BG_DOWN),
                                max(1, int(round(fill_px / BG_DOWN / 2)))),
                       h, w).astype(np.uint8)

    if open_px > 0:
        # on the finished mask: before the threshold `dark_always` couldn't apply
        phase(f"opening {open_px} px", t_f)
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
    """numpy → a georeferenced compressed GTiff, without GDAL's python bindings."""
    h, w = arr.shape
    # through `.part`: a file means "band computed", half a TIFF would lock a hole
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
    """The darkness mosaic in bands of tile rows → a list of GTiffs."""
    # a band loads with an overlap so the background window isn't cut at its edge
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
    print(f"  band = {rows_per_band} tile rows "
          f"({rows_per_band * TILE} px), overlap {pad_tiles}, "
          f"{n_bands} bands", flush=True)

    for bi, ty in enumerate(range(y0, y1, rows_per_band)):
        ty1 = min(ty + rows_per_band, y1)
        py0, py1 = max(y0, ty - pad_tiles), min(y1, ty1 + pad_tiles)
        tif = os.path.join(tmp, f"score{bi:04d}.tif")
        # a band finished by an earlier run isn't computed again
        if os.path.exists(tif) and os.path.getsize(tif) > 0:
            tifs.append(tif)
            print(f"  … darkness: band {bi + 1}/{n_bands} is there "
                  f"({dir_mb(tif):.0f} MB) – skipping", flush=True)
            continue
        # a heartbeat around the band – otherwise "computing" looks like "stuck"
        hb = Heartbeat(f"band {bi + 1}/{n_bands}", every=args.heartbeat)
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
        # the preview is assembled as it goes, never the whole mosaic in memory
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
        print(f"  … darkness: band {bi + 1}/{n_bands}, "
              f"{done}/{y1 - y0} rows, running {hms(el)}, {hms(eta)} left, "
              f"{dir_mb(tmp):.0f} MB on disk", flush=True)
    return tifs, time.time() - t0
