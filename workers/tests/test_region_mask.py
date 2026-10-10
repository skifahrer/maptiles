import unittest

from load import worker

mask = worker("deploy/region-mask.py")

BOX = (0.0, 0.0, 10.0, 10.0)
SQUARE = [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]


def bounds(ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


class ClipRing(unittest.TestCase):
    def test_inside_unchanged(self):
        self.assertEqual(mask.clip_ring(SQUARE, BOX), SQUARE)

    def test_closed_ring_same_as_open(self):
        self.assertEqual(mask.clip_ring(SQUARE + [SQUARE[0]], BOX), SQUARE)

    def test_outside_is_empty(self):
        far = [(x + 20, y) for x, y in SQUARE]
        self.assertEqual(mask.clip_ring(far, BOX), [])

    def test_crosses_one_edge(self):
        ring = [(8.0, 2.0), (12.0, 2.0), (12.0, 4.0), (8.0, 4.0)]
        self.assertEqual(bounds(mask.clip_ring(ring, BOX)), (8.0, 2.0, 10.0, 4.0))

    def test_crosses_two_edges(self):
        ring = [(8.0, 8.0), (12.0, 8.0), (12.0, 12.0), (8.0, 12.0)]
        self.assertEqual(bounds(mask.clip_ring(ring, BOX)), (8.0, 8.0, 10.0, 10.0))

    def test_too_few_points(self):
        self.assertEqual(mask.clip_ring([(1.0, 1.0), (2.0, 2.0)], BOX), [])


class MaskGeojson(unittest.TestCase):
    def setUp(self):
        hole = [(2.5, 2.5), (3.0, 2.5), (3.0, 3.0)]
        data = mask.mask_geojson([SQUARE], [hole])
        self.by_kind = {f["properties"]["kind"]: f["geometry"]["coordinates"]
                        for f in data["features"]}

    def test_region_is_a_hole_in_the_world(self):
        world, region = self.by_kind["outside"][0]
        self.assertEqual(bounds(world), (-180.0, -mask.LAT_MAX, 180.0, mask.LAT_MAX))
        self.assertEqual(bounds(region), (2.0, 2.0, 4.0, 4.0))

    def test_enclave_is_masked(self):
        self.assertEqual(len(self.by_kind["outside"]), 2)
        self.assertEqual(bounds(self.by_kind["outside"][1][0]), (2.5, 2.5, 3.0, 3.0))

    def test_rings_are_closed(self):
        for polys in self.by_kind.values():
            for poly in polys:
                for ring in poly:
                    self.assertEqual(ring[0], ring[-1])


class Area(unittest.TestCase):
    def test_square_at_equator(self):
        side = 0.1
        ring = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
        expected = side * 111.32 * side * 110.57
        self.assertAlmostEqual(mask.ring_area_km2(ring), expected, delta=expected * 0.01)

    def test_degenerate(self):
        self.assertEqual(mask.ring_area_km2([(0.0, 0.0), (1.0, 1.0)]), 0.0)


if __name__ == "__main__":
    unittest.main()
