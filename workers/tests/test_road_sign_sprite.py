import json
import os
import tempfile
import unittest

from load import needs, needs_cmd, worker

sp = worker("transport/sprite.py")
sg = worker("transport/signs.py")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
       '<circle cx="50" cy="50" r="48" fill="red"/></svg>')


def sign(root, category, folder, country, code, names=None):
    d = os.path.join(root, "signs", category, folder, country)
    os.makedirs(d)
    name = f"{folder}-{country}"
    with open(os.path.join(d, name + ".svg"), "w") as f:
        f.write(SVG)
    with open(os.path.join(d, name + ".json"), "w") as f:
        json.dump({"sign": folder, "category": category, "country": country,
                   "code": code, "image": {"file": name + ".svg"}}, f)
    with open(os.path.join(root, "signs", category, folder, folder + ".json"), "w") as f:
        json.dump(names or {"en": folder}, f)


class Mapping(unittest.TestCase):
    def test_every_key_names_a_folder(self):
        with open(sp.MAPPING, encoding="utf-8") as f:
            mapping = json.load(f)
        for country, by_key in mapping.items():
            if country.startswith("_"):
                continue
            self.assertRegex(country, r"^[a-z]{2}$")
            names = {}
            for key, folder in by_key.items():
                self.assertRegex(folder, r"^[a-z-]+/[a-z0-9-]+$", key)
                name = sg.mapped_name(key, country)
                self.assertTrue(name, f"{country}: {key}")
                self.assertEqual(names.setdefault(name, folder), folder,
                                 f"{country}: {name} points at two images")


class Entries(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        sign(self.root, "regulatory", "speed-limit-50", "sk", "253-50")
        sign(self.root, "regulatory", "stop", "sk", "202", {"en": "Stop", "sk": "Stoj"})
        sign(self.root, "regulatory", "give-way", "sk", "201")
        sign(self.root, "warning", "danger", "sk", "101")
        self.mapping = os.path.join(self.root, "road-signs.json")
        with open(self.mapping, "w") as f:
            json.dump({"sk": {"SK:P1": "regulatory/give-way", "SK:202": "regulatory/stop",
                              "stop": "regulatory/stop", "highway=stop": "regulatory/stop",
                              "maxspeed=50": "regulatory/speed-limit-50",
                              "SK:101": "warning/danger"},
                       "at": {"AT:52.1": "regulatory/no-vehicles", "AT:52.24": "regulatory/stop"}}, f)
        sign(self.root, "regulatory", "no-vehicles", "sk", "201", {"en": "No vehicles"})
        self.used = {"sk.ts.p1": 9, "sk.ts.202": 4, "sk.ts.stop": 100,
                     "sk.ts.maxspeed-50": 2, "sk.ts.nothing": 7}

    def entries(self, used):
        return sp.entries(self.root, "sk", used, self.mapping)

    def test_only_the_folders_the_region_uses(self):
        self.assertEqual(set(sp.needed("sk", self.used, self.mapping).values()),
                         {"regulatory/give-way", "regulatory/stop", "regulatory/speed-limit-50"})
        self.assertEqual(sp.needed("sk", {}, self.mapping), {})

    def test_a_foreign_sign_is_drawn_as_the_home_one(self):
        by_country = sg.folders(self.mapping)
        self.assertEqual(sg.at_home("at.ts.52.24", "sk", by_country), "sk.ts.202",
                         "the home key of that meaning")
        name = sg.at_home("at.ts.52.1", "sk", by_country)
        self.assertEqual(name, "sk.ts.no-vehicles", "no home key: the folder's name")
        self.assertEqual(sg.at_home("at.ts.99", "sk", by_country), "at.ts.99", "unknown abroad")
        got = self.entries({name: 3})
        self.assertEqual([v["names"] for v in got.values()], [["sk.ts.no-vehicles"]])
        self.assertTrue(next(iter(got)).endswith("no-vehicles-sk.svg"))

    def test_a_country_with_no_mapping(self):
        self.assertEqual(sp.needed("cz", {"cz.ts.p1": 1}, self.mapping), {})

    def test_uses_are_the_regions_own_count(self):
        stop = next(v for v in self.entries(self.used).values() if v["sign"] == "regulatory/stop")
        self.assertEqual(sorted(stop["names"]), ["sk.ts.202", "sk.ts.stop"])
        self.assertEqual(stop["uses"], 104)
        self.assertEqual(stop["label"], {"en": "Stop", "sk": "Stoj"})

    def test_translations_fill_languages_without_an_official_name(self):
        os.makedirs(os.path.join(self.root, "names"))
        for language, name in (("sk", "Stoj!"), ("hu", "Állj")):
            with open(os.path.join(self.root, "names", language + ".json"), "w") as f:
                json.dump({"regulatory/stop": name, "warning/danger": "x"}, f)
        stop = next(v for v in self.entries(self.used).values() if v["sign"] == "regulatory/stop")
        self.assertEqual(stop["label"], {"en": "Stop", "sk": "Stoj", "hu": "Állj"})

    def test_a_folder_missing_from_the_checkout_is_skipped(self):
        self.assertEqual(self.entries({"sk.ts.101": 1, "sk.ts.p1": 1}).keys(),
                         self.entries({"sk.ts.p1": 1}).keys() | self.entries({"sk.ts.101": 1}).keys())
        os.remove(os.path.join(self.root, "signs/warning/danger/sk/danger-sk.svg"))
        self.assertEqual(self.entries({"sk.ts.101": 1}), {})

    def test_used_file_reads_counts(self):
        path = os.path.join(self.root, "used.txt")
        with open(path, "w") as f:
            f.write("sk.ts.202\t4\nsk.ts.stop\t100\n")
        self.assertEqual(sp.read_used(path), {"sk.ts.202": 4, "sk.ts.stop": 100})

    @needs("PIL")
    @needs_cmd("rsvg-convert")
    def test_sheet_names_point_at_one_cut_with_the_legend(self):
        base = os.path.join(self.root, "r-roadsigns")
        sp.write(self.entries(self.used), base)
        with open(base + "@2x.json") as f:
            index = json.load(f)
        stop = index["sk.ts.stop"]
        self.assertEqual((stop["x"], stop["y"]), (index["sk.ts.202"]["x"], index["sk.ts.202"]["y"]))
        self.assertEqual((stop["height"], stop["pixelRatio"]), (2 * sp.SIDE, 2))
        self.assertEqual((stop["category"], stop["uses"], stop["label"]["sk"]),
                         ("regulatory", 104, "Stoj"))
        self.assertNotIn("sk.ts.101", index, "the region has no SK:101, so no image")


if __name__ == "__main__":
    unittest.main()


class EveryLimit(unittest.TestCase):
    def test_a_region_carries_every_limit_its_country_has(self):
        used = sp.with_every_limit("sk", {"sk.ts.maxspeed-40": 3, "sk.ts.stop": 1})
        self.assertEqual(used["sk.ts.maxspeed-40"], 3)
        self.assertEqual(used["sk.ts.stop"], 1)
        for kph in (30, 50, 90, 130):
            self.assertIn(f"sk.ts.maxspeed-{kph}", used)
        self.assertFalse([n for n in used if n.endswith("_end") and n not in ("sk.ts.stop",)])
        self.assertTrue(set(sp.needed("sk", used)) >= {"sk.ts.maxspeed-30", "sk.ts.maxspeed-130"})
