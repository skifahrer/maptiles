import io
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout

from load import needs_cmd, worker
from geo import hill, write_dem
from stubs import shadow_workers

# --get copies from FAKE_STORE/<store>/, --rm logs; the real store.py talks to Drive
FAKE_STORE = """import os, shutil, sys
args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
root = os.path.join(os.environ["FAKE_STORE"], args.get("--store", ""))
if "--rm" in sys.argv:
    with open(os.path.join(os.environ["FAKE_STORE"], "removed"), "a") as f:
        f.write(args["--name"] + "\\n")
    sys.exit(0)
if "--get" in sys.argv:
    got = 0
    for name in args.get("--name", "").split():
        src = os.path.join(root, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(args["--dir"], name))
            got += 1
    sys.exit(0 if got or "--missing-ok" in sys.argv else 1)
"""
BBOX = "19.2,49.2,20.8,49.8"


@needs_cmd("gdalinfo", "gdal_translate", "gdalbuildvrt")
class Fetch(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work)
        shadow_workers(self.work, {"drive/store.py": FAKE_STORE})
        self.store = os.path.join(self.work, "store")

    def tile(self, store, name, box, cells=50):
        os.makedirs(os.path.join(self.store, store), exist_ok=True)
        w, s, e, n = box
        rows = round((n - s) / ((e - w) / cells))
        write_dem(os.path.join(self.store, store, name), hill(cells)[:rows], box)

    def fetch(self, source="sonny", area="whole", bbox=BBOX):
        r = subprocess.run(["bash", "workers/dem/fetch.sh", bbox, "dem/x", "", source, area], cwd=self.work,
                           capture_output=True, text=True,
                           env={**os.environ, "FAKE_STORE": self.store, **{k: "" for k in (
                               "DEM_STORE", "DMR5_STORE", "DMR35_STORE", "UGKK_STORE", "SONNY1_STORE")}})
        removed = os.path.join(self.store, "removed")
        if not os.path.exists(removed):
            return r, []
        with open(removed) as f:
            return r, f.read().split()

    def test_whole_tiles_make_a_mosaic(self):
        self.tile("dem-sonny", "N49E019.tif", (19, 49, 20, 50))
        self.tile("dem-sonny", "N49E020.tif", (20, 49, 21, 50))
        r, gone = self.fetch()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.work, "dem/x/all.vrt")))
        self.assertEqual(gone, [])

    def test_a_tile_short_of_its_degree_is_deleted(self):
        self.tile("dem-dmr5-v2", "N49E019.tif", (19, 49, 20, 50))
        self.tile("dem-dmr5-v2", "N49E020.tif", (20, 49, 20.5, 49.5), cells=25)
        r, gone = self.fetch(source="dmr5")
        self.assertEqual(gone, ["N49E020.tif"])
        self.assertEqual(r.returncode, 3, "dmr5 short of the area stops the build")
        self.assertIn("covers only", r.stdout)

    def test_sonny_short_only_warns(self):
        self.tile("dem-sonny", "N49E019.tif", (19, 49, 20, 50))
        r, _ = self.fetch()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::The Sonny mosaic covers only", r.stdout)

    def test_empty_store(self):
        self.assertEqual(self.fetch()[0].returncode, 1, "without Sonny there is nothing to fall back to")
        self.assertEqual(self.fetch(source="dmr35")[0].returncode, 3)

    def test_empty_tile_from_an_old_check_is_dishonest(self):
        self.tile("dem-dmr5-v2", "N49E019.tif", (19, 49, 20, 50))
        tiles = worker("dem/tiles.py")
        os.makedirs(os.path.join(self.store, "dem-dmr5-v2"), exist_ok=True)
        dst = os.path.join(self.store, "dem-dmr5-v2", "N49E020.tif")
        with redirect_stdout(io.StringIO()):
            self.assertTrue(tiles.empty_tile(dst, 20, 49, "Float32", None))
        subprocess.run(["gdal_translate", "-q", "-mo", f"{tiles.EMPTY_TAG}=v1", dst, dst + ".v1.tif"], check=True)
        os.replace(dst + ".v1.tif", dst)
        r, gone = self.fetch(source="dmr5")
        self.assertIn("N49E020.tif", gone)

    def test_cutout_from_the_store(self):
        self.tile("dem-ugkk", "ugkk-vysoke_tatry.tif", (20, 49.1, 20.3, 49.25), cells=30)
        r, _ = self.fetch(source="dmr5", area="vysoke_tatry", bbox="20,49.1,20.3,49.25")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.work, "dem/x/all.vrt")) as f:
            self.assertIn("ugkk-vysoke_tatry.tif", f.read())
        r, _ = self.fetch(source="dmr5", area="male_karpaty", bbox="17,48,17.3,48.3")
        self.assertEqual(r.returncode, 3)


if __name__ == "__main__":
    unittest.main()
