import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from load import worker

carry_over = worker("deploy/carry-over.py")
catalog = worker("deploy/catalog.py")


class Carry(unittest.TestCase):
    OLD = ["roads/contents.json", "roads/tiles/r-transport.pmtiles", "roads/tiles/r-routing.pmtiles",
           "roads/tiles/r-omt-roads.pmtiles", "roads/fragments/roads/r-zakladna-svetla.json",
           "roads/fragments/roads/sprites/roads-osm-liberty.png"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.site = os.path.join(self.tmp, "_site")
        os.makedirs(os.path.join(self.site, "tiles"))
        with open(os.path.join(self.site, "tiles", "r-transport.pmtiles"), "wb") as f:
            f.write(b"new")
        self.zip = os.path.join(self.tmp, "r-roads.zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            for name in self.OLD:
                z.writestr(name, b"old")

    def test_the_cut_and_fragments_come_back_the_rebuilt_layer_doesnt(self):
        kept = carry_over.carry(self.zip, self.site, "roads")
        self.assertEqual(sorted(kept), ["fragments/roads/r-zakladna-svetla.json",
                                        "fragments/roads/sprites/roads-osm-liberty.png",
                                        "tiles/r-omt-roads.pmtiles"])
        with open(os.path.join(self.site, "tiles", "r-transport.pmtiles"), "rb") as f:
            self.assertEqual(f.read(), b"new")

    def test_a_layer_file_the_run_left_out_stays_out(self):
        self.assertFalse(carry_over.carried("tiles/r-routing.pmtiles", "roads", lambda r: False))
        self.assertFalse(carry_over.carried("contents.json", "roads", lambda r: False))
        self.assertTrue(carry_over.carried("tiles/r-omt-roads.pmtiles", "roads", lambda r: False))
        self.assertTrue(carry_over.carried("region.geojson", "paths", lambda r: False))


class LastCopy(unittest.TestCase):
    def test_the_package_zip_of_this_region(self):
        data = {"slovensko": {"regions": {"bratislavsky": {"maps": {"roads": {"formats": {"zip": {
            "download": "https://drive.google.com/uc?export=download&id=ABC",
            "file": "bratislavsky-roads.zip", "size": 12}}}}}}}}
        path = os.path.join(tempfile.mkdtemp(), "maps.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path))
        with open(path, "w") as f:
            json.dump(data, f)
        with mock.patch.object(carry_over.names, "drive_path", return_value=["slovensko", "bratislavsky"]):
            self.assertEqual(carry_over.last_copy(path, "roads"),
                             {"id": "ABC", "size": 12, "name": "bratislavsky-roads.zip"})
            self.assertIsNone(carry_over.last_copy(path, "water"))

    def test_node_at_reads_without_making(self):
        data = {"slovensko": {"regions": {}}}
        self.assertEqual(catalog.node_at(data, ["slovensko", "kosicky"]), {})
        self.assertEqual(data, {"slovensko": {"regions": {}}})


if __name__ == "__main__":
    unittest.main()
