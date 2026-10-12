import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from load import worker

catalog = worker("deploy/catalog.py")
merge = worker("deploy/catalog-merge.py").merge
packages = catalog.packages
folder = catalog.folder


def record(fid, name="trnavsky.zip"):
    return {"file": name, "link": folder.file_link(fid), "download": folder.download_link(fid)}


class Names(unittest.TestCase):
    def test_split_test(self):
        self.assertEqual(catalog.split_test("vysoke_tatry_test4km2"), ("vysoke_tatry", "4"))
        self.assertEqual(catalog.split_test("x_test0.5km2"), ("x", "0.5"))
        self.assertEqual(catalog.split_test("vysoke_tatry"), ("vysoke_tatry", ""))
        self.assertEqual(catalog.split_test("x_testerkm2"), ("x_testerkm2", ""))

    def test_catalog_file(self):
        with mock.patch.dict(os.environ, {"TEST_KM2": "0"}):
            self.assertEqual(catalog.catalog_file(), "maps.json")
        with mock.patch.dict(os.environ, {"TEST_KM2": "4"}):
            self.assertEqual(catalog.catalog_file(), "maps-test.json")
            self.assertEqual(catalog.catalog_file("maps-test.json"), "maps-test.json")
            self.assertEqual(catalog.catalog_file(""), "")

    def test_catalog_name_never_made_up(self):
        regions = {"trnavsky": {"name": "Trnavský kraj"}}
        self.assertEqual(catalog.catalog_name(regions, "trnavsky", "region"), "Trnavský kraj")
        self.assertEqual(catalog.catalog_name(regions, "trnavsky_test4km2", "region"),
                         "Trnavský kraj – quick test 4 km²")
        self.assertEqual(catalog.catalog_name({}, "neznamy", "region"), "neznamy")

    def test_registry_rename_reaches_the_catalog(self):
        regions = {"kosicky": {"name": "Košice Region"}}
        node = {"name": "Košický kraj"}
        catalog.name_node(node, regions, "kosicky", "region")
        self.assertEqual(node["name"], "Košice Region")
        test = {"name": "Košický kraj – quick test 4 km²"}
        catalog.name_node(test, regions, "kosicky_test4km2", "region")
        self.assertEqual(test["name"], "Košice Region – quick test 4 km²")
        unknown = {"name": "Kept"}
        catalog.name_node(unknown, {}, "neznamy", "region")
        self.assertEqual(unknown["name"], "Kept")
        fresh = {}
        catalog.name_node(fresh, {}, "neznamy", "region")
        self.assertEqual(fresh["name"], "neznamy")

    def test_countries_are_english_regions_native(self):
        with open(os.path.join(catalog._DATA, "regions.json"), encoding="utf-8") as f:
            regions = json.load(f)
        self.assertEqual(regions["slovensko"]["name"], "Slovakia")
        self.assertEqual(regions["kosicky"]["name"], "Košický kraj")
        slovak = ("Slovensko", "Česko", "Rakúsko", "Navigácia", "Svet")
        for key, r in regions.items():
            if r.get("admin_level") == 2:
                for word in slovak:
                    self.assertNotIn(word, r["name"], key)

    def test_tiles_paths(self):
        man = {"dem": "https://x/tiles/trnavsky-terrain.pmtiles"}
        reg = {"pmtiles": "tiles/t.pmtiles", "trails": "tiles/t-trails.pmtiles", "bbox": [1, 2, 3, 4]}
        self.assertEqual(catalog.tiles_paths(man, reg), {
            "pmtiles": "tiles/t.pmtiles", "trails": "tiles/t-trails.pmtiles",
            "terrain": "tiles/trnavsky-terrain.pmtiles"})
        self.assertNotIn("terrain", catalog.tiles_paths({"dem": "https://aws/{z}/{x}/{y}.png"}, reg))


class RegionIds(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(catalog._DATA, "regions.json")) as f:
            self.regions = json.load(f)

    def test_osmfr_path(self):
        names = catalog.names
        self.assertEqual(names.osmfr_id("europe/slovakia-latest.osm.pbf"), "slovakia")
        self.assertEqual(names.osmfr_id(
            "https://download.openstreetmap.fr/extracts/europe/france/rhone_alpes/"
            "savoie-latest.osm.pbf"), "france-rhone_alpes-savoie")
        self.assertEqual(names.osmfr_id("north-america/us-west/california-latest"),
                         "us_west-california")
        self.assertEqual(names.osmfr_id("russia/ural_federal_district-latest"),
                         "russia-ural_federal_district")

    def test_registry_ids_are_unique_and_follow_osmfr(self):
        ids = [r["id"] for r in self.regions.values()]
        self.assertEqual(len(ids), len(set(ids)))
        for key, r in self.regions.items():
            self.assertRegex(r["id"], r"^[a-z0-9_]+(-[a-z0-9_]+)*$", key)
            if r.get("osmfr"):
                path = f"{r['osmfr']['dir']}/{r['osmfr']['slugs'][0]}"
                self.assertEqual(r["id"], catalog.names.osmfr_id(path), key)

    def test_every_node_stamped(self):
        data = {"_comment": "x", "slovensko": {"regions": {
            "presovsky": {"subregions": {"pieniny": {}}},
            "presovsky_test4km2": {}}, "subregions": {"vysoke_tatry": {}}},
            "austria": {"regions": {"tirol": {}}}}
        catalog.stamp_ids(data, self.regions)
        sk = data["slovensko"]
        self.assertEqual(sk["id"], "slovakia")
        self.assertEqual(sk["regions"]["presovsky"]["id"], "slovakia-presovsky")
        self.assertEqual(sk["regions"]["presovsky"]["subregions"]["pieniny"]["id"],
                         "slovakia-presovsky-pieniny")
        self.assertEqual(sk["regions"]["presovsky_test4km2"]["id"],
                         "slovakia-presovsky_test4km2")
        self.assertEqual(sk["subregions"]["vysoke_tatry"]["id"], "slovakia-vysoke_tatry")
        self.assertEqual(data["austria"]["regions"]["tirol"]["id"], "austria-tirol")
        self.assertNotIn("id", data)


class Migrate(unittest.TestCase):
    def test_old_keys_become_today(self):
        old, new = next((o, n) for o, n in packages.legacy().items() if n != "base")
        data = {"_comment": "x", "slovensko": {"regions": {"trnavsky": {"maps": {
            old: {"popis": "d"},
            "base": {"casti": {"trasy": {"popis": "t"}}}}}}}}
        maps = catalog.migrate(data)["slovensko"]["regions"]["trnavsky"]["maps"]
        self.assertNotIn(old, maps)
        self.assertEqual(maps[new], {"description": "d"})
        self.assertEqual(maps["base"], {"parts": {"trails": {"description": "t"}}})


class Prune(unittest.TestCase):
    def test_live_kept_dead_revived_or_dropped(self):
        maps = {"base": dict(record("A"), formats={"zip": record("A"), "aar": record("B", "trnavsky.aar")}),
                "trails": record("C", "trnavsky-trails.zip"),
                "water": record("D", "trnavsky-water.zip")}
        live = {"A": "trnavsky.zip", "E": "trnavsky-trails.zip"}
        fixed, dropped = catalog.prune_dead(maps, live)
        self.assertEqual(fixed, ["trails (trnavsky-trails.zip)"])
        self.assertEqual(sorted(dropped), ["base/aar (trnavsky.aar)", "water (trnavsky-water.zip)"])
        self.assertEqual(list(maps["base"]["formats"]), ["zip"])
        self.assertEqual(catalog.link_id(maps["trails"]), "E")
        self.assertNotIn("water", maps)

    def test_protected_and_ambiguous(self):
        maps = {"base": record("A")}
        self.assertEqual(catalog.prune_dead(maps, {}, protected=("A",)), ([], []))
        twice = {"X": "trnavsky.zip", "Y": "trnavsky.zip"}
        self.assertEqual(catalog.revival(record("A"), twice), "")

    def test_top_follows_a_live_format(self):
        maps = {"base": dict(record("OLD"), formats={"aar": record("B", "t.aar")})}
        catalog.prune_dead(maps, {"B": "t.aar"})
        self.assertEqual(catalog.link_id(maps["base"]), "B")


class Write(unittest.TestCase):
    def test_package_record(self):
        maps = {}
        with mock.patch.dict(os.environ, {"GITHUB_RUN_NUMBER": "7"}):
            catalog.write_package(maps, "", "t.aar", 10, "B", "aar", sha="s1")
            catalog.write_package(maps, "", "t.zip", 20, "A", "zip", at="2026", at_ts=1)
        base = maps["base"]
        self.assertEqual(sorted(base["formats"]), ["aar", "zip"])
        self.assertEqual((base["file"], base["run"]), ("t.zip", "7"), "the top mirrors the ZIP")
        self.assertEqual(base["app"], packages.package("base")["app"])

    def test_unchanged_isnt_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            path = os.path.join(tmp, "maps.json")
            self.assertTrue(catalog.write(path, {"b": 1, "a": {"č": 2}}, "x"))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"a":{"č":2},"b":1}\n')
            self.assertFalse(catalog.write(path, {"a": {"č": 2}, "b": 1}, "x"))

    def test_parts(self):
        maps = {"base": {"parts": {"old": {}}}}
        catalog.write_parts(maps, {"trails": {"size": 0}})
        self.assertEqual(maps["base"]["parts"], {"trails": {"size": 0}})
        catalog.write_parts(maps, {})
        self.assertNotIn("parts", maps["base"])
        other = {}
        catalog.write_parts(other, {"trails": {}})
        self.assertEqual(other, {})


class Merge(unittest.TestCase):
    def test_three_way(self):
        base = {"sk": {"a": 1, "b": 1, "gone": 1}}
        mine = {"sk": {"a": 2, "b": 1}}
        theirs = {"sk": {"a": 1, "b": 3, "gone": 1, "new": 4}, "cz": {}}
        self.assertEqual(merge(base, mine, theirs), {"sk": {"a": 2, "b": 3, "new": 4}, "cz": {}})

    def test_untouched_keys_keep_theirs(self):
        self.assertEqual(merge({"x": 1}, {"x": 1}, {"x": 9}), {"x": 9})


class Packages(unittest.TestCase):
    def test_registry_holds_together(self):
        keys = packages.keys()
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("base", keys)
        for old, new in packages.legacy().items():
            self.assertNotIn(old, keys, f"{old} is both legacy and live")
        for p in packages.listing():
            if p.get("part_of"):
                self.assertIn(p["part_of"], keys)
                self.assertIn(p["key"], packages.subpackages(p["part_of"]))

    def test_unknown_package_is_an_error(self):
        with self.assertRaises(SystemExit):
            packages.package("neexistuje")

    def test_credits_follow_the_model(self):
        dem = [p["key"] for p in packages.listing() if any(s.startswith("dem:") for s in p.get("sources") or ())]
        self.assertTrue(dem)
        a = packages.credits(dem[0], {"contours": "sonny", "rocks": "sonny", "shading": "sonny"})
        b = packages.credits(dem[0], {"contours": "dmr5", "rocks": "dmr5", "shading": "dmr5"})
        self.assertTrue(a and b)
        self.assertNotEqual(a, b)
        self.assertEqual(packages.credits(dem[0], {"contours": "?"}),
                         packages.credits(dem[0], {"contours": packages.DEFAULT_MODEL}))


if __name__ == "__main__":
    unittest.main()
