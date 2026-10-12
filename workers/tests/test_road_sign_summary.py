import os
import tempfile
import unittest

from load import worker

s = worker("transport/signs.py")
summary = worker("transport/signs-summary.py")


class Tagged(unittest.TestCase):
    def test_how_a_sign_is_tagged(self):
        self.assertEqual(s.tagged({"traffic_sign": "SK:253[50]"}), "SK:253[50]")
        self.assertEqual(s.tagged({"highway": "stop"}), "highway=stop")
        self.assertEqual(s.tagged({"traffic_sign": "maxspeed", "maxspeed": "50"}),
                         "maxspeed + maxspeed=50")
        self.assertEqual(s.tagged({"traffic_sign:forward": "city_limit", "city_limit": "end"}),
                         "city_limit + city_limit=end")


class Summary(unittest.TestCase):
    def test_each_tagging_with_its_count_and_mapping(self):
        path = os.path.join(tempfile.mkdtemp(), "report.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("SK:P1\tsk.ts.p1\t3\nhighway=stop\tsk.ts.stop\t9\nSK:999\tsk.ts.999\t1\n")
        md = summary.markdown("bratislavsky", "sk", summary.read_report(path), {"sk.ts.stop"})
        lines = md.splitlines()
        self.assertIn("**13** sign points in 3 taggings; **9** drawn (69 %) with 1 images.", md)
        self.assertEqual(lines[6], "| `highway=stop` | 9 | `sk.ts.stop` | `regulatory/stop` | yes |")
        self.assertEqual(lines[7], "| `SK:P1` | 3 | `sk.ts.p1` | `regulatory/give-way` | no image |")
        self.assertEqual(lines[8], "| `SK:999` | 1 | `sk.ts.999` | – | not mapped |")

    def test_a_region_without_signs(self):
        self.assertIn("No traffic sign", summary.markdown("r", "sk", [], set()))


if __name__ == "__main__":
    unittest.main()
