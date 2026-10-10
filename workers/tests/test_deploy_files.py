import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest import mock

from load import worker

files = worker("deploy/files.py")
pack = worker("deploy/pack.py")
packages = files.packages


def touch(root, rel, data=b"x"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class Site(unittest.TestCase):
    TREE = ["index.html", "app.js", "style-overrides.json", "fonts/Noto Sans Regular/0-255.pbf",
            "tiles/manifest.json", "tiles/r.pmtiles", "tiles/r-trails.pmtiles", "tiles/r-routing.pmtiles",
            "tiles/r-rail.pmtiles", "tiles/r-rail-routing.pmtiles", "tiles/r-signs.json",
            "tiles/r-signs.png", "tiles/r-water.pmtiles", "tiles/r-terrain.pmtiles",
            "sprites/osm-liberty.json", "styles/r-svetla.json"]

    def setUp(self):
        self.site = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.site)
        for rel in self.TREE:
            touch(self.site, rel)
        self.man = {"default_region": "r", "glyphs": "https://x/fonts/{fontstack}/{range}.pbf",
                    "regions": {"r": {"water": "tiles/r-water.pmtiles", "routing": "tiles/r-routing.pmtiles"}}}

    def rel(self, paths):
        return sorted(os.path.relpath(p, self.site) for p in paths)

    def test_suffix_isnt_a_longer_foreign_one(self):
        self.assertTrue(files.has_suffix("r-routing.pmtiles", ("-routing.pmtiles",)))
        self.assertFalse(files.has_suffix("r-rail-routing.pmtiles", ("-routing.pmtiles",)))
        self.assertTrue(files.has_suffix("r-rail-routing.pmtiles", ("-rail-routing.pmtiles",)))

    def test_package_files_from_manifest_then_suffix(self):
        water = packages.package("water")
        self.assertEqual(self.rel(files.package_files(self.site, self.man, water)), ["tiles/r-water.pmtiles"])
        rail = packages.package("railways")
        self.assertEqual(self.rel(files.package_files(self.site, {}, rail)),
                         ["tiles/r-rail-routing.pmtiles", "tiles/r-rail.pmtiles",
                          "tiles/r-signs.json", "tiles/r-signs.png"])

    def test_parts_of_the_base_map(self):
        parts = {k: self.rel(f) for k, _, f in files.base_parts(self.site, self.man)}
        self.assertEqual(parts, {"trails": ["tiles/r-trails.pmtiles"], "routing": ["tiles/r-routing.pmtiles"],
                                 "signs": ["tiles/r-signs.json", "tiles/r-signs.png"]})
        sizes = files.part_sizes(files.base_parts(self.site, self.man))
        self.assertEqual(sizes["signs"]["files"], 2)
        self.assertEqual(sizes["signs"]["raw_size"], 2)

    def test_viewer_and_glyphs_stay_out(self):
        with redirect_stdout(io.StringIO()):
            out, reasons = files.outside_packages(self.site, self.man)
        self.assertEqual(self.rel(out), ["app.js", "fonts/Noto Sans Regular/0-255.pbf",
                                         "index.html", "style-overrides.json"])
        self.assertIn("https://x/fonts", reasons[1][0])
        self.assertFalse(files.is_viewer(self.site, os.path.join(self.site, "tiles", "manifest.json")))

    def test_base_files_keep_wins(self):
        trails = os.path.join(self.site, "tiles/r-trails.pmtiles")
        water = os.path.join(self.site, "tiles/r-water.pmtiles")
        got = self.rel(files.base_files(self.site, [trails, water], keep=[trails]))
        self.assertIn("tiles/r-trails.pmtiles", got)
        self.assertNotIn("tiles/r-water.pmtiles", got)

    def test_contents_sha(self):
        a = [os.path.join(self.site, r) for r in ("tiles/r.pmtiles", "styles/r-svetla.json")]
        first = files.contents_sha(self.site, a)
        self.assertEqual(first, files.contents_sha(self.site, list(reversed(a))))
        touch(self.site, "styles/r-svetla.json", b"y")
        self.assertNotEqual(first, files.contents_sha(self.site, a))

    def test_zip_has_one_root_and_contents_first(self):
        dest = os.path.join(tempfile.mkdtemp(), "r.zip")
        picked = [os.path.join(self.site, r) for r in ("tiles/r.pmtiles", "styles/r-svetla.json")]
        with redirect_stdout(io.StringIO()):
            pack.pack_zip(self.site, dest, "r", picked, info={"package": "base"})
        with zipfile.ZipFile(dest) as z:
            names = z.namelist()
            self.assertEqual(names[0], f"r/{pack.CONTENTS}")
            self.assertEqual(sorted(names[1:]), ["r/styles/r-svetla.json", "r/tiles/r.pmtiles"])
            self.assertEqual(json.loads(z.read(names[0])), {"package": "base"})


class PublishContents(unittest.TestCase):
    def test_contents_says_what_the_file_holds(self):
        env = {"REGION_KEY": "trnavsky_test4", "AREA_KEY": "", "TEST_KM2": "0", "MAP_LAYERS": "",
               "GITHUB_RUN_NUMBER": "5", "TRAILS_ENABLED": "true"}
        with mock.patch.dict(os.environ, env):
            publish = worker("deploy/publish-map.py")
            got = publish.contents("water", {"glyphs": "https://g", "default_region": "r", "regions": {"r": {}}}, "aar")
            base = publish.contents("", {}, parts=[("trails", "t", [])])
        self.assertEqual((got["package"], got["format"], got["region"], got["area"]), ("water", "aar", "trnavsky", "whole"))
        self.assertTrue(got["file"].endswith("-water.aar"))
        self.assertTrue(got["no_glyphs"] and got["no_viewer"])
        self.assertNotIn("parts", got)
        self.assertEqual(base["parts"]["trails"]["files"], 0)
        self.assertIn("trails", base["layers"])


if __name__ == "__main__":
    unittest.main()
