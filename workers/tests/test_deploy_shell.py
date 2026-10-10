import json
import os
import shutil
import subprocess
import tempfile
import unittest

from load import WORKERS, needs_cmd
from stubs import Stubs, shadow_workers

ROOT = os.path.dirname(WORKERS)
SCHEMA_OK = "import sys\nsys.exit(0)\n"
SCHEMA_BAD = "import sys\nprint('::error::bad catalog')\nsys.exit(1)\n"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@needs_cmd("git")
class CatalogCommit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.origin = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", self.origin], check=True)
        seed = os.path.join(self.tmp, "seed")
        subprocess.run(["git", "clone", "-q", self.origin, seed], check=True, capture_output=True)
        for args in (("config", "user.email", "t@x"), ("config", "user.name", "t")):
            git(seed, *args)
        self.write(seed, {"sk": {"a": 1}})
        git(seed, "add", "maps.json")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "push", "-q", "origin", "HEAD:master")
        self.seed = seed

    def write(self, where, data, name="maps.json"):
        # the form catalog.py and catalog-merge.py write
        with open(os.path.join(where, name), "w") as f:
            f.write(json.dumps(data, separators=(",", ":"), sort_keys=True) + "\n")

    def read_origin(self):
        return json.loads(subprocess.run(["git", "--git-dir", self.origin, "show", "master:maps.json"],
                                         capture_output=True, text=True, check=True).stdout)

    def clone(self, schema=SCHEMA_OK):
        """A job's checkout, as the run started; `maps.json.base` is what catalog.py found."""
        job = os.path.join(self.tmp, f"job{len(os.listdir(self.tmp))}")
        subprocess.run(["git", "clone", "-q", self.origin, job], check=True, capture_output=True)
        shadow_workers(job, {"deploy/catalog-schema.py": schema})
        shutil.copy(os.path.join(job, "maps.json"), os.path.join(job, "maps.json.base"))
        return job

    def commit(self, job, mine):
        self.write(job, mine)
        with Stubs(sleep=[{"match": ".*"}]) as s:
            return s.run(["bash", "workers/deploy/catalog.sh"], cwd=job,
                         env=s.env(MAPS_JSON="maps.json", BRANCH="master", RUN_URL="http://run/1"))

    def run_job(self, mine, schema=SCHEMA_OK):
        return self.commit(self.clone(schema), mine)

    def test_unchanged_makes_no_commit(self):
        before = git(self.seed, "ls-remote", "origin", "master")
        r = self.run_job({"sk": {"a": 1}})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("didn't change", r.stdout)
        self.assertEqual(git(self.seed, "ls-remote", "origin", "master"), before)

    def test_change_is_pushed_onto_a_moved_branch(self):
        # another job of the run wrote `cz` meanwhile; this run's `b` must not drop it
        job = self.clone()
        self.write(self.seed, {"sk": {"a": 1}, "cz": {"x": 1}})
        git(self.seed, "commit", "-q", "-am", "other job")
        git(self.seed, "push", "-q", "origin", "HEAD:master")
        r = self.commit(job, {"sk": {"a": 1, "b": 2}})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_origin(), {"sk": {"a": 1, "b": 2}, "cz": {"x": 1}})

    def test_bad_catalog_isnt_committed(self):
        r = self.run_job({"sk": {"a": 2}}, schema=SCHEMA_BAD)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read_origin(), {"sk": {"a": 1}})

    def test_repository_rule_fails_the_run(self):
        hook = os.path.join(self.origin, "hooks", "pre-receive")
        with open(hook, "w") as f:
            f.write("#!/bin/sh\necho 'GH013: Repository rule violations found' >&2\nexit 1\n")
        os.chmod(hook, 0o755)
        r = self.run_job({"sk": {"a": 2}})
        self.assertEqual(r.returncode, 1)
        self.assertIn("repository rule rejected the push", r.stdout)


SPRITE = {"bus": {}, "mark-white-red-bar": {}}


@needs_cmd("jq", "node")
class SiteCheck(unittest.TestCase):
    def site(self, style=None, sprite2x=SPRITE, tiles=("r.pmtiles",)):
        site = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, site)
        style = style or {"glyphs": "https://fonts.openmaptiles.org/{fontstack}", "sources": {"base": {}},
                          "layers": [{"id": "poi", "layout": {"icon-image": "bus"}}]}
        for rel, data in (("styles/r-svetla.json", style), ("sprites/s.json", SPRITE),
                          ("sprites/s@2x.json", sprite2x)):
            os.makedirs(os.path.dirname(os.path.join(site, rel)), exist_ok=True)
            if data is not None:
                with open(os.path.join(site, rel), "w") as f:
                    json.dump(data, f)
        for rel in ("sprites/s.png", "sprites/s@2x.png", *(f"tiles/{t}" for t in tiles)):
            os.makedirs(os.path.dirname(os.path.join(site, rel)), exist_ok=True)
            with open(os.path.join(site, rel), "wb") as f:
                f.write(b"x")
        return site

    def check(self, site, limit="900"):
        return subprocess.run(["bash", "workers/deploy/check.sh"], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "SPRITE": "s", "REGION_KEY": "r", "LIMIT_MB": limit, "SITE": site})

    def test_whole_site_passes(self):
        r = self.check(self.site())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_retina_sprite_missing_an_image(self):
        r = self.check(self.site(sprite2x={"bus": {}}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("lacks images the 1× has: mark-white-red-bar", r.stdout)

    def test_icon_not_in_the_sprite(self):
        style = {"glyphs": "https://fonts.openmaptiles.org/x", "sources": {},
                 "layers": [{"id": "poi", "layout": {"icon-image": "train"}}]}
        r = self.check(self.site(style=style))
        self.assertIn("icon 'train', which isn't in the sprite", r.stdout)

    def test_layer_without_its_archive(self):
        style = {"glyphs": "https://fonts.openmaptiles.org/x", "sources": {"contours": {}}, "layers": []}
        r = self.check(self.site(style=style))
        self.assertIn("the style uses contours, but", r.stdout)

    def test_own_glyphs_must_be_there(self):
        style = {"glyphs": "https://me/fonts/{fontstack}/{range}.pbf", "sources": {},
                 "layers": [{"id": "l", "layout": {"text-font": ["Noto Sans Regular"]}}]}
        r = self.check(self.site(style=style))
        self.assertIn("fontstack 'Noto Sans Regular'", r.stdout)

    def test_over_budget(self):
        r = self.check(self.site(), limit="0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the budget is 0 MB", r.stdout)


if __name__ == "__main__":
    unittest.main()
