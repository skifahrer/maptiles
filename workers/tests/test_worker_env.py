import io
import os
import unittest
from contextlib import redirect_stdout

from load import WORKERS, worker

lint = worker("lint/worker-env.py")


class Arithmetic(unittest.TestCase):
    def test_a_name_without_dollar_is_read(self):
        got = lint.read_vars("TBUDGET_MB=$(( LIMIT_MB * BUDGET_TRAILS_PCT / 100 ))")
        self.assertIn("BUDGET_TRAILS_PCT", got)

    def test_a_command_inside_is_no_variable(self):
        got = lint.arithmetic_names('echo "$(( $(date +%s) - T0 )) s, $(( ${A:-1} + $B ))"')
        self.assertEqual(got, {"T0"})


class Workflows(unittest.TestCase):
    def test_every_script_gets_what_it_reads(self):
        here = os.getcwd()
        os.chdir(os.path.dirname(WORKERS))
        self.addCleanup(os.chdir, here)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(lint.main(), 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
