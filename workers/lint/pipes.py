#!/usr/bin/env python3
"""A reader that quits early must not hang off a live producer.

`curl … | grep -q`: `grep -q` quits on the first match, `curl` gets EPIPE and
`pipefail` turns it into a non-zero pipeline although grep matched. A race, not
a deterministic failure. A pipe may end only in a reader that reads to EOF;
early quitters (`grep -q`, `head -n`, `sed …q`, `awk …exit`) read from a
variable instead (`head -1 <<<\"$VAR\"`). Short `printf`/`echo` producers are fine.
"""
import glob
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))

# readers that quit before reading all input
EARLY = re.compile(r"""\|\s*(
      grep\b[^|;&]*\s-[a-zA-Z]*q          # grep -q / -qE / -iq …
    | head\b                              # head -n
    | sed\b[^|;&]*(?<!\\)\bq[;}'"]        # sed …q
    | awk\b[^|;&]*\bexit\b                # awk … exit
)""", re.VERBOSE)

# producers done before the pipe can close
SMALL = re.compile(r"(printf|echo)\s")


def main():
    bad = []
    for path in sorted(glob.glob(os.path.join(_ROOT, "workers", "*", "*.sh"))):
        text = open(path, encoding="utf-8").read()
        if "pipefail" not in text:
            continue
        rel = os.path.relpath(path, _ROOT)
        for i, line in enumerate(text.splitlines(), 1):
            bare = line.strip()
            if bare.startswith("#") or "|" not in bare:
                continue
            m = EARLY.search(bare)
            if not m:
                continue
            # what precedes the pipe is the producer
            producer = bare[:m.start()]
            if SMALL.search(producer) or "<<<" in producer:
                continue
            bad.append(
                f"::error file={rel},line={i}::`{m.group(1).strip()}` quits "
                f"before the producer finishes – it gets EPIPE and `pipefail` "
                f"fails the step although the value was found. Save the output "
                f"to a variable and search that (`head -1 <<<\"$VAR\"`). Line: "
                f"{bare[:90]}"
            )
    for r in bad:
        print(r)
    print(f"pipes and early readers: {len(bad)} errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
