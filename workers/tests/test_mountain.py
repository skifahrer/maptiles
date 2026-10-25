import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from load import WORKERS, worker

ROOT = os.path.dirname(WORKERS)
plan = worker("mountain/plan.py")
manifest = worker("mountain/manifest.py")
styles = worker("mountain/styles.py")
names = worker("deploy/names.py")
catalog = worker("deploy/catalog.py")

CLEAR = {k: "" for k in ("REGION_KEY", "AREA_KEY", "CUSTOM_PBF_URL", "CUSTOM_NAME",
                         "TEST_KM2", "MAP_LAYERS", "MOUNTAIN_COUNTRY")}


def env(**kw):
    return mock.patch.dict(os.environ, {**CLEAR, **kw})


def registry(name):
    with open(os.path.join(WORKERS, "data", name), encoding="utf-8") as f:
        return json.load(f)


class Registry(unittest.TestCase):
    def test_every_mountain_has_a_country_and_a_cut_out(self):
        areas, regions = registry("areas.json"), registry("regions.json")
        for key, entry in registry("mountains.json").items():
            if key.startswith("_"):
                continue
            self.assertEqual(regions[entry["country"]]["admin_level"], 2, key)
            self.assertIn(entry["area"], areas, key)

    def test_the_form_offers_every_mountain(self):
        import yaml
        with open(os.path.join(ROOT, ".github", "workflows", "build-mountain-region.yml")) as f:
            flow = yaml.safe_load(f)
        on = flow.get("on") or flow.get(True)
        offered = on["workflow_dispatch"]["inputs"]["mountain"]["options"]
        known = [k for k in registry("mountains.json") if not k.startswith("_")]
        self.assertEqual(sorted(offered), sorted(known))

    def test_exaggeration_is_the_styles(self):
        with open(os.path.join(ROOT, "poc", "web", "themes.js"), encoding="utf-8") as f:
            found = re.search(r"DEFAULT_TERRAIN_EXAGGERATION = ([\d.]+)", f.read())
        self.assertEqual(float(found.group(1)), manifest.TERRAIN_EXAGGERATION)


class Plan(unittest.TestCase):
    def test_a_range_resolves_to_its_country_and_cut_out(self):
        got = plan.plan("vysoke_tatry")
        self.assertEqual((got["key"], got["country"], got["area"], got["area_key"]),
                         ("vysoke_tatry", "slovensko", "vysoke_tatry", "vysoke_tatry"))
        self.assertEqual(got["name"], "Vysoké Tatry")
        self.assertEqual(got["bbox"], "19.9,49.09,20.32,49.25")
        self.assertEqual(got["bboxkey"], "19_9_49_09_20_32_49_25")

    def test_a_test_never_shares_keys_with_the_real_one(self):
        got = plan.plan("vysoke_tatry", test_km2=4)
        self.assertEqual((got["key"], got["area_key"]), ("vysoke_tatry_test4", "vysoke_tatry_test4"))
        self.assertEqual(names.strip_test(got["key"]), "vysoke_tatry")
        self.assertLess(float(got["km2"]), 5)

    def test_unknown_range(self):
        with self.assertRaises(SystemExit):
            plan.plan("alpy")

    def test_outline_is_the_bbox(self):
        ring = plan.outline([1, 2, 3, 4])["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(ring, [[1, 2], [3, 2], [3, 4], [1, 4], [1, 2]])


class Manifest(unittest.TestCase):
    def site(self, *kinds):
        site = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, site)
        os.makedirs(os.path.join(site, "tiles"))
        for kind in kinds:
            open(os.path.join(site, "tiles", f"vysoke_tatry-{kind}.pmtiles"), "wb").close()
        return site

    def test_says_what_the_layers_really_are(self):
        site = self.site("contours", "rocks", "terrain")
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="19.9,49.09,20.32,49.25",
                 CONTOUR_INTERVAL="2.5", CONTOURS_MAXZOOM="16", ROCKS_MAXZOOM="16",
                 ROCK_SLOPE="50", ROCKS_SOURCE="dmr5", CONTOURS_SOURCE="dmr5",
                 TERRAIN_MAXZOOM="16", TERRAIN_SOURCE="dmr5", MOUNTAIN_NAME="Vysoké Tatry"):
            got = manifest.manifest(site)
        reg = got["regions"]["vysoke_tatry"]
        self.assertEqual(reg["contour_interval"], 2.5)
        self.assertEqual(reg["bbox"], [19.9, 49.09, 20.32, 49.25])
        self.assertEqual(reg["contours"], "tiles/vysoke_tatry-contours.pmtiles")
        self.assertEqual((got["dem"], got["dem_maxzoom"], got["terrain_3d"]),
                         ("tiles/vysoke_tatry-terrain.pmtiles", 16, True))
        self.assertEqual(catalog.tiles_paths(got, reg)["terrain"], "tiles/vysoke_tatry-terrain.pmtiles")

    def test_a_missing_layer_is_left_out(self):
        site = self.site("contours")
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="1,2,3,4", CONTOUR_INTERVAL="5"):
            got = manifest.manifest(site)
        self.assertNotIn("rocks", got["regions"]["vysoke_tatry"])
        self.assertNotIn("dem", got)
        self.assertEqual(got["regions"]["vysoke_tatry"]["contour_interval"], 5)

    def test_nothing_to_package_fails(self):
        site = self.site()
        with env(REGION_KEY="vysoke_tatry", AREA_BBOX="1,2,3,4"), \
                redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            manifest.main([site])


class Names(unittest.TestCase):
    def test_drive_folder_is_under_the_countrys_mountains(self):
        with env(REGION_KEY="vysoke_tatry", AREA_KEY="whole", MOUNTAIN_COUNTRY="slovensko"):
            self.assertEqual(names.drive_path({}), ["slovensko", "mountains", "vysoke_tatry"])
            self.assertEqual(names.file_name("contours"), "vysoke_tatry-contours.zip")

    def test_a_test_gets_its_own_node(self):
        with env(REGION_KEY="vysoke_tatry_test4", AREA_KEY="whole", TEST_KM2="4",
                 MOUNTAIN_COUNTRY="slovensko"):
            parts = names.drive_path({})
            self.assertEqual(parts, ["slovensko", "mountains", "vysoke_tatry"])
            self.assertEqual(names.catalog_path(parts)[-1], "vysoke_tatry_test4km2")
            self.assertEqual(names.file_name("rocks"), "vysoke_tatry-test4km2-rocks.zip")

    def test_a_region_is_untouched(self):
        with env(REGION_KEY="presovsky", AREA_KEY="whole"):
            self.assertEqual(names.drive_path({"presovsky": {"country": "slovensko"}}),
                             ["slovensko", "presovsky"])


class Catalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = os.path.join(self.tmp, "maps.json")
        self.regions = registry("regions.json")
        with open(self.path, "w") as f:
            json.dump({"slovensko": {"name": "Slovakia", "regions": {"presovsky": {"maps": {}}}}}, f)

    def write(self, parts, man, uploaded, **kw):
        with redirect_stdout(io.StringIO()):
            catalog.write_catalog(self.path, parts, self.regions, uploaded, man,
                                  owns=[k for k, *_ in uploaded], **kw)
        with open(self.path) as f:
            return json.load(f)

    def mountain(self):
        man = {"default_region": "vysoke_tatry", "dem": "tiles/vysoke_tatry-terrain.pmtiles",
               "dem_maxzoom": 16, "dem_source": "dmr5",
               "regions": {"vysoke_tatry": {"bbox": [19.9, 49.09, 20.32, 49.25],
                                            "contours": "tiles/vysoke_tatry-contours.pmtiles",
                                            "contours_maxzoom": 16, "contour_interval": 2.5}}}
        uploaded = [("contours", "vysoke_tatry-contours.zip", 10, "id1", "zip", "a" * 64),
                    ("terrain", "vysoke_tatry-terrain.zip", 20, "id2", "zip", "b" * 64)]
        return self.write(["slovensko", "mountains", "vysoke_tatry"], man, uploaded)

    def test_a_mountain_sits_under_its_country(self):
        data = self.mountain()
        node = data["slovensko"]["mountains"]["vysoke_tatry"]
        self.assertEqual((node["id"], node["name"]), ("slovakia-vysoke_tatry", "Vysoké Tatry"))
        self.assertEqual(node["contour_interval"], 2.5)
        self.assertEqual(node["terrain_maxzoom"], 16)
        self.assertEqual(sorted(node["maps"]), ["contours", "terrain"])
        self.assertNotIn("area_bbox", node)
        self.assertNotIn("vysoke_tatry", data["slovensko"]["regions"])

    def test_a_country_build_keeps_its_mountains(self):
        self.mountain()
        man = {"default_region": "slovensko", "regions": {"slovensko": {"bbox": [16, 47, 23, 50]}}}
        data = self.write(["slovensko"], man, [("", "slovensko.zip", 5, "id3", "zip", "c" * 64)])
        self.assertIn("vysoke_tatry", data["slovensko"]["mountains"])
        self.assertIn("presovsky", data["slovensko"]["regions"])


class Publish(unittest.TestCase):
    def test_a_mountain_publishes_its_layers_and_no_base_map(self):
        site = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, site)
        os.makedirs(os.path.join(site, "tiles"))
        for kind in ("contours", "rocks", "terrain"):
            with open(os.path.join(site, "tiles", f"vysoke_tatry-{kind}.pmtiles"), "wb") as f:
                f.write(b"x")
        with open(os.path.join(site, "tiles", "manifest.json"), "w") as f:
            json.dump({"default_region": "vysoke_tatry", "regions": {"vysoke_tatry": {}}}, f)
        os.makedirs(os.path.join(site, "styles"))
        with open(os.path.join(site, "styles", "vysoke_tatry-light.json"), "w") as f:
            f.write("{}")
        run = subprocess.run(
            ["python3", os.path.join(WORKERS, "deploy", "publish-map.py"),
             f"--site={site}", "--maps=", "--dry-run"],
            capture_output=True, text=True,
            env={**os.environ, **CLEAR, "REGION_KEY": "vysoke_tatry", "AREA_KEY": "whole",
                 "MOUNTAIN_COUNTRY": "slovensko"})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        listed = re.findall(r"^\s+(vysoke_tatry\S*\.zip)", run.stdout, re.M)
        self.assertEqual(sorted(listed), ["vysoke_tatry-contours.zip", "vysoke_tatry-rocks.zip",
                                          "vysoke_tatry-terrain.zip"])
        self.assertIn("slovensko/mountains/vysoke_tatry", run.stdout)
        self.assertEqual(len(re.findall(r"vysoke_tatry-\w+\.zip .* – 2 files", run.stdout)), 3,
                         "each package carries the styles beside its archive")


class Styles(unittest.TestCase):
    def test_the_map_builds_style_keeps_the_ranges_layers_alone(self):
        if not shutil.which("node"):
            self.skipTest("node")
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        built = subprocess.run(
            ["node", os.path.join(WORKERS, "styles", "build.mjs"), "--base-url=https://mountain.invalid",
             "--region=vysoke_tatry", "--name=Vysoké Tatry", "--contours=true", "--rocks=true",
             "--dem-source=dmr5", "--dem-tiles-source=dmr5", "--dem-maxzoom=16",
             "--dem-tiles=pmtiles://https://mountain.invalid/tiles/vysoke_tatry-terrain.pmtiles",
             f"--out={out}"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        with redirect_stdout(io.StringIO()):
            styles.main([out])
        with open(os.path.join(out, "vysoke_tatry-svetla.json"), encoding="utf-8") as f:
            style = json.load(f)
        self.assertEqual(sorted(style["sources"]), ["contours", "dem", "rocks"])
        self.assertEqual(style["terrain"]["source"], "dem")
        self.assertNotIn("sprite", style)
        drawn = {layer.get("source") for layer in style["layers"]}
        self.assertEqual(drawn - {None}, {"contours", "rocks"} | ({"dem"} & drawn))
        self.assertTrue(any(layer["type"] == "background" for layer in style["layers"]))

    def test_a_style_without_the_ranges_layers_fails(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        with open(os.path.join(out, "x-light.json"), "w") as f:
            json.dump({"sources": {"omt": {}}, "layers": [{"id": "a", "source": "omt"}]}, f)
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            styles.main([out])


if __name__ == "__main__":
    unittest.main()
