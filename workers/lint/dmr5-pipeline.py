#!/usr/bin/env python3
"""Check: DMR 5.0 is refilled by its own pipeline and the way to it stays whole."""
import re, sys, yaml
bad = 0

# 1. update-dem.yml must fail on `dmr5`
txt = open(".github/workflows/update-dem.yml").read()
m = re.search(r"^\s*dmr5\)(.*?);;", txt, re.S | re.M)
if not m or "::error::" not in m.group(1) or "exit 1" not in m.group(1):
    print("::error file=.github/workflows/update-dem.yml::the `dmr5` branch "
          "must fail – a refill that refills nothing must not turn green "
          "(run 31307163093).")
    bad += 1

# 2. dmr5-drive.yml must be callable and take what Build map passes
d = yaml.safe_load(open(".github/workflows/dmr5-drive.yml"))
on = d[[k for k in d if k is True or k == "on"][0]]
call = (on.get("workflow_call") or {}).get("inputs") or {}
LAYERS = ".github/workflows/dem-layers.yml"
bm = yaml.safe_load(open(LAYERS))
for name, job in (bm.get("jobs") or {}).items():
    if job.get("uses") != "./.github/workflows/dmr5-drive.yml":
        continue
    for key in (job.get("with") or {}):
        if key not in call:
            print(f"::error file={LAYERS}::job '{name}' passes `{key}`, "
                  f"which dmr5-drive.yml lacks in `workflow_call`")
            bad += 1
if not any(j.get("uses") == "./.github/workflows/dmr5-drive.yml"
           for j in (bm.get("jobs") or {}).values()):
    print(f"::error file={LAYERS}::nobody refills DMR 5.0 – "
          f"no job calls dmr5-drive.yml")
    bad += 1

# 3. a cut-out is refilled by bbox, not by range key: a key read the whole rectangle
for name, job in (bm.get("jobs") or {}).items():
    with_ = job.get("with") or {}
    if job.get("uses") != "./.github/workflows/dmr5-drive.yml":
        continue
    if str(with_.get("tiles", "")).lower() == "true":
        continue   # tiles are given by degrees, the name comes from them
    area, asset = str(with_.get("area", "")), str(with_.get("asset", ""))
    if "mirror_dmr5_area" not in area:
        print(f"::error file={LAYERS}::job '{name}' passes dmr5-drive.yml "
              f"`area: {area}` – a cut-out must take `check-dem.outputs."
              f"mirror_dmr5_area` (the bbox the run asked for), otherwise "
              f"the whole rectangle from areas.json is read from Drive.")
        bad += 1
    if "mirror_dmr5_asset" not in asset:
        print(f"::error file={LAYERS}::job '{name}' doesn't pass `asset` from "
              f"`check-dem.outputs.mirror_dmr5_asset`. It is required with a "
              f"bbox in `area` – a name can't be derived from a bbox.")
        bad += 1

chk = open("workers/dem/check.sh").read()
for out in ("mirror_dmr5_area", "mirror_dmr5_asset"):
    if f"{out}=" not in chk:
        print(f"::error file=workers/dem/check.sh::output `{out}` is missing, "
              f"{LAYERS} passes it to dmr5-drive.yml")
        bad += 1

# 4. a tile promises a whole degree: the WGS84 conversion bulges the window
cut = open("workers/drive/dmr5-cut.py").read()
m = re.search(r"def country_tiles\((.*?)\):(.*?)(?=\ndef |\Z)", cut, re.S)
if not m or "window" not in m.group(1):
    print("::error file=workers/drive/dmr5-cut.py::`country_tiles` must take "
          "a `window` – without it the WGS84 overhang is stored under a whole "
          "degree's name (runs 31476448895 → 31484544154).")
    bad += 1
elif "--window" not in m.group(2):
    print("::error file=workers/drive/dmr5-cut.py::`country_tiles` doesn't "
          "pass the window to `workers/dem/tiles.py` (`--window=`), so a tile "
          "will lie about its extent.")
    bad += 1
dm = open("workers/drive/dmr5.py").read()
if not re.search(r"country_tiles\([^)]*window\s*=", dm, re.S):
    print("::error file=workers/drive/dmr5.py::the `finish` stage must pass "
          "`country_tiles` the plan's window (`window=state[\"bbox\"]`) – the "
          "area really read.")
    bad += 1
tl = open("workers/dem/tiles.py").read()
if "--window" not in tl:
    print("::error file=workers/dem/tiles.py::option `--window` is missing, "
          "by which the caller says which degrees it read whole.")
    bad += 1

# 5. a missing tile must be refilled: "when there is none" let 48 % of a region through
if "coverage.py" not in open("workers/dem/fetch.sh").read():
    print("::error file=workers/dem/fetch.sh::downloading tiles doesn't measure "
          "whether the mosaic covers the area (`workers/dem/coverage.py`) – "
          "a file count can't tell.")
    bad += 1
if not re.search(r"\$src\" = 'dmr5'.{0,200}?missing.{0,80}?need=true", chk, re.S):
    print("::error file=workers/dem/check.sh::with `dmr5` EVERY missing tile "
          "must be refilled (`[ -n \"$missing\" ] && need=true`). The refill "
          "reads exactly the degrees given and stores empty ones empty, so a "
          "missing name means it was never read.")
    bad += 1
print(f"way to DMR 5.0: {bad} errors")
sys.exit(1 if bad else 0)
