#!/usr/bin/env python3
"""`needs.<job>.outputs.<x>` must point at an output that job really gives.

A missing output isn't a run error – GitHub reads it as an empty string, an
`if:` on it is false, the layer isn't added and the run goes green.

  1. `needs.<job>` must be in that job's `needs:`;
  2. the output must exist – for a plain job in its `outputs:`, for a job with
     `uses: ./.github/workflows/X.yml` in that file's `on.workflow_call.outputs`.
"""
import glob
import os
import re
import sys

import yaml


def load(path):
    """YAML without whole commented-out lines, which the text search would match."""
    txt = open(path, encoding="utf-8").read()
    txt = re.sub(r"^[ \t]*#.*$", "", txt, flags=re.M)
    return txt, (yaml.safe_load(txt) or {})


def call_outputs(uses):
    """A called workflow's outputs, or None when it isn't a local call.

    YAML reads `on:` as boolean `True`, so both keys are tried.
    """
    if not isinstance(uses, str) or not uses.startswith("./"):
        return None
    # `removeprefix`, not `lstrip("./")`, which strips characters and eats `.github`
    path = uses.split("@", 1)[0].removeprefix("./")
    if not os.path.exists(path):
        return {}
    _, doc = load(path)
    on = doc.get("on", doc.get(True)) or {}
    return ((on.get("workflow_call") or {}).get("outputs") or {})


def main():
    errs = 0
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        txt, doc = load(path)
        jobs = doc.get("jobs") or {}
        starts = {}
        for j in jobs:
            m = re.search(r"^  " + re.escape(j) + r":$", txt, re.M)
            if m:
                starts[j] = m.start()
        if not starts:
            continue

        def job_of(pos):
            return max(((j, p) for j, p in starts.items() if p < pos),
                       key=lambda x: x[1])[0]

        for m in re.finditer(
                r"needs\.([a-zA-Z0-9_-]+)\.(outputs\.([a-zA-Z0-9_]+)|result)",
                txt):
            tgt, cur = m.group(1), job_of(m.start())
            needs = jobs[cur].get("needs") or []
            if isinstance(needs, str):
                needs = [needs]
            if tgt not in needs:
                print(f"::error file={path}::job '{cur}' uses needs.{tgt}, "
                      f"but lacks it in needs")
                errs += 1
                continue
            key = m.group(3)
            if not key:
                continue
            declared = jobs[tgt].get("outputs") or {}
            called = call_outputs(jobs[tgt].get("uses"))
            if called is not None:
                # the job calls another workflow – its outputs are THERE
                declared = called
            if key not in declared:
                where = (f" (it calls `{jobs[tgt]['uses']}`, the output must be in "
                         f"its `on.workflow_call.outputs`)" if called is not None
                         else "")
                print(f"::error file={path}::job '{tgt}' has no output '{key}' "
                      f"('{cur}' wants it){where}")
                errs += 1
    print(f"references between jobs: {errs} errors")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
