#!/usr/bin/env python3
"""Every store the pipeline asks for is in the list of known stores.

Three places say which stores exist: `drive/store.py` (`KNOWN`),
`data/dem-sources.json` and workflow `env:`. When they drift it fails only after
the work – on upload.
"""
import glob
import json
import re
import sys

STORE_PY = "workers/drive/store.py"
SOURCES = "workers/data/dem-sources.json"

bad = []

# regex, not import: importing `store.py` signs in to Drive and pulls many modules
text = open(STORE_PY, encoding="utf-8").read()
block = re.search(r"^KNOWN = \{(.*?)^\}", text, re.S | re.M)
if not block:
    print(f"::error::`KNOWN = {{…}}` can't be found in {STORE_PY} – the store check "
          f"has nothing to compare. If that list moved, update "
          f"`workers/lint/stores.py` too.")
    sys.exit(1)
known = set(re.findall(r'"([^"]+)"\s*:', block.group(1)))
print(f"{STORE_PY}: knows {len(known)} stores")

# 1. elevation sources: `store` (tiles) and `store_area` (full-resolution cutout)
sources = json.load(open(SOURCES, encoding="utf-8"))
for key, meta in sources.items():
    if key.startswith("_") or not isinstance(meta, dict):
        continue
    for field in ("store", "store_area"):
        store = meta.get(field)
        if store and store not in known:
            bad.append(f"{SOURCES}: source `{key}` wants store `{store}` "
                       f"({field}), which KNOWN in {STORE_PY} lacks. Add it "
                       f"there – otherwise the run fails only on upload, when the "
                       f"work is done.")

# 2. workflow `env:` `…_STORE: dem-…`; the value is what goes to `--store=`
for path in sorted(glob.glob(".github/workflows/*.yml")):
    for var, value in re.findall(r"^\s*([A-Z0-9_]*STORE):\s*(\S+)\s*$",
                                        open(path, encoding="utf-8").read(),
                                        re.M):
        value = value.strip("'\"")
        # a Drive folder or a `${{ … }}` expression isn't a store name
        if value.startswith("${{") or "/" in value:
            continue
        if value not in known:
            bad.append(f"{path}: `{var}: {value}` – {STORE_PY} knows no such "
                       f"store. Either the name has a typo, or it must be added "
                       f"to KNOWN.")

for b in bad:
    print(f"::error::{b}")
print(f"stores: {len(bad)} errors")
sys.exit(1 if bad else 0)
