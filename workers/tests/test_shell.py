import http.server
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest

from load import WORKERS
from stubs import Stubs

ROOT = os.path.dirname(WORKERS)
CACHE_KEYS = os.path.join(WORKERS, "plan/cache-keys.sh")


def bash(script, env=None, cwd=ROOT):
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, cwd=cwd)


class StoreArea(unittest.TestCase):
    def ask(self, fn, value):
        r = bash(f'. workers/lib/store-area.sh; {fn} "$1"'.replace('"$1"', f"'{value}'"))
        return r.stdout.strip()

    def test_store_area(self):
        self.assertEqual(self.ask("store_area", "whole"), "cely")
        self.assertEqual(self.ask("store_area", "cutout_tatry"), "vyrez_tatry")
        self.assertEqual(self.ask("store_area", "vysoke_tatry"), "vysoke_tatry")

    def test_store_token(self):
        for given, stored in (("shading", "tienovanie"), ("none", "ziadne"),
                              ("whole_region", "cely_region"), ("dmr5", "dmr5")):
            self.assertEqual(self.ask("store_token", given), stored)

    def test_python_spelling_agrees(self):
        from load import worker
        target = worker("dem/target.py")
        for key in ("whole", "cutout_tatry", "vysoke_tatry"):
            self.assertEqual(target.store_area(key), self.ask("store_area", key))


class LayerDone(unittest.TestCase):
    def decide(self, **env):
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
            r = bash("workers/plan/layer-done.sh", {"LAYER": "rocks", "HIT": "", "MATCHED": "",
                                                    "HIT_LEGACY": "", "GITHUB_OUTPUT": out.name, **env})
            self.assertEqual(r.returncode, 0, r.stderr)
            return dict(line.split("=", 1) for line in out.read().split()), r.stdout

    def test_decisions(self):
        self.assertEqual(self.decide(HIT="true")[0], {"have": "true", "compute": "false"})
        got, said = self.decide(MATCHED="rocks-v3-x-old")
        self.assertEqual(got, {"have": "true", "compute": "false"})
        self.assertIn("::notice::", said)
        self.assertEqual(self.decide(HIT_LEGACY="true")[0]["have"], "true")
        self.assertEqual(self.decide()[0], {"have": "false", "compute": "true"})
        self.assertEqual(self.decide(HIT="false")[0]["compute"], "true")


class CacheKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CACHE_KEYS) as f:
            text = f.read()
        names = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]+)", text)) - {"GITHUB_OUTPUT"}
        names -= {"B", "DC", "DR", "DT", "CS", "RS", "TS", "RA", "CCAP", "LOWLAND", "TBITS",
                  "TFMT", "C_OPT", "T_OPT", "C_SETTINGS", "R_SETTINGS", "T_SETTINGS", "LEGACY"}
        cls.inputs = sorted(names)
        cls.base = {n: f"v{i}" for i, n in enumerate(cls.inputs)}
        cls.base.update(AREA_IN="whole_region", AREA_KEY="whole", OPT_CONTOUR_SOURCE="dmr5",
                        OPT_ROCK_SOURCE="shading", OPT_SHADING_SOURCE="sonny")

    def keys(self, **change):
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
            r = subprocess.run(["bash", CACHE_KEYS], capture_output=True, text=True,
                               env={**os.environ, **self.base, **change, "GITHUB_OUTPUT": out.name})
            self.assertEqual(r.returncode, 0, r.stderr)
            return dict(line.split("=", 1) for line in out.read().split("\n") if line)

    def test_stable(self):
        self.assertEqual(self.keys(), self.keys())

    def test_inputs_found(self):
        for name in ("DEM_BBOXKEY", "DEMKEY_ROCKS", "OPT_ROCK_RES", "CONTOUR_INTERVAL",
                     "SCHEMA_CONTOURS", "OPT_TERRAIN_MAXZOOM"):
            self.assertIn(name, self.inputs)

    def test_every_input_changes_a_key(self):
        base = self.keys()
        for name in self.inputs:
            with self.subTest(input=name):
                self.assertNotEqual(self.keys(**{name: self.base[name] + "x"}), base)

    def test_layers_keep_their_own_keys(self):
        base = self.keys()
        rocks = self.keys(OPT_ROCK_RES="2")
        self.assertEqual(rocks["contours"], base["contours"])
        self.assertEqual(rocks["terrain"], base["terrain"])
        self.assertNotEqual(rocks["rocks"], base["rocks"])
        self.assertNotEqual(rocks["slope"], base["slope"])
        terrain = self.keys(DEMKEY_TERRAIN="refilled")
        self.assertEqual((terrain["contours"], terrain["rocks"]), (base["contours"], base["rocks"]))

    def test_done_is_the_prefix_of_its_key(self):
        k = self.keys()
        for layer in ("contours", "rocks", "terrain"):
            self.assertTrue(k[f"{layer}_done"].endswith("-"))
            self.assertTrue(k[layer].startswith(k[f"{layer}_done"]))
        # the trailing dash: z1 isn't a prefix of z15
        self.assertFalse(self.keys(OPT_TERRAIN_MAXZOOM="15")["terrain"].startswith(
            self.keys(OPT_TERRAIN_MAXZOOM="1")["terrain_done"]))

    def test_old_spelling_kept(self):
        k = self.keys()
        self.assertIn("-rtienovanie", k["rocks"])
        self.assertIn("-acely_region", k["rocks"])
        self.assertIn("slope-v1-cely-tienovanie-", k["slope"])


FAKE_JAVA = """#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in --output=*) out="${a#--output=}";; --maxzoom=*) z="${a#--maxzoom=}";; esac
done
echo "$z" >> "$FAKE_DIR/zooms"
mb=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$FAKE_DIR/sizes.json" "$z")
truncate -s "$(( mb * 1048576 ))" "$out"
"""


class PmtilesBudget(unittest.TestCase):
    def budget(self, sizes, start, floor=10, cap_zoom=""):
        with Stubs() as s:
            s.script("java", FAKE_JAVA)
            with open(os.path.join(s.dir, "sizes.json"), "w") as f:
                json.dump({str(z): mb for z, mb in sizes.items()}, f)
            out = os.path.join(s.dir, "x.pmtiles")
            r = s.run(["bash", "-c", f'. workers/lib/pmtiles-budget.sh; '
                                     f'pmtiles_in_budget s.yml {out} {start} 100 {floor} Tiles "advice" {cap_zoom}; '
                                     f'echo "PM_Z=$PM_Z PM_MB=$PM_MB"'], cwd=ROOT, env=s.env(FAKE_DIR=s.dir))
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(s.dir, "zooms")) as f:
                tried = [int(z) for z in f.read().split()]
            return r.stdout.strip().splitlines()[-1], tried, r.stdout

    SIZES = {10: 8, 11: 15, 12: 30, 13: 60, 14: 120, 15: 240}

    def test_fits_and_no_room(self):
        self.assertEqual(self.budget(self.SIZES, 13)[:2], ("PM_Z=13 PM_MB=60", [13]))

    def test_lowered_never_raised(self):
        self.assertEqual(self.budget(self.SIZES, 15)[:2], ("PM_Z=13 PM_MB=60", [15, 14, 13]))

    def test_raised_while_room(self):
        self.assertEqual(self.budget(self.SIZES, 11, cap_zoom=14)[:2], ("PM_Z=13 PM_MB=60", [11, 12, 13]))

    def test_no_cap_never_above_the_start(self):
        self.assertEqual(self.budget(self.SIZES, 11)[:2], ("PM_Z=11 PM_MB=15", [11]))

    def test_zoom_cap(self):
        self.assertEqual(self.budget(self.SIZES, 11, cap_zoom=12)[:2], ("PM_Z=12 PM_MB=30", [11, 12]))

    def test_floor_warns(self):
        last, tried, out = self.budget({z: 500 for z in range(8, 16)}, 12, floor=11)
        self.assertEqual((last, tried), ("PM_Z=11 PM_MB=500", [12, 11]))
        self.assertIn("::warning::Tiles take 500 MB even at maxzoom 11", out)


class Site(http.server.SimpleHTTPRequestHandler):
    missing, flaky, no_range = set(), {}, False

    def log_message(self, *a):
        pass

    def send_head(self):
        path = self.path.split("?")[0]
        if path in self.missing:
            self.send_error(404)
            return None
        if self.flaky.get(path, 0) > 0:
            self.flaky[path] -= 1
            self.send_error(503)
            return None
        rng = self.headers.get("Range")
        if rng and not self.no_range and path.endswith(".pmtiles"):
            a, b = (int(v) for v in rng.split("=")[1].split("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/4096")
            self.send_header("Content-Length", str(b - a + 1))
            self.end_headers()
            return io.BytesIO(b"\0" * (b - a + 1))
        return super().send_head()


class SmokeTest(unittest.TestCase):
    FILES = ["tiles/manifest.json", "sprites/s.json", "sprites/s.png", "sprites/s@2x.json",
             "sprites/s@2x.png", "styles/r-svetla.json", "styles/r-cestna-svetla.json",
             "style-overrides.json", "tiles/r.pmtiles", "tiles/r-trails.pmtiles", "region.geojson"]

    def setUp(self):
        self.site = tempfile.mkdtemp()
        for rel in self.FILES:
            path = os.path.join(self.site, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("x" * 4096)
        with open(os.path.join(self.site, "index.html"), "w") as f:
            f.write('<div id="map"></div>')
        handler = lambda *a, **kw: Site(*a, directory=self.site, **kw)
        Site.missing, Site.flaky, Site.no_range = set(), {}, False
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        manifest = {"built_at": "t1", "glyphs": "https://fonts.example/{fontstack}",
                    "default_region": "r", "regions": {"r": {"outline": "region.geojson"}}}
        with open(os.path.join(self.site, "tiles/manifest.json"), "w") as f:
            json.dump(manifest, f)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def smoke(self):
        with Stubs(sleep=[{"match": ".*"}]) as s:
            return s.run(["bash", os.path.join(WORKERS, "deploy/smoke-test.sh")], cwd=ROOT, env=s.env(
                BASE=self.base, REGION="r", SPRITE="s", SITE_DIR=self.site, TRAILS="true",
                PAGES_BUILD_TYPE="workflow", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1"))

    def test_all_there(self):
        r = self.smoke()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("✓ waymarked trails (Range request) (206)", r.stdout)
        self.assertIn("✓ downloaded region outline", r.stdout)

    def test_missing_package_fails(self):
        Site.missing = {"/tiles/r-trails.pmtiles"}
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("waymarked trails (Range request) returned HTTP 404", r.stdout)

    def test_retry_that_succeeds_passes(self):
        Site.flaky = {"/sprites/s@2x.png": 2}
        r = self.smoke()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_no_range_support_fails(self):
        Site.no_range = True
        r = self.smoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("returned HTTP 200 (expected 206)", r.stdout)

    def test_old_deploy_stops_early(self):
        built = tempfile.mkdtemp()
        os.makedirs(os.path.join(built, "tiles"))
        with open(os.path.join(built, "tiles/manifest.json"), "w") as f:
            json.dump({"built_at": "t2"}, f)
        with Stubs(sleep=[{"match": ".*"}]) as s:
            r = s.run(["bash", os.path.join(WORKERS, "deploy/smoke-test.sh")], cwd=ROOT, env=s.env(
                BASE=self.base, REGION="r", SPRITE="s", SITE_DIR=built,
                NO_PROXY="127.0.0.1", no_proxy="127.0.0.1"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Pages don't serve this deploy", r.stdout)

if __name__ == "__main__":
    unittest.main()
