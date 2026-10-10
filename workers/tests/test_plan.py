import math
import unittest

from load import worker

poly = worker("plan/region-poly.py")
seam = worker("plan/seam.py")
area = worker("plan/area.py")
boundary = worker("plan/boundary.py")

POLY = """region
1
\t17.0\t48.0
\t18.0\t48.0
\t18.0\t49.0
\t17.0\t49.0
\t17.0\t48.0
END
!2
\t17.4\t48.4
\t17.6\t48.4
\t17.6\t48.6
\t17.4\t48.4
END
3
\t19.0\t48.0
\t19.5\t48.0
\t19.5\t48.5
END
END
"""


def rect(w, s, e, n):
    return [(w, s), (e, s), (e, n), (w, n)]


class ParsePoly(unittest.TestCase):
    def test_rings_and_hole(self):
        rings = poly.parse_poly(POLY)
        self.assertEqual([hole for _, hole in rings], [False, True, False])
        self.assertEqual(rings[0][0][1], (18.0, 48.0))

    def test_round_trip(self):
        rings = poly.parse_poly(POLY)
        again = poly.parse_poly(poly.rings_to_poly_text(rings))
        self.assertEqual([h for _, h in again], [h for _, h in rings])
        for (a, _), (b, _) in zip(again, rings):
            closed = b if b[0] == b[-1] else b + [b[0]]
            self.assertEqual(a, closed)

    def test_bbox(self):
        self.assertEqual(poly.ring_bbox(poly.parse_poly(POLY)), (17.0, 48.0, 19.5, 49.0))


class Seam(unittest.TestCase):
    PARENT = [(rect(0.0, 48.0, 0.4, 48.4), False)]
    OWN = [(rect(0.0, 48.0, 0.2, 48.4), False)]
    SHIFT = 300 / (seam.M_PER_DEG_LON * math.cos(math.radians(48.2)))

    def measure(self, west):
        nb = {"east": [(rect(west, 48.0, 0.4, 48.4), False)]}
        return seam.measure_seam(self.OWN, nb, self.PARENT, buffer_m=0)

    def test_touching_fits(self):
        r = self.measure(0.2)
        self.assertGreater(r["points"], 0)
        self.assertTrue(r["fits"], r)

    def test_overlap(self):
        r = self.measure(0.2 - self.SHIFT)
        self.assertFalse(r["fits"])
        self.assertAlmostEqual(r["overlap_m"], 300, delta=5)
        self.assertEqual(r["neighbour_overlap"], "east")

    def test_gap(self):
        r = self.measure(0.2 + self.SHIFT)
        self.assertFalse(r["fits"])
        self.assertAlmostEqual(r["gap_m"], 300, delta=5)

    def test_inside_with_hole(self):
        rings = [(rect(0, 0, 10, 10), False), (rect(4, 4, 6, 6), True)]
        self.assertTrue(seam._inside(rings, 2, 2))
        self.assertFalse(seam._inside(rings, 5, 5))
        self.assertFalse(seam._inside(rings, 12, 5))

    def test_dist_to_boundary(self):
        rings = [(rect(0, 0, 10, 10), False)]
        self.assertAlmostEqual(seam.dist_to_boundary(rings, 3, 5), 3)
        self.assertAlmostEqual(seam.dist_to_boundary(rings, 13, 14), 5)


class Area(unittest.TestCase):
    def test_bbox_km2(self):
        self.assertAlmostEqual(area.bbox_km2(0, 0, 1, 1), 111.32 * 110.54, delta=1)

    def test_pad_bbox(self):
        w, s, e, n = area.pad_bbox([17, 48, 18, 49], 1000)
        self.assertAlmostEqual((48 - s) * area.M_PER_DEG_LAT, 1000)
        self.assertLess(w, 17)
        self.assertGreater(e, 18)

    def test_square_inside(self):
        bbox = [17, 48, 18, 49]
        w, s, e, n = area.test_square(bbox, 4)
        self.assertAlmostEqual(area.bbox_km2(w, s, e, n), 4, delta=0.01)

    def test_square_moved_inward(self):
        w, s, e, n = area.test_square([17, 48, 18, 49], 4, at="17.0,48.0")
        self.assertEqual((w, s), (17, 48))
        self.assertAlmostEqual(area.bbox_km2(w, s, e, n), 4, delta=0.01)

    def test_square_bigger_than_bbox(self):
        self.assertEqual(area.test_square([17, 48, 17.01, 48.01], 100), [17, 48, 17.01, 48.01])

    def test_bad_at(self):
        with self.assertRaises(ValueError):
            area.test_square([17, 48, 18, 49], 4, at="17")


class Boundary(unittest.TestCase):
    def test_geojson_round_trip(self):
        rings = [(rect(0, 0, 10, 10), False), (rect(4, 4, 6, 6), True)]
        again = boundary.rings_from_geojson(boundary.geojson_from_rings(rings))
        self.assertEqual([h for _, h in again], [False, True])
        self.assertEqual(again[1][0][:4], rings[1][0])

    def test_no_outline_gives_none(self):
        self.assertIsNone(boundary.geojson_from_rings([(rect(0, 0, 1, 1), True)]))

    def test_pick(self):
        small = [(rect(0, 0, 1, 1), False)]
        big = [(rect(0, 0, 5, 5), False)]
        borders = [
            {"admin_level": 4, "name": "Prešovský kraj", "names": ["Presov Region"], "rings": small},
            {"admin_level": 4, "name": "Prešovský kraj", "names": [], "rings": big},
            {"admin_level": 2, "name": "Slovensko", "names": [], "rings": small},
        ]
        self.assertIs(boundary.pick(borders, "Prešovský kraj", 4), big)
        self.assertIs(boundary.pick(borders, "Presov Region", 4), small)
        self.assertIsNone(boundary.pick(borders, "Slovensko", 4))
        self.assertIsNone(boundary.pick(borders, "", 4))


if __name__ == "__main__":
    unittest.main()
