#!/usr/bin/env python3
"""World map: the style draws exactly the schema's layers, from the schema's zooms, per variant."""
import json
import os
import subprocess
import sys
import tempfile

import yaml

SCHEMA = "workers/world/world.yml"
STYLE = "workers/world/style.mjs"

sys.path.insert(0, os.path.join("workers", "world"))
import variant as variant_mod  # noqa: E402

bad = []

doc = yaml.safe_load(open(SCHEMA, encoding="utf-8"))
raw = variant_mod.load()
variants = variant_mod.variants(raw)


def floors(layers):
    """A layer's floor in the schema: the lowest `min_zoom` of its features."""
    out = {}
    for lay in doc.get("layers") or []:
        if lay["id"] not in layers:
            continue
        zooms = [f.get("min_zoom", 0) for f in (lay.get("features") or [])]
        out[lay["id"]] = min(zooms) if zooms else 0
    return out


for name, variant in sorted(variants.items()):
    try:
        variant_mod.schema_for(variant["layers"], doc)
    except SystemExit as exc:
        bad.append(f"variant `{name}`: {exc}")
        continue
    schema_min = floors(variant["layers"])
    print(f"variant `{name}`: layers "
          + ", ".join(f"{k} from z{v}" for k, v in sorted(schema_min.items())))

    with tempfile.TemporaryDirectory() as tmp:
        done = subprocess.run(
            ["node", STYLE, f"--out={tmp}", f"--variant={name}"],
            capture_output=True, text=True, check=False)
        if done.returncode != 0:
            print(f"::error file={STYLE}::the style of variant `{name}` can't be "
                  f"generated: {done.stderr.strip() or done.stdout.strip()}")
            sys.exit(1)
        files = sorted(f for f in os.listdir(tmp) if f.endswith(".json"))
        if not files:
            print(f"::error file={STYLE}::variant `{name}` made no style.")
            sys.exit(1)

        for fname in files:
            with open(os.path.join(tmp, fname), encoding="utf-8") as f:
                style = json.load(f)
            style_min = {}
            for lay in style.get("layers") or []:
                src = lay.get("source-layer")
                if not src:
                    continue        # `background` has no source
                z = lay.get("minzoom", 0)
                style_min[src] = min(style_min.get(src, z), z)

            for src, z in sorted(style_min.items()):
                if src not in schema_min:
                    bad.append(
                        f"variant `{name}`, {fname}: a style layer has `source-layer: {src}`, "
                        f"which the variant lacks (it has {sorted(schema_min)}). MapLibre "
                        f"says nothing – that layer simply won't be in the map.")
                elif z != schema_min[src]:
                    why = ("the map has a hole at those zooms"
                           if z < schema_min[src]
                           else "tiles are paid for that nobody draws")
                    bad.append(
                        f"variant `{name}`, {fname}: `{src}` is drawn from z{z}, but the "
                        f"schema makes it from z{schema_min[src]} – {why}. Align `minzoom` "
                        f"in {STYLE} with `min_zoom` in {SCHEMA}.")
            for src in schema_min:
                if src not in style_min:
                    bad.append(
                        f"variant `{name}`, {fname}: the schema makes layer `{src}`, but the "
                        f"style never draws it. Draw it, or drop it from the schema – "
                        f"otherwise they're tiles nobody gets anything for.")

for b in bad:
    print(f"::error::{b}")
print(f"world map (schema × style × {len(variants)} variants): {len(bad)} errors")
sys.exit(1 if bad else 0)
