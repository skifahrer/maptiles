import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from load import worker

watch = worker("lib/watch.py")
cell = worker("lib/cell.py")
blocks = worker("lib/contour-blocks.py")


class Format(unittest.TestCase):
    def test_hms(self):
        self.assertEqual(watch.hms(0), "0:00:00")
        self.assertEqual(watch.hms(3725.9), "1:02:05")

    def test_gb(self):
        self.assertEqual(watch.gb(512), "512 MB")
        self.assertEqual(watch.gb(1536), "1.5 GB")

    def test_percent(self):
        self.assertEqual(watch.percent(b"0...10...20"), 20.0)
        self.assertEqual(watch.percent(b"0...10.."), 15.0)
        self.assertEqual(watch.percent(b"0...10...20...30...40...50...60...70...80...90...100"), 100.0)
        self.assertIsNone(watch.percent(b"..."))


class RunWatched(unittest.TestCase):
    def run_quiet(self, cmd, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            watch.run_watched(cmd, "t", every=1, **kw)
        return out.getvalue()

    def test_success(self):
        self.assertIn("✔ t: done", self.run_quiet(["true"]))

    def test_exit_code_passes_through(self):
        with self.assertRaises(subprocess.CalledProcessError) as err:
            self.run_quiet([sys.executable, "-c", "raise SystemExit(3)"])
        self.assertEqual(err.exception.returncode, 3)

    def test_time_cap_stops_it(self):
        with self.assertRaises(TimeoutError):
            self.run_quiet(["sleep", "30"], max_s=1)

    def test_progress_and_messages_relayed(self):
        script = ("import sys,time\n"
                  "print('Warning 1: odd pixel', flush=True)\n"
                  "for p in '0...10...20...30...40...50...60...70...80...90...100 - done.':\n"
                  "    sys.stdout.write(p); sys.stdout.flush()\n"
                  "print()\n")
        out = self.run_quiet([sys.executable, "-c", script])
        self.assertIn("t: Warning 1: odd pixel", out)
        for ten in range(10, 100, 10):
            self.assertIn(f"… t: {ten} %", out)


class Cell(unittest.TestCase):
    def test_terrain_zoom(self):
        self.assertEqual(cell.terrain_zoom_for(20), 13)
        self.assertEqual(cell.terrain_zoom_for(5), 15)

    def test_terrain_zoom_clamped(self):
        self.assertEqual(cell.terrain_zoom_for(10_000), 8)
        self.assertEqual(cell.terrain_zoom_for(10_000, lo=5), 5)
        self.assertEqual(cell.terrain_zoom_for(0.01), 16)
        self.assertEqual(cell.terrain_zoom_for(0.01, hi=14), 14)


class ContourBlocks(unittest.TestCase):
    def test_plan_covers_exactly(self):
        for w, h, b in ((1000, 700, 256), (512, 512, 256), (10, 10, 256)):
            with self.subTest(size=(w, h, b)):
                covered = set()
                for x0, y0 in blocks.plan(w, h, b):
                    for x in range(x0, min(x0 + b, w)):
                        for y in range(y0, min(y0 + b, h)):
                            self.assertNotIn((x, y), covered)
                            covered.add((x, y))
                self.assertEqual(len(covered), w * h)

    def seq(self, coords):
        f = tempfile.NamedTemporaryFile("w", suffix=".geojsonl", delete=False)
        self.addCleanup(os.remove, f.name)
        f.write(json.dumps({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}}) + "\n")
        f.close()
        return f.name

    def test_check_metric_catches_degrees(self):
        with self.assertRaises(RuntimeError):
            blocks.check_metric(self.seq([[19.1, 49.1], [19.2, 49.1], [19.2, 49.2], [19.1, 49.1]]))
        self.assertTrue(blocks.check_metric(self.seq([[400000, 5400000], [400100, 5400000],
                                                     [400100, 5400100], [400000, 5400000]])))
        self.assertTrue(blocks.check_metric("/nonexistent.geojsonl"))

    def test_touches(self):
        geom = {"type": "Polygon", "coordinates": [[[5, 5], [10, 5], [10, 10], [5, 5]]]}
        self.assertTrue(blocks._touches(geom, 0, 0, 10, 20, 0.5))
        self.assertFalse(blocks._touches(geom, 0, 0, 20, 20, 0.5))

    def test_area_with_hole(self):
        geom = {"type": "Polygon", "coordinates": [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]]}
        self.assertEqual(blocks._area(geom), 96)


if __name__ == "__main__":
    unittest.main()
