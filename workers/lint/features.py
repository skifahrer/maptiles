#!/usr/bin/env python3
"""What the landscape feature schemas ask for, their prefilter passes.

Job `features` reads the PBF three times: the prefilter (`filter.txt`) and two
Planetiler runs over its output (`features.yml`, `points.yml`). When they drift
it's quiet – Planetiler gets a PBF without those objects and makes tiles without
them. Every `include_when` must have its bare key or key=value in the prefilter;
the filter may be wider.
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
# both schemas read the same prefiltered PBF, so both check against one `filter.txt`
SCHEMAS = [os.path.join(_WORKERS, "features", "features.yml"),
           os.path.join(_WORKERS, "features", "points.yml")]
FILTER = os.path.join(_WORKERS, "features", "filter.txt")

bad = []


def filter_tags(path):
    """`{key: {values} or None}` from `osmium tags-filter --expressions`; None = the whole key."""
    out = {}
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "/" in line.split("=", 1)[0]:
                line = line.split("/", 1)[1]
            key, _, values = line.partition("=")
            key = key.strip()
            if not values:
                out[key] = None
                continue
            if out.get(key, "x") is None:
                continue                      # the whole key passed already
            out.setdefault(key, set()).update(
                v.strip() for v in values.split(",") if v.strip())
    return out


def schema_tags(path):
    """`[(key, value, where)]` from every `include_when` in a schema."""
    with open(path) as f:
        data = yaml.safe_load(f)
    out = []
    for layer in data.get("layers") or []:
        for feat in layer.get("features") or []:
            when = feat.get("include_when")
            if not isinstance(when, dict):
                continue
            for key, value in when.items():
                values = value if isinstance(value, list) else [value]
                for v in values:
                    out.append((key, v, layer.get("id", "?")))
    return out


tags = filter_tags(FILTER)
requirements = 0
for schema in SCHEMAS:
    short = os.path.relpath(schema, _WORKERS)
    reqs = schema_tags(schema)
    requirements += len(reqs)
    for key, value, layer_id in reqs:
        if key in tags and tags[key] is None:
            continue                          # a bare key passes everything
        # `true` means "the tag is present", so knowing the key is enough
        if value is True:
            if key not in tags:
                bad.append(f"{short} (layer `{layer_id}`) wants tag `{key}` "
                           f"present, but the prefilter doesn't know that key – "
                           f"objects with it never reach Planetiler's PBF and "
                           f"quietly miss from the tiles.")
            continue
        if key not in tags:
            bad.append(f"{short} (layer `{layer_id}`) wants `{key}={value}`, "
                       f"but the prefilter doesn't know key `{key}` – the class "
                       f"quietly misses from the tiles. Add it to "
                       f"workers/features/filter.txt.")
        elif value not in tags[key]:
            bad.append(f"{short} (layer `{layer_id}`) wants `{key}={value}`, "
                       f"but for `{key}` the prefilter passes only "
                       f"{', '.join(sorted(tags[key]))} – the class quietly "
                       f"misses from the tiles.")

for b in bad:
    print(f"::error file=workers/features/filter.txt::{b}")
print(f"landscape features: {len(bad)} errors "
      f"({requirements} schema requirements against the prefilter)")
sys.exit(1 if bad else 0)
