import json
import os
import subprocess
import sys
import tempfile
import unittest

from load import FIXTURES, WORKERS, needs, worker

speed = worker("transport/speed.py")


def way(refs, line, **tags):
    return {"tags": tags, "refs": refs, "line": line}


class Transitions(unittest.TestCase):
    """A village on road 2: rural 1–2, urban 2–3, rural 3–4, a side street 3–5."""

    def setUp(self):
        self.ways = {
            200: way([1, 2], [(17.08, 48.2), (17.10, 48.2)], highway="primary", ref="2"),
            201: way([2, 3], [(17.10, 48.2), (17.11, 48.2)], highway="primary", ref="2"),
            202: way([3, 4], [(17.11, 48.2), (17.13, 48.2)], highway="primary", ref="2"),
            203: way([3, 5], [(17.11, 48.2), (17.11, 48.21)], highway="residential"),
        }
        self.contexts = {200: "rural", 201: "urban", 202: "rural", 203: "rural"}

    def found(self):
        return sorted((s["way"], s["context"], s["direction"]) for s in speed.signs(self.ways, self.contexts))

    def test_entry_and_exit_both_ways(self):
        self.assertEqual(self.found(), [(200, "rural", 270), (201, "urban", 90), (201, "urban", 270),
                                        (202, "rural", 90)])

    def test_sign_stands_past_the_junction(self):
        [entry] = [s for s in speed.signs(self.ways, self.contexts)
                   if s["way"] == 201 and s["direction"] == 90]
        self.assertAlmostEqual(speed._metres((17.10, 48.2), entry["point"]), speed.SIGN_M, delta=0.5)

    def test_a_side_street_off_the_road_gets_none(self):
        self.contexts[203] = "urban"
        self.assertNotIn(203, {w for w, _, _ in self.found()})

    def test_a_signed_limit_needs_no_computed_sign(self):
        self.ways[201]["tags"]["maxspeed"] = "50"
        self.assertEqual({w for w, _, _ in self.found()}, {200, 202})

    def test_no_sign_against_a_one_way(self):
        self.ways[201]["tags"]["oneway"] = "yes"
        self.assertEqual([d for w, _, d in self.found() if w == 201], [90])

    def test_same_context_no_sign(self):
        self.contexts[201] = "rural"
        self.assertEqual(self.found(), [])

    def test_continues(self):
        self.assertTrue(speed.continues({"highway": "primary"}, {"highway": "primary"}))
        self.assertTrue(speed.continues({"highway": "primary", "name": "Hlavná"},
                                        {"highway": "secondary", "name": "Hlavná"}))
        self.assertFalse(speed.continues({"highway": "primary", "ref": "2"}, {"highway": "residential"}))


@needs("osmium", "shapely", "numpy")
class Region(unittest.TestCase):
    def test_ways_tagged_and_signs_written(self):
        import osmium
        with tempfile.TemporaryDirectory() as tmp:
            out, geo = os.path.join(tmp, "out.osm.pbf"), os.path.join(tmp, "signs.geojson")
            subprocess.run([sys.executable, os.path.join(WORKERS, "transport", "speed.py"),
                            "--pbf", os.path.join(FIXTURES, "speed-signs.osm"),
                            "--out", out, "--signs", geo, "--country", "sk"],
                           check=True, capture_output=True)
            tagged = {o.id: o.tags.get("speed_context") for o in osmium.FileProcessor(out)
                      if o.type_str() == "w"}
            with open(geo, encoding="utf-8") as f:
                features = json.load(f)["features"]
        self.assertEqual(tagged, {200: "rural", 201: "urban", 202: "rural", 203: "rural", 900: None})
        self.assertEqual(sorted((f["properties"]["osm_way"], f["properties"]["direction"]) for f in features),
                         [(200, 270), (201, 90), (201, 270), (202, 90)])
        self.assertEqual({f["properties"]["country"] for f in features}, {"SK"})

    def test_no_sign_is_an_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            geo = os.path.join(tmp, "signs.geojson")
            subprocess.run([sys.executable, os.path.join(WORKERS, "transport", "speed.py"),
                            "--pbf", os.path.join(FIXTURES, "speed-context.osm"),
                            "--out", os.path.join(tmp, "out.osm.pbf"), "--signs", geo],
                           check=True, capture_output=True)
            self.assertEqual(os.path.getsize(geo), 0, "an empty `features` list kills Planetiler")


if __name__ == "__main__":
    unittest.main()
