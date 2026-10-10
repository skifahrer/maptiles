import glob
import os
import py_compile
import shutil
import subprocess
import tempfile
import unittest

from load import WORKERS

ROOT = os.path.dirname(WORKERS)


def files(*patterns):
    return sorted(f for p in patterns
                  for f in glob.glob(os.path.join(ROOT, p), recursive=True))


class Syntax(unittest.TestCase):
    def check(self, cmd, paths):
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=os.path.relpath(path, ROOT)):
                r = subprocess.run(cmd + [os.path.relpath(path, ROOT)], capture_output=True, text=True,
                                   cwd=ROOT, env={**os.environ, "LANG": "C.UTF-8"})
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_shell(self):
        self.check(["bash", "-n"], files("workers/**/*.sh"))

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_js(self):
        self.check(["node", "--check"], files("workers/**/*.mjs", "poc/web/*.js"))

    @unittest.skipUnless(shutil.which("shellcheck"), "needs shellcheck")
    def test_shellcheck(self):
        # SC1111: typographic quotes in messages are meant, as in the actionlint step
        self.check(["shellcheck", "-x", "-S", "warning", "-e", "SC1111"], files("workers/**/*.sh"))

    def test_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in files("workers/**/*.py"):
                with self.subTest(path=os.path.relpath(path, ROOT)):
                    py_compile.compile(path, cfile=os.path.join(tmp, "x.pyc"), doraise=True)


if __name__ == "__main__":
    unittest.main()
