"""Synthetic rasters for tests, through the GDAL command line the build uses."""
import os
import subprocess
import tempfile


def write_dem(path, heights, bbox, nodata=-9999):
    """A GeoTIFF (EPSG:4326) of `heights` (rows north to south) over `bbox`."""
    w, s, e, n = bbox
    rows, cols = len(heights), len(heights[0])
    if abs((e - w) / cols - (n - s) / rows) > 1e-12:
        raise ValueError("cells must be square in degrees")
    with tempfile.TemporaryDirectory() as tmp:
        asc = os.path.join(tmp, "dem.asc")
        with open(asc, "w") as f:
            f.write(f"ncols {cols}\nnrows {rows}\nxllcorner {w!r}\nyllcorner {s!r}\n"
                    f"cellsize {(e - w) / cols!r}\nNODATA_value {nodata}\n")
            for row in heights:
                f.write(" ".join(f"{v:.3f}" for v in row) + "\n")
        subprocess.run(["gdal_translate", "-q", "-of", "GTiff", "-ot", "Float32",
                        "-a_srs", "EPSG:4326", asc, path], check=True)
    return path


def hill(size, top=500.0, base=200.0, hole=None):
    """A round hill on a plain; `hole` = (row0, row1, col0, col1) of nodata."""
    c = (size - 1) / 2
    out = []
    for r in range(size):
        row = []
        for k in range(size):
            d2 = ((r - c) ** 2 + (k - c) ** 2) / (c * c)
            v = base + (top - base) * max(0.0, 1 - d2)
            if hole and hole[0] <= r < hole[1] and hole[2] <= k < hole[3]:
                v = -9999
            row.append(v)
        out.append(row)
    return out
