import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

from load import WORKERS, needs, worker

OPTIONS = os.path.join(WORKERS, "plan/options.py")


def run(*args, **kw):
    with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
        defaults = {"--contour-source": "sonny", "--rock-source": "sonny", "--shading-source": "sonny"}
        defaults.update(kw)
        argv = [sys.executable, OPTIONS, f"--out={out.name}", *args,
                *(f"{k}={v}" for k, v in defaults.items())]
        r = subprocess.run(argv, capture_output=True, text=True)
        values = dict(line.removeprefix("opt_").split("=", 1) for line in out.read().splitlines() if "=" in line)
    return r, values


class Options(unittest.TestCase):
    def ok(self, *args, **kw):
        r, values = run(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return values, r.stdout + r.stderr

    def fails(self, *args, **kw):
        r, values = run(*args, **kw)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("::error::", r.stderr)
        self.assertEqual(values, {}, "a refused form writes no settings")
        return r.stderr

    def test_defaults(self):
        v, _ = self.ok()
        self.assertEqual((v["test_km2"], v["contours"], v["rocks"], v["terrain"]), ("0", "true", "true", "true"))
        self.assertEqual(v["rock_dem"], "sonny")
        self.assertTrue(v["terrain_maxzoom"].isdigit(), "auto is decided here")

    def test_options_parsed_and_quoted(self):
        v, _ = self.ok('--options=rock_res=2 crop_bbox="17,48,18,49" contour_interval=5.0')
        self.assertEqual((v["rock_res"], v["crop_bbox"], v["contour_interval"]), ("2", "17,48,18,49", "5"))

    def test_unknown_and_moved_keys(self):
        self.assertIn("Unknown option", self.fails("--options=rock_ress=2"))
        self.assertIn("not key=value", self.fails("--options=rock_res"))

    def test_old_names_still_mean_the_same(self):
        v, said = self.ok("--options=rock_plne=0", **{"--rock-source": "tienovanie", "--rebuild": "nic"})
        self.assertEqual((v["rock_solid"], v["rock_source"], v["rock_dem"]), ("0", "shading", ""))
        self.assertIn("::notice::", said)

    def test_sources_checked(self):
        self.assertIn("Unknown source", self.fails(**{"--contour-source": "google"}))
        v, _ = self.ok(**{"--contour-source": "none", "--rock-source": "none", "--shading-source": "none"})
        self.assertEqual((v["contours"], v["terrain"]), ("false", "false"))

    def test_quick_test(self):
        v, _ = self.ok("--test=true", "--options=reuse_layers=true")
        self.assertEqual((v["test_km2"], v["reuse_layers"], v["rocks_rebuild"]), ("4", "false", "true"))
        self.assertIn("only with the switch", self.fails("--options=test_km2=2"))
        self.assertIn("above zero", self.fails("--test=true", "--options=test_km2=0"))

    def test_switches_and_numbers(self):
        self.assertIn("true or false", self.fails("--options=trails=1"))
        self.assertIn("whole number", self.fails("--options=contour_maxzoom_cap=20"))
        self.assertIn("png or webp", self.fails("--options=terrain_format=jpg"))
        self.assertIn("above zero", self.fails("--options=contour_interval=0"))
        self.assertIn("Unknown rebuild", self.fails("--rebuild=all"))

    def test_rebuild_flags(self):
        v, _ = self.ok("--rebuild=rocks")
        self.assertEqual((v["rocks_rebuild"], v["terrain_rebuild"]), ("true", "false"))


class Jobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j = worker("state/jobs.py")

    def test_every_job_is_a_regenerable_package(self):
        reg = self.j._packages.regenerable()
        for key, job in self.j.JOBS.items():
            self.assertEqual(reg[key]["key"], job["package"])

    def test_fields_pass_every_input(self):
        got = self.j.fields("rocks", {"ROCK_SLOPE": "45", "OPTIONS": "rock_res=2"})
        self.assertEqual(got["what"], "rocks")
        self.assertEqual((got["rock_slope"], got["options"], got["test"]), ("45", "rock_res=2", "false"))
        self.assertEqual(set(got) - {"what"}, set(self.j.TARGETS["regenerate-region.yml"]["passes"]))

    def test_unknown_job(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            self.j.job("everything")


@needs("PIL")
class TestMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = worker("plan/test-map.py")

    def test_window_shows_the_whole_cutout_when_it_fits(self):
        test = [20.0, 49.0, 20.02, 49.01]
        full = [19.9, 48.95, 20.1, 49.05]
        got = self.t.window(test, full, 3, 20)
        self.assertLess(got[0], 19.9)
        self.assertGreater(got[2], 20.1)

    def test_window_bounded_by_the_square(self):
        test = [20.0, 49.0, 20.02, 49.01]
        got = self.t.window(test, [10, 40, 30, 60], 3, 20)
        self.assertAlmostEqual(got[2] - got[0], 0.02 * 20)
        got = self.t.window(test, None, 3, 20)
        self.assertAlmostEqual(got[2] - got[0], 0.06)

    def test_link_zoom(self):
        self.assertGreater(self.t.link_zoom([20.0, 49.0, 20.01, 49.01]), self.t.link_zoom([20.0, 49.0, 20.1, 49.1]))
        self.assertEqual(self.t.link_zoom([20, 49, 20, 49]), 15)
        self.assertEqual(self.t.link_zoom([0, -60, 170, 60]), 9)

    def test_strip_diacritics(self):
        self.assertEqual(self.t.strip_diacritics("Žilinský kraj – 4 km²"), "Zilinsky kraj - 4 km2")


if __name__ == "__main__":
    unittest.main()
