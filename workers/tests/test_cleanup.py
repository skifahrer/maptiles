import json
import os
import sys
import unittest

from load import WORKERS
from stubs import Stubs

ROOT = os.path.dirname(WORKERS)
REPO = "o/r"


def answer(match, data):
    return {"match": match, "out": json.dumps(data)}


def deleted(stubs):
    return [c[-1] for c in stubs.calls("gh") if "DELETE" in c]


class CleanupCache(unittest.TestCase):
    CACHES = [{"id": 1, "key": "dem-N49E019", "size_in_bytes": 10},
              {"id": 2, "key": "keep-me", "size_in_bytes": 20},
              {"id": 3, "key": "contours-x", "size_in_bytes": 30}]
    RULES = [answer(r"actions/caches\?", {"actions_caches": CACHES}),
             answer(r"cache/usage", {"active_caches_size_in_bytes": 60, "active_caches_count": 3}),
             {"match": r"-X DELETE", "out": ""}]

    def run_cleanup(self, **env):
        with Stubs(gh=self.RULES) as s:
            r = s.run([sys.executable, os.path.join(WORKERS, "tools/cleanup-cache.py")],
                      env=s.env(GITHUB_REPOSITORY=REPO, GITHUB_STEP_SUMMARY="", **env), cwd=ROOT)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return deleted(s)

    def test_keep_prefix_survives(self):
        self.assertEqual(self.run_cleanup(KEEP="keep"),
                         [f"/repos/{REPO}/actions/caches/1", f"/repos/{REPO}/actions/caches/3"])

    def test_everything_without_keep(self):
        self.assertEqual(len(self.run_cleanup()), 3)

    def test_dry_run_deletes_nothing(self):
        self.assertEqual(self.run_cleanup(DRY_RUN="true", KEEP=""), [])


class CleanupActions(unittest.TestCase):
    WORKFLOWS = [{"id": 10, "path": ".github/workflows/tests.yml"},
                 {"id": 11, "path": ".github/workflows/retired-long-ago.yml"},
                 {"id": 12, "path": "dynamic/pages/pages-build-deployment"}]
    RULES = [
        answer(r"actions/workflows\?", {"workflows": WORKFLOWS}),
        answer(r"workflows/10/runs", {"workflow_runs": [
            {"id": 100, "name": "Check · tests", "run_number": 1},
            {"id": 101, "name": ".github/workflows/tests.yml", "run_number": 2},
            {"id": 999, "name": ".github/workflows/tests.yml", "run_number": 3}]}),
        answer(r"workflows/11/runs", {"workflow_runs": [{"id": 110, "name": "Old", "run_number": 1}]}),
        answer(r"/compare/master\.\.\.claude/merged", {"status": "behind", "ahead_by": 0}),
        answer(r"/compare/master\.\.\.claude/open", {"status": "ahead", "ahead_by": 2}),
        answer(r"/branches\?", [{"name": "master"}, {"name": "claude/merged"},
                                {"name": "claude/open"}, {"name": "feature/merged"}]),
        answer(r"/releases\?", [{"id": 7, "tag_name": "dem-sonny", "name": "DEM",
                                 "assets": [{"size": 5}]}]),
        answer(r"actions/artifacts\?", {"artifacts": [
            {"id": 20, "name": "site", "size_in_bytes": 3, "workflow_run": {"id": 5}},
            {"id": 21, "name": "site-self", "size_in_bytes": 3, "workflow_run": {"id": 999}}]}),
        answer(r"^-H \S+ \S+ /repos/o/r$", {"default_branch": "master"}),
        {"match": r"-X DELETE", "out": ""},
    ]

    def run_cleanup(self, **env):
        with Stubs(gh=self.RULES) as s:
            r = s.run([sys.executable, os.path.join(WORKERS, "tools/cleanup-actions.py")],
                      env=s.env(GITHUB_REPOSITORY=REPO, GITHUB_RUN_ID="999",
                                GITHUB_STEP_SUMMARY="", **env), cwd=ROOT)
            return r, deleted(s)

    def test_runs(self):
        r, gone = self.run_cleanup(MODE="runs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # a live workflow's real run and this run itself survive
        self.assertEqual(sorted(gone), [f"/repos/{REPO}/actions/runs/101",
                                        f"/repos/{REPO}/actions/runs/110"])

    def test_branches_only_merged_claude(self):
        _, gone = self.run_cleanup(MODE="runs_and_branches")
        self.assertIn(f"/repos/{REPO}/git/refs/heads/claude/merged", gone)
        self.assertFalse([g for g in gone if "claude/open" in g or "feature/" in g])

    def test_releases_and_artifacts(self):
        _, gone = self.run_cleanup(MODE="releases_and_artifacts")
        self.assertEqual(sorted(gone), [f"/repos/{REPO}/actions/artifacts/20",
                                        f"/repos/{REPO}/git/refs/tags/dem-sonny",
                                        f"/repos/{REPO}/releases/7"])

    def test_old_mode_name(self):
        _, gone = self.run_cleanup(MODE="behy")
        self.assertEqual(len(gone), 2)

    def test_dry_run_deletes_nothing(self):
        r, gone = self.run_cleanup(MODE="everything", DRY_RUN="true")
        self.assertEqual((r.returncode, gone), (0, []))

    def test_unknown_mode_fails(self):
        r, gone = self.run_cleanup(MODE="evrything")
        self.assertEqual((r.returncode, gone), (1, []))


if __name__ == "__main__":
    unittest.main()
