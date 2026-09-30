#!/usr/bin/env python3
"""Check: the "Regenerate state" batch regenerates what it promises."""
import importlib.util
import json
import os
import re
import sys

import yaml

STATE = ".github/workflows/regenerate-state.yml"
REGION = ".github/workflows/regenerate-region.yml"
BUILD = ".github/workflows/build-map-region.yml"
RELAY = "workers/state/regenerate.sh"
CORE = "workers/state/relay-core.sh"
JOBS = "workers/state/jobs.py"
REGISTRY = "workers/data/packages.json"
with open(REGISTRY, encoding="utf-8") as _f:
    KNOWN_PACKAGES = {b["key"] for b in json.load(_f).get("packages") or []}
REGIONS = "workers/data/regions.json"
WF_DIR = ".github/workflows"
# batch inputs that aren't run settings
OWN = {"country", "what", "continuation"}
# budget shares must equal the build's – `env:` isn't inherited
SHARES = ("BUDGET_TRAILS_PCT", "BUDGET_FEATURES_PCT", "BUDGET_TRANSPORT_PCT",
           "BUDGET_BOUNDARIES_PCT", "BUDGET_WATER_PCT", "BUDGET_RAIL_PCT",
           "BUDGET_BUILDINGS_PCT",
           "BUDGET_CONTOURS_PCT", "BUDGET_ROCKS_PCT", "BUDGET_TERRAIN_PCT")
REGION_LEVEL = 4

bad = 0


def error(path, text):
    global bad
    bad += 1
    print(f"::error file={path}::{text}")


def wf(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def inputs(data):
    # `on` is the boolean `True` in YAML
    on = data.get("on") or data.get(True) or {}
    return (on.get("workflow_dispatch") or {}).get("inputs") or {}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


for path in (STATE, REGION, RELAY, CORE, JOBS):
    if not os.path.exists(path):
        print(f"::error::{path} doesn't exist – the regeneration batch is gone.")
        sys.exit(1)

jobs = load("state_jobs", JOBS)
state = wf(STATE)
region = wf(REGION)
build = wf(BUILD)
state_in = inputs(state)
region_in = inputs(region)
build_in = inputs(build)
relay = open(RELAY, encoding="utf-8").read()

# 1. the batch form offers exactly what the registry knows
offered = list((state_in.get("what") or {}).get("options") or [])
if offered != list(jobs.JOBS):
    error(STATE, f"The `what` choice is {offered}, by {JOBS} it should be "
                 f"{list(jobs.JOBS)}. A choice the registry doesn't know fails "
                 f"only in the run; one missing from the form nobody picks.")

# 2. the same for the one-region form – no more, no less
via_region = [k for k, v in jobs.JOBS.items()
              if v["workflow"] == os.path.basename(REGION)]
offered_region = list((region_in.get("what") or {}).get("options") or [])
if offered_region != via_region:
    error(REGION, f"The `what` choice is {offered_region}, by {JOBS} it should "
                  f"be {via_region} (what really goes through this workflow). "
                  f"The batch would otherwise start a run with a value this "
                  f"form doesn't know – and it fails right at the input.")

# 3. the registry passes only what the target form has; empty env: shape, not values
for key, j in jobs.JOBS.items():
    target = os.path.join(WF_DIR, j["workflow"])
    if not os.path.exists(target):
        error(JOBS, f"`{key}` is to be run by `{j['workflow']}`, which doesn't "
                    f"exist ({target}).")
        continue
    target_in = inputs(wf(target))
    if "region" not in target_in:
        error(JOBS, f"`{j['workflow']}` has no `region` input, but the relay "
                    f"passes it – the batch can't say which region it is.")
    for name, value in jobs.fields(key, env={}).items():
        spec = target_in.get(name)
        if spec is None:
            error(JOBS, f"`{key}` passes `{j['workflow']}` field `{name}`, "
                        f"which that form lacks – the region run would fail "
                        f"right at the input.")
            continue
        choices = spec.get("options")
        if choices and value not in choices:
            error(JOBS, f"`{key}` passes `{name}={value}`, but "
                        f"`{j['workflow']}` offers {choices}.")
    # a package the packer doesn't know fails only at `--only`
    if j["package"] not in KNOWN_PACKAGES:
        error(JOBS, f"`{key}` promises package `{j['package']}`, which "
                    f"{REGISTRY} doesn't know – the run would fail at `--only`.")

# 3b. somebody really does every choice; otherwise every job skips, green
region_text = open(REGION, encoding="utf-8").read()
for key in offered_region:
    if f"inputs.what == '{key}'" not in region_text:
        error(REGION, f"No job condition mentions `{key}` "
                      f"(`inputs.what == '{key}'`) – the run would take it, "
                      f"skip every job and end green having regenerated nothing.")

# 4. what is asked is passed – an input not passed is a silent lie
for name in state_in:
    if name == "continuation":
        continue
    if not re.search(rf"-f {re.escape(name)}=", relay):
        error(RELAY, f"The batch asks for `{name}`, but `regenerate.sh` doesn't "
                     f"pass it to the next leg (`-f {name}=`) – from the second "
                     f"region on the chain would regenerate something else, green.")

# settings must reach the region run too – through the registry
passed = {m for c in jobs.TARGETS.values() for m in c["passes"]}
for name in state_in:
    if name in OWN or name in passed:
        continue
    error(JOBS, f"The batch asks for `{name}`, but no target in `TARGETS` passes "
                f"it to the region run – the whole country would be regenerated "
                f"with the default and nobody would learn it.")

# 5. settings match the region form – the same values, not just names
for name, spec in state_in.items():
    if name in OWN:
        continue
    model = build_in.get(name) or region_in.get(name)
    if model is None:
        error(STATE, f"The batch asks for `{name}`, but neither the region form "
                     f"({BUILD}) nor {REGION} has it – nobody to pass it to.")
        continue
    for key in ("type", "default", "options"):
        if (spec or {}).get(key) != (model or {}).get(key):
            error(STATE, f"Input `{name}`: the batch has {key}="
                         f"{(spec or {}).get(key)!r}, the region form "
                         f"{key}={(model or {}).get(key)!r}. The batch is the "
                         f"same form one level up.")

# 6. the same regions are offered as in the build
a = list((region_in.get("region") or {}).get("options") or [])
b = list((build_in.get("region") or {}).get("options") or [])
if a != b:
    error(REGION, f"The `region` choice is {a}, the map build offers {b}. A "
                  f"region that can be built must be regenerable too – otherwise "
                  f"its layer grows stale and nobody learns it.")

# 7. the country choice matches the region registry
regions = json.load(open(REGIONS, encoding="utf-8"))
with_regions = [k for k, v in regions.items()
                if v.get("admin_level") != REGION_LEVEL
                and any(r.get("country") == k
                        and r.get("admin_level") == REGION_LEVEL
                        for r in regions.values())]
offered_countries = list((state_in.get("country") or {}).get("options") or [])
if offered_countries != with_regions:
    error(STATE, f"The `country` choice is {offered_countries}, by {REGIONS} it "
                 f"should be {with_regions} (countries that really have a region).")


# 8. budget shares didn't drift from the build
def env_values(data):
    return {k: str(v) for k, v in (data.get("env") or {}).items()}


e_reg, e_build = env_values(region), env_values(build)
for k in SHARES:
    if k not in e_reg:
        error(REGION, f"`env:` lacks `{k}`, but the layer script reads it – "
                      f"the share would be empty and `$(( … ))` would fail.")
    elif e_reg[k] != e_build.get(k):
        error(REGION, f"`{k}` is {e_reg[k]!r} here, {e_build.get(k)!r} in "
                      f"{BUILD}. A workflow's `env:` isn't inherited, so it is "
                      f"written twice – and when they drift, the same layer "
                      f"warns differently in regeneration than in the build.")

# 9. the relay starts itself and stands on the shared core
if 'gh workflow run "$SELF"' not in relay:
    error(RELAY, "`regenerate.sh` doesn't start its next run "
                 "(`gh workflow run \"$SELF\"`). Without it the batch "
                 "regenerates one region and pretends it is done.")
if os.path.basename(CORE) not in relay:
    error(RELAY, f"`regenerate.sh` doesn't build on {CORE}. A second copy of "
                 f"the relay would one day drift exactly on whether the chain goes on.")

text = open(STATE, encoding="utf-8").read()
m = re.search(r"timeout-minutes:\s*(\d+)", text)
if not m:
    error(STATE, "The relay job has no `timeout-minutes`. A job's cap is 6 h and "
                 "waiting for a region is 5 h in the script – a stuck leg would "
                 "hold the runner for all six.")
elif int(m.group(1)) > 360:
    error(STATE, f"`timeout-minutes: {m.group(1)}` is over a job's cap (360). "
                 f"GitHub kills it before the next leg starts.")

print(f"regeneration batch: {bad} errors ({len(jobs.JOBS)} things to "
      f"regenerate, {len(state_in)} form inputs)")
sys.exit(1 if bad else 0)
