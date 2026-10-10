import json
import os
import tempfile
import unittest

from load import needs_cmd, worker
from geo import hill, write_dem

BBOX = (19.95, 49.15, 20.05, 49.25)


@needs_cmd("gdaltransform", "gdalwarp", "gdaldem", "gdal_translate")
class RockPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = worker("contours-rocks/rock-plan.py")
        cls.slope = worker("contours-rocks/slope-chunks.py")

    def test_chunks_cover_the_extent(self):
        res = 5.0
        x0, y0, x1, y1 = self.plan.to_metric(BBOX)
        keep, total, cells, (nx, ny, sx, sy, wm, hm) = self.plan.chunk_plan(
            x0, y0, x1, y1, res, 4e6, BBOX)
        self.assertEqual(total, nx * ny)
        self.assertGreater(total, 1)
        area = 0.0
        for i, a in enumerate(keep):
            area += (a[4] - a[2]) * (a[5] - a[3])
            for b in keep[i + 1:]:
                overlap = (min(a[4], b[4]) - max(a[2], b[2]) > 0 and min(a[5], b[5]) - max(a[3], b[3]) > 0)
                self.assertFalse(overlap, (a, b))
        self.assertAlmostEqual(cells, area / res / res)
        self.assertLessEqual(area, wm * hm + 1e-6)
        self.assertGreater(area, (x1 - x0) * (y1 - y0) * 0.5)

    def test_chunk_grid_is_absolute(self):
        res, px = 5.0, 512
        side = res * px
        chunks = self.slope.chunk_grid(BBOX, res, px)
        self.assertTrue(chunks)
        names = {self.slope.chunk_name(ix, iy, res) for ix, iy, *_ in chunks}
        self.assertEqual(len(names), len(chunks))
        for ix, iy, x0, y0, x1, y1 in chunks:
            self.assertEqual((x0, y0, x1 - x0, y1 - y0), (ix * side, iy * side, side, side))
        self.assertEqual(self.slope.chunk_name(-3, 2, 1.5), "slope-r1.5-W0003N0002.tif")

    def test_vec_res(self):
        self.assertEqual(self.plan.pick_vec_res(1.0), 2.0)
        self.assertEqual(self.plan.pick_vec_res(5.0), 5.0)
        self.assertEqual(self.plan.pick_vec_res(30.0), 30.0)

    def test_failed_chunk_is_not_done(self):
        chunk = self.slope.chunk_grid(BBOX, 5.0, 256)[0]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "slope.tif")
            with self.assertRaises(RuntimeError):
                self.slope.slope_chunk(os.path.join(tmp, "missing.tif"), chunk, 5.0, out, tmp)
            self.assertEqual(sorted(os.listdir(tmp)), [])
            store = self.slope.Store(tmp, "dem-slope", use_store=False)
            self.assertIsNone(store.local("slope.tif"))

    def test_chunk_from_a_hill(self):
        with tempfile.TemporaryDirectory() as tmp:
            dem = write_dem(os.path.join(tmp, "dem.tif"), hill(100), BBOX)
            chunks = self.slope.chunk_grid(BBOX, 10.0, 256)
            x0, y0, x1, y1 = self.plan.to_metric(BBOX)
            middle = min(chunks, key=lambda c: abs((c[2] + c[4]) / 2 - (x0 + x1) / 2)
                         + abs((c[3] + c[5]) / 2 - (y0 + y1) / 2))
            out = os.path.join(tmp, "chunk.tif")
            self.slope.slope_chunk(dem, middle, 10.0, out, tmp)
            self.assertFalse(os.path.exists(out + ".part"))
            info = json.loads(self.plan.run(["gdalinfo", "-json", "-stats", out]).stdout)
        band = info["bands"][0]
        self.assertEqual((info["size"], band["type"]), ([256, 256], "Int16"))
        # hundredths of a degree: a 300 m hill over ~5 km has a few degrees of slope
        self.assertGreater(band["maximum"], 100)
        self.assertLess(band["maximum"], 90 * self.slope.SCALE)


if __name__ == "__main__":
    unittest.main()
