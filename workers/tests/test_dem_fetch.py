import io
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest import mock

from load import needs_cmd, worker
from geo import hill, write_dem
import rangeserver

fetch = worker("dem/fetch-open.py")
ugkk = worker("dem/fetch-ugkk.py")
probe = worker("dem/probe.py")
LOCAL = {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"}


def zipped(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


@needs_cmd("curl")
class Download(unittest.TestCase):
    def setUp(self):
        self.server, self.base = rangeserver.serve({
            "/dem.zip": zipped({"dem/a.tif": b"II*\0", "readme.txt": b"x"}),
            "/error.zip": b"<html>quota exceeded</html>", "/": b"ok"})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, LOCAL)
        env.start()
        self.addCleanup(env.stop)

    def test_zip_downloaded(self):
        dest = os.path.join(self.tmp, "dem.zip")
        with redirect_stdout(io.StringIO()):
            self.assertTrue(fetch.download(f"{self.base}/dem.zip", dest, timeout=10))

    def test_error_page_isnt_a_zip(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(fetch.download(f"{self.base}/error.zip", os.path.join(self.tmp, "e.zip"), timeout=10))
        self.assertIn("isn't a ZIP", out.getvalue())

    def test_unpack_finds_rasters(self):
        path = os.path.join(self.tmp, "dem.zip")
        with open(path, "wb") as f:
            f.write(zipped({"dem/a.tif": b"x", "dem/b.TIF": b"x", "readme.txt": b"x"}))
        with redirect_stdout(io.StringIO()):
            got = fetch.unpack(path, os.path.join(self.tmp, "out"))
        self.assertEqual([os.path.basename(p) for p in got], ["a.tif", "b.TIF"])

    def test_probe_get_and_reachable(self):
        data, how = probe.smart_get(f"{self.base}/dem.zip", timeout=5)
        self.assertTrue(data.startswith(b"PK"))
        self.assertIn("urllib", how)
        self.assertTrue(probe.host_reachable(f"{self.base}/missing", timeout=5)[0])
        self.assertFalse(probe.host_reachable("http://127.0.0.1:9/", timeout=2)[0])


@needs_cmd("gdalinfo", "gdalwarp", "gdal_translate")
class Rasters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 19.5..20.5 × 49.2..49.7, 0.01° cells – two whole-degree tiles, one per side
        self.dem = write_dem(os.path.join(self.tmp, "dem.tif"), hill(100)[:50], (19.5, 49.2, 20.5, 49.7))

    def test_describe_in_metres(self):
        info, err = fetch.describe(self.dem)
        self.assertIsNone(err)
        self.assertAlmostEqual(info["cell_y_m"], 1105.4, delta=1)
        self.assertEqual(info["size"], [100, 50])

    def test_cut_tiles_by_degree(self):
        with redirect_stdout(io.StringIO()):
            made = fetch.cut_tiles(self.dem, os.path.join(self.tmp, "tiles"), (19.5, 49.2, 20.5, 49.7))
        self.assertEqual(sorted(os.path.basename(p) for p in made), ["N49E019.tif", "N49E020.tif"])

    def test_is_elevation_raster(self):
        got = ugkk.is_elevation_raster(self.dem)
        self.assertEqual(got["type"], "Float32")
        self.assertFalse(got["ok"], "a 700 m grid is no DMR 5.0")
        self.assertTrue(ugkk.is_elevation_raster(self.dem, min_cell_m=2000)["ok"])
        self.assertIsNone(ugkk.is_elevation_raster(os.path.join(self.tmp, "none.tif")))

    def test_hms(self):
        self.assertEqual(ugkk.hms(3661), "1:01:01")


if __name__ == "__main__":
    unittest.main()
