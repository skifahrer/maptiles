import unittest

from load import worker

s = worker("rail/sections.py")

RAIL = {"railway": "rail", "usage": "main", "gauge": "1435", "voltage": "3000"}


def sections_of(sec, *ways):
    return {w: [section for _, section in sec.split(w)] for w in ways}


class Kind(unittest.TestCase):
    def test_kind(self):
        self.assertIsNone(s.kind({"railway": "abandoned"}))
        self.assertIsNone(s.kind({"highway": "primary"}))
        self.assertNotEqual(s.kind(RAIL), s.kind({**RAIL, "voltage": "25000"}))
        self.assertEqual(s.kind(RAIL), s.kind({**RAIL, "maxspeed": "160"}))


class Sections(unittest.TestCase):
    def test_ways_end_to_end_are_one_section(self):
        sec = s.Sections()
        sec.add(1, RAIL, [10, 11, 12], [(17.0, 48.0), (17.1, 48.0), (17.2, 48.0)])
        sec.add(2, RAIL, [12, 13], [(17.2, 48.0), (17.3, 48.0)])
        sec.solve()
        got = sections_of(sec, 1, 2)
        self.assertEqual(got[1], got[2])
        self.assertEqual(sec.box(got[1][0]), "17.00000,48.00000,17.30000,48.00000")

    def test_a_change_of_kind_starts_a_section(self):
        sec = s.Sections()
        sec.add(1, RAIL, [10, 11])
        sec.add(2, {**RAIL, "voltage": "25000"}, [11, 12])
        sec.solve()
        got = sections_of(sec, 1, 2)
        self.assertNotEqual(got[1], got[2])

    def test_a_switch_splits_the_through_track(self):
        sec = s.Sections()
        sec.add(1, RAIL, [10, 11, 12])
        sec.add(2, RAIL, [11, 20])
        sec.solve()
        pieces = sec.split(1)
        self.assertEqual([refs for refs, _ in pieces], [[10, 11], [11, 12]])
        three = {section for _, section in pieces} | set(sections_of(sec, 2)[2])
        self.assertEqual(len(three), 3)

    def test_a_switch_of_another_kind_doesnt_split(self):
        sec = s.Sections()
        sec.add(1, RAIL, [10, 11, 12])
        sec.add(2, {"railway": "tram"}, [11, 20])
        sec.solve()
        self.assertEqual(len(sec.split(1)), 1)

    def crossing(self, flagged):
        sec = s.Sections(crossings=[50] if flagged else [])
        sec.add(1, RAIL, [10, 50, 11], [(17.0, 48.0), (17.1, 48.0), (17.2, 48.0)])
        sec.add(2, RAIL, [20, 50, 21], [(17.1, 47.9), (17.1, 48.0), (17.1, 48.1)])
        sec.solve()
        return sections_of(sec, 1, 2)

    def test_a_diamond_crossing_runs_on_straight(self):
        got = self.crossing(flagged=True)
        self.assertEqual(len(set(got[1])), 1)
        self.assertEqual(len(set(got[2])), 1)
        self.assertNotEqual(got[1][0], got[2][0])

    def test_an_unflagged_crossing_is_a_switch(self):
        got = self.crossing(flagged=False)
        self.assertEqual(len(set(got[1]) | set(got[2])), 4)

    def test_straightest_pairs_opposite_arms(self):
        a, b, c, d = (1, 0.0), (2, 3.1), (3, 1.6), (4, -1.5)
        pairs = s.straightest([a, b, c, d])
        self.assertEqual({frozenset(p[0] for p in pair) for pair in pairs},
                         {frozenset({1, 2}), frozenset({3, 4})})

    def test_unknown_and_short_ways(self):
        sec = s.Sections()
        sec.add(1, RAIL, [10])
        sec.add(2, {"railway": "abandoned"}, [10, 11])
        sec.add(3, RAIL, [10, 11])
        sec.solve()
        self.assertIsNone(sec.split(1))
        self.assertIsNone(sec.split(2))
        self.assertIsNone(sec.box(sections_of(sec, 3)[3][0]))


if __name__ == "__main__":
    unittest.main()
