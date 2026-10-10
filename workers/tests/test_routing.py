import datetime
import gzip
import io
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from load import needs, worker

order = worker("routing/order.py", name="order")
profile = worker("routing/profile.py")


def grid(n):
    """An n×n street grid as a network: nodes in e7, edges between neighbours."""
    nodes = {r * n + c + 1: (int((48 + r * 0.001) * 1e7), int((17 + c * 0.001) * 1e7))
             for r in range(n) for c in range(n)}
    edges = []
    for r in range(n):
        for c in range(n):
            u = r * n + c + 1
            if c + 1 < n:
                edges.append({"from": u, "to": u + 1})
            if r + 1 < n:
                edges.append({"from": u, "to": u + n})

    def neighbours():
        out = {u: set() for u in nodes}
        for h in edges:
            out[h["from"]].add(h["to"])
            out[h["to"]].add(h["from"])
        return out
    return SimpleNamespace(nodes=nodes, edges=edges, neighbours=neighbours)


class Order(unittest.TestCase):
    def test_a_permutation(self):
        net = grid(20)
        got = order.order(list(net.nodes), order.Neighbours(net))
        self.assertEqual(sorted(got), sorted(net.nodes))

    def test_separator_splits_and_goes_last(self):
        net = grid(20)
        nb = order.Neighbours(net)
        a, b, sep = order._cut(sorted(net.nodes), nb)
        self.assertTrue(a and b and sep)
        self.assertLessEqual(len(sep), 25, "a straight cut across a 20×20 grid")
        a_set = set(a)
        self.assertFalse([u for u in b if nb[u] & a_set], "the halves touch past the separator")
        got = order.order(list(net.nodes), nb)
        self.assertEqual(set(got[-len(sep):]), set(sep))

    def test_small_group_isnt_cut(self):
        net = grid(5)
        self.assertEqual(order.order(list(net.nodes), order.Neighbours(net)), sorted(net.nodes))

    def test_cover_covers_every_edge(self):
        rnd = random.Random(3)
        edges = [(rnd.randrange(30), rnd.randrange(30, 60)) for _ in range(80)]
        cover = order._cover(edges)
        self.assertTrue(all(u in cover or v in cover for u, v in edges))

    def test_components(self):
        nb = {1: {2}, 2: {1}, 3: {4, 5}, 4: {3}, 5: {3}, 6: set()}
        self.assertEqual(order._components(list(nb), nb), [[3, 4, 5], [1, 2], [6]])

    def test_id_stable(self):
        self.assertEqual(order._id({1: 0, 2: 1}), order._id({2: 1, 1: 0}))
        self.assertNotEqual(order._id({1: 0, 2: 1}), order._id({1: 1, 2: 0}))


PROFILES = {
    "modes": {"auto": {"options": ["avoid_motorway", "top_speed", "vignettes", "surface"],
                       "costing": {"valhalla": "auto", "graphhopper": "car"}},
              "bus": {"options": [], "costing": {"valhalla": "bus"}, "needs_gtfs": True}},
    "options": {
        "avoid_motorway": {"name": "a", "type": "switch",
                           "valhalla": {"set": {"use_highways": 0}},
                           "graphhopper": {"priority": [{"if": "road_class == MOTORWAY", "multiply_by": "0"}]}},
        "top_speed": {"name": "t", "type": "speed", "range": [30, 160],
                      "valhalla": {"set_value": "top_speed"},
                      "graphhopper": {"speed": [{"if": "true", "limit_to": "{value}"}]}},
        "surface": {"name": "s", "type": "enum", "values": ["paved", "any"],
                    "valhalla": {"unsupported": ["no such knob"]}, "graphhopper": {}},
        "vignettes": {"name": "v", "type": "switch", "valhalla": {"unsupported": ["no vignettes"]},
                      "graphhopper": {"priority_template": [{"if": "country == {alpha3} && ({classes})",
                                                             "multiply_by": "0"}]}},
    },
    "engines": {"valhalla": {}, "graphhopper": {}},
}
VIGNETTES = {"countries": {
    "SK": {"sells_vignette": True, "alpha3": "SVK", "required_on": ["motorway"], "state": "verified"},
    "AT": {"sells_vignette": True, "alpha3": "AUT", "required_on": ["motorway", "trunk"], "state": "unverified"},
    "PL": {"sells_vignette": False}}}
TRIP = datetime.date(2026, 9, 1)


class Profile(unittest.TestCase):
    def setUp(self):
        self.p = profile.Profile(PROFILES, VIGNETTES)

    def test_coerce(self):
        self.assertIs(self.p.coerce("avoid_motorway", "ano"), True)
        self.assertEqual(self.p.coerce("top_speed", "110"), 110.0)
        self.assertEqual(self.p.coerce("surface", "paved"), "paved")
        for key, text in (("avoid_motorway", "maybe"), ("top_speed", "200"), ("surface", "gravel")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.p.coerce(key, text)

    def test_options_must_be_offered(self):
        self.p.check_option("auto", "top_speed")
        with self.assertRaises(ValueError):
            self.p.check_option("bus", "top_speed")
        with self.assertRaises(ValueError):
            self.p.check_mode("plane")

    def test_vignettes(self):
        avoid, notes = self.p.vignette_state({"SK": "2026-08-31"}, TRIP)
        self.assertEqual(sorted(avoid), ["AT", "SK"], "unsaid and expired are avoided")
        self.assertTrue(any("valid until" in n for n in notes))
        self.assertTrue(any("UNVERIFIED" in n and "AT" in n for n in notes))
        avoid, _ = self.p.vignette_state({"SK": "yes", "AT": "2027-01-01"}, TRIP)
        self.assertEqual(avoid, {})

    def test_valhalla_says_what_it_cant(self):
        out = self.p.compile("auto", {"avoid_motorway": True, "top_speed": 110.0, "surface": "paved",
                                      "vignettes": True}, {"SK": "no"}, TRIP, "valhalla")
        self.assertEqual(out["costing_options"]["auto"], {"use_highways": 0, "top_speed": 110.0})
        self.assertEqual(sorted(m["option"] for m in out["_unsupported"]), ["surface", "vignettes"])

    def test_graphhopper_model(self):
        out = self.p.compile("auto", {"top_speed": 110.0, "avoid_motorway": False, "vignettes": True},
                             {"SK": "no", "AT": "yes"}, TRIP, "graphhopper")
        self.assertEqual(out["custom_model"]["speed"], [{"if": "true", "limit_to": "110"}])
        self.assertEqual(out["custom_model"]["priority"],
                         [{"if": "country == SVK && (road_class == MOTORWAY)", "multiply_by": "0"}])
        self.assertTrue(out["ch.disable"])

    def test_missing_costing_and_gtfs_note(self):
        with self.assertRaises(ValueError):
            self.p.compile("bus", {}, {}, TRIP, "graphhopper")
        self.assertTrue(any("GTFS" in n for n in self.p.compile("bus", {}, {}, TRIP, "valhalla")["_notes"]))

    def test_coverage(self):
        rows = {r["option"]: r for r in self.p.coverage()}
        self.assertEqual((rows["surface"]["valhalla"], rows["surface"]["graphhopper"]), ("no", "missing"))
        self.assertEqual(rows["top_speed"]["graphhopper"], "yes")

    def test_real_lookup_loads(self):
        real = profile.Profile()
        for mode, spec in real.modes.items():
            for key in spec["options"]:
                with self.subTest(mode=mode, option=key):
                    real.check_option(mode, key)

    def test_as_text(self):
        self.assertEqual((profile.as_text(110.0), profile.as_text(0.5), profile.as_text(3)), ("110", "0.5", "3"))


class Crosscheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = worker("routing/crosscheck.py")

    def test_pairs_within_distance(self):
        net = grid(10)
        net.edges = [dict(h, tags=[("highway", sorted(self.c.SHARED)[0])]) for h in net.edges]
        got = self.c.pairs(net, 20, seed=1, min_m=300, max_m=800)
        self.assertEqual(len(got), 20)
        self.assertTrue(all(a != b and 300 <= d <= 800 for a, b, d in got))
        self.assertEqual(got, self.c.pairs(net, 20, seed=1, min_m=300, max_m=800))

    def test_air_m(self):
        self.assertAlmostEqual(self.c.air_m((480000000, 170000000), (490000000, 170000000)), 111195, delta=5)


@needs("pmtiles")
class Fixture(unittest.TestCase):
    def test_archives_read_back(self):
        from pmtiles.reader import MmapSource, Reader, all_tiles
        fixture = worker("routing/fixture.py")
        fmt = fixture.fmt
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                argv, sys.argv = sys.argv, ["fixture.py", f"--out={tmp}"]
                try:
                    self.assertEqual(fixture.main(), 0)
                finally:
                    sys.argv = argv
            names = sorted(n for n in os.listdir(tmp) if n.endswith(".pmtiles"))
            self.assertEqual(len(names), 6)
            orders, splits = {}, {}
            for path in [os.path.join(tmp, n) for n in names] + [os.path.join(tmp, "other-order", "routing-fixture-east.pmtiles")]:
                with open(path, "r+b") as f:
                    reader = Reader(MmapSource(f))
                    graph = reader.metadata()["graph"]
                    bodies = [fmt.read(gzip.decompress(d)) for _, d in all_tiles(reader.get_bytes)]
                self.assertEqual(len(bodies), graph["tiles"], path)
                self.assertTrue(all(b["edges"] for b in bodies), path)
                orders[path] = graph["order"]
                splits[os.path.basename(path)] = graph["split"]
            self.assertGreater(splits["routing-fixture.pmtiles"], 0, "the dense part splits")
            self.assertEqual(len(set(orders.values())), 2, "one shared order, one deliberately other")


if __name__ == "__main__":
    unittest.main()
