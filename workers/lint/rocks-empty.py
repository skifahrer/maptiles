#!/usr/bin/env python3
"""Empty rocks from a failed computation must not be saved as a finished layer."""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_WORKERS)
ROCKS = os.path.join(_WORKERS, "contours-rocks", "rocks.sh")
SITE = os.path.join(_WORKERS, "contours-rocks", "site.sh")
PLAN = os.path.join(_WORKERS, "contours-rocks", "rock-plan.py")
FLOW = os.path.join(_ROOT, ".github", "workflows", "dem-layers.yml")
MARKER = "contours-out/rock-failed.txt"


def main():
    bad = []
    rocks = open(ROCKS, encoding="utf-8").read()
    site = open(SITE, encoding="utf-8").read()
    plan = open(PLAN, encoding="utf-8").read()
    flow = open(FLOW, encoding="utf-8").read()

    if not re.search(rf">\s*{re.escape(MARKER)}", rocks):
        bad.append(f"workers/contours-rocks/rocks.sh doesn't mark a failed "
                   f"computation in `{MARKER}`. Without it an empty layer is "
                   f"saved as finished and the region has no rocks while the "
                   f"cache key holds.")

    # the step is found by what it saves, not by name: a name is a typo away
    saving = [ln for ln in flow.splitlines()
              if "if:" in ln
              and "steps.done.outputs.compute == 'true'" in ln
              and "contours-out/rock" in ln]
    if not saving:
        bad.append("no step saving rocks to the cache can be found in "
                   ".github/workflows/dem-layers.yml – fix this check along "
                   "with the workflow.")
    else:
        for condition, why in (
                ("hashFiles('contours-out/rocks.pmtiles') != ''",
                 "a run that never got to the tiles (e.g. failed in the slope) "
                 "is saved as a finished layer"),
                (f"hashFiles('{MARKER}') == ''",
                 "an empty layer from a failed computation is saved as finished")):
            if not any(condition in ln for ln in saving):
                bad.append(f"saving rocks to the cache in dem-layers.yml lacks "
                           f"the condition `{condition}` – {why} and later runs "
                           f"take it from the cache.")

    if MARKER not in site:
        bad.append(f"workers/contours-rocks/site.sh doesn't look at `{MARKER}` "
                   f"– an empty `.pmtiles` goes into the map and the package, "
                   f"where it can't be told from a region without rocks.")

    if "capture_output=True" in plan and not re.search(r"raise\s+CommandError",
                                                       plan):
        bad.append("workers/contours-rocks/rock-plan.py drops the stderr of the "
                   "commands it runs – a failed ogr2ogr leaves only \"exit "
                   "status 1\" and nothing to fix it by.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Rocks: a failed computation is marked, not cached, kept out of the "
          "map, and its stderr is in the log ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
