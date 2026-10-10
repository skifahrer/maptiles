import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from load import FIXTURES, WORKERS, needs, worker


def read(path):
    """`{("n"|"w"|"r", id): tags}` of an OSM file."""
    import osmium
    out = {}
    for o in osmium.FileProcessor(path):
        out[(o.type_str(), o.id)] = dict(o.tags)
    return out


@needs("osmium")
class Rail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = worker("rail/lines.py")

    def test_speed(self):
        self.assertEqual(self.r.speed("80;60"), 80)
        self.assertEqual(self.r.speed("50 mph"), 80)
        self.assertIsNone(self.r.speed("none"))
        self.assertIsNone(self.r.speed(""))

    def test_gauge(self):
        self.assertEqual(self.r.gauge("1435;1520"), 1520)
        self.assertIsNone(self.r.gauge("standard"))

    def test_bearing(self):
        p = lambda lat, lon: SimpleNamespace(lat=lat, lon=lon)
        self.assertAlmostEqual(self.r.bearing(p(48, 17), p(49, 17)), 0)
        self.assertAlmostEqual(self.r.bearing(p(48, 17), p(48, 18)), 90, delta=0.5)
        self.assertAlmostEqual(self.r.bearing(p(48, 17), p(47, 17)), 180)

    def test_speed_changes(self):
        self.assertEqual(self.r.speed_changes({1: [(80, "end"), (120, "start")]}), {1: (80, 120)})
        self.assertEqual(self.r.speed_changes({1: [(120, "end"), (80, "start")]}), {1: (120, 80)})
        self.assertEqual(self.r.speed_changes({1: [(120, "start"), (80, "start")]}), {1: (80, 120)})
        self.assertEqual(self.r.speed_changes({1: [(80, "end"), (80, "start")], 2: [(80, "end")]}), {})

    def test_rewrite_writes_a_readable_pbf(self):
        # fix 843: PBF writing broke on pyosmium 3
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "rail.osm.pbf")
            r = subprocess.run([sys.executable, os.path.join(WORKERS, "rail/lines.py"),
                                "--pbf", os.path.join(FIXTURES, "rail.osm"), "--out", out],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            tags = read(out)
        self.assertEqual(tags[("w", 10)]["colour"], "#0000cc", "the tram line wins the colour")
        self.assertEqual(tags[("w", 10)]["route_ref"], "4;R10")
        self.assertEqual(tags[("w", 10)]["rail_gauge"], "1520")
        self.assertEqual(tags[("w", 11)]["colour"], "#cc0000")
        self.assertEqual(tags[("w", 11)]["route_ref"], "R10;Os 3301")
        self.assertEqual((tags[("n", 3)]["rail_speed_prev"], tags[("n", 3)]["rail_speed"]), ("80", "121"))
        self.assertEqual(tags[("n", 2)]["rail_bearing"], "90")
        self.assertEqual(tags[("n", 5)]["rail_bearing"], "270")
        self.assertIn(("r", 20), tags)



@needs("osmium")
class RoutingNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n = worker("routing/network.py")
        cls.fmt = sys.modules["format"]
        cls.net = cls.n.load(os.path.join(FIXTURES, "roads.osm"))

    def edge(self, way):
        [e] = [e for e in self.net.edges if e["way"] == way]
        return e

    def test_only_roads_cut_at_junctions(self):
        self.assertEqual(sorted({e["way"] for e in self.net.edges}), [100, 101, 102, 103, 104])
        self.assertEqual(set(self.net.nodes), {1, 2, 3, 4, 5, 7})
        self.assertEqual(self.edge(104)["geom"], [(482010000, 171210000)])

    def test_direction(self):
        both = self.fmt.D_FORWARD | self.fmt.D_BACKWARD
        self.assertEqual(self.edge(100)["direction"], both)
        self.assertEqual(self.edge(101)["direction"], self.fmt.D_FORWARD)
        self.assertEqual(self.edge(103)["direction"], self.fmt.D_BACKWARD)
        self.assertEqual(self.edge(104)["direction"], self.fmt.D_FORWARD, "a roundabout is one-way")

    def test_length_is_haversine(self):
        expected = self.n._haversine(48.2, 17.1, 48.2, 17.11) * 100
        self.assertAlmostEqual(self.edge(100)["length_cm"], expected, delta=1)
        self.assertAlmostEqual(expected / 100, 741.6, delta=1)

    def test_restrictions(self):
        kinds = self.fmt.RESTRICTION_KINDS
        got = {kinds[r["kind"]]: r for r in self.net.restrictions}
        self.assertEqual(sorted(got), ["no_left_turn", "only_straight_on"])
        self.assertEqual(got["no_left_turn"]["edges"], [(1, 2), (2, 4)])
        self.assertEqual(got["no_left_turn"]["via"], 2)
        spared = {self.fmt.EXCEPTIONS[i] for i in range(len(self.fmt.EXCEPTIONS))
                  if got["no_left_turn"]["exceptions"] >> i & 1}
        self.assertEqual(spared, {"bicycle", "psv"})
        self.assertEqual(got["only_straight_on"]["edges"], [(4, 2), (2, 3), (3, 7)])
        self.assertEqual(self.net.skipped["restriction:hgv"], 1)



def box_m2(dlon, dlat, lat):
    import math
    deg = 6371008.8 * math.pi / 180
    return dlon * deg * math.cos(math.radians(lat)) * dlat * deg


@needs("osmium")
class Buildings(unittest.TestCase):
    def test_area_on_ways_and_multipolygons(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "b.osm.pbf")
            r = subprocess.run([sys.executable, os.path.join(WORKERS, "buildings/areas.py"),
                                "--pbf", os.path.join(FIXTURES, "buildings.osm"), "--out", out],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            tags = read(out)
        house = box_m2(0.0003, 0.0001, 48.15)
        court = box_m2(0.002, 0.001, 48.1605) - box_m2(0.0005, 0.0003, 48.1605)
        self.assertAlmostEqual(int(tags[("w", 100)]["area_m2"]), house, delta=house * 0.01)
        self.assertAlmostEqual(int(tags[("r", 200)]["area_m2"]), court, delta=court * 0.01)
        self.assertNotIn("area_m2", tags[("w", 103)])
        self.assertNotIn("area_m2", tags[("w", 101)])

    def test_ring_area(self):
        a = worker("buildings/areas.py")
        self.assertEqual(a.ring_area([(0, 0), (1, 1), (0, 0)]), 0.0)
        ring = [(17.1, 48.15), (17.1003, 48.15), (17.1003, 48.1501), (17.1, 48.1501), (17.1, 48.15)]
        self.assertAlmostEqual(a.ring_area(ring), box_m2(0.0003, 0.0001, 48.15), delta=1)


@needs("osmium")
class Trails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = worker("trails/routes.py")

    def test_way_class(self):
        self.assertEqual(self.t.way_class({"highway": "path"}), "path")
        self.assertEqual(self.t.way_class({"highway": "Track "}), "path")
        self.assertEqual(self.t.way_class({"highway": "secondary"}), "road")
        self.assertEqual(self.t.way_class({}), "road")

    def test_straight_line_untouched(self):
        line = [[17.0, 48.0], [17.001, 48.0], [17.002, 48.0]]
        self.assertEqual(self.t.ease_corners(line), (line, 0))

    def test_sharp_turn_eased_ends_kept(self):
        # a hairpin: there and almost straight back
        line = [[17.0, 48.0], [17.001, 48.0], [17.0, 48.00002]]
        out, eased = self.t.ease_corners(line)
        self.assertEqual(eased, 1)
        self.assertEqual((out[0], out[-1]), (line[0], line[-1]))
        self.assertGreater(len(out), len(line))
        self.assertNotIn(line[1], out)

    def test_orient_ways(self):
        # 1→2, 3→2 (backwards), 3→4: one chain, the middle one flipped
        flip, conflicts, chains = self.t.orient_ways({10: (1, 2), 11: (3, 2), 12: (3, 4)})
        self.assertEqual((chains, conflicts), (1, 0))
        self.assertEqual(len(flip), 1)
        self.assertEqual(self.t.orient_ways({10: (1, 2), 11: (5, 6)})[2], 2)

    def test_lane_order_stable_and_collapsed(self):
        base = {"route": "hiking", "colour": "red", "hex": "", "tier": "national", "ref": "", "name": ""}
        routes = [dict(base, rel=3, colour="blue", name="Modrá"),
                  dict(base, rel=1, ref="0001", name="Cesta SNP"),
                  dict(base, rel=2, ref="0001", name=""),
                  dict(base, rel=4, route="bicycle", tier="international", ref="EV13")]
        order = [r["rel"] for r in self.t.Ways.lane_order(routes)]
        self.assertEqual(order, [4, 3, 1], "the unnamed part collapses into its named parent")
        self.assertEqual(order, [r["rel"] for r in self.t.Ways.lane_order(list(reversed(routes)))])


if __name__ == "__main__":
    unittest.main()
