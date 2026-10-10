import argparse
import io
import json
import math
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from load import needs, worker

remote = worker("drive/dmr5-remote.py")


class Dmr5Remote(unittest.TestCase):
    def plan(self, entries):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"entries": entries}, f)
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_biggest_raster_not_a_sidecar(self):
        path = self.plan([{"name": "DMR5/small.tif", "usize": 10}, {"name": "DMR5/big.tif", "usize": 99},
                          {"name": "DMR5/big.tif.ovr", "usize": 999}, {"name": "readme.pdf", "usize": 5000}])
        self.assertEqual(remote.pick_member(path, ""), "DMR5/big.tif")
        self.assertEqual(remote.pick_member(path, "x.tif"), "x.tif")
        with self.assertRaises(SystemExit):
            remote.pick_member(self.plan([{"name": "a.pdf", "usize": 1}]), "")

    def test_sidecar_added_or_replaced(self):
        path = self.plan([{"name": "D/big.tif.ovr", "usize": 1}, {"name": "D/BIG.TFW", "usize": 1}])
        self.assertEqual(remote.find_sidecar(path, "D/big.tif", ".ovr")["name"], "D/big.tif.ovr")
        self.assertEqual(remote.find_sidecar(path, "D/big.tif", ".tfw")["name"], "D/BIG.TFW")
        self.assertIsNone(remote.find_sidecar(path, "D/big.tif", ".aux.xml"))
        self.assertIsNone(remote.find_sidecar("/nonexistent.json", "D/big.tif", ".ovr"))

    def test_vsi_path(self):
        self.assertEqual(remote.vsi_path("https://x/a.zip", "D/b.tif"), "/vsizip//vsicurl/https://x/a.zip/D/b.tif")


@needs("numpy", "PIL")
class RocksShadingOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = worker("rocks-shading/build.py")

    def ap(self):
        ap = argparse.ArgumentParser()
        ap.add_argument("--options", default="")
        ap.add_argument("--solid", type=int, default=0)
        ap.add_argument("--fill-holes", type=int, default=0)
        return ap

    def apply(self, options):
        ap = self.ap()
        with mock.patch.object(sys, "argv", ["build.py", f"--options={options}"]), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return self.b.apply_options(ap, ap.parse_args())

    def test_options_become_flags(self):
        got = self.apply("plne=1 fill-holes=1")
        self.assertEqual((got.solid, got.fill_holes), (1, 1))

    def test_typo_is_an_error(self):
        for bad in ("solidd=1", "solid"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                self.apply(bad)

    def test_histogram(self):
        import numpy as np
        rows = [(np.full((4, 4), 10, np.uint8), None), (np.full((4, 4), 250, np.uint8), None)]
        text = self.b.histogram(rows)
        self.assertIn("50.0 %", text)
        self.assertEqual(self.b.histogram([]), "")


@needs("numpy")
class MeasureResampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = worker("dem/measure-resampling.py")

    def test_rows_sum_to_one(self):
        for kernel in ("average", "average-exact", "bilinear", "cubicspline", "near"):
            with self.subTest(kernel=kernel):
                w = self.m.weights(100, 1.0, 20, 5.0, kernel)
                self.assertTrue(all(abs(s - 1) < 1e-9 for s in w.sum(axis=1)))

    def test_flat_stays_flat(self):
        import numpy as np
        flat = np.full((60, 60), 250.0)
        out = self.m.resample(flat, 1.0, 5.0, "cubicspline")
        self.assertTrue(np.allclose(out, 250.0))


class MeasureSmoothing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.m = worker("contours-rocks/measure-smoothing.py")
        except ImportError as err:
            raise unittest.SkipTest(str(err))

    def test_simplify_keeps_ends_and_corners(self):
        line = [(0, 0), (1, 0.01), (2, 0), (3, 5), (4, 0)]
        out = self.m.simplify(line, 0.1)
        self.assertEqual(out, [(0, 0), (2, 0), (3, 5), (4, 0)])
        self.assertEqual(self.m.simplify(line, 0), line)

    def test_chaikin_keeps_ends(self):
        out = self.m.chaikin([(0, 0), (4, 0), (4, 4)], 2)
        self.assertEqual((out[0], out[-1]), ((0, 0), (4, 4)))
        self.assertEqual(len(out), 2 + 2 * (2 + 2 * 2 - 1))

    def test_quantize(self):
        self.assertEqual(self.m.quantize([(1.2, 3.7)], 0.5), [(1.0, 3.5)])


if __name__ == "__main__":
    unittest.main()
