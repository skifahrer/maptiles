#!/usr/bin/env python3
"""World map variant: what of `world.yml` really gets built – schema, sources, name, budget.

Usage:
    python3 workers/world/variant.py --variant=basic \\
        --schema-out=/tmp/world-basic.yml --out=/tmp/variant.json
    python3 workers/world/variant.py --list        # what can be built
"""
import argparse
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
SCHEMA = os.path.join(_HERE, "world.yml")
VARIANTS = os.path.join(_DATA, "world-variants.json")

# former form values
VARIANT_ALIAS = {"plna": "full"}
GLYPHS_ALIAS = {"cele": "all", "podla_dat": "from_data"}


def load(path=VARIANTS):
    """The variant list as it is (`_` keys are comments and lookups)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return raw


def variants(raw=None):
    raw = raw if raw is not None else load()
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def pick(name, raw=None):
    """A variant by name; an unknown name is an error, not the default."""
    raw = raw if raw is not None else load()
    v = variants(raw)
    name = VARIANT_ALIAS.get(name, name)
    if name not in v:
        raise SystemExit(
            f"::error::World map variant “{name}” is unknown. There are: "
            f"{', '.join(sorted(v))} (the list is in `workers/data/"
            f"world-variants.json`).")
    return v[name]


def schema_for(layers, doc=None):
    """`world.yml` cut to the chosen layers, with only the sources still used."""
    doc = doc if doc is not None else yaml.safe_load(open(SCHEMA, encoding="utf-8"))
    have = {l["id"] for l in doc.get("layers") or []}
    missing = [v for v in layers if v not in have]
    if missing:
        # Planetiler would silently build a map without them
        raise SystemExit(
            f"::error::The variant asks for layers {missing} `workers/world/"
            f"world.yml` doesn't have (it has {sorted(have)}). Align `layers` "
            f"in `workers/data/world-variants.json` with the schema.")
    out = dict(doc)
    out["layers"] = [l for l in doc["layers"] if l["id"] in layers]
    # an unused source needn't even be downloaded
    needed = {f.get("source") for l in out["layers"]
              for f in (l.get("features") or [])}
    out["sources"] = {k: v for k, v in (doc.get("sources") or {}).items()
                      if k in needed}
    return out, sorted(s for s in needed if s)


def map_layers(layers, raw=None):
    """Layer names for `contents.json` and `maps.json`, in `_names` order."""
    raw = raw if raw is not None else load()
    names = raw.get("_names") or {}
    out = []
    for layer, labels in names.items():
        if layer.startswith("_") or layer not in layers:
            continue
        for label in labels or []:
            if label not in out:
                out.append(label)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="full")
    ap.add_argument("--schema-out", default="",
                    help="where to write the schema for Planetiler")
    ap.add_argument("--out", default="",
                    help="where to write the JSON of values for build.sh")
    ap.add_argument("--list", action="store_true", help="list the variants and stop")
    args = ap.parse_args()

    raw = load()
    if args.list:
        for k, v in sorted(variants(raw).items()):
            print(f"{k:<8} {v.get('label', '')}")
        return 0

    name = VARIANT_ALIAS.get(args.variant, args.variant)
    p = pick(name, raw)
    layers = p["layers"]
    doc, sources = schema_for(layers)
    glyphs = p.get("glyphs", "all")
    values = {
        "variant": name,
        "label": p.get("label", name),
        "region": p["region"],
        "layers": layers,
        "sources": sources,
        "map_layers": ",".join(map_layers(layers, raw)),
        "limit_mb": int(p.get("limit_mb", 250)),
        "glyphs": GLYPHS_ALIAS.get(glyphs, glyphs),
    }

    if args.schema_out:
        with open(args.schema_out, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False, indent=2)

    everything = {l["id"] for l in yaml.safe_load(
        open(SCHEMA, encoding="utf-8"))["layers"]}
    left_out = sorted(everything - set(layers))
    print(f"Variant `{name}`: {values['label']}")
    print(f"  layers    {', '.join(layers)}"
          + (f"   (left out: {', '.join(left_out)})" if left_out else ""))
    print(f"  sources   {', '.join(sources)}")
    print(f"  region    {values['region']}   "
          f"catalog layers: {values['map_layers'] or '(none)'}")
    print(f"  cap       {values['limit_mb']} MB     fonts: {values['glyphs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
