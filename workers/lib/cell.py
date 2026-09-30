#!/usr/bin/env python3
"""How many metres one cell is – and what follows from it (no numpy: the lint job runs it)."""
import json
import math
import subprocess

# Web Mercator metres are equatorial, so scale to our latitude
DEFAULT_LAT = 49.0

# zoom 0 at the equator: 256 px over 40 075 km
EQUATOR_M_PER_PX = 156543.03

# metres → degrees divides by the longer one, so it never grows on the ground
M_PER_DEG_LAT = 110540
M_PER_DEG_LON_EQ = 111320


def tile_m_per_px(z, lat=DEFAULT_LAT):
    """Ground metres of one tile pixel at the zoom."""
    return EQUATOR_M_PER_PX * math.cos(math.radians(lat)) / (2 ** z)


# every vector tile point snaps to this grid, so smoothed contours follow it
TILE_EXTENT = 4096
TILE_PX = 256


def tile_grid_m(z, lat=DEFAULT_LAT):
    """Tile coordinate grid step in metres at the zoom."""
    return tile_m_per_px(z, lat) * TILE_PX / TILE_EXTENT


def terrain_zoom_for(cell_m, lo=8, hi=16):
    """Lowest zoom whose tile pixel is finer than the model cell (20 m → z13, 5 m → z15)."""
    for z in range(lo, hi + 1):
        if tile_m_per_px(z) <= cell_m:
            return z
    return hi


# slope shading can't tell from flat; picks the encoding step and flat tiles
SLOPE_EPS = 0.02

# finer than 1/64 m is below every model's noise
MAX_FRAC_BITS = 6

# regular quantisation reads as a grid, so stay bits below visibility
FRAC_BITS_MARGIN = 3


def frac_bits(px_m):
    """Fraction bits of height (byte B) for a `px_m` metre pixel; 0 means whole metres."""
    want = SLOPE_EPS * px_m
    if not (want > 0):
        return 0
    # the top zooms get a smaller margin, which is fine
    target = want / (2 ** FRAC_BITS_MARGIN)
    return max(0, min(MAX_FRAC_BITS, int(math.ceil(-math.log2(target)))))


# just above one cell `average` alternates one and two cells – a grid
AVERAGE_RATIO = 2.0


def resampling(px_m, cell_m):
    """`average` only once the pixel is `AVERAGE_RATIO`× coarser than the cell."""
    if not cell_m or px_m >= AVERAGE_RATIO * cell_m:
        return "average"
    return "cubicspline"


def dem_cell_metres(dem, lat=DEFAULT_LAT):
    """Source DEM cell in metres, measured from the raster: `(dx, dy)` or `(None, None)`."""
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
