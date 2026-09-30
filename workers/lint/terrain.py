#!/usr/bin/env python3
"""Hillshading must not silently lose the precision it stands on."""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
TILES = os.path.join(_WORKERS, "terrain", "tiles.py")
BUILD = os.path.join(_WORKERS, "terrain", "build.sh")
KEYS = os.path.join(_WORKERS, "plan", "cache-keys.sh")
MASK = os.path.join(_WORKERS, "lib", "region-mask.py")
# work on the height grid is in height.py – the check looks into both
HEIGHT = os.path.join(_WORKERS, "terrain", "height.py")
# the decisions are run, not read, so they live in numpy-free lib/cell.py
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402

# zooms hillshading really runs on
ZOOMS = range(5, 17)


def main():
    bad = []
    t = cell

    # 1. the vertical step follows the pixel; `MAX_FRAC_BITS` is no excuse for a coarse step
    for z in ZOOMS:
        px = t.tile_m_per_px(z)
        bits = t.frac_bits(px)
        step = 2.0 ** -bits
        cap = t.SLOPE_EPS * px
        if step > cap:
            bad.append(f"z{z}: a {px:.1f} m pixel bears a step of at most "
                       f"{cap:.3f} m, but `frac_bits` gave {bits} bits, "
                       f"that is {step:g} m"
                       + (f" (held by MAX_FRAC_BITS={t.MAX_FRAC_BITS})"
                          if bits >= t.MAX_FRAC_BITS else "")
                       + ". Hillshade turns the terraces into a regular weave.")
        # with a margin: a step right at the edge leaves a regular false slope
        s_margin = cap / (2 ** t.FRAC_BITS_MARGIN)
        if step > s_margin and bits < t.MAX_FRAC_BITS:
            bad.append(f"z{z}: step {step:g} m is only just under the edge of "
                       f"visibility ({cap:.3f} m). Quantisation makes a false "
                       f"slope REGULARLY, so it must be {t.FRAC_BITS_MARGIN} "
                       f"bits under it, at most {s_margin:.4f} m – "
                       f"`frac_bits` gave {bits} bits.")
    # the other side: coarse zooms shouldn't pay for nothing
    if t.frac_bits(t.tile_m_per_px(5)) != 0:
        bad.append("z5: such a coarse pixel bears a whole metre, but "
                   "`frac_bits` asks for fraction bits – an extra byte per "
                   "tile for precision nobody sees there.")

    # 2. average only when there is something to average; numbers at `AVERAGE_RATIO`
    for grid in (1.0, 5.0, 10.0, 20.0, 31.0):
        for z in ZOOMS:
            px = t.tile_m_per_px(z)
            r = t.resampling(px, grid)
            if px < t.AVERAGE_RATIO * grid and r == "average":
                bad.append(f"model {grid:g} m, z{z} (pixel {px:.1f} m): the "
                           f"pixel isn't even {t.AVERAGE_RATIO:g}× coarser than "
                           f"a cell, but `average` resamples – it covers one "
                           f"cell, then two, and hillshade makes a grid of it.")
            if px >= t.AVERAGE_RATIO * grid and r != "average":
                bad.append(f"model {grid:g} m, z{z} (pixel {px:.1f} m): the DEM "
                           f"shrinks at least {t.AVERAGE_RATIO:g}×, it must "
                           f"average (`average`), not `{r}`.")
    # just above the cell `average` must not come back
    if t.resampling(25.0, 20.0) == "average":
        bad.append("A 25 m pixel over a 20 m cell (z12 with Sonny) resamples by "
                   "`average` – measured 5.45 against 4.07 with `cubicspline` "
                   "(and 5.36 against 0.53 on the warp alone). That is the grid "
                   "seen on the map, and `cubicspline` is free here.")
    # without a known grid no guessing
    if t.resampling(10.0, 0.0) != "average":
        bad.append("Without a known model grid `resampling` must stay at "
                   "`average` – the behaviour so far, and right when shrinking.")

    # 3. the warp must carry the fraction
    src = open(TILES).read()
    warp = src[src.index("def warp_level"):]
    warp = warp[:warp.index("\ndef ")] if "\ndef " in warp[1:] else warp
    if re.search(r'"-ot",\s*"Int16"', warp):
        bad.append("`warp_level` warps to Int16 – the height fraction is "
                   "dropped before encoding and the vertical step is a metre "
                   "whatever `frac_bits` says.")
    elif not re.search(r'"-ot",\s*"Float32"', warp):
        bad.append("`warp_level` lacks `-ot Float32`; check that the height "
                   "fraction survives to the encoding.")

    # 3b. encoding rounds, not masks: masking low bits is `floor`, a stair at zoom borders
    enc = src[src.index("def terrarium"):]
    enc = enc[:enc.index("\ndef ", 1)] if "\ndef " in enc[1:] else enc
    if re.search(r">>\s*\(?\s*8\s*-\s*bits", enc):
        bad.append("`terrarium` cuts the fraction with a mask (`>> (8 - bits)`), "
                   "which is `floor` – every height drops by up to a step. It "
                   "must round TO the step (`np.rint(… / step) * step`).")
    elif "np.rint" not in enc:
        bad.append("`terrarium` doesn't round (`np.rint`); without it the "
                   "fraction is cut down and heights shift systematically.")

    # 4. the encoding shape: store and cache
    build = open(BUILD).read()
    keys = open(KEYS).read()
    # the version is a variable (`ENC_VER`): written twice, `-v4` was stored and `-v3` sought
    v_asset = set(re.findall(r"^ENC_VER=v(\d+)\s*$", build, re.M))
    # comments may name the version; a number in code is forbidden
    code = "\n".join(r for r in build.splitlines()
                     if not r.lstrip().startswith("#"))
    written = set(re.findall(r"-v(\d+)\\?\.pmtiles", code))
    # the hillshading key is built in `T_SETTINGS`
    v_cache = set(re.findall(r'^T_SETTINGS="terrain-v(\d+)-', keys, re.M))
    if len(v_asset) != 1:
        bad.append(f"`ENC_VER=v<number>` can't be read in `workers/terrain/build.sh` "
                   f"(found {sorted(v_asset)}). The encoding shape must be a "
                   f"variable in ONE place – the asset name is built both when "
                   f"searching the store and when saving, and both must agree.")
    elif written:
        bad.append(f"`workers/terrain/build.sh` writes the encoding version as a "
                   f"number ({sorted('v' + v for v in written)}) beside `ENC_VER`. "
                   f"That is how `-v4` in the asset name and `-v3` in the `sed` "
                   f"searching the store drifted: stored tiles were never found "
                   f"and hillshading was computed in every run. Use `${{ENC_VER}}`.")
    elif not v_cache:
        bad.append("`workers/plan/cache-keys.sh` has no version in the "
                   "hillshading key (`T_SETTINGS=\"terrain-v<number>-…\"`) – "
                   "without it the cache returns old tiles.")
    elif v_asset != v_cache:
        bad.append(f"The encoding shape drifted: the store says v{v_asset.pop()}, "
                   f"the cache v{v_cache.pop()}. One of them returns tiles "
                   f"computed the old way and the build is green.")
    else:
        print(f"  ✓ encoding shape v{v_cache.pop()} in the store and the cache")

    # 5. hillshading ends at the region's edge: tiles and pixels, a plane beyond
    if "--poly=data/region.geojson" not in build:
        bad.append("`workers/terrain/build.sh` doesn't pass `tiles.py` the region "
                   "polygon (`--poly=data/region.geojson`) – tiles are made over "
                   "the whole bbox and hillshading reaches far beyond the region "
                   "(37 % extra area for the Prešov region).")
    strip = src[src.index("def main("):]
    if "pixel_mask(" not in strip:
        bad.append("`terrain/tiles.py` doesn't ask which PIXELS are in the region "
                   "(`pixel_mask`). A tile clip can't be finer than a tile, so "
                   "hillshading overhangs the region again – twice its area at "
                   "z10, and the build is green.")
    if "flatten_outside(" not in strip:
        bad.append("`terrain/tiles.py` doesn't flatten the height outside the "
                   "region (`flatten_outside`). Anything but a plane has slope "
                   "and the client shades it outside the region – visible on a "
                   "map without the `outside` fill (a layer over another base).")
    if "pokracuj_okolim" in src or "continue_surroundings" in src:
        bad.append("`terrain/tiles.py` fills the height outside from the "
                   "surroundings again – a continuation has slope, so it is "
                   "shaded outside the region.")
    # one height for the whole run: a plane per strip or zoom would seam
    if strip.count("plane_height(") != 1 or "def plane_height" not in src:
        bad.append("`terrain/tiles.py` doesn't compute the plane height outside "
                   "once per run (`plane_height`). Another height in another "
                   "strip or zoom is a stair, a shaded line outside the region.")
    if not re.search(r"keep\[[^\]]*\][^\n]*\.any\(\)", strip):
        bad.append("`terrain/tiles.py` doesn't skip a tile with no region pixel "
                   "– the plane would be written into tiles with nothing of the "
                   "region in them.")
    if "def flatten_outside" not in open(HEIGHT).read():
        bad.append("`workers/terrain/height.py` no longer has `flatten_outside` "
                   "– that is what stops shading outside the region.")
    if "def pixel_mask" not in open(MASK).read():
        bad.append("`workers/lib/region-mask.py` no longer has `pixel_mask` – "
                   "which PIXELS are in the region has one answer, beside the "
                   "tile one, not a second in `tiles.py`.")
    # a margin: with `--edge 0` the last strip in the region would shade the plane's edge
    edge = re.search(r'"--edge",\s*type=int,\s*default=(\d+)', src)
    if not edge:
        bad.append("`terrain/tiles.py` lacks the `--edge` option (how many "
                   "pixels of real terrain stay outside the region).")
    elif int(edge.group(1)) < 1:
        bad.append("`--edge` defaults to 0 pixels: the plane starts right at the "
                   "region's edge, so the last strip of shading IN the region "
                   "draws its edge, not terrain. The margin moves it under the "
                   "`outside` fill.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Hillshading: the vertical step follows the pixel, averaging only "
          "down, the warp carries the fraction, a plane outside the region ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
