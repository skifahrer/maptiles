import math
import unittest
from types import SimpleNamespace

from load import needs, worker


@needs("numpy")
class Heights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.h = worker("routing/heights.py")
        cls.fmt = worker("routing/format.py", name="format")

    def test_bilinear(self):
        np = self.np
        grid = np.array([[0.0, 10.0], [20.0, 30.0]])
        got = self.h.bilinear(grid, np.array([0.0, 1.0, 0.0, 0.5]), np.array([0.0, 0.0, 1.0, 0.5]))
        self.assertEqual(got.tolist(), [0.0, 10.0, 20.0, 15.0])

    def test_bilinear_skips_nodata(self):
        np = self.np
        grid = np.array([[self.h.NODATA, 10.0], [self.h.NODATA, self.h.NODATA]])
        got = self.h.bilinear(grid, np.array([0.5, 0.0]), np.array([0.0, 1.0]))
        self.assertEqual(got[0], 10.0)
        self.assertTrue(math.isnan(got[1]))

    def test_fill_from_neighbours(self):
        heights = {1: 100}
        edges = [{"from": 1, "to": 2}, {"from": 2, "to": 3}, {"from": 8, "to": 9}]
        missing = self.h.fill_from_neighbours(heights, edges, [1, 2, 3, 8, 9])
        self.assertEqual(heights, {1: 100, 2: 100, 3: 100})
        self.assertEqual(missing, 2)

    def test_to_nodes_spreads_the_difference(self):
        edge = {"profile": [100, 100, 100, 100, 100]}
        self.h._to_nodes(edge, 120, 80)
        self.assertEqual(edge["profile"], [120, 110, 100, 90, 80])

    def test_profiles_meet_at_nodes(self):
        # fix 814: edges met a node at different heights
        e7 = self.h.E7
        nodes = {1: (48.0 * e7, 19.0 * e7), 2: (48.001 * e7, 19.0 * e7),
                 3: (48.002 * e7, 19.001 * e7), 4: (48.0 * e7, 19.002 * e7)}
        edges = [
            {"from": 1, "to": 2, "geom": [], "length_cm": 11132, "tags": {}},
            {"from": 2, "to": 3, "geom": [], "length_cm": 13500, "tags": {"bridge": "yes"}},
            {"from": 2, "to": 4, "geom": [(48.0015 * e7, 19.001 * e7)], "length_cm": 30000, "tags": {}},
            {"from": 4, "to": 1, "geom": [], "length_cm": 14900, "tags": {}},
        ]
        network = SimpleNamespace(nodes=nodes, edges=edges, heights={})
        np = self.np
        node2 = np.array(nodes[2]) / e7

        def stub(dem, lat, lon):
            v = 300 + 5000 * (lat - 48) + 40 * np.sin(lon * 3000)
            # a hole at the node: each edge bridges it from its own samples
            near = np.hypot(lat - node2[0], lon - node2[1]) < 1e-4
            return np.where(near, np.nan, v)
        real, self.h.sample = self.h.sample, stub
        try:
            result = self.h.fill_with_profiles(network, dem=None)
        finally:
            self.h.sample = real
        self.assertEqual(result[3:], (4, 0))
        at_node = {}
        for e in edges:
            # the profile is laid out by the edge length, not a flat-plane distance
            self.assertEqual(len(e["profile"]),
                             self.fmt.sample_count(e["length_cm"] / 100, self.h.STEP_M))
            at_node.setdefault(e["from"], set()).add(e["profile"][0])
            at_node.setdefault(e["to"], set()).add(e["profile"][-1])
        for node, ends in at_node.items():
            with self.subTest(node=node):
                self.assertEqual(len(ends), 1, ends)
        self.assertEqual(set(network.heights), set(nodes))


if __name__ == "__main__":
    unittest.main()
