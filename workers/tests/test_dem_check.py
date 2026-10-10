import os
import shutil
import subprocess
import tempfile
import unittest

from load import WORKERS
from stubs import shadow_workers

# the store listing comes from STORE_LISTING, one `name:size` a line per store
FAKE_STORE = """import os, sys
store = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--store="))
listing = os.environ.get("STORE_LISTING_" + store.replace("-", "_").upper(), "")
print("\\n".join(x for x in listing.split() if x))
"""
BBOX = "19.9,49.1,20.4,49.3"
BIG = 90_000_000


class DemCheck(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work)
        shadow_workers(self.work, {"drive/store.py": FAKE_STORE})

    def check(self, contours="", rocks="", terrain="", stores=None, **env):
        out = os.path.join(self.work, "out")
        open(out, "w").close()
        listing = {f"STORE_LISTING_{k.replace('-', '_').upper()}": " ".join(v) for k, v in (stores or {}).items()}
        for k in ("DEM_STORE", "DMR5_STORE", "DMR35_STORE", "UGKK_STORE", "SONNY1_STORE"):
            env.setdefault(k, "")
        r = subprocess.run(["bash", "workers/dem/check.sh"], cwd=self.work, capture_output=True, text=True,
                           env={**os.environ, **listing, **env, "BBOX": BBOX, "GITHUB_OUTPUT": out,
                                "SRC_CONTOURS": contours, "SRC_ROCKS": rocks, "SRC_TERRAIN": terrain})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(out) as f:
            return dict(line.split("=", 1) for line in f.read().splitlines()), r.stdout

    def test_tiles_in_the_store(self):
        stores = {"dem-sonny": [f"N49E019.tif:{BIG}", f"N49E020.tif:{BIG}", f"N48E017.tif:{BIG}"]}
        got, _ = self.check(contours="sonny", stores=stores)
        self.assertEqual(got["mirror_contours"], "")
        self.assertEqual(len(got["demkey_contours"]), 12)
        # a refilled tile changes the key, a foreign one doesn't
        again, _ = self.check(contours="sonny", stores={"dem-sonny": stores["dem-sonny"][:2] + [f"N48E017.tif:{BIG + 1}"]})
        self.assertEqual(again["demkey_contours"], got["demkey_contours"])
        changed, _ = self.check(contours="sonny", stores={"dem-sonny": [f"N49E019.tif:{BIG + 1}", f"N49E020.tif:{BIG}"]})
        self.assertNotEqual(changed["demkey_contours"], got["demkey_contours"])

    def test_empty_store_is_refilled(self):
        got, said = self.check(contours="sonny", terrain="sonny")
        self.assertEqual((got["mirror_contours"], got["mirror_terrain"]), ("sonny", ""),
                         "one mirror queued once for two layers")
        self.assertIn("refilled by another layer already", said)

    def test_dmr5_missing_degree(self):
        got, _ = self.check(terrain="dmr5", stores={"dem-dmr5-v2": [f"N49E019.tif:{BIG}"]})
        self.assertEqual(got["mirror_dmr5_tiles"], "20,49,21,50")
        self.assertEqual(got["mirror_dmr5_area"], "")

    def test_dmr5_cutout(self):
        got, _ = self.check(contours="dmr5", AREA_KEY="vysoke_tatry", AREA_BBOX="20.0,49.1,20.3,49.25")
        self.assertEqual((got["mirror_dmr5_area"], got["mirror_dmr5_asset"]),
                         ("20.0,49.1,20.3,49.25", "ugkk-vysoke_tatry.tif"))
        got, _ = self.check(contours="dmr5", AREA_KEY="vysoke_tatry", AREA_BBOX="20.0,49.1,20.3,49.25",
                            stores={"dem-ugkk": ["ugkk-vysoke_tatry.tif:5"]})
        self.assertEqual(got["mirror_dmr5_area"], "")

    def test_terrain_ignores_the_cutout(self):
        got, _ = self.check(terrain="dmr5", AREA_KEY="vysoke_tatry",
                            stores={"dem-dmr5-v2": [f"N49E019.tif:{BIG}", f"N49E020.tif:{BIG}"]})
        self.assertEqual((got["mirror_dmr5_area"], got["mirror_dmr5_tiles"]), ("", ""))

    def test_rocks_from_dmr5_read_drive_directly(self):
        got, said = self.check(rocks="dmr5")
        self.assertEqual((got["mirror_rocks"], got["demkey_rocks"]), ("", ""))
        self.assertIn("slope is read from Drive", said)

    def test_off_layers(self):
        got, said = self.check(contours="none", terrain="ziadne")
        self.assertEqual((got["demkey_contours"], got["mirror_terrain"]), ("", ""))
        self.assertIn("To refill: nothing", said)


if __name__ == "__main__":
    unittest.main()
