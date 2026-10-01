#!/usr/bin/env python3
"""Publish only to Drive. Run by `Check · workflow lint`.

Neither a release nor an artifact meant to outlive a run goes to GitHub –
everything goes to the Drive store. And a typo in a store name doesn't fail but
gives an empty store, so literal names are checked against `KNOWN`.
"""
import ast
import glob
import re
import sys

import yaml

STORE = "workers/drive/store.py"

# the searched commands are assembled, or this file would find itself
REL = "gh " + "release"
UP = "actions/upload" + "-artifact"
FLAG = "--store" + "="


def sources():
    """Everything that can publish: workflows and workers."""
    return (sorted(glob.glob(".github/workflows/*.yml"))
            + sorted(glob.glob("workers/**/*.sh", recursive=True))
            + sorted(glob.glob("workers/**/*.py", recursive=True)))


def no_releases():
    """1. Not a single RUN `gh release` anywhere.

    A call, not a mention: comment lines are skipped, and Python is searched for
    an argument list, not text. `gh api /repos/…/releases` is fine – that's how
    `workers/tools/cleanup-actions.py` DELETES old releases.
    """
    bad = 0

    def scan(path, text, where=""):
        nonlocal bad
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if REL in line:
                print(f"::error file={path}::{where}`{REL}` publishes to a GitHub "
                      f"release (line {i}). Nothing goes to releases – use "
                      f"`python3 {STORE}` (--put / --get / --names / --rm).")
                bad += 1

    for path in sorted(glob.glob("workers/**/*.sh", recursive=True)):
        scan(path, open(path, encoding="utf-8").read())

    for path in sorted(glob.glob(".github/workflows/*.yml")):
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for job, jd in (d.get("jobs") or {}).items():
            for st in (jd or {}).get("steps") or []:
                run = str((st or {}).get("run") or "")
                if run:
                    scan(path, run, f"{job} / {st.get('name', '?')}: ")

    # Python calls `gh` with an argument list, so that list is searched
    for path in sorted(glob.glob("workers/**/*.py", recursive=True)):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as exc:
            print(f"::error file={path}::can't be parsed ({exc})")
            bad += 1
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            first = [e.value for e in node.elts[:2]
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            # `REL.split()`, not a literal list, or this check finds itself
            if first[:2] == REL.split():
                print(f"::error file={path},line={node.lineno}::calls "
                      f"`{REL}` with an argument list. Nothing goes to releases "
                      f"– use `{STORE}` as a module (`index`, `download`, "
                      f"`upload`) or a command.")
                bad += 1
    return bad


def artifact_lives_a_day():
    """2. An artifact lives one day at most – a crate between jobs of one run.

    Longer is publishing, which belongs in the `results` store
    (`workers/deploy/publish-results.sh`).
    """
    bad = 0
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for job, jd in (d.get("jobs") or {}).items():
            for st in (jd or {}).get("steps") or []:
                uses = str((st or {}).get("uses") or "")
                if not uses.startswith(UP):
                    continue
                days = (st.get("with") or {}).get("retention-days")
                if days is not None and int(days) <= 1:
                    continue
                print(f"::error file={path}::step '{st.get('name', '?')}' "
                      f"in job '{job}' keeps an artifact for "
                      f"{days if days is not None else 'the repository default of'} days. "
                      f"An artifact may only be a crate between jobs of one run "
                      f"(`retention-days: 1`); what must outlive a run goes to "
                      f"the Drive store (`workers/deploy/publish-results.sh`).")
                bad += 1
    return bad


def known_names():
    """3. The store exists and `--store=` has no typo. Returns (errors, names)."""
    try:
        tree = ast.parse(open(STORE, encoding="utf-8").read())
    except OSError:
        print(f"::error::{STORE} is missing – without it the pipeline has nowhere to publish.")
        return 1, set()
    known = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == "KNOWN" for target in node.targets)
                and isinstance(node.value, ast.Dict)):
            known = {k.value for k in node.value.keys}
    if not known:
        print(f"::error file={STORE}::no KNOWN list of stores found in it.")
        return 1, known

    # a literal name after `--store=`; `$VARIABLE` is `known_or_die`'s job at run time
    used = re.compile(re.escape(FLAG) + r"[\"']?([a-z][a-z0-9-]*)")
    bad = 0
    for path in sources():
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            for m in used.finditer(line):
                if m.group(1) not in known:
                    print(f"::error file={path},line={i}::store "
                          f"`{m.group(1)}` isn't in KNOWN in {STORE} "
                          f"({', '.join(sorted(known))}). A name typo looks like "
                          f"an empty store, so the build would quietly recompute "
                          f"everything.")
                    bad += 1
    return bad, known


def names_tell_truth():
    """4. `*_RELEASE` in `env:` lies about where the thing lives."""
    bad = 0
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            m = re.match(r"\s*([A-Z][A-Z0-9_]*)_RELEASE:", line)
            if m:
                print(f"::error file={path},line={i}::`{m.group(1)}_RELEASE` "
                      f"names a Drive store “release”. Rename it to "
                      f"`{m.group(1)}_STORE` – a name saying where the thing "
                      f"really is.")
                bad += 1
    return bad


def stores_agree():
    """5. The same `*_STORE` in two workflows must hold the same value.

    A store has a WRITER and a READER, usually two workflows; if they drift the
    reader looks into a store nobody writes and says there's nothing there.
    """
    where = {}
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for k, v in (d.get("env") or {}).items():
            if k.endswith("_STORE") and isinstance(v, str) and "${" not in v:
                where.setdefault(k, {})[path] = v
    bad = 0
    for k, m in sorted(where.items()):
        if len(set(m.values())) > 1:
            listing = ", ".join(f"{p}={v}" for p, v in sorted(m.items()))
            print(f"::error::`{k}` has different values in different workflows "
                  f"({listing}). One store, one name – otherwise it's written "
                  f"elsewhere than read, and the run only says nothing is there.")
            bad += 1
    return bad


def main():
    bad = (no_releases() + artifact_lives_a_day() + names_tell_truth()
           + stores_agree())
    errors, known = known_names()
    bad += errors
    print(f"publishing only to Drive: {bad} errors "
          f"({len(known)} stores in KNOWN)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
