#!/usr/bin/env python3
"""Check: the "Build map state" batch builds what you would build by hand."""
import json
import os
import re
import sys

import yaml

STATE = ".github/workflows/build-map-state.yml"
REGION = ".github/workflows/build-map-region.yml"
RELAY = "workers/state/relay.sh"
QUEUE = "workers/state/queue.py"
REGIONS = "workers/data/regions.json"
OPTIONS_PY = "workers/plan/options.py"
# batch inputs that aren't map settings
OWN = {"country", "continuation"}
# passed fixed – otherwise eight runs would fight over Pages
FIXED = {"area": "whole_region", "publish_pages": "false"}

bad = 0


def error(path, text):
    global bad
    bad += 1
    print(f"::error file={path}::{text}")


def inputs(path):
    d = yaml.safe_load(open(path)) or {}
    on = d[[k for k in d if k is True or k == "on"][0]]
    return (on.get("workflow_dispatch") or {}).get("inputs") or {}


if not os.path.exists(STATE):
    print(f"::error::{STATE} doesn't exist – the country batch is gone.")
    sys.exit(1)

state_in = inputs(STATE)
region_in = inputs(REGION)
relay = open(RELAY).read()

# 1. the batch form matches the region form – the same values, not just names
for name, spec in state_in.items():
    if name in OWN:
        continue
    if name not in region_in:
        error(STATE, f"The batch asks for `{name}`, but the region form ({REGION}) "
                     f"has no such input – nobody to pass it to.")
        continue
    a, b = spec or {}, region_in[name] or {}
    for key in ("type", "default", "options"):
        if a.get(key) != b.get(key):
            error(STATE, f"Input `{name}`: the batch has {key}={a.get(key)!r}, "
                         f"the region {key}={b.get(key)!r}. A different default "
                         f"or list means the whole country comes out different "
                         f"from one region built by hand.")

# the other way: `area` and `publish_pages` are left out on purpose, `region` is the batch's
for name in region_in:
    if name in state_in or name in FIXED or name == "region":
        continue
    error(STATE, f"The region form has `{name}`, the batch doesn't. Ask for it, "
                 f"or pass it fixed and add it to `FIXED` in "
                 f"{os.path.basename(__file__)} with the reason – otherwise the "
                 f"whole country is built with the default and nobody learns it.")

# 2. what is asked is passed – an input not passed is a silent lie
for name in state_in:
    if name in OWN:
        continue
    if not re.search(rf"-f {re.escape(name)}=", relay):
        error(RELAY, f"The batch asks for `{name}`, but `relay.sh` doesn't pass "
                     f"it to the region run (`-f {name}=`) – the whole country "
                     f"would be built with the default, and green.")

for name, value in FIXED.items():
    if not re.search(rf"-f {re.escape(name)}={re.escape(value)}\b", relay):
        error(RELAY, f"`relay.sh` doesn't pass `-f {name}={value}`. That is "
                     f"exactly how the batch differs from one region, on purpose "
                     f"– see the workflow header.")

# 3. the country choice matches the registry – `type: choice` can't be generated, only guarded
sys.path.insert(0, os.path.dirname(os.path.abspath(QUEUE)))
regions = json.load(open(REGIONS))
REGION_LEVEL = 4
with_regions = [k for k, v in regions.items()
                if v.get("admin_level") != REGION_LEVEL
                and any(r.get("country") == k and r.get("admin_level") == REGION_LEVEL
                        for r in regions.values())]
offered = ((state_in.get("country") or {}).get("options")) or []
if offered != with_regions:
    error(STATE, f"The `country` choice is {offered}, by {REGIONS} it should be "
                 f"{with_regions} (countries that really have a region). A "
                 f"country without regions leaves the batch nothing to run.")

# 3b. the batch doesn't recompute what exists: reuse layers from the stores
OPTION = "reuse_layers"
if f"{OPTION}=true" not in relay:
    error(RELAY, f"`relay.sh` doesn't pass the region run `{OPTION}=true`. The "
                 f"batch would then compute contours, rocks and hillshading "
                 f"anew in every region – most of the day the batch takes.")
if f'"{OPTION}"' not in open(OPTIONS_PY).read():
    error(OPTIONS_PY, f"`{OPTION}` isn't a known option, but `relay.sh` passes "
                      f"it – every region would fail on an unknown option.")

# 4. the relay starts itself – otherwise the chain ends with the first region, green
if "gh workflow run \"$SELF\"" not in relay:
    error(RELAY, "`relay.sh` doesn't start its next run (`gh workflow run "
                 "\"$SELF\"`). Without it the batch builds one region and "
                 "pretends it is done.")
if not re.search(r"timeout-minutes:\s*(\d+)", open(STATE).read()):
    error(STATE, "The relay job has no `timeout-minutes`. A job's cap is 6 h and "
                 "waiting for a region is 5 h in the script – a stuck leg would "
                 "hold the runner for all six.")
else:
    minutes = int(re.search(r"timeout-minutes:\s*(\d+)", open(STATE).read()).group(1))
    if minutes > 360:
        error(STATE, f"`timeout-minutes: {minutes}` is over a job's cap (360). "
                     f"GitHub kills it before the next leg starts.")

print(f"country batch: {bad} errors ({len(state_in)} form inputs, "
      f"{len(with_regions)} countries with regions)")
sys.exit(1 if bad else 0)
