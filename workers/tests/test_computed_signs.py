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


@needs("shapely", "numpy")
class TownSigns(unittest.TestCase):
    """Road 2 through a town sign at 17.10; the village lies east."""

    def setUp(self):
        import shapely
        import context
        self.context = context
        self.ways = {300: way([1, 2, 3], [(17.08, 48.2), (17.10, 48.2), (17.12, 48.2)],
                              highway="primary", ref="2")}
        self.ways[300]["road"] = ("road", None)
        self.contexts = {300: "urban"}
        self.east = context.BuiltUp([shapely.box(17.10, 48.19, 17.13, 48.21)])
        self.nowhere = context.BuiltUp([])

    def found(self, towns, built_up=None):
        return sorted((s["context"], s["direction"]) for s in
                      speed.town_signs(self.ways, self.contexts, towns, built_up or self.east))

    def test_built_up_land_says_where_the_village_is(self):
        self.assertEqual(self.found({2: ("begin", None)}), [("rural", 270), ("urban", 90)])

    def test_the_sign_facing_wins_over_the_land(self):
        self.assertEqual(self.found({2: ("begin", "backward")}), [("rural", 90), ("urban", 270)])
        self.assertEqual(self.found({2: ("end", "forward")}, self.nowhere), [("rural", 90), ("urban", 270)])

    def test_no_evidence_no_sign(self):
        self.assertEqual(self.found({2: ("begin", None)}, self.nowhere), [])

    def test_signed_or_one_way(self):
        self.ways[300]["tags"]["oneway"] = "yes"
        self.assertEqual(self.found({2: ("begin", None)}), [("urban", 90)])
        self.ways[300]["tags"]["maxspeed"] = "50"
        self.assertEqual(self.found({2: ("begin", None)}), [])

    def test_a_motor_road_keeps_its_kind(self):
        self.ways[300]["road"] = ("motorroad", None)
        self.assertEqual(self.found({2: ("begin", None)}), [("motorroad", 270), ("urban_motorroad", 90)])

    def test_town_sign_tags(self):
        self.assertEqual(speed.town_sign({"traffic_sign": "city_limit"}), ("begin", None))
        self.assertEqual(speed.town_sign({"traffic_sign": "city_limit", "city_limit": "end",
                                          "direction": "forward"}), ("end", "forward"))
        self.assertEqual(speed.town_sign({"traffic_sign:backward": "city_limit"}), ("begin", "backward"))
        self.assertIsNone(speed.town_sign({"traffic_sign": "SK:253[50]"}))

    def test_junction_signs_near_a_town_sign_give_way(self):
        town = [{"point": (17.10, 48.2)}]
        near, far = {"point": (17.101, 48.2)}, {"point": (17.2, 48.2)}
        self.assertEqual(speed.merged([near, far], town), town + [far])


class DeadEnds(unittest.TestCase):
    """A village street 1–2–3, short past 2 each way, and a side street 2–10, 111 m north."""

    def setUp(self):
        self.ways = {
            400: way([1, 2, 3], [(17.1015, 48.2), (17.102, 48.2), (17.1025, 48.2)], highway="residential"),
            401: way([2, 11, 10], [(17.102, 48.2), (17.102, 48.2005), (17.102, 48.201)],
                     highway="residential"),
        }
        self.contexts = {400: "urban", 401: "urban"}

    def found(self, signed=frozenset()):
        return [(s["way"], s["direction"]) for s in speed.dead_ends(self.ways, self.contexts, signed)]

    def test_a_side_street_to_nowhere_gets_one_past_its_junction(self):
        [sign] = speed.dead_ends(self.ways, self.contexts)
        self.assertEqual((sign["way"], sign["direction"], sign["kind"]), (401, 0, "dead-end"))
        self.assertAlmostEqual(speed._metres((17.102, 48.2), sign["point"]), speed.DEAD_END_SIGN_M, delta=0.5)

    def test_a_short_one_or_one_out_of_the_village_gets_none(self):
        self.ways[401]["line"][-1] = (17.102, 48.2004)
        self.ways[401]["line"][1] = (17.102, 48.2002)
        self.assertEqual(self.found(), [])
        self.setUp()
        self.contexts[401] = "rural"
        self.assertEqual(self.found(), [])

    def test_a_street_going_on_as_a_track_isnt_one(self):
        self.ways[402] = way([10, 12], [(17.102, 48.201), (17.102, 48.203)], highway="track")
        self.assertEqual(self.found(), [])

    def test_a_driveway_neither_splits_the_street_nor_gets_one(self):
        self.ways[402] = way([11, 12], [(17.102, 48.2005), (17.103, 48.2005)], highway="service")
        self.assertEqual(self.found(), [(401, 0)])

    def test_a_street_of_two_ways(self):
        self.ways[401] = way([2, 11], [(17.102, 48.2), (17.102, 48.2005)], highway="residential")
        self.ways[403] = way([11, 10], [(17.102, 48.2005), (17.102, 48.201)], highway="residential")
        self.contexts[403] = "urban"
        self.assertEqual(self.found(), [(401, 0)])

    def test_a_one_way_out_or_a_mapped_sign(self):
        self.assertEqual(self.found(signed={10}), [])
        self.ways[401]["tags"]["oneway"] = "-1"
        self.assertEqual(self.found(), [])

    def test_a_street_cut_at_the_border_isnt_one(self):
        self.assertEqual(speed.dead_ends(self.ways, self.contexts, in_region=lambda p: p[1] < 48.2008), [])
        self.assertEqual(len(speed.dead_ends(self.ways, self.contexts, in_region=lambda p: True)), 1)

    def test_a_through_road_gets_none(self):
        self.ways[401]["tags"]["highway"] = "secondary"
        self.assertEqual(self.found(), [])

    def test_a_mapped_dead_end_sign(self):
        by_country = worker("transport/signs.py").folders()
        self.assertTrue(speed.dead_end_sign({"traffic_sign": "CZ:IP10a"}, by_country))
        self.assertFalse(speed.dead_end_sign({"traffic_sign": "SK:253[50]"}, by_country))

    def test_its_feature_has_no_speed_context(self):
        [sign] = speed.dead_ends(self.ways, self.contexts)
        [feature] = speed.geojson([sign], "SK")["features"]
        self.assertEqual(feature["properties"], {"kind": "dead-end", "country": "SK", "direction": 0,
                                                 "osm_way": 401})


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

    def test_a_dead_end_street_gets_its_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            geo = os.path.join(tmp, "signs.geojson")
            subprocess.run([sys.executable, os.path.join(WORKERS, "transport", "speed.py"),
                            "--pbf", os.path.join(FIXTURES, "dead-end.osm"),
                            "--out", os.path.join(tmp, "out.osm.pbf"), "--signs", geo, "--country", "sk",
                            "--outline", os.path.join(tmp, "missing.geojson")],
                           check=True, capture_output=True)
            with open(geo, encoding="utf-8") as f:
                features = json.load(f)["features"]
        self.assertEqual([(f["properties"]["kind"], f["properties"]["osm_way"], f["properties"]["direction"])
                          for f in features], [("dead-end", 501, 0)])

    def test_a_mapped_town_sign_places_both_signs(self):
        with tempfile.TemporaryDirectory() as tmp:
            geo = os.path.join(tmp, "signs.geojson")
            subprocess.run([sys.executable, os.path.join(WORKERS, "transport", "speed.py"),
                            "--pbf", os.path.join(FIXTURES, "speed-town-sign.osm"),
                            "--out", os.path.join(tmp, "out.osm.pbf"), "--signs", geo, "--country", "sk"],
                           check=True, capture_output=True)
            with open(geo, encoding="utf-8") as f:
                features = json.load(f)["features"]
        self.assertEqual(sorted((f["properties"]["speed_context"], f["properties"]["direction"])
                                for f in features), [("rural", 270), ("urban", 90)])

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
