#!/usr/bin/env python3
"""Every path to a worker must point at a file that exists.

`bash -n` sees syntax, not paths. Guarded: `$HERE/x`, `$WORKERS/x`,
`$(dirname \"$0\")/x` and full `workers/…` paths in workers and workflows;
comments are dropped (error texts name wrong paths on purpose).

The other half: a script without `+x` gives "Permission denied" and code 126.
Pieces another script reads through `.` are exempt – they aren't steps.
"""
import glob
import os
import re
import sys

EXT = r"(?:py|sh|mjs|json|txt|yml)"


def no_comments(text, style):
    """`#` for shell and python, `//` and `/* */` for JS; strings aren't told apart."""
    if style == "js":
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(re.sub(r"//.*$", "", r) for r in text.split("\n"))
    out = []
    for r in text.split("\n"):
        # whole-line comments and trailing ones after a space only
        r = re.sub(r"(^|\s)#.*$", r"\1", r)
        out.append(r)
    return "\n".join(out)


def errors_in(path, text, style):
    here = os.path.dirname(path)
    workers = os.path.dirname(here)
    t = no_comments(text, style)
    wrong = []

    # shell: $HERE/x, $WORKERS/x, $(dirname "$0")/x
    base_vars = {"HERE": here, "WORKERS": workers}
    for m in re.finditer(r'\$\{?(HERE|WORKERS)\}?/([\w./-]+\.' + EXT + r')', t):
        target = os.path.normpath(os.path.join(base_vars[m.group(1)], m.group(2)))
        if not os.path.exists(target):
            wrong.append((f"${m.group(1)}/{m.group(2)}", target))
    for m in re.finditer(r'\$\(dirname "\$0"\)/([\w./-]+\.' + EXT + r')', t):
        target = os.path.normpath(os.path.join(here, m.group(1)))
        if not os.path.exists(target):
            wrong.append((f'$(dirname "$0")/{m.group(1)}', target))

    # python: os.path.join(_HERE | _WORKERS | _DATA | _DRIVE, "…")
    # literal calls only – a variable argument can't be resolved statically
    base = {"_HERE": here, "_WORKERS": workers,
            "_DATA": os.path.join(workers, "data"),
            "_DRIVE": os.path.join(workers, "drive")}
    for m in re.finditer(
            r'os\.path\.join\(\s*(_HERE|_WORKERS|_DATA|_DRIVE)\s*,\s*'
            r'((?:"[\w.-]+"\s*,\s*)*"[\w.-]+\.' + EXT + r'")\s*\)', t):
        parts = re.findall(r'"([^"]+)"', m.group(2))
        target = os.path.normpath(os.path.join(base[m.group(1)], *parts))
        if not os.path.exists(target):
            wrong.append((f"os.path.join({m.group(1)}, {m.group(2)})", target))

    # JS: join(<a base derived from import.meta.url>, "…")
    # the base may sit in a variable that adds `".."`, so its definition is read first
    if style == "js":
        SELF_DIR = r'dirname\(\s*fileURLToPath\(\s*import\.meta\.url\s*\)\s*\)'
        bases = {}
        for m in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*' + SELF_DIR + r'\s*;', t):
            bases[m.group(1)] = here
        for m in re.finditer(
                r'(?:const|let|var)\s+(\w+)\s*=\s*join\(\s*' + SELF_DIR + r'\s*,\s*'
                r'((?:"[\w.-]+"\s*,?\s*)+)\)\s*;', t):
            bases[m.group(1)] = os.path.normpath(
                os.path.join(here, *re.findall(r'"([^"]+)"', m.group(2))))
        patterns = [(SELF_DIR, here)] + [(re.escape(k), v) for k, v in bases.items()]
        for pattern, base in patterns:
            for m in re.finditer(
                    r'join\(\s*' + pattern + r'\s*,\s*'
                    r'((?:"[\w.-]+"\s*,\s*)*"[\w.-]+\.' + EXT + r'")\s*\)', t):
                parts = re.findall(r'"([^"]+)"', m.group(1))
                target = os.path.normpath(os.path.join(base, *parts))
                if not os.path.exists(target):
                    wrong.append((f"join(…, {m.group(1)})", target))

    # python: load("name", "module.py")
    # `load()` joins onto `_HERE`; `os.pardir` reaches a sibling job
    if style == "py":
        for m in re.finditer(
                r'load\(\s*"[\w_]+"\s*,\s*((?:os\.path\.join\(\s*)?'
                r'(?:os\.pardir\s*,\s*)?(?:"[\w.-]+"\s*,?\s*)+\)?)\s*\)', t):
            arg = m.group(1)
            parts = re.findall(r'"([^"]+)"', arg)
            if not parts or not parts[-1].endswith(".py"):
                continue
            base = os.path.join(here, os.pardir) if "os.pardir" in arg else here
            target = os.path.normpath(os.path.join(base, *parts))
            if not os.path.exists(target):
                wrong.append((f"load(…, {arg})", target))

    # full `workers/…` paths
    for m in re.finditer(r'(?<![\w/.])workers/[\w./-]+\.' + EXT, t):
        if not os.path.exists(m.group(0)):
            wrong.append((m.group(0), m.group(0)))
    return wrong


def sourced():
    """`.sh` another script READS through `.` (source) – a piece of that script, not a step."""
    out = set()
    for f in glob.glob("workers/**/*.sh", recursive=True):
        t = no_comments(open(f, encoding="utf-8").read(), "sh")
        for m in re.finditer(r"(?:^|\s)(?:\.|source)\s+(workers/[\w./-]+\.sh)",
                             t, re.M):
            out.add(m.group(1))
    return out


def not_executable():
    """`workers/**/*.sh` without `+x` – every one, since scripts call each other too."""
    fragments = sourced()
    return sorted(f for f in glob.glob("workers/**/*.sh", recursive=True)
                  if f not in fragments and not os.access(f, os.X_OK))


def main():
    bad = 0
    for f in not_executable():
        print(f"::error file={f}::the script lacks `+x`, so `run: {f}` ends in "
              f"“Permission denied” (code 126). Steps run directly – fix it with "
              f"`git update-index --chmod=+x {f}` (a plain `chmod` outside the "
              f"git index isn't enough).")
        bad += 1
    files = ([(f, "sh") for f in glob.glob("workers/**/*.sh", recursive=True)]
              + [(f, "py") for f in glob.glob("workers/**/*.py", recursive=True)]
              + [(f, "js") for f in glob.glob("workers/**/*.mjs", recursive=True)]
              + [(f, "sh") for f in glob.glob(".github/workflows/*.yml")]
              + [(f, "sh") for f in glob.glob(".github/actions/*/action.yml")])
    for path, style in sorted(files):
        for written, target in errors_in(path, open(path, encoding="utf-8").read(), style):
            print(f"::error file={path}::`{written}` points at `{target}`, "
                  f"and no such file exists. Folder = job, file = step – a "
                  f"sibling is `$HERE/<step>`, another job "
                  f"`$WORKERS/<job>/<step>`.")
            bad += 1
    print(f"worker paths: {bad} errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
