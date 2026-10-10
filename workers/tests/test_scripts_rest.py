import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from load import WORKERS, needs, needs_cmd
from stubs import Stubs, shadow_workers
import mini_region

ROOT = os.path.dirname(WORKERS)
FAKE_PUT = """import os, sys
args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
with open(os.environ["PUT_LOG"], "a") as f:
    f.write(args["--store"] + " " + os.path.basename(args["--file"]) + "\\n")
"""


def work_dir(test, replace=None):
    work = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, work)
    shadow_workers(work, replace or {})
    return work


class Guards(unittest.TestCase):
    def run_in(self, cwd, script, **env):
        return subprocess.run(["bash", script], cwd=cwd, capture_output=True, text=True,
                              env={**os.environ, **env})

    def test_graph_needs_a_scope_and_a_pbf(self):
        work = work_dir(self)
        r = self.run_in(work, "workers/routing/graph.sh", AREA="", REGION_KEY="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Say what scope", r.stdout)
        r = self.run_in(work, "workers/routing/graph.sh", AREA="slovensko")
        self.assertEqual(r.returncode, 1)
        self.assertIn("workers/routing/pbf.sh must pass first", r.stdout)

    def test_apple_archive_needs_aa_and_a_site(self):
        work = work_dir(self)
        r = self.run_in(work, "workers/deploy/apple-archive.sh", PATH="/usr/bin:/bin")
        self.assertEqual(r.returncode, 1)
        self.assertIn("macos-latest", r.stdout)
        with Stubs(aa=[{"match": ".*"}]) as s:
            r = s.run(["bash", "workers/deploy/apple-archive.sh"], cwd=work, env=s.env(TEST_KM2="0"))
            self.assertEqual(r.returncode, 1)
            self.assertIn("_site isn't assembled", r.stdout)
            r = s.run(["bash", "workers/deploy/apple-archive.sh"], cwd=work,
                      env=s.env(ONLY="wikipedia", WIKI=os.path.join(work, "none"), TEST_KM2="0"))
            self.assertIn("there are no articles", r.stdout)


class PublishResults(unittest.TestCase):
    def publish(self, work, **env):
        log = os.path.join(work, "put.log")
        r = subprocess.run(["bash", "workers/deploy/publish-results.sh"], cwd=work, capture_output=True, text=True,
                           env={**os.environ, "PUT_LOG": log, "RUNNER_TEMP": work, "GITHUB_RUN_NUMBER": "7", **env})
        if not os.path.exists(log):
            return r, []
        with open(log) as f:
            return r, f.read().split("\n")[:-1]

    def setUp(self):
        self.work = work_dir(self, {"drive/store.py": FAKE_PUT})
        for rel in ("data/trails.geojson", "steps-out/trail-stats.txt", "data/one.gpkg"):
            os.makedirs(os.path.dirname(os.path.join(self.work, rel)), exist_ok=True)
            with open(os.path.join(self.work, rel), "w") as f:
                f.write("x")

    def test_several_files_go_as_one_archive(self):
        r, put = self.publish(self.work, NAME="trails-r", KIND="trails")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(put), 1)
        store, name = put[0].split()
        self.assertEqual(store, "results")
        self.assertRegex(name, r"^trails-r-\d{8}-\d{4}-r7\.tar\.(zst|gz)$")

    def test_one_file_keeps_its_type(self):
        _, put = self.publish(self.work, NAME="x", KIND="files", PATHS="data/one.gpkg data/missing.tif")
        self.assertTrue(put[0].endswith(".gpkg"))

    def test_nothing_made_nothing_sent(self):
        r, put = self.publish(self.work, NAME="t", KIND="terrain")
        self.assertEqual((r.returncode, put), (0, []))
        self.assertIn("nothing goes to the store", r.stdout)

    def test_unknown_kind(self):
        self.assertEqual(self.publish(self.work, NAME="t", KIND="rocks")[0].returncode, 1)
        self.assertEqual(self.publish(self.work, NAME="t", KIND="files")[0].returncode, 1)


@needs_cmd("osmium")
@needs("osmium")
class NodeOrder(unittest.TestCase):
    def setUp(self):
        osm = os.path.join(tempfile.mkdtemp(), "mini.osm")
        self.addCleanup(shutil.rmtree, os.path.dirname(osm))
        with open(osm, "w", encoding="utf-8") as f:
            f.write(mini_region.build().xml())
        fake_pbf = f"#!/usr/bin/env bash\nosmium cat --overwrite {osm} -o data/routing.osm.pbf\n"
        self.work = work_dir(self, {"routing/pbf.sh": fake_pbf})
        os.chmod(os.path.join(self.work, "workers/routing/pbf.sh"), 0o755)
        os.makedirs(os.path.join(self.work, "data"))

    def order(self, **env):
        out = os.path.join(self.work, "out")
        open(out, "w").close()
        r = subprocess.run(["bash", "workers/routing/order.sh"], cwd=self.work, capture_output=True, text=True,
                           env={**os.environ, "AREA": "mini", "GITHUB_OUTPUT": out, **env})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(out) as f:
            return dict(line.split("=", 1) for line in f.read().split())

    def cached(self, name="mini", days=0):
        with open(os.path.join(self.work, "data/routing-order.json")) as f:
            raw = json.load(f)
        raw["name"] = name
        raw["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime(time.time() - days * 86400 - 60))
        with open(os.path.join(self.work, "data/routing-order.json"), "w") as f:
            json.dump(raw, f)

    def test_computed_then_taken_then_recomputed(self):
        first = self.order()
        self.assertEqual(first["computed"], "true")
        self.assertGreater(int(first["nodes"]), 10)
        self.cached(days=3)
        self.assertEqual(self.order(), dict(first, computed="false"))
        self.cached(days=40)
        self.assertEqual(self.order()["computed"], "true", "older than the cap")
        self.cached(name="slovensko")
        self.assertEqual(self.order()["computed"], "true", "another area's order")
        self.cached(days=1)
        self.assertEqual(self.order(FORCE="true")["computed"], "true")


class Summary(unittest.TestCase):
    ENV = {"REGION_NAME": "Trnavský kraj", "R_PLAN": "success", "R_CONTOURS": "success",
           "R_SHADING_ROCKS": "skipped", "R_TRAILS": "success", "R_FEATURES": "success",
           "R_TERRAIN": "failure", "R_TILES": "success", "R_ASSETS": "success",
           "SRC_CONTOURS": "dmr5", "SRC_ROCKS": "dmr5", "SRC_SHADING": "sonny", "USED_CONTOURS": "dmr5",
           "USED_ROCKS": "dmr5", "USED_SHADING": "sonny", "SIZE_LIMIT_MB": "900", "PAGE_URL": "https://x/",
           "PUBLISH_PAGES": "true", "PAGES_BUILD_TYPE": "workflow", "REGION_KEY": "trnavsky",
           "TEST_KM2": "0", "TEST_BBOX": "", "TEST_FULL_BBOX": "", "INPUTS_JSON": "{}",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1"}
    GH = [{"match": r"-q \.run_started_at", "out": "2026-10-10T10:00:00Z"},
          {"match": r"runs/1/jobs", "out": "55\tterrain\tfailure\t2026-10-10T10:00:00Z\t2026-10-10T11:00:00Z\tHeight tiles\thttps://j\n"},
          {"match": r"jobs/55/logs", "out": "2026-10-10T10:59:59.0Z ##[error]The model is missing\n"}]

    def summary(self, steps):
        work = work_dir(self)
        os.makedirs(os.path.join(work, "steps-out"))
        for name, text in steps.items():
            with open(os.path.join(work, "steps-out", name), "w") as f:
                f.write(text)
        out = os.path.join(work, "summary.md")
        with Stubs(gh=self.GH) as s:
            r = s.run(["bash", "workers/deploy/summary.sh"], cwd=work,
                      env=s.env(**self.ENV, GITHUB_STEP_SUMMARY=out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(out) as f:
            return f.read()

    def test_steps_by_order_and_what_failed(self):
        text = self.summary({"a.tsv": "30\tContours\t75\t10 m\n", "b.tsv": "10\tRegion PBF\t3661\t373 MB\n",
                             "rock-stats.txt": "failed=1\ncount=0\n"})
        self.assertLess(text.index("| Region PBF | 1:01:01 | 373 MB |"), text.index("| Contours | 0:01:15 | 10 m |"))
        self.assertIn("The rock computation failed", text)
        self.assertIn("### [terrain](https://j) – failure after 1:00:00", text)
        self.assertIn("##[error]The model is missing", text)

    def test_no_steps(self):
        self.assertIn("no job got to its first measured step", self.summary({}))


if __name__ == "__main__":
    unittest.main()
