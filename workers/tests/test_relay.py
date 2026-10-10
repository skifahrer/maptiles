import os
import tempfile
import unittest

from load import WORKERS, needs_cmd, worker
from stubs import Stubs

ROOT = os.path.dirname(WORKERS)
REGIONS = worker("state/queue.py").regions_of(worker("state/queue.py").read(), "slovensko")
CALLER = """
TITLE="Batch" DESCRIPTION="Test."
hand_over() { echo "$1" > "$OUT/baton"; }
start_region() { echo "$1" >> "$OUT/started"; }
. workers/state/relay-core.sh
relay_main
"""


def view(run, state, times=None):
    rule = {"match": rf"^run view {run} .*status,conclusion", "out": state}
    return dict(rule, times=times) if times else rule


def never_started(run, answer, times=None):
    rule = {"match": rf"^run view {run} .*attempt,jobs", "out": answer}
    return dict(rule, times=times) if times else rule


NEW_RUN = {"match": r"^run list", "out": "333"}


@needs_cmd("bash")
class Relay(unittest.TestCase):
    def relay(self, baton, gh):
        self.out = tempfile.mkdtemp()
        with Stubs(gh=gh, sleep=[{"match": ".*"}]) as s:
            r = s.run(["bash", "-c", CALLER], cwd=ROOT, env=s.env(
                COUNTRY="slovensko", REPO="o/r", REGION_WF="build-map-region.yml",
                CONTINUATION=baton, SUMMARY=os.path.join(self.out, "summary"), OUT=self.out))
            self.gh = s.calls("gh")
        return r

    def read(self, name):
        path = os.path.join(self.out, name)
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read().strip()

    def test_first_leg_starts_the_first_region(self):
        r = self.relay("", [NEW_RUN])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read("started"), REGIONS[0])
        self.assertEqual(self.read("baton"), f"333:{REGIONS[0]}|{','.join(REGIONS[1:])}||1")

    def test_baton_hands_over_the_done_region(self):
        a, b, c = REGIONS[:3]
        r = self.relay(f"111:{a}|{b},{c}||1", [view(111, "completed success"), NEW_RUN])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read("started"), b)
        self.assertEqual(self.read("baton"), f"333:{b}|{c}|{a}:success:111|2")

    def test_failed_region_goes_on_and_the_last_leg_fails(self):
        a, b = REGIONS[:2]
        r = self.relay(f"111:{a}|{b}||1", [view(111, "completed failure"), never_started(111, "false"), NEW_RUN])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read("started"), b)
        r = self.relay(f"333:{b}||{a}:failure:111|2", [view(333, "completed success")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("1 region(s) failed", r.stdout)
        self.assertEqual(self.read("started"), "")

    def test_cancelled_region_stops_green(self):
        a, b = REGIONS[:2]
        r = self.relay(f"111:{a}|{b}||1", [view(111, "completed cancelled")])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read("started"), self.read("baton")), ("", ""))
        self.assertIn(f"|{b}|{a}:cancelled:111|0", self.read("summary"))

    def test_never_started_run_is_rerun_once(self):
        # fix 1681: the relay never re-ran a region whose jobs never started
        a, b = REGIONS[:2]
        r = self.relay(f"111:{a}|{b}||1", [
            view(111, "completed failure"), never_started(111, "true", times=1),
            never_started(111, "false"), {"match": r"^run rerun 111"}, NEW_RUN])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sum(c[:2] == ["run", "rerun"] for c in self.gh), 1)
        self.assertIn(f"{a}:failure:111", self.read("baton"))

    def test_rerun_that_succeeds_counts_as_success(self):
        a, b = REGIONS[:2]
        r = self.relay(f"111:{a}|{b}||1", [
            view(111, "completed failure", times=1), never_started(111, "true"),
            {"match": r"^run rerun 111"}, view(111, "completed success"), NEW_RUN])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"{a}:success:111", self.read("baton"))

    def test_legs_are_capped(self):
        cap = len(REGIONS) * 3 + 2
        r = self.relay(f"111:{REGIONS[0]}|||{cap}", [view(111, "completed success")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't shrinking", r.stdout)
        self.assertEqual(self.gh, [])

    def test_no_run_found_stops_the_chain(self):
        r = self.relay("", [{"match": r"^run list", "out": ""}])
        self.assertEqual(r.returncode, 1)
        self.assertIn("didn't show", r.stdout)
        self.assertEqual(self.read("baton"), "")


if __name__ == "__main__":
    unittest.main()
