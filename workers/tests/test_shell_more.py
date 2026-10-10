import json
import os
import shutil
import subprocess
import tempfile
import unittest

from load import WORKERS, needs, needs_cmd, worker
from stubs import Stubs, shadow_workers

ROOT = os.path.dirname(WORKERS)
REGIONS = worker("state/queue.py").regions_of(worker("state/queue.py").read(), "slovensko")
NEW_RUN = {"match": r"^run list", "out": "333"}
DISPATCH = {"match": r"^workflow run"}


def fields(call):
    """`gh workflow run X … -f k=v …` → (X, {k: v})."""
    out = {}
    for flag, value in zip(call, call[1:]):
        if flag == "-f":
            k, _, v = value.partition("=")
            out[k] = v
    return call[2], out


@needs_cmd("bash")
class RelayCallers(unittest.TestCase):
    def leg(self, script, **env):
        with Stubs(gh=[NEW_RUN, DISPATCH], sleep=[{"match": ".*"}]) as s:
            r = s.run(["bash", f"workers/state/{script}"], cwd=ROOT, env=s.env(
                COUNTRY="slovensko", REPO="o/r", REF="master", CONTINUATION="",
                SUMMARY=os.devnull, **env))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            runs = [fields(c) for c in s.calls("gh") if c[:2] == ["workflow", "run"]]
        self.assertEqual(len(runs), 2, "one region started, one leg handed on")
        return runs

    def test_map_batch(self):
        (wf, region), (self_wf, baton) = self.leg("relay.sh", OPTIONS="rock_res=2", TEST="false")
        self.assertEqual(wf, "build-map-region.yml")
        self.assertEqual(region["region"], REGIONS[0])
        self.assertEqual((region["area"], region["publish_pages"]), ("whole_region", "false"))
        self.assertEqual(region["options"], "reuse_layers=true rock_res=2")
        self.assertEqual(self_wf, "build-map-state.yml")
        self.assertEqual(baton["options"], "rock_res=2", "the next leg gets the original options")
        self.assertTrue(baton["continuation"].startswith(f"333:{REGIONS[0]}|"))

    def test_own_reuse_layers_left(self):
        (_, region), _ = self.leg("relay.sh", OPTIONS="reuse_layers=false")
        self.assertEqual(region["options"], "reuse_layers=false")

    def test_regenerate_batch(self):
        (wf, region), (self_wf, baton) = self.leg("regenerate.sh", WHAT="rocks", ROCK_SLOPE="45",
                                                  OPTIONS="rock_res=2 test_at=20,49")
        jobs = worker("state/jobs.py")
        self.assertEqual(wf, jobs.job("rocks")["workflow"])
        self.assertEqual((region["what"], region["rock_slope"], region["options"]),
                         ("rocks", "45", "rock_res=2 test_at=20,49"), "options keep their spaces")
        self.assertEqual((self_wf, baton["what"]), ("regenerate-state.yml", "rocks"))

    def test_wiki_batch(self):
        (wf, region), (self_wf, baton) = self.leg("wiki.sh", REBUILD="true")
        self.assertEqual((wf, region["rebuild"], self_wf, baton["rebuild"]),
                         ("wiki.yml", "true", "wiki-state.yml", "true"))


class PagesSource(unittest.TestCase):
    def pages(self, rules):
        with tempfile.NamedTemporaryFile("r") as out, Stubs(gh=rules) as s:
            r = s.run(["bash", "workers/deploy/pages-source.sh"], cwd=ROOT,
                      env=s.env(GITHUB_REPOSITORY="o/r", GITHUB_OUTPUT=out.name))
            return r, out.read().strip(), s.calls("gh")

    def test_already_actions(self):
        r, out, calls = self.pages([{"match": r"^api repos/o/r/pages$", "out": '{"build_type":"workflow"}'}])
        self.assertEqual((r.returncode, out), (0, "build_type=workflow"))
        self.assertEqual(len(calls), 1)

    def test_branch_switched_and_verified(self):
        r, out, _ = self.pages([
            {"match": r"^api repos/o/r/pages$", "out": '{"build_type":"legacy"}', "times": 1},
            {"match": r"^api -X PUT"},
            {"match": r"--jq", "out": "workflow"}])
        self.assertEqual((r.returncode, out), (0, "build_type=workflow"))

    def test_switch_refused_is_a_warning(self):
        r, out, _ = self.pages([
            {"match": r"^api repos/o/r/pages$", "out": '{"build_type":"legacy"}'},
            {"match": r"^api -X PUT", "err": "403", "exit": 1}])
        self.assertEqual((r.returncode, out), (0, "build_type=legacy"))
        self.assertIn("::warning::", r.stdout)

    def test_off_and_no_rights_stops(self):
        r, _, _ = self.pages([{"match": r"^api repos/o/r/pages$", "exit": 1},
                              {"match": r"^api -X POST", "err": "Resource not accessible", "exit": 1}])
        self.assertEqual(r.returncode, 1)
        self.assertIn("admin rights", r.stdout)


class NameLanguages(unittest.TestCase):
    def test_every_language_beside_every_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "s.yml"), os.path.join(tmp, "o.yml")
            with open(src, "w") as f:
                f.write("attrs:\n  - key: class\n    - key: name\n  - key: name_en\n")
            r = subprocess.run(["bash", "workers/lib/name-languages.sh", src, dst], cwd=ROOT,
                               env={**os.environ, "TILE_LANGUAGES": "sk,de"}, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(dst) as f:
                lines = f.read().splitlines()
        self.assertEqual(lines, ["attrs:", "  - key: class", "    - key: name",
                                 '    - key: "name:sk"', '    - key: "name:de"', "  - key: name_en"])


class WikiCache(unittest.TestCase):
    def key(self, **env):
        r = subprocess.run(["bash", "workers/wiki/key.sh"], cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "COUNTRY": "", "LANGS": "", "RUN_ID": "9", **env})
        return dict(line.split("=", 1) for line in r.stdout.split())

    def test_key(self):
        k = self.key(REGION="trnavsky", COUNTRY="slovensko", LANGS="sk,en")
        self.assertEqual(k["prefix"], "wiki-v3-trnavsky_slovensko_sk_en_text-")
        self.assertEqual(k["key"], k["prefix"] + "9")
        self.assertNotEqual(self.key(REGION="trnavsky", LANGS="sk")["prefix"], k["prefix"])

    @needs_cmd("jq")
    def test_need(self):
        catalog = {"slovensko": {"regions": {"trnavsky": {"maps": {"wikipedia": {}}}}}}
        for cached, catalogued, skip in ((True, True, "true"), (False, True, "false"), (True, False, "false")):
            with self.subTest(cached=cached, catalogued=catalogued):
                work = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, work)
                fake = ("import os\nwith open(os.environ['GITHUB_OUTPUT'], 'a') as f:\n"
                        f"    f.write({'cache-matched-key=wiki-v3-x' if cached else ''!r})\n")
                shadow_workers(work, {"drive/cache.py": fake})
                with open(os.path.join(work, "maps.json"), "w") as f:
                    json.dump(catalog if catalogued else {"slovensko": {"regions": {}}}, f)
                out = os.path.join(work, "out")
                r = subprocess.run(["bash", "workers/wiki/need.sh"], cwd=work, capture_output=True, text=True,
                                   env={**os.environ, "REGION_KEY": "trnavsky", "COUNTRY": "", "LANGS": "",
                                        "RUN_ID": "1", "GITHUB_OUTPUT": out, "RUNNER_TEMP": work})
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(out) as f:
                    self.assertEqual(f.read().strip(), f"skip={skip}")


@needs("yaml")
class Settings(unittest.TestCase):
    ENV = {"INPUTS_JSON": '{"region": "trnavsky"}', "OPT_OPTIONS": "", "OPT_REBUILD": "nothing",
           "OPT_CONTOUR_SOURCE": "sonny", "OPT_ROCK_SOURCE": "sonny", "OPT_SHADING_SOURCE": "sonny",
           "OPT_TEST": "false", "OPT_PUBLISH_PAGES": "true"}

    def settings(self, **env):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        summary = os.path.join(tmp, "summary.md")
        r = subprocess.run(["bash", "workers/plan/settings.sh"], cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, **self.ENV, **env, "RUNNER_TEMP": tmp, "GITHUB_STEP_SUMMARY": summary})
        if not os.path.exists(summary):
            return r, ""
        with open(summary) as f:
            return r, f.read()

    def test_summary_has_form_and_result(self):
        r, summary = self.settings()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## The form this run came from", summary)
        self.assertIn("## What came of it", summary)

    def test_unknown_option_fails_first(self):
        r, _ = self.settings(OPT_OPTIONS="rock_ress=2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Unknown option", r.stderr)


if __name__ == "__main__":
    unittest.main()
