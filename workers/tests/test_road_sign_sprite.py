import json
import os
import tempfile
import unittest

from load import needs, needs_cmd, worker

sp = worker("transport/sprite.py")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
       '<circle cx="50" cy="50" r="48" fill="red"/></svg>')


def sign(root, category, folder, country, code):
    d = os.path.join(root, "signs", category, folder, country)
    os.makedirs(d)
    name = f"{folder}-{country}"
    with open(os.path.join(d, name + ".svg"), "w") as f:
        f.write(SVG)
    with open(os.path.join(d, name + ".json"), "w") as f:
        json.dump({"sign": folder, "category": category, "country": country,
                   "code": code, "image": {"file": name + ".svg"}}, f)


class Entries(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        sign(self.root, "regulatory", "speed-limit-50", "sk", "253-50")
        sign(self.root, "regulatory", "stop", "sk", "202")
        sign(self.root, "regulatory", "stop", "cz", "P 6")
        sign(self.root, "additional-panel", "distance", "sk", "501")

    def names(self, country):
        return sorted(n for v in sp.entries(self.root, country).values() for n in v)

    def test_codes_and_osm_words(self):
        self.assertEqual(self.names("sk"), ["sk.ts.202", "sk.ts.253-50",
                                            "sk.ts.maxspeed-50", "sk.ts.stop"])

    def test_codes_are_spelled_as_signs_py_spells_them(self):
        self.assertIn("cz.ts.p6", self.names("cz"))

    def test_a_country_without_signs(self):
        self.assertEqual(sp.entries(self.root, "xx"), {})

    @needs("PIL")
    @needs_cmd("rsvg-convert")
    def test_sheet_names_point_at_one_cut(self):
        base = os.path.join(self.root, "r-roadsigns")
        sp.write(sp.entries(self.root, "sk"), base)
        with open(base + "@2x.json") as f:
            index = json.load(f)
        self.assertEqual(index["sk.ts.253-50"], index["sk.ts.maxspeed-50"])
        self.assertEqual((index["sk.ts.stop"]["height"], index["sk.ts.stop"]["pixelRatio"]),
                         (2 * sp.SIDE, 2))
        self.assertTrue(os.path.getsize(base + ".png") > 0)


if __name__ == "__main__":
    unittest.main()
