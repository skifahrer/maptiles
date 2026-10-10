import unittest

from load import worker

tags = worker("trails/tags.py")


class ParseHex(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(tags.parse_hex("#a3b"), (0xAA, 0x33, 0xBB))
        self.assertEqual(tags.parse_hex("a3b2c1"), (0xA3, 0xB2, 0xC1))
        for junk in ("", "#12", "red", "#12345g"):
            with self.subTest(junk=junk):
                self.assertIsNone(tags.parse_hex(junk))


class ResolveColour(unittest.TestCase):
    def test_osmc_wins_over_colour(self):
        self.assertEqual(tags.resolve_colour({"osmc:symbol": "red:white:red_bar",
                                              "colour": "blue"}), ("red", ""))

    def test_colour_and_alias(self):
        self.assertEqual(tags.resolve_colour({"colour": "Blue"}), ("blue", ""))
        self.assertEqual(tags.resolve_colour({"color": "grey"}), ("gray", ""))

    def test_hex_snaps_only_when_close(self):
        self.assertEqual(tags.resolve_colour({"colour": "#e01b24"}), ("red", ""))
        self.assertEqual(tags.resolve_colour({"colour": "#ff69b4"}), ("", "#ff69b4"))

    def test_nothing(self):
        self.assertEqual(tags.resolve_colour({}), ("", ""))
        self.assertEqual(tags.resolve_colour({"colour": "plaid"}), ("", ""))


class SplitSymbol(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(tags.split_symbol("red_bar"), ("red", "bar"))
        self.assertEqual(tags.split_symbol("blue_triangle_turned"), ("blue", "triangle"))
        self.assertEqual(tags.split_symbol("bar"), ("", "bar"))
        self.assertEqual(tags.split_symbol(""), ("", ""))


class ResolveMark(unittest.TestCase):
    def mark(self, osmc, route="hiking", colour=""):
        return tags.resolve_mark({"osmc:symbol": osmc} if osmc else {}, route, colour)

    def test_plain(self):
        self.assertEqual(self.mark("red:white:red_bar"), ("bar", "white", "red"))

    def test_foreground_a_field_later(self):
        self.assertEqual(self.mark("red:white::red_bar"), ("bar", "white", "red"))

    def test_bicycle_on_yellow_is_black(self):
        self.assertEqual(self.mark("yellow:yellow:yellow_bicycle", route="bicycle"),
                         ("bicycle", "yellow", "black"))
        self.assertEqual(self.mark("", route="bicycle"), ("bicycle", "yellow", "black"))

    def test_colourless_walk_gets_no_mark(self):
        self.assertEqual(self.mark(""), (None, None, None))

    def test_every_result_is_baked(self):
        for osmc in ("red:white:red_bar", "blue:blue:white_bar", "green:yellow:green_dot",
                     "black:black:white_cross", "white:red:white_bar", "yellow::yellow_bar",
                     "orange:white:orange_bar", "red:red:red_bar"):
            for route in ("hiking", "bicycle", "mtb", "ski"):
                with self.subTest(osmc=osmc, route=route):
                    shape, bg, fg = self.mark(osmc, route)
                    if shape is not None:
                        self.assertIn((bg, fg), tags.MARK_FACES)


class ResolveTier(unittest.TestCase):
    def test_network(self):
        for network, tier in (("iwn", "international"), ("nwn", "national"),
                              ("rwn", "regional"), ("lwn", "local"), ("rcn:sk", "regional")):
            with self.subTest(network=network):
                self.assertEqual(tags.resolve_tier({"network": network})[0], tier)

    def test_distance_fallback(self):
        for distance, tier in (("150", "national"), ("149.9 km", "regional"),
                               ("50", "regional"), ("49", "local"), ("", "local")):
            with self.subTest(distance=distance):
                self.assertEqual(tags.resolve_tier({"distance": distance})[0], tier)


if __name__ == "__main__":
    unittest.main()
