import io
import math
import os
import unittest

from load import needs, worker

rmask = worker("lib/region-mask.py")
SQUARE = [([(19.0, 49.0), (20.0, 49.0), (20.0, 50.0), (19.0, 50.0)], False)]
WITH_HOLE = SQUARE + [([(19.4, 49.4), (19.6, 49.4), (19.6, 49.6), (19.4, 49.6)], True)]


class RegionMask(unittest.TestCase):
    def test_inside_with_hole(self):
        self.assertTrue(rmask.inside(WITH_HOLE, 19.2, 49.2))
        self.assertFalse(rmask.inside(WITH_HOLE, 19.5, 49.5))
        self.assertFalse(rmask.inside(WITH_HOLE, 20.5, 49.5))

    def test_touches(self):
        m = rmask.Mask(SQUARE, (18.0, 48.0, 21.0, 51.0), cells=64)
        self.assertTrue(m.touches(19.9, 49.9, 20.1, 50.1))
        self.assertFalse(m.touches(20.2, 49.0, 20.4, 49.5))
        self.assertFalse(m.touches(30.0, 49.0, 31.0, 50.0))
        self.assertAlmostEqual(m.pct, 100 / 9, delta=1)

    def tile_at(self, z, lon, lat):
        n = 2 ** z
        x = int((lon + 180) / 360 * n)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
        return x, y

    def test_tile_outside_the_border(self):
        # fix 1160: hillshading and rocks ran past the county border
        z = 12
        m = rmask.Mask(SQUARE, (18.0, 48.0, 21.0, 51.0), cells=512)
        x, y = self.tile_at(z, 19.5, 49.5)
        self.assertTrue(rmask.tile_touches(m, z, x, y))
        east_x, _ = self.tile_at(z, 20.0, 49.5)
        self.assertGreater(rmask.tile_box(z, east_x + 1, y)[0], 20.0)
        self.assertTrue(rmask.tile_touches(m, z, east_x + 1, y), "half a tile may overhang")
        self.assertFalse(rmask.tile_touches(m, z, east_x + 1, y, grow=0))
        self.assertFalse(rmask.tile_touches(m, z, east_x + 2, y))

    def test_tile_box(self):
        w, s, e, n = rmask.tile_box(1, 1, 0)
        self.assertEqual((w, e), (0.0, 180.0))
        self.assertAlmostEqual(n, 85.0511, places=3)
        self.assertEqual(s, 0.0)

    @needs("numpy")
    def test_pixel_mask(self):
        box = (18.0, 48.0, 21.0, 51.0)
        mask = rmask.pixel_mask(WITH_HOLE, box, 30, 30)
        self.assertEqual(int(mask.sum()), 100 - 4)
        self.assertTrue(mask[12, 12])
        self.assertFalse(mask[0, 0])
        self.assertFalse(mask[15, 15], "in the hole")
        grown = rmask.pixel_mask(SQUARE, box, 30, 30, grow=1)
        self.assertEqual(int(grown.sum()), 12 * 12)
        shrunk = rmask.pixel_mask(SQUARE, box, 30, 30, grow=-1)
        self.assertEqual(int(shrunk.sum()), 8 * 8)
        inner = rmask.pixel_mask(SQUARE, (19.2, 49.2, 19.8, 49.8), 6, 6, grow=-1)
        self.assertTrue(inner.all(), "a strip's own edge isn't the region's")


@needs("numpy")
class Height(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.h = worker("terrain/height.py")

    def test_linear_between_two_sides(self):
        np = self.np
        g = np.array([[10.0, 0, 0, 0, 50.0]])
        got = self.h.fill_nodata(g, g == 0)
        self.assertEqual(got.tolist(), [[10.0, 20.0, 30.0, 40.0, 50.0]])

    def test_corner_without_a_neighbour_in_its_row(self):
        np = self.np
        g = np.array([[0.0, 0.0], [7.0, 9.0]])
        got = self.h.fill_nodata(g, g == 0)
        self.assertEqual(got.tolist(), [[7.0, 9.0], [7.0, 9.0]])

    def test_all_missing_unchanged(self):
        np = self.np
        g = np.full((3, 3), self.h.NODATA)
        self.assertIs(self.h.fill_nodata(g, np.ones_like(g, dtype=bool)), g)

    def test_edge_height_takes_the_rim(self):
        np = self.np
        g = np.full((5, 5), 100.0)
        g[2, 2] = 900.0
        known = np.ones((5, 5), dtype=bool)
        self.assertEqual(self.h.edge_height(g, known), 100.0)

    def test_nothing_is_shaded_past_the_border(self):
        # fix 2052: the app draws no `outside` fill, so the plane's wall showed past the border
        np = self.np
        box = (18.0, 48.0, 21.0, 51.0)
        known = rmask.pixel_mask(SQUARE, box, 30, 30)
        keep = rmask.pixel_mask(SQUARE, box, 30, 30, grow=self.edge())
        terrain = np.random.default_rng(7).uniform(0.0, 2000.0, (30, 30))
        g = np.pad(self.h.flatten_outside(terrain, keep, 500.0), 1, mode="edge")
        # hillshade reads a pixel's 3 × 3 neighbourhood
        rough = np.zeros((30, 30))
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                rough = np.maximum(rough, np.abs(g[dy:dy + 30, dx:dx + 30] - g[1:31, 1:31]))
        self.assertEqual(float(rough[~known].max()), 0.0)
        self.assertGreater(float(rough[known].max()), 0.0)

    def edge(self):
        import re
        with open(os.path.join(os.path.dirname(__file__), "..", "terrain", "tiles.py")) as f:
            src = f.read()
        return int(re.search(r'"--edge",\s*type=int,\s*default=(-?\d+)', src).group(1))

    def test_a_range_runs_past_its_box(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "terrain", "build.sh")) as f:
            src = f.read()
        self.assertIn('[ "$CUT_KEY" != whole ] && EDGE=1', src)
        self.assertIn('--edge="$EDGE"', src)

    def test_flatten_outside(self):
        np = self.np
        g = np.array([[1.0, 2.0], [3.0, 4.0]])
        known = np.array([[True, False], [False, True]])
        self.assertEqual(self.h.flatten_outside(g, known, 0.5).tolist(), [[1.0, 0.5], [0.5, 4.0]])


@needs("numpy", "PIL")
class TerrainTiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.t = worker("terrain/tiles.py")

    def decode(self, rgb):
        rgb = rgb.astype(self.np.float64)
        return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768

    def test_terrarium_round_trip(self):
        np = self.np
        heights = np.array([[-430.3, 0.0, 132.71], [2654.987, 8848.1, 1.0 / 3]])
        for bits in (0, 3, 6):
            with self.subTest(bits=bits):
                back = self.decode(self.t.terrarium(heights, bits))
                self.assertLessEqual(float(np.abs(back - heights).max()), 0.5 / 2 ** bits + 1e-9)

    def test_tile_range(self):
        self.assertEqual(self.t.tile_range(0, -180, -85, 180, 85), (0, 0, 0, 0))
        for z, lon, lat in ((14, 17.1, 48.142), (12, 22.53, 49.1), (8, -74.0, -3.5)):
            n = 2 ** z
            x = int((lon + 180) / 360 * n)
            y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
            self.assertEqual(self.t.tile_range(z, lon, lat, lon, lat), (x, x, y, y))
        x0, x1, y0, y1 = self.t.tile_range(10, 17.0, 47.7, 22.6, 49.6)
        self.assertLess(x0, x1)
        self.assertLess(y0, y1, "y grows southwards")

    def test_mercator(self):
        self.assertEqual(self.t.merc_x(0), 0)
        self.assertAlmostEqual(self.t.merc_x(180), self.t.ORIGIN)
        self.assertAlmostEqual(self.t.merc_y(85.05112878), self.t.ORIGIN, delta=1)
        self.assertEqual(self.t.merc_y(90), self.t.merc_y(89))

    def test_is_flat(self):
        np = self.np
        self.assertTrue(self.t.is_flat(np.zeros((4, 4)), 10))
        hill = np.zeros((4, 4))
        hill[2, 2] = 5
        self.assertFalse(self.t.is_flat(hill, 10))
        self.assertFalse(self.t.is_flat(np.zeros((1, 4)), 10))

    def test_png_reads_back(self):
        from PIL import Image
        np = self.np
        rng = np.random.default_rng(1)
        arr = rng.integers(0, 256, (37, 23, 3), dtype=np.uint8)
        back = np.asarray(Image.open(io.BytesIO(self.t.png_rgb(arr))).convert("RGB"))
        self.assertTrue((back == arr).all())


@needs("PIL", "pmtiles")
class TerrainPlane(unittest.TestCase):
    """The plane's height, which the app leaves out where it cuts or merges heights."""

    @classmethod
    def setUpClass(cls):
        cls.p = worker("terrain/plane.py")

    def tile(self, plane_share):
        from PIL import Image
        image = Image.new("RGB", (256, 256), (131, 229, 0))  # 997 m
        hill = int(256 * (1 - plane_share) ** 0.5)
        for x in range(hill):
            for y in range(hill):
                image.putpixel((x, y), (131, (x * 7 + y) % 256, x % 256))
        out = io.BytesIO()
        image.save(out, "WEBP", lossless=True)
        return out.getvalue()

    def test_the_commonest_height_is_the_plane(self):
        self.assertEqual(self.p.plane_of(self.tile(0.9)), 997)

    def test_ground_alone_has_no_plane(self):
        self.assertIsNone(self.p.plane_of(self.tile(0.1)))

    def test_read_from_the_archive(self):
        import tempfile
        from pmtiles.tile import Compression, TileType, zxy_to_tileid
        from pmtiles.writer import Writer
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "r-terrain.pmtiles")
        z, x, y = 5, 17, 10
        with open(path, "wb") as f:
            writer = Writer(f)
            writer.write_tile(zxy_to_tileid(z, x, y), self.tile(0.9))
            writer.finalize({"tile_type": TileType.WEBP, "tile_compression": Compression.NONE,
                             "min_zoom": z, "max_zoom": z,
                             "min_lon_e7": int(19.0e7), "min_lat_e7": int(49.0e7),
                             "max_lon_e7": int(20.0e7), "max_lat_e7": int(49.5e7),
                             "center_zoom": z, "center_lon_e7": int(19.5e7),
                             "center_lat_e7": int(49.25e7)}, {})
        self.assertEqual(self.p.plane(path), 997)
        self.assertIsNone(self.p.plane(os.path.join(folder, "none.pmtiles")))


if __name__ == "__main__":
    unittest.main()
