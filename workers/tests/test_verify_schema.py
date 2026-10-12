import os
import unittest

from load import WORKERS
from stubs import Stubs

SCRIPT = os.path.join(WORKERS, "lib/verify-schema.sh")


class VerifySchema(unittest.TestCase):
    def verify(self, out, exit=0):
        with Stubs(java=[{"match": "verify", "out": out, "exit": exit}]) as s:
            return s.run(["bash", SCRIPT, "x.yml"], env=s.env(JAR="p.jar"))

    def test_all_passing_is_green(self):
        self.assertEqual(self.verify("\x1b[1m\x1b[32m9 passed\x1b[0m\n").returncode, 0)

    def test_a_failed_example_fails_although_planetiler_exits_0(self):
        r = self.verify("\x1b[1m\x1b[31m3 failed\x1b[0m, \x1b[1m\x1b[32m4 passed\x1b[0m, 7 total\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::x.yml", r.stdout)

    def test_no_example_verified_fails(self):
        self.assertEqual(self.verify("OK\n").returncode, 1)

    def test_planetiler_failing_fails(self):
        self.assertEqual(self.verify("bad schema\n", exit=2).returncode, 1)


if __name__ == "__main__":
    unittest.main()
