#!/usr/bin/env python3
"""Army and history: the prefilter passes what the schema asks for, and every theme draws all it promises."""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "history", "history.yml")
FILTER = os.path.join(_WORKERS, "history", "filter.txt")
BUILD = os.path.join(_WORKERS, "history", "build.sh")

# layer → geometries it promises; embankments are lines only
PROMISED = {
    "army": {"point", "line", "polygon"},
    "mining": {"point", "line", "polygon"},
    "embankment": {"line"},
    "history": {"point", "line", "polygon"},
    "gone": {"point", "line", "polygon"},
}
# the `gone` expressions read these; osmium must let them through
LIFECYCLE_LINES = ("abandoned:*", "disused:*", "abandoned=yes", "disused=yes",
                   "*=abandoned", "*=disused")
EVERY_BLOCK = ("name", "lifecycle", "osm_id")
COMBINATORS = {"__any__", "__all__", "__not__"}

bad = []


def filter_lines(path):
    """Expressions of `osmium tags-filter --expressions`, without the `nwr/` part."""
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "/" in line.split("=", 1)[0]:
                line = line.split("/", 1)[1]
            out.add(line)
    return out


def theme_keys(blocks):
    """Keys of plain tag-map conditions; combined ones only narrow what these let in."""
    keys = set()
    for b in blocks:
        condition = b.get("include_when")
        if isinstance(condition, dict) and not COMBINATORS & set(condition):
            keys |= set(condition)
    return keys


def main():
    for path in (SCHEMA, FILTER, BUILD):
        if not os.path.exists(path):
            print(f"::error::{path} doesn't exist.")
            return 1
    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    lines = filter_lines(FILTER)
    passes = {e.split("=", 1)[0] for e in lines}

    layers = {v.get("id"): v.get("features") or [] for v in schema.get("layers") or []}
    blocks = [b for features in layers.values() for b in features]

    missing = sorted(theme_keys(blocks) - passes)
    if missing:
        bad.append(f"{FILTER}: the schema asks for {', '.join(missing)}, but the prefilter "
                   f"doesn't pass it – the run goes green and that theme is empty.")
    for expr in LIFECYCLE_LINES:
        if expr not in lines:
            bad.append(f"{FILTER}: `{expr}` is missing, so osmium drops what the `gone` "
                       f"layer and `lifecycle` read.")

    if " -R " in build or "--omit-referenced" in build:
        bad.append(f"{BUILD}: `osmium tags-filter -R` drops relation members – training "
                   f"areas and castles are multipolygons and would vanish.")
    if "region-cut.sh" not in build:
        bad.append(f"{BUILD}: the PBF isn't cut to the region (`workers/lib/region-cut.sh`), "
                   f"so border relations far away land in low-zoom tiles.")

    for layer, geometries in PROMISED.items():
        made = {b.get("geometry") for b in layers.get(layer, [])}
        if not geometries <= made:
            bad.append(f"{SCHEMA}: layer `{layer}` lacks "
                       f"{', '.join(sorted(geometries - made))} – the package promises "
                       f"points, lines and areas.")
        if layer == "embankment" and made - {"line"}:
            bad.append(f"{SCHEMA}: `embankment` makes {', '.join(sorted(made - {'line'}))} – "
                       f"a closed embankment around a pond would turn into a filled area.")

    for layer, features in layers.items():
        for i, b in enumerate(features, start=1):
            attrs = {a.get("key") for a in b.get("attributes") or [] if isinstance(a, dict)}
            for key in EVERY_BLOCK:
                if key not in attrs:
                    bad.append(f"{SCHEMA}: block {i} of `{layer}` gives no `{key}`.")

    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in the army and history layer.")
        return 1
    print("Army and history: the prefilter passes every theme and what `gone` reads, "
          "relation members stay, and every layer draws points, lines and areas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
