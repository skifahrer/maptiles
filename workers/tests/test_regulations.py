import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from load import worker

r = worker("transport/regulations.py")

SK = {"country": "sk", "law": {"name": "Zákon č. 8/2009 Z. z."},
      "speed": {"urban": {"default": 50, "section": "§ 16 ods. 4"},
                "motorway": {"default": 130, "hgv": 90}}}


class Checked(unittest.TestCase):
    def test_the_countrys_limits_pass(self):
        self.assertEqual(r.checked(SK, "sk"), (SK, None))

    def test_another_country_is_refused(self):
        self.assertIsNone(r.checked(SK, "cz")[0])

    def test_a_context_without_a_whole_default_is_refused(self):
        bad = {**SK, "speed": {"urban": {"default": "50"}}}
        self.assertIn("urban", r.checked(bad, "sk")[1])
        self.assertIsNotNone(r.checked({**SK, "speed": {}}, "sk")[1])


class Main(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        os.makedirs(os.path.join(self.root, "regulations"))
        self.out = os.path.join(self.root, "r-regulations.json")

    def write(self, country, doc):
        with open(os.path.join(self.root, "regulations", f"{country}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def run_it(self, country):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return r.main([f"--signs={self.root}", f"--country={country}", f"--out={self.out}"])

    def test_the_file_is_copied_whole(self):
        self.write("sk", SK)
        self.assertEqual(self.run_it("sk"), 0)
        with open(self.out, encoding="utf-8") as f:
            self.assertEqual(json.load(f), SK)

    def test_a_country_without_regulations_writes_nothing(self):
        self.assertEqual(self.run_it("pl"), 0)
        self.assertFalse(os.path.exists(self.out))

    def test_a_broken_file_fails_and_writes_nothing(self):
        self.write("sk", {**SK, "country": "cz"})
        self.assertEqual(self.run_it("sk"), 1)
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
