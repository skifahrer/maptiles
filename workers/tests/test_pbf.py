import json
import os
import shutil
import subprocess
import tempfile
import unittest

from load import WORKERS, needs, needs_cmd
from stubs import shadow_workers
import mini_region
import rangeserver

ROOT = os.path.dirname(WORKERS)
LOCAL = {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"}
SUDO = '#!/bin/sh\n[ "$1" = apt-get ] && exit 0\nexec "$@"\n'


def mini_pbf(tmp):
    osm = os.path.join(tmp, "mini.osm")
    with open(osm, "w", encoding="utf-8") as f:
        f.write(mini_region.build().xml())
    pbf = os.path.join(tmp, "mini.osm.pbf")
    subprocess.run(["osmium", "cat", "--overwrite", osm, "-o", pbf], check=True)
    with open(pbf, "rb") as f:
        return f.read()


def count(pbf):
    out = subprocess.run(["osmium", "fileinfo", "-e", "-g", "data.count.nodes", pbf],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


@needs_cmd("osmium", "curl", "jq")
@needs("osmium")
class RegionPbf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.blob = mini_pbf(self.tmp)
        self.server, self.base = rangeserver.serve({"/europe/mini.osm.pbf": self.blob})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def pbf(self, **opts):
        work = os.path.join(self.tmp, f"w{len(os.listdir(self.tmp))}")
        os.makedirs(os.path.join(work, "steps-out"))
        os.symlink(WORKERS, os.path.join(work, "workers"))
        stubs = os.path.join(work, "stubs")
        os.makedirs(stubs)
        with open(os.path.join(stubs, "sudo"), "w") as f:
            f.write(SUDO)
        os.chmod(os.path.join(stubs, "sudo"), 0o755)
        out = os.path.join(work, "out")
        env = {**os.environ, **LOCAL, "PATH": stubs + os.pathsep + os.environ["PATH"],
               "GITHUB_OUTPUT": out, "GITHUB_STEP_SUMMARY": os.devnull,
               "OPT_CUSTOM_PBF_URL": f"{self.base}/europe/mini.osm.pbf", "OPT_CUSTOM_NAME": "Malá Obec",
               "OPT_CUSTOM_BBOX": ",".join(map(str, mini_region.BBOX)), "OPT_CROP_BBOX": "",
               "OPT_TEST_KM2": "0", "OPT_TEST_AT": "", "OPT_AREA_BBOX": "", "AREA_IN": "", **opts}
        r = subprocess.run(["bash", "workers/plan/pbf.sh"], cwd=work, env=env, capture_output=True, text=True)
        outputs = {}
        if os.path.exists(out):
            with open(out) as f:
                outputs = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)
        return r, outputs, os.path.join(work, "data", "region.osm.pbf")

    def test_custom_region(self):
        r, out, pbf = self.pbf()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((out["key"], out["name"]), ("mala_obec", "Malá Obec"))
        self.assertEqual(out["bbox"], ",".join(map(str, mini_region.BBOX)))
        self.assertEqual(out["dem_bboxkey"], out["dem_bbox"].replace(",", "_").replace(".", "_"))
        with open(pbf, "rb") as f:
            self.assertEqual(f.read(), self.blob)

    def test_no_bbox_anywhere_is_an_error(self):
        r, out, _ = self.pbf(OPT_CUSTOM_BBOX="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no bbox in its header", r.stdout)

    def test_crop(self):
        _, whole, whole_pbf = self.pbf()
        r, out, pbf = self.pbf(OPT_CROP_BBOX="17.12,48.12,17.16,48.15")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((out["key"], out["bbox"]), ("mala_obec_crop", "17.12,48.12,17.16,48.15"))
        self.assertLess(count(pbf), count(whole_pbf))

    def test_quick_test_shrinks_the_map(self):
        r, out, pbf = self.pbf(OPT_TEST_KM2="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out["key"], "mala_obec_test1")
        self.assertEqual(out["bbox"], out["dem_bbox"], "the map is the square")
        self.assertEqual(out["test_bbox"], out["bbox"])
        w, s, e, n = map(float, out["bbox"].split(","))
        self.assertAlmostEqual((e - w) * 111.32 * 0.667 * (n - s) * 110.54, 1, delta=0.1)

    def test_bad_crop_fails(self):
        r, _, _ = self.pbf(OPT_CROP_BBOX="nonsense")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Cropping to bbox 'nonsense' failed", r.stdout)


@needs_cmd("osmium", "curl")
class RoutingPbf(unittest.TestCase):
    def test_extracts_merged_not_cut(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        blob = mini_pbf(tmp)
        area = {"areas": {"two": {"pbf": ["europe/a", "europe/b"]}}}
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        shadow = shadow_workers(work, {})
        os.remove(os.path.join(shadow, "data"))
        os.makedirs(os.path.join(shadow, "data"))
        with open(os.path.join(shadow, "data", "routing-areas.json"), "w") as f:
            json.dump(area, f)
        server, base = rangeserver.serve({"/europe/a-latest.osm.pbf": blob, "/europe/b-latest.osm.pbf": blob})
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        out = os.path.join(work, "out")
        r = subprocess.run(["bash", "workers/routing/pbf.sh"], cwd=work, capture_output=True, text=True,
                           env={**os.environ, **LOCAL, "AREA": "two", "OSMFR_BASE": base, "GITHUB_OUTPUT": out})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        merged = os.path.join(work, "data", "routing.osm.pbf")
        with open(os.path.join(tmp, "one.osm.pbf"), "wb") as f:
            f.write(blob)
        self.assertEqual(count(merged), count(os.path.join(tmp, "one.osm.pbf")), "shared nodes unified by id")
        r = subprocess.run(["bash", "workers/routing/pbf.sh"], cwd=work, capture_output=True, text=True,
                           env={**os.environ, **LOCAL, "AREA": "three", "OSMFR_BASE": base, "GITHUB_OUTPUT": out})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't in workers/data/routing-areas.json", r.stderr)


if __name__ == "__main__":
    unittest.main()
