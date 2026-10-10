"""Fake commands first on `PATH`: each answers from a table and logs its arguments."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

STUB = r'''#!/usr/bin/env python3
import json, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.path.join(here, name + ".log"), "a") as f:
    f.write(json.dumps(args) + "\n")
with open(os.path.join(here, name + ".json")) as f:
    table = json.load(f)
line = " ".join(args)
for rule in table:
    if re.search(rule["match"], line):
        sys.stdout.write(rule.get("out", ""))
        sys.stderr.write(rule.get("err", ""))
        sys.exit(rule.get("exit", 0))
sys.stderr.write(f"stub {name}: no rule for {line}\n")
sys.exit(97)
'''


class Stubs:
    """`with Stubs(gh=[{"match": "...", "out": "..."}]) as s: s.run([...])`."""

    def __init__(self, **commands):
        self.dir = tempfile.mkdtemp(prefix="stubs-")
        for name, rules in commands.items():
            self.add(name, rules)

    def add(self, name, rules):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(STUB.replace("/usr/bin/env python3", sys.executable, 1))
        os.chmod(path, 0o755)
        with open(path + ".json", "w") as f:
            json.dump(rules, f)

    def calls(self, name):
        path = os.path.join(self.dir, name + ".log")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def env(self, **extra):
        return {**os.environ, "PATH": self.dir + os.pathsep + os.environ["PATH"], **extra}

    def run(self, cmd, **kw):
        kw.setdefault("env", self.env())
        return subprocess.run(cmd, capture_output=True, text=True, **kw)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
