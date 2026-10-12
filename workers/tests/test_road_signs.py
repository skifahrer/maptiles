import unittest

from load import worker

s = worker("transport/signs.py")


class SignName(unittest.TestCase):
    def test_a_value_is_part_of_the_name(self):
        self.assertEqual(s.sign_name("SK:253[50]", "sk"), "sk.ts.253-50")
        self.assertEqual(s.sign_name("DE:274[50],1020-30", "sk"), "de.ts.274-50")

    def test_the_first_of_several_signs(self):
        self.assertEqual(s.sign_name("SK:202;SK:E9", "sk"), "sk.ts.202")

    def test_a_comma_inside_the_value_does_not_split(self):
        self.assertEqual(s.sign_name("SK:262[3,5];SK:506", "sk"), "sk.ts.262-3-5")

    def test_codes_lose_spaces_and_paragraphs(self):
        self.assertEqual(s.sign_name("CZ:P 6", "sk"), "cz.ts.p6")
        self.assertEqual(s.sign_name("AT:§52 Z24", "sk"), "at.ts.52z24")

    def test_a_bare_word_takes_the_region_country(self):
        self.assertEqual(s.sign_name("city_limit", "sk"), "sk.ts.city_limit")
        self.assertIsNone(s.sign_name("city_limit", ""))

    def test_no_sign(self):
        for value in ("", "yes", "none", None):
            self.assertIsNone(s.sign_name(value, "sk"))


class NodeTags(unittest.TestCase):
    def test_a_stop_node_is_a_stop_sign(self):
        tags = s.node_tags({"highway": "stop"}, "sk")
        self.assertEqual(tags["sign"], "sk.ts.stop")

    def test_a_tagged_sign_beats_the_implied_one(self):
        tags = s.node_tags({"highway": "stop", "traffic_sign": "SK:202"}, "sk")
        self.assertEqual(tags["sign"], "sk.ts.202")

    def test_maxspeed_gives_the_figure(self):
        tags = s.node_tags({"traffic_sign": "maxspeed", "maxspeed": "40"}, "sk")
        self.assertEqual(tags["sign"], "sk.ts.maxspeed-40")

    def test_limits_take_their_figure(self):
        tags = s.node_tags({"traffic_sign": "maxweight", "maxweight": "7.5"}, "sk")
        self.assertEqual(tags["sign"], "sk.ts.maxweight-7-5")
        tags = s.node_tags({"traffic_sign": "maxheight", "maxheight": "3.8 m"}, "sk")
        self.assertEqual(tags["sign"], "sk.ts.maxheight-3-8")
        tags = s.node_tags({"traffic_sign": "maxspeed", "maxspeed": "none"}, "sk")
        self.assertEqual(tags["sign"], "sk.ts.maxspeed")

    def test_end_signs(self):
        self.assertEqual(s.node_tags({"traffic_sign": "city_limit", "city_limit": "end"}, "sk")["sign"],
                         "sk.ts.city_limit_end")
        self.assertEqual(s.node_tags({"traffic_sign": "overtaking", "overtaking": "yes"}, "sk")["sign"],
                         "sk.ts.overtaking_end")
        self.assertEqual(s.node_tags({"traffic_sign": "SK:P1"}, "sk")["sign"], "sk.ts.p1")

    def test_forward_key_is_the_direction(self):
        tags = s.node_tags({"traffic_sign:forward": "SK:230"}, "sk")
        self.assertEqual((tags["sign"], tags["sign_direction"], tags["traffic_sign"]),
                         ("sk.ts.230", "forward", "SK:230"))

    def test_other_nodes_are_dropped(self):
        self.assertIsNone(s.node_tags({"highway": "crossing"}, "sk"))
        self.assertIsNone(s.node_tags({"amenity": "bench"}, "sk"))

    def test_unrelated_tags_are_dropped(self):
        tags = s.node_tags({"traffic_sign": "SK:201", "source": "survey"}, "sk")
        self.assertNotIn("source", tags)


if __name__ == "__main__":
    unittest.main()
