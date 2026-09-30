#!/usr/bin/env python3
"""Whoever runs Planetiler needs `actions/setup-java` in the job – and the same version.

The JAR targets Java 21 and `ubuntu-latest` has 17, so without that step
`java -jar` doesn't start. `setup-java` is an action and can't move into bash.

  1. every job running Planetiler (also through `workers/*.sh`) has `setup-java`;
  2. its `java-version` equals `JAVA_MIN` in `workers/lib/planetiler.sh`;
  3. no `setup-java` in the repository has another version;
  4. a clipped run doesn't pass `--bounds` and `--polygon` together – `tileExtents`
     is computed in the constructor, so the polygon shows in the log and clips nothing.
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

import yaml

SCRIPT = "workers/lib/planetiler.sh"
IS_PLANETILER = re.compile(r"planetiler\.jar|lib/planetiler\.sh")
# a run script, not a mentioned one: the path is the command's first word
SCRIPT_PATH = re.compile(
    r"^\s*(?:(?:bash|sh|source|\.)\s+)?(workers/[\w./-]+\.sh)\b", re.M)


def no_comments(s):
    """A line starting with `#` runs nothing, in bash or `run:`."""
    return "\n".join(l for l in s.split("\n") if not re.match(r"^\s*#", l))


def with_called(text, seen=None):
    """A step's text plus every `workers/*.sh` it runs, recursively."""
    seen = seen if seen is not None else set()
    out = [text]
    for path in SCRIPT_PATH.findall(no_comments(text)):
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        with open(path, encoding="utf-8") as f:
            out.append(with_called(f.read(), seen))
    return "\n".join(out)


bad = []

with open(SCRIPT, encoding="utf-8") as f:
    source = f.read()
m = re.search(r'^JAVA_MIN="\$\{JAVA_MIN:-(\d+)\}"', source, re.M)
if not m:
    print(f"::error file={SCRIPT}::has no `JAVA_MIN=\"${{JAVA_MIN:-<number>}}\"` line. "
          f"It's the one place saying which Java Planetiler wants – without "
          f"it there's no checking that jobs really set it.")
    sys.exit(1)
WANTS = m.group(1)
print(f"{SCRIPT}: Planetiler wants Java {WANTS}")

for path in sorted(glob.glob(".github/workflows/*.yml")):
    with open(path, encoding="utf-8") as f:
        wf = yaml.safe_load(f) or {}
    for job_name, job in (wf.get("jobs") or {}).items():
        steps = job.get("steps") or []

        java = [s for s in steps
                if "actions/setup-java" in str(s.get("uses") or "")]
        for st in java:
            ver = str((st.get("with") or {}).get("java-version") or "")
            if ver != WANTS:
                bad.append(
                    f"{path}: job '{job_name}' sets Java {ver or '?'}, but "
                    f"Planetiler wants {WANTS} (`JAVA_MIN` in {SCRIPT}). Two "
                    f"versions side by side mean one job builds differently.")

        runs = any(IS_PLANETILER.search(no_comments(with_called(
            str(s.get("run") or "")))) for s in steps)
        if runs and not java:
            bad.append(
                f"{path}: job '{job_name}' runs Planetiler but has no "
                f"`actions/setup-java` step. The runner has Java 17 and the jar "
                f"targets {WANTS} – `java -jar` fails with "
                f"UnsupportedClassVersionError after all the work before it. Add "
                f"`- uses: actions/setup-java@v5` with `distribution: temurin` and "
                f"`java-version: \"{WANTS}\"` (as the jobs in build-map-region.yml have).")

# 4. `--bounds` and `--polygon` together (see the docstring)
# searched in scripts, not YAML: the call is in `workers/<job>/build.sh`
for path in sorted(glob.glob("workers/*/*.sh")):
    with open(path, encoding="utf-8") as f:
        text = no_comments(f.read())
    if not IS_PLANETILER.search(text):
        continue
    # either in the command itself or both printed by `region-clip.sh`
    together = with_called(text)
    has_polygon = "--polygon" in no_comments(together)
    has_bounds = "--bounds" in no_comments(together)
    # `region-clip.sh` names both (one per branch); it's run below instead
    if path.endswith("region-clip.sh"):
        continue
    if has_polygon and has_bounds and "region-clip.sh" not in text:
        bad.append(
            f"{path}: runs Planetiler with `--polygon` AND `--bounds`. That "
            f"quietly turns the shape off and the map reaches past the region. "
            f"Keep one – `workers/lib/region-clip.sh` builds the clip.")

# `region-clip.sh` is RUN, not read – with and without a polygon
CLIP = "workers/lib/region-clip.sh"
with tempfile.TemporaryDirectory() as tmp:
    poly = os.path.join(tmp, "region.poly")
    with open(poly, "w", encoding="utf-8") as f:
        f.write("test\n1\n  19.0 49.0\n  20.0 49.0\n  20.0 50.0\nEND\nEND\n")
    # clip off must give `--bounds` without `--polygon`; an empty switch means on
    for label, args, env, must, must_not in (
        ("with a polygon", [CLIP, "19,48,20,49", poly], {}, "--polygon", "--bounds"),
        ("without a polygon", [CLIP, "19,48,20,49", os.path.join(tmp, "none.poly")],
         {}, "--bounds", "--polygon"),
        ("with the clip off", [CLIP, "19,48,20,49", poly],
         {"OPT_REGION_CLIP": "false"}, "--bounds", "--polygon"),
        ("with an empty OPT_REGION_CLIP", [CLIP, "19,48,20,49", poly],
         {"OPT_REGION_CLIP": ""}, "--polygon", "--bounds"),
    ):
        r = subprocess.run(args, capture_output=True, text=True,
                           env={**os.environ, **env})
        if r.returncode != 0:
            bad.append(f"{CLIP} ({label}) failed: {r.stderr.strip()[:200]}")
            continue
        if must not in r.stdout:
            bad.append(f"{CLIP} ({label}) didn't print `{must}`: {r.stdout!r}")
        if must_not in r.stdout:
            bad.append(
                f"{CLIP} ({label}) printed `{must_not}` – `--bounds` must NOT "
                f"go with `--polygon` (it quietly turns the shape off), and "
                f"without a polygon there's nothing to clip with.")

for b in bad:
    print(f"::error::{b}")
print(f"Planetiler and Java: {len(bad)} errors")
sys.exit(1 if bad else 0)
