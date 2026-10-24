import os
import re
import sqlite3
import subprocess
import unittest

from load import WORKERS


class ContourLevels(unittest.TestCase):
    """`contour_levels` and `on_step` from `contours-rocks/build.sh`, run as they are."""

    def functions(self):
        with open(os.path.join(WORKERS, "contours-rocks", "build.sh")) as f:
            text = f.read()
        levels = re.search(r"^contour_levels\(\) \{\n.*?\n\}\n", text, re.M | re.S).group(0)
        step = re.search(r"^\s*on_step\(\) \{.*\}$", text, re.M).group(0)
        return levels + step + "\n"

    def levels(self, interval):
        out = subprocess.run(["bash", "-c", self.functions() + f'contour_levels "{interval}"'],
                             capture_output=True, text=True, check=True).stdout.split()
        return float(out[0]), float(out[1])

    def test_a_whole_interval_keeps_tenth_and_fifth(self):
        self.assertEqual(self.levels(5), (50, 25))
        self.assertEqual(self.levels(10), (100, 50))

    def test_a_fractional_interval_keeps_whole_metres(self):
        self.assertEqual(self.levels(2.5), (50, 10))

    def test_the_level_query_takes_fractional_heights(self):
        cond = subprocess.run(["bash", "-c", self.functions() + 'on_step 10'],
                              capture_output=True, text=True, check=True).stdout.strip()
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE contours (ele REAL)")
        db.executemany("INSERT INTO contours VALUES (?)",
                       [(v,) for v in (1000.0, 1002.5, 1007.5, 1010.0, 1012.5)])
        got = [r[0] for r in db.execute(f"SELECT ele FROM contours WHERE {cond}")]
        self.assertEqual(got, [1000.0, 1010.0])

    def test_the_interval_check_lets_a_fraction_through(self):
        with open(os.path.join(WORKERS, "contours-rocks", "build.sh")) as f:
            text = f.read()
        guard = re.search(r'^case "\$INTERVAL" in .*esac$', text, re.M).group(0)
        for given, kept in (("2.5", "2.5"), ("5", "5"), ("", "10"), ("1.2.3", "10"), ("x", "10")):
            out = subprocess.run(["bash", "-c", f'INTERVAL="{given}"\n{guard}\necho "$INTERVAL"'],
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(out, kept, given)


if __name__ == "__main__":
    unittest.main()
