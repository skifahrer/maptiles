import gzip
import io
import math
import os
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from types import SimpleNamespace

from load import needs, worker

tiles = worker("rocks-shading/tiles.py")


class Tiles(unittest.TestCase):
    def test_lonlat_to_tile(self):
        self.assertEqual(tiles.lonlat_to_tile(0, 0, 1), (1.0, 1.0))
        x, y = tiles.lonlat_to_tile(-180, 85.05112, 3)
        self.assertEqual(x, 0)
        self.assertAlmostEqual(y, 0, places=4)

    def test_tile_range_half_open(self):
        x0, y0, x1, y1 = tiles.tile_range((19.9, 49.0, 20.4, 49.3), 12)
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        fx, fy = tiles.lonlat_to_tile(20.4, 49.0, 12)
        self.assertEqual((x1, y1), (math.ceil(fx), math.ceil(fy)))
        # a point bbox is still one tile
        p = tiles.tile_range((20.0, 49.0, 20.0, 49.0), 12)
        self.assertEqual((p[2] - p[0], p[3] - p[1]), (1, 1))

    def test_resolution(self):
        self.assertAlmostEqual(tiles.tile_res(0), 156543.03, places=1)
        self.assertAlmostEqual(tiles.ground_res(16, 60), tiles.tile_res(16) / 2, places=6)

    def test_looks_like_image(self):
        self.assertTrue(tiles.looks_like_image(b"\x89PNG\r\n\x1a\n...."))
        self.assertTrue(tiles.looks_like_image(b"\xff\xd8\xff\xe0"))
        self.assertFalse(tiles.looks_like_image(b"<html>429 Too Many Requests"))
        self.assertFalse(tiles.looks_like_image(b""))

    def test_decode_body(self):
        body = b"\xff\xd8\xffjpeg"
        self.assertEqual(tiles.decode_body(gzip.compress(body), "gzip"), body)
        self.assertEqual(tiles.decode_body(zlib.compress(body), "deflate"), body)
        raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        headerless = raw.compress(body) + raw.flush()
        self.assertEqual(tiles.decode_body(headerless, "Deflate"), body)
        self.assertEqual(tiles.decode_body(body, ""), body)
        self.assertEqual(tiles.decode_body(b"not gzip", "gzip"), b"")


class Vector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = worker("rocks-shading/vector.py")

    def test_ring_area_signed(self):
        ccw = [(0, 0), (2, 0), (2, 1), (0, 1), (0, 0)]
        self.assertEqual(self.v.ring_area(ccw), 2.0)
        self.assertEqual(self.v.ring_area(list(reversed(ccw))), -2.0)

    def test_downloaded_round_trip(self):
        fetcher = SimpleNamespace(n_miss=3, n_fail=1, bytes=5 * 1048576, ua_seen={"a", "b"})
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            self.v.write_downloaded(tmp, fetcher, 40)
            got = self.v.read_downloaded(tmp, 0)
            missing = self.v.read_downloaded(os.path.join(tmp, "nope"), 7)
        self.assertEqual(got, {"tiles": 40, "tiles_missing": 3, "tiles_failed": 1,
                               "mb_downloaded": "5", "ua_profiles": 2})
        self.assertEqual(missing["tiles"], 7)
        self.assertEqual(missing["tiles_missing"], 0)

    def test_done_needs_a_whole_file(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            path = os.path.join(tmp, "rocks.geojsonl")
            self.assertFalse(self.v.done(path, "x"))
            open(path, "w").close()
            self.assertFalse(self.v.done(path, "x"))
            with open(path, "w") as f:
                f.write("{}\n")
            self.assertTrue(self.v.done(path, "x"))


@needs("numpy", "PIL")
class Raster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.r = worker("rocks-shading/raster.py")

    def test_block_mean(self):
        np = self.np
        a = np.arange(16, dtype=np.uint8).reshape(4, 4)
        self.assertEqual(self.r.block_mean(a, 2, chunk_rows=2).tolist(), [[2.5, 4.5], [10.5, 12.5]])

    def test_box_mean_matches_brute_force(self):
        np = self.np
        a = np.random.default_rng(0).integers(0, 255, (9, 7)).astype(np.float32)
        got = self.r.box_mean(a, 2)
        pad = np.pad(a, 2, mode="edge")
        want = np.array([[pad[y:y + 5, x:x + 5].mean() for x in range(7)] for y in range(9)])
        self.assertTrue(np.allclose(got, want, atol=1e-3))
        self.assertIs(self.r.box_mean(a, 0).dtype, np.dtype(np.float32))

    def test_upsample(self):
        np = self.np
        small = np.array([[1, 2], [3, 4]])
        full = self.r.upsample(small, 5, 3, k=2)
        self.assertEqual(full.tolist(), [[1, 1, 2], [1, 1, 2], [3, 3, 4], [3, 3, 4], [3, 3, 4]])

    def test_open_mask_drops_thin_lines_keeps_blobs(self):
        np = self.np
        score = np.zeros((20, 20), np.float32)
        score[2, :] = 1.0
        score[8:16, 8:16] = 2.0
        out = self.r.open_mask(score, 1)
        self.assertEqual(float(out[2].sum()), 0.0)
        self.assertEqual(float(out[8:16, 8:16].min()), 2.0)
        self.assertEqual(float(score[2].sum()), 20.0, "the input is untouched")


if __name__ == "__main__":
    unittest.main()
