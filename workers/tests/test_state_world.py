import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from load import needs, worker

queue = worker("state/queue.py")
world = worker("world/sources.py")

REGIONS = {
    "slovensko": {"country": "slovensko", "admin_level": 2},
    "bratislavsky": {"country": "slovensko", "admin_level": 4},
    "trnavsky": {"country": "slovensko", "admin_level": 4},
    "svet": {"country": "svet", "admin_level": 2},
    "tirol": {"country": "rakusko", "admin_level": 4},
}


class Queue(unittest.TestCase):
    def test_regions_in_registry_order(self):
        self.assertEqual(queue.regions_of(REGIONS, "slovensko"), ["bratislavsky", "trnavsky"])
        self.assertEqual(queue.regions_of(REGIONS, "svet"), [])

    def test_countries_have_regions(self):
        self.assertEqual(queue.countries(REGIONS), ["slovensko"])

    def test_real_registry(self):
        regions = queue.read()
        for country in queue.countries(regions):
            with self.subTest(country=country):
                self.assertTrue(queue.regions_of(regions, country))


@needs("yaml")
class SummaryInputs(unittest.TestCase):
    WORKFLOW = """
name: x
on:
  workflow_dispatch:
    inputs:
      region: {default: trnavsky}
      dry: {type: boolean, default: false}
      area: {}
env:
  TOKEN: ${{ secrets.TOKEN }}
  STEP: "5"
  EMPTY: ""
"""

    @classmethod
    def setUpClass(cls):
        cls.s = worker("plan/summary-inputs.py")

    def setUp(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False)
        f.write(self.WORKFLOW)
        f.close()
        self.path = f.name
        self.addCleanup(os.remove, f.name)

    def test_defaults(self):
        self.assertEqual(self.s.defaults(self.path), {"region": "trnavsky", "dry": "false", "area": ""})

    def test_env_never_shows_secrets(self):
        with mock.patch.dict(os.environ, {"STEP": "7", "TOKEN": "hunter2"}):
            rows = dict(self.s.env_table(self.path))
        self.assertNotIn("hunter2", rows["TOKEN"])
        self.assertIn("secret", rows["TOKEN"])
        self.assertEqual(rows["STEP"], "`7`")

    def test_text(self):
        self.assertEqual((self.s.text(True), self.s.text(False), self.s.text(" a ")), ("true", "false", "a"))


class World(unittest.TestCase):
    def test_prop(self):
        p = {"name": "Slovensko", "NAME_EN": -99, "name_en": "Slovakia", "RANK": ""}
        self.assertEqual(world.prop(p, "NAME"), "Slovensko")
        self.assertEqual(world.prop(p, "NAME_EN"), "Slovakia")
        self.assertEqual(world.prop(p, "RANK", default=6), 6)

    def test_names_by_language(self):
        got = world.names_by_language({"NAME_DE": "Slowakei", "NAME_ZHT": "斯洛伐克", "NAME_FR": ""})
        self.assertEqual(got, {"name:de": "Slowakei", "name:zh-Hant": "斯洛伐克"})

    def test_human_and_took(self):
        self.assertEqual(world.human(512), "512 B")
        self.assertEqual(world.human(1536), "1.5 kB")
        self.assertEqual(world.took(30), "30 s")
        self.assertEqual(world.took(150), "2.5 min")

    def geojson(self, features):
        f = tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False)
        json.dump({"type": "FeatureCollection", "features": features}, f)
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def prepare(self, fn, features, key):
        out = self.geojson([])
        with mock.patch.dict(world.MINIMUM, {key: 1}), redirect_stdout(io.StringIO()):
            fn(self.geojson(features), out)
        with open(out) as f:
            return [x["properties"] for x in json.load(f)["features"]]

    def test_prepare_countries(self):
        point = {"type": "Point", "coordinates": [19, 48]}
        props = self.prepare(world.prepare_countries, [
            {"geometry": point, "properties": {"NAME": "Slovensko", "NAME_EN": "Slovakia",
                                               "NAME_DE": "Slowakei", "LABELRANK": 2, "ISO_A2": "SK"}},
            {"geometry": point, "properties": {"NAME": "Malta", "LABELRANK": "x"}},
            {"geometry": None, "properties": {"NAME": "Nikde"}},
        ], "countries")
        self.assertEqual([p["name"] for p in props], ["Slovensko", "Malta"])
        self.assertEqual(props[0]["rank"], "major")
        self.assertEqual(props[0]["name:de"], "Slowakei")
        self.assertEqual(props[1]["rank"], "minor")

    def test_prepare_lakes(self):
        poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        props = self.prepare(world.prepare_lakes, [
            {"geometry": poly, "properties": {"name": "Balaton", "scalerank": 1}},
            {"geometry": poly, "properties": {"name": "Malé", "scalerank": 9}},
            {"geometry": poly, "properties": {}},
        ], "lakes")
        self.assertEqual([p["rank"] for p in props], ["major", "minor", "minor"])
        self.assertTrue(all(p["kind"] == "lake" for p in props))

    def test_too_few_features_fail(self):
        poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            world.prepare_lakes(self.geojson([{"geometry": poly, "properties": {}}]), self.geojson([]))

    def test_error_page_is_not_a_layer(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False)
        f.write("<html>502</html>")
        f.close()
        self.addCleanup(os.remove, f.name)
        with self.assertRaises(SystemExit):
            world.read_geojson(f.name, "lakes")


if __name__ == "__main__":
    unittest.main()
