import json
import os
import unittest

from load import FIXTURES, WORKERS, needs, worker

context = worker("routing/context.py", name="context")


class Classify(unittest.TestCase):
    def test_tagged_zone(self):
        self.assertEqual(context.tagged_zone({"source:maxspeed": "SK:urban"}), "urban")
        self.assertEqual(context.tagged_zone({"maxspeed:type": "DE:rural"}), "rural")
        self.assertEqual(context.tagged_zone({"maxspeed": "CZ:living_street"}), "living_street")
        self.assertIsNone(context.tagged_zone({"maxspeed": "50", "source:maxspeed": "sign"}))
        self.assertIsNone(context.tagged_zone({"zone:maxspeed": "SK:30"}))

    def test_road(self):
        self.assertIsNone(context.road({"highway": "footway"}))
        self.assertEqual(context.road({"highway": "primary"}), ("road", None))
        self.assertEqual(context.road({"highway": "motorway_link"}), ("motorway", None))
        self.assertEqual(context.road({"highway": "trunk", "motorroad": "yes"}), ("motorroad", None))
        self.assertEqual(context.road({"highway": "trunk", "zone:traffic": "AT:urban"}),
                         ("road", "urban"))
        self.assertEqual(context.road({"highway": "primary", "maxspeed": "SK:motorway"}),
                         ("motorway", "rural"))
        self.assertEqual(context.road({"highway": "residential", "maxspeed:type": "SK:living_street"}),
                         ("living_street", None))

    def test_name(self):
        self.assertEqual(context.name("road", True), "urban")
        self.assertEqual(context.name("road", False), "rural")
        self.assertEqual(context.name("motorroad", True), "urban_motorroad")
        self.assertEqual(context.name("motorway", False), "motorway")
        self.assertEqual(context.name("living_street", False), "living_street")

    def test_every_name_is_a_context(self):
        names = {context.name(kind, urban) for kind in ("road", "motorway", "motorroad", "living_street")
                 for urban in (True, False)}
        self.assertEqual(names, set(context.CONTEXTS))

    def test_dictionary_lists_the_contexts(self):
        with open(os.path.join(WORKERS, "data", "routing-tags.json"), encoding="utf-8") as f:
            keys = json.load(f)["keys"]
        self.assertEqual(tuple(keys["speed_context"]["values"]), context.CONTEXTS)
        self.assertEqual(list(keys)[-1], "speed_context", "a new key goes last, or old indices move")

    def test_prefilter_keeps_built_up_areas(self):
        tags = worker("routing/tags.py", name="tags")
        self.assertIn("wr/landuse=residential,commercial,retail", tags.filter_expressions())


@needs("shapely", "numpy")
class Shares(unittest.TestCase):
    def setUp(self):
        import shapely
        self.built_up = context.BuiltUp([shapely.box(17.100, 48.200, 17.110, 48.205),
                                         shapely.box(17.1103, 48.200, 17.120, 48.205)])

    def test_inside_and_outside(self):
        inside, outside = self.built_up.shares([[(17.101, 48.202), (17.109, 48.202)],
                                                [(17.101, 48.300), (17.109, 48.300)]])
        self.assertAlmostEqual(inside, 1.0)
        self.assertEqual(outside, 0.0)

    def test_gap_between_areas_is_closed(self):
        [share] = self.built_up.shares([[(17.1101, 48.202), (17.1102, 48.202)]])
        self.assertAlmostEqual(share, 1.0)

    def test_without_areas_all_is_outside(self):
        self.assertEqual(list(context.BuiltUp([]).shares([[(17.1, 48.2), (17.2, 48.2)]])), [0.0])

    def test_point_long_edge(self):
        [share] = self.built_up.shares([[(17.101, 48.202), (17.101, 48.202)]])
        self.assertEqual(share, 0.0)


@needs("osmium", "shapely", "numpy")
class Network(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        n = worker("routing/network.py")
        cls.net = n.load(os.path.join(FIXTURES, "speed-context.osm"))

    def context_of(self, way):
        [edge] = [e for e in self.net.edges if e["way"] == way]
        return edge["tags"].get("speed_context")

    def test_contexts(self):
        expected = {100: "urban", 101: "rural", 102: "motorway", 103: "urban_motorway",
                    104: "motorroad", 105: "living_street", 106: "urban", 107: "rural",
                    108: None, 109: "rural", 110: "urban", 111: "motorway"}
        self.assertEqual({way: self.context_of(way) for way in expected}, expected)

    def test_no_edge_keeps_the_road_scratch(self):
        self.assertFalse([e for e in self.net.edges if "road" in e])

    def test_counted(self):
        self.assertEqual(sum(self.net.contexts.values()), 11)


@needs("osmium", "shapely", "numpy")
class RailNetwork(unittest.TestCase):
    def test_a_tram_on_a_street_gets_no_speed_context(self):
        n = worker("routing/network.py")
        rail = worker("routing/tags.py", name="tags").dictionary(
            os.path.join(WORKERS, "data", "rail-routing-tags.json"))
        net = n.load(os.path.join(FIXTURES, "tram-street.osm"), rail)
        self.assertEqual(len(net.edges), 2)
        self.assertFalse([e for e in net.edges if "speed_context" in e["tags"] or "road" in e])


if __name__ == "__main__":
    unittest.main()
