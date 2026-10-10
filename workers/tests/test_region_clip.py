import os
import subprocess
import tempfile
import unittest

from load import WORKERS
from stubs import Stubs

ROOT = os.path.dirname(WORKERS)
CLIP = "workers/lib/region-clip.sh"
CUT = "workers/lib/region-cut.sh"

POLY = """region
1
   17.25   48.05
   9.5     48.20
   17.40   48.30
   17.25   48.05
END
END
"""

# `-o` must exist for the `mv`; the size changes so the log line differs
OSMIUM = """#!/usr/bin/env bash
echo "$*" >> "$(dirname "$0")/osmium.log"
while [ $# -gt 0 ]; do
  if [ "$1" = -o ]; then printf 'cut' > "$2"; fi
  shift
done
"""


def run(cmd, env=None, path=None):
    full = {**os.environ, **(env or {})}
    if path:
        full["PATH"] = path + os.pathsep + full["PATH"]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=full)


class RegionClip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.poly = os.path.join(self.dir.name, "region.poly")
        with open(self.poly, "w") as f:
            f.write(POLY)

    def tearDown(self):
        self.dir.cleanup()

    def clip(self, bbox, poly, **env):
        r = run(["bash", CLIP, bbox, poly], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split(), r.stderr

    def test_polygon_alone_never_with_bounds(self):
        args, log = self.clip("17.1,48.1,17.2,48.2", self.poly)
        self.assertEqual(args, [f"--polygon={self.poly}"])
        self.assertNotIn("::warning::", log)

    def test_clip_off_gives_padded_bounds_and_warns(self):
        args, log = self.clip("17.1,48.1,17.2,48.2", self.poly, OPT_REGION_CLIP="false")
        self.assertEqual(len(args), 1)
        self.assertTrue(args[0].startswith("--bounds="))
        box = [float(v) for v in args[0].split("=", 1)[1].split(",")]
        for got, want in zip(box, (17.1, 48.1, 17.2, 48.2)):
            self.assertAlmostEqual(got, want, places=6)
        self.assertIn("region_clip=true", log)

    def test_no_polygon_falls_back_to_bounds(self):
        missing = os.path.join(self.dir.name, "none.poly")
        args, log = self.clip("17.1,48.1,17.2,48.2", missing)
        self.assertEqual(args, ["--bounds=17.1,48.1,17.2,48.2"])
        self.assertIn("::warning::", log)

    def test_empty_bbox_without_polygon_gives_nothing(self):
        args, _ = self.clip("", os.path.join(self.dir.name, "none.poly"))
        self.assertEqual(args, [])
        args, _ = self.clip("", self.poly, OPT_REGION_CLIP="false")
        self.assertEqual(args, [])


class RegionCut(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.poly = os.path.join(self.dir.name, "region.poly")
        with open(self.poly, "w") as f:
            f.write(POLY)
        self.pbf = os.path.join(self.dir.name, "water.osm.pbf")
        with open(self.pbf, "w") as f:
            f.write("uncut data")
        self.stubs = Stubs()
        self.stubs.script("osmium", OSMIUM)

    def tearDown(self):
        self.stubs.__exit__()
        self.dir.cleanup()

    def cut(self, bbox, poly, **env):
        r = run(["bash", CUT, self.pbf, bbox, poly], env, self.stubs.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        log = os.path.join(self.stubs.dir, "osmium.log")
        if not os.path.exists(log):
            return [], r.stderr
        with open(log) as f:
            return f.read().splitlines(), r.stderr

    def test_polygon_gives_its_numeric_extent(self):
        calls, _ = self.cut("17.1,48.1,17.2,48.2", self.poly)
        self.assertEqual(len(calls), 1)
        self.assertIn("-b 9.500000,48.050000,17.400000,48.300000", calls[0])
        self.assertIn("-s smart", calls[0])
        with open(self.pbf) as f:
            self.assertEqual(f.read(), "cut")
        self.assertFalse(os.path.exists(self.pbf.replace(".osm.pbf", "-cut.osm.pbf")))

    def test_clip_off_cuts_by_bbox(self):
        calls, _ = self.cut("17.1,48.1,17.2,48.2", self.poly, OPT_REGION_CLIP="false")
        self.assertEqual(len(calls), 1)
        box = calls[0].split("-b ", 1)[1].split()[0]
        self.assertEqual([round(float(v), 6) for v in box.split(",")], [17.1, 48.1, 17.2, 48.2])

    def test_nothing_to_cut_by_keeps_the_pbf(self):
        calls, log = self.cut("", os.path.join(self.dir.name, "none.poly"))
        self.assertEqual(calls, [])
        self.assertIn("::warning::", log)
        with open(self.pbf) as f:
            self.assertEqual(f.read(), "uncut data")


if __name__ == "__main__":
    unittest.main()
