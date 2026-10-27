#!/usr/bin/env python3
"""A job using the `extracts` action may read the repository's artifacts.

Without `actions: read` the lookup is refused, the action only warns and every
job downloads from osm.fr again – a cache that quietly does nothing.
"""
import glob
import sys

import yaml

ACTION = "./.github/actions/extracts"

bad = []
for path in sorted(glob.glob(".github/workflows/*.yml")):
    wf = yaml.safe_load(open(path, encoding="utf-8")) or {}
    top = wf.get("permissions")
    for name, job in (wf.get("jobs") or {}).items():
        if not any(st.get("uses") == ACTION for st in job.get("steps") or []):
            continue
        perms = job.get("permissions", top)
        if not isinstance(perms, dict) or perms.get("actions") not in ("read", "write"):
            bad.append(f"::error file={path}::job `{name}` uses {ACTION} without "
                       f"`permissions: actions: read`, so it can't see the day's extracts.")

print("\n".join(bad))
print(f"extracts action permissions: {len(bad)} errors")
sys.exit(1 if bad else 0)
