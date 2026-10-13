import os
import subprocess
import sys
import tempfile
import unittest

from load import WORKERS, needs, worker

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



class AtHome(unittest.TestCase):
    def test_a_foreign_code_takes_the_home_sign(self):
        by_country = s.folders()
        tags = s.node_tags({"traffic_sign": "AT:53.8a"}, "sk", by_country)
        self.assertEqual(tags["sign"], "sk.ts.309", "Austrian motorway sign → Slovak 309")
        self.assertEqual(tags["traffic_sign"], "AT:53.8a", "the OSM value stays")
        self.assertEqual(s.node_tags({"traffic_sign": "AT:53.8a"}, "at", by_country)["sign"],
                         "at.ts.53.8a")


class MappedName(unittest.TestCase):
    """A key of `road-signs.json` names the image the tiles ask for."""

    def tiles(self, **tags):
        return s.node_tags(tags, "sk")["sign"]

    def test_every_form_matches_the_tiles(self):
        cases = {"SK:253[50]": self.tiles(traffic_sign="SK:253[50]"),
                 "stop": self.tiles(traffic_sign="stop"),
                 "maxspeed=50": self.tiles(traffic_sign="maxspeed", maxspeed="50"),
                 "maxweight=7.5": self.tiles(traffic_sign="maxweight", maxweight="7.5"),
                 "city_limit=end": self.tiles(traffic_sign="city_limit", city_limit="end"),
                 "highway=give_way": self.tiles(highway="give_way")}
        for key, name in cases.items():
            self.assertEqual(s.mapped_name(key, "sk"), name, key)


OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
 <node id="1" version="1" lat="48.13" lon="17.12"><tag k="traffic_sign" v="SK:253[50]"/></node>
 <node id="2" version="1" lat="48.14" lon="17.13"><tag k="highway" v="stop"/></node>
 <node id="3" version="1" lat="48.15" lon="17.14"/>
 <way id="10" version="1"><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way>
</osm>
"""


@needs("osmium")
class Rewrite(unittest.TestCase):
    def test_the_roads_keep_everything_and_signs_get_their_name(self):
        # fix 1847: osmium.FileProcessor is missing from the runners' pyosmium 3
        import osmium

        with tempfile.TemporaryDirectory() as tmp:
            src, out = os.path.join(tmp, "in.osm"), os.path.join(tmp, "out.osm.pbf")
            with open(src, "w", encoding="utf-8") as f:
                f.write(OSM)
            r = subprocess.run([sys.executable, os.path.join(WORKERS, "transport/signs.py"),
                                f"--pbf={src}", f"--out={out}", "--country=sk",
                                f"--report={tmp}/report.tsv"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = {}

            class Read(osmium.SimpleHandler):
                def node(self, n):
                    got[("n", n.id)] = dict(n.tags)

                def way(self, w):
                    got[("w", w.id)] = dict(w.tags)

            Read().apply_file(out)
            with open(f"{tmp}/report.tsv", encoding="utf-8") as f:
                report = f.read()
        self.assertEqual(got[("n", 1)]["sign"], "sk.ts.253-50")
        self.assertEqual(got[("n", 2)], {"highway": "stop", "sign": "sk.ts.stop"})
        self.assertEqual(got[("n", 3)], {})
        self.assertEqual(got[("w", 10)], {"highway": "residential"})
        self.assertIn("highway=stop\tsk.ts.stop\t1", report)

if __name__ == "__main__":
    unittest.main()
