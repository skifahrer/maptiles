import glob
import os
import re
import unittest

import yaml

from load import WORKERS

ROOT = os.path.dirname(WORKERS)
# what bash 4 added; macOS runs bash 3.2, which stops on them
BASH4 = [
    (r"\$\{[^}]*[\^,]{1,2}\}", "case change `${x^^}` / `${x,,}`"),
    (r"\b(declare|local|typeset)\s+-[a-zA-Z]*A", "associative array"),
    (r"\b(mapfile|readarray|coproc)\b", "a bash 4 builtin"),
    (r"&>>|\|&", "a bash 4 redirection"),
]


def macos_scripts():
    """Every `workers/*.sh` a job on a macOS runner runs, by the workflow that runs it."""
    found = {}
    for path in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        with open(path, encoding="utf-8") as f:
            jobs = (yaml.safe_load(f) or {}).get("jobs") or {}
        for name, job in jobs.items():
            if not str(job.get("runs-on", "")).startswith("macos"):
                continue
            for step in job.get("steps") or []:
                for script in re.findall(r"workers/[\w/.-]+\.sh", step.get("run") or ""):
                    found.setdefault(script, f"{os.path.basename(path)} / {name}")
    return found


class MacosBash(unittest.TestCase):
    def test_scripts_on_macos_runners_read_in_bash_3_2(self):
        scripts = macos_scripts()
        self.assertIn("workers/mountain/layers-env.sh", scripts)
        for script, where in scripts.items():
            with open(os.path.join(ROOT, script), encoding="utf-8") as f:
                text = re.sub(r"^\s*#.*$", "", f.read(), flags=re.M)
            for pattern, what in BASH4:
                with self.subTest(script=script):
                    self.assertIsNone(re.search(pattern, text),
                                      f"{script} ({where}) uses {what}, which macOS's bash 3.2 can't run")


if __name__ == "__main__":
    unittest.main()
