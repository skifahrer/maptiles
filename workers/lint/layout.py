#!/usr/bin/env python3
"""Workers lie in a folder per job – exactly one level deep.

  1. no runnable worker lies in `workers/` itself;
  2. the depth is exactly one – modules find shared things through
     `os.path.dirname(_HERE)`, which is `workers/` only from `workers/<job>/`;
  3. the folder must be known: add a new job here and to `workers/README.md`.
"""
import os
import sys

# folder = job (or the workflow that job calls)
KNOWN = {
    "data": "lookups (areas, regions, dem-sources)",
    "lib": "what several jobs share (watch, planetiler, png, budget)",
    "plan": "jobs `settings`, `plan` and `keys`",
    "dem": "job `check-dem` and model refills",
    "drive": "Google Drive: DMR 5.0, store, cache, sign-in",
    "contours-rocks": "jobs `contours` and `rocks`",
    "rocks-shading": "workflow “Data · shaded rocks”",
    "terrain": "job `terrain`",
    "trails": "job `trails`",
    "features": "job `features`",
    "transport": "workflow “Map · transport network” (transport.yml)",
    "boundaries": "workflow “Map · boundaries” (boundaries.yml)",
    "water": "workflow “Map · water” (water.yml)",
    "rail": "workflow “Map · railways” (rail.yml)",
    "history": "workflow “Map · history” (history.yml)",
    "buildings": "workflow “Map · settlements” (buildings.yml)",
    "routing": "routing: profile, routing tiles and node order",
    "tiles": "job `tiles`",
    "wiki": "workflow “Map · Build wiki” (wiki.yml)",
    "world": "workflow “Map · Build world” (world-map.yml)",
    "state": "the “… state” workflows (batches of a country's regions)",
    "assets": "job `assets`",
    "styles": "styles for web and iOS",
    "deploy": "job `deploy` and publishing",
    "lint": "checks run by lint-workflows.yml",
    "tests": "unit tests run by tests.yml",
    "tools": "outside the build (cleanup)",
}
SUFFIXES = (".py", ".sh", ".mjs")

bad = 0
roots = sorted(f for f in os.listdir("workers")
                if os.path.isfile(os.path.join("workers", f)))
for f in roots:
    if f.endswith(SUFFIXES):
        print(f"::error file=workers/{f}::a worker lies directly in `workers/`, "
              f"not in a job folder. Move it to `workers/<job>/` – checks "
              f"(file length, step env, publishing) look at `workers/<job>/*` "
              f"and would quietly skip this one.")
        bad += 1

for name in sorted(os.listdir("workers")):
    path = os.path.join("workers", name)
    if not os.path.isdir(path) or name == "__pycache__":
        continue
    if name not in KNOWN:
        print(f"::error file={path}::unknown folder `{name}`. A folder is a job – "
              f"add it to KNOWN in this script and to workers/README.md, or move "
              f"the files to the job they belong to.")
        bad += 1
        continue
    for root, _, files in os.walk(path):
        if "__pycache__" in root:
            continue
        depth = root.count(os.sep)
        for s in files:
            if not s.endswith(SUFFIXES):
                continue
            if depth > 1:  # workers/<job> = 1
                print(f"::error file={os.path.join(root, s)}::a worker is deeper "
                      f"than `workers/<job>/`. Modules find shared things "
                      f"through `os.path.dirname(_HERE)`, which is `workers/` "
                      f"only at depth one – from level two `_DATA` misses.")
                bad += 1

counts = {m: len([s for s in os.listdir(os.path.join("workers", m))
                 if s.endswith(SUFFIXES)])
         for m in KNOWN if os.path.isdir(os.path.join("workers", m))}
print("workers per job: "
      + ", ".join(f"{m} {n}" for m, n in sorted(counts.items()) if n))
print(f"workers/ layout: {bad} errors")
sys.exit(1 if bad else 0)
