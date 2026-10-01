#!/usr/bin/env python3
"""The `rebuild` choice really recomputes what it promises.

The one lever for "don't use the cache". When it promises a layer and the layer
still comes from the cache, the run is green and the result old. It drifts three ways:

  * a form value `plan/options.py` doesn't know (or the reverse);
  * a `REBUILD` flag no `plan` job output carries;
  * `rebuild: rocks` with `rock_source: shading` – then a sub-pipeline that keeps
    half-done outlines computes rocks and resumes them without `fresh=1`.

Former names stay accepted as aliases but mustn't be offered.
"""
import importlib.util
import sys

import yaml

WORKFLOW = ".github/workflows/build-map-region.yml"
# elevation layers (and the shaded-rocks sub-pipeline) live in their own workflow
LAYERS = ".github/workflows/dem-layers.yml"
OPTIONS = "workers/plan/options.py"

bad = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    opts = load("plan_options", OPTIONS)
except Exception as exc:                      # noqa: BLE001 – anything is an error
    print(f"::error::{OPTIONS} can't be loaded: {exc!r}")
    sys.exit(1)

try:
    wf = yaml.safe_load(open(WORKFLOW, encoding="utf-8"))
    layers = yaml.safe_load(open(LAYERS, encoding="utf-8"))
    # a flag must be READ, by either file: the build passes it on, the layers use it
    text = (open(WORKFLOW, encoding="utf-8").read()
            + open(LAYERS, encoding="utf-8").read())
except (OSError, ValueError) as exc:
    print(f"::error::{WORKFLOW} or {LAYERS} can't be read: {exc}")
    sys.exit(1)

# YAML reads `on` as `True`, so both are tried
on = wf.get("on") or wf.get(True) or {}
inputs = ((on.get("workflow_dispatch") or {}).get("inputs") or {})
in_form = list((inputs.get("rebuild") or {}).get("options") or [])

if not in_form:
    bad.append(f"{WORKFLOW}: input `rebuild` has no choice of values – the form "
               f"can't say what to recompute.")

known = set(opts.REBUILD)
alias = set(getattr(opts, "REBUILD_ALIAS", {}))

for v in in_form:
    if v in alias:
        bad.append(f"{WORKFLOW}: `rebuild` offers `{v}`, a former name for "
                   f"`{opts.REBUILD_ALIAS[v]}`. It must be accepted (Re-run "
                   f"repeats the old values), not offered – two names for one "
                   f"thing in a form are worse than one.")
    elif v not in known:
        bad.append(f"{WORKFLOW}: `rebuild` offers `{v}`, which {OPTIONS} "
                   f"doesn't know (it knows {sorted(known)}) – the run would "
                   f"fail right in the plan job.")

for v in sorted(known - set(in_form)):
    bad.append(f"{OPTIONS}: `REBUILD` knows `{v}`, but the form in {WORKFLOW} "
               f"doesn't offer it – a value that can't be picked is never used.")

# the flag must get from `plan` to the job that recomputes
plan_outputs = ((wf.get("jobs") or {}).get("plan") or {}).get("outputs") or {}
for flag in opts.REBUILD_FLAGS:
    if f"opt_{flag}" not in plan_outputs:
        bad.append(f"{WORKFLOW}: job `plan` doesn't output `opt_{flag}`, so the "
                   f"flag never reaches the job that should recompute – a "
                   f"rebuild would quietly do nothing.")
    elif f"needs.plan.outputs.opt_{flag}" not in text:
        bad.append(f"{WORKFLOW}: nobody reads `opt_{flag}` "
                   f"(`needs.plan.outputs.opt_{flag}`) – the form would promise "
                   f"a recompute that never happens.")

# rocks from shading: `rebuild: rocks` must drop half-done outlines too
sr = ((layers.get("jobs") or {}).get("shading-rocks") or {}).get("with") or {}
sr_options = str(sr.get("options", ""))
if not sr_options:
    bad.append(f"{LAYERS}: job `shading-rocks` gets no `options`, so it can't "
               f"be told `fresh=1`.")
else:
    if "fresh=1" not in sr_options:
        bad.append(f"{LAYERS}: `shading-rocks` never gets `fresh=1` – it resumes "
                   f"the previous run's half-done outlines even when a rebuild "
                   f"is picked.")
    if "opt_rocks_rebuild" not in sr_options:
        bad.append(f"{LAYERS}: `rebuild: rocks` doesn't reach `shading-rocks` "
                   f"(`options` doesn't mention `opt_rocks_rebuild`). With "
                   f"`rock_source: shading` no slope is computed – this "
                   f"sub-pipeline makes the outlines and without `fresh=1` "
                   f"returns the old ones, on a green run.")

for b in bad:
    print(f"::error::{b}")
print(f"the `rebuild` choice: {len(bad)} errors")
sys.exit(1 if bad else 0)
