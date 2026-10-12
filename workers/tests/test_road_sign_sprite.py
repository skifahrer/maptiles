import json
import os
import tempfile
import unittest

from load import needs, needs_cmd, worker

sp = worker("transport/sprite.py")

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


class Entries(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        sign(self.root, "regulatory", "speed-limit-50", "sk", "253-50")
        sign(self.root, "regulatory", "stop", "sk", "202", {"en": "Stop", "sk": "Stoj"})
        sign(self.root, "regulatory", "give-way", "sk", "201")
        sign(self.root, "warning", "danger", "sk", "101")
        os.makedirs(os.path.join(self.root, "osm"))
        with open(os.path.join(self.root, "osm", "sk.json"), "w") as f:
            json.dump({"signs": {"SK:P1": {"sign": "regulatory/give-way", "count": 9},
                                 "SK:202": {"sign": "regulatory/stop", "count": 4},
                                 "stop": {"sign": "regulatory/stop", "count": 100}},
                       "figures": {"maxspeed": {"50": "regulatory/speed-limit-50"}},
                       "implied": {"stop": "regulatory/stop"},
                       "unmatched": {"SK:B1": 3}}, f)

    def names(self, country):
        return sorted(n for v in sp.entries(self.root, country).values() for n in v["names"])

    def test_only_what_osm_supports(self):
        self.assertEqual(self.names("sk"), ["sk.ts.202", "sk.ts.maxspeed-50", "sk.ts.p1",
                                            "sk.ts.stop"])

    def test_a_region_takes_only_the_signs_it_uses(self):
        got = sorted(n for v in sp.entries(self.root, "sk", {"sk.ts.p1", "sk.ts.nothing"}).values()
                     for n in v["names"])
        self.assertEqual(got, ["sk.ts.p1"])
        self.assertEqual(sp.entries(self.root, "sk", set()), {})

    def test_a_country_osm_has_not_been_read_for(self):
        self.assertEqual(sp.entries(self.root, "cz"), {})

    def test_uses_add_up_per_image(self):
        stop = next(v for v in sp.entries(self.root, "sk").values() if v["sign"] == "regulatory/stop")
        self.assertEqual(stop["uses"], 104)
        self.assertEqual(stop["label"], {"en": "Stop", "sk": "Stoj"})

    @needs("PIL")
    @needs_cmd("rsvg-convert")
    def test_sheet_names_point_at_one_cut_with_the_legend(self):
        base = os.path.join(self.root, "r-roadsigns")
        sp.write(sp.entries(self.root, "sk"), base)
        with open(base + "@2x.json") as f:
            index = json.load(f)
        stop = index["sk.ts.stop"]
        self.assertEqual((stop["x"], stop["y"]), (index["sk.ts.202"]["x"], index["sk.ts.202"]["y"]))
        self.assertEqual((stop["height"], stop["pixelRatio"]), (2 * sp.SIDE, 2))
        self.assertEqual((stop["category"], stop["uses"], stop["label"]["sk"]),
                         ("regulatory", 104, "Stoj"))
        self.assertNotIn("sk.ts.101", index, "OSM has no SK:101, so no image")


if __name__ == "__main__":
    unittest.main()
