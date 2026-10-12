#!/usr/bin/env python3
"""Sign nodes → `sign`, the sprite name of the first sign (`sk.ts.253-50`), for `roadsigns.yml`."""
import argparse
import re
from pathlib import Path

# nodes that are a sign without `traffic_sign`
IMPLIED = {"stop": "stop", "give_way": "give_way", "traffic_signals": "traffic_signals",
           "speed_camera": "speed_camera"}
KEYS = ("traffic_sign", "traffic_sign:forward", "traffic_sign:backward")
FIGURES = ("maxspeed", "maxweight", "maxheight", "maxwidth")
FIGURE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[a-z]*$")
# the tag that turns a sign into its end sign
ENDS = {"city_limit": "end", "overtaking": "yes"}
COUNTRY = re.compile(r"^([A-Za-z]{2}):(.*)$")
VALUE = re.compile(r"^(.*?)\[(.*?)\]")


def code(text):
    """Sprite spelling of a national code or a value: `P 6` and `§52 Z24` lose spaces and `§`."""
    return re.sub(r"[\s§]", "", text).replace(",", "-").lower()


def first(value):
    """First sign of `SK:253[50];SK:E9` or `DE:274[50],1020-30`, split at a top-level separator."""
    depth = 0
    for i, ch in enumerate(value):
        depth += ch == "["
        depth -= ch == "]"
        if ch in ";," and depth <= 0:
            return value[:i].strip()
    return value.strip()


def sign_name(value, country):
    """`SK:253[50]` → `sk.ts.253-50`; a bare `stop` takes the region's `country`."""
    head = first(value or "")
    if not head or head in ("yes", "no", "none"):
        return None
    m = COUNTRY.match(head)
    cc, body = (m.group(1).lower(), m.group(2)) if m else (country, head)
    if not cc:
        return None
    v = VALUE.match(body)
    body, val = (v.group(1), v.group(2)) if v else (body, "")
    key = code(body)
    if not key:
        return None
    return f"{cc}.ts.{key}-{code(val)}" if val.strip() else f"{cc}.ts.{key}"


def figured(name, tags):
    """`traffic_sign=maxspeed` takes its figure from `maxspeed`; an end sign gets `_end`."""
    word = name.split(".ts.", 1)[1]
    m = FIGURE.match(tags.get(word, "")) if word in FIGURES else None
    if m:
        return f"{name}-{code(m.group(1)).replace('.', '-')}"
    if word in ENDS and tags.get(word) == ENDS[word]:
        return f"{name}_end"
    return name


def direction(tags):
    """Which way the sign faces: its own tag, else the key it came in."""
    for k in ("traffic_sign:direction", "direction"):
        if tags.get(k):
            return tags[k]
    for side in ("forward", "backward"):
        if tags.get(f"traffic_sign:{side}"):
            return side
    return None


def node_tags(tags, country):
    """Tags a sign node keeps, `sign` and `sign_direction` added; None for a node that isn't one."""
    raw = next((tags[k] for k in KEYS if tags.get(k)), None)
    implied = IMPLIED.get(tags.get("highway", ""))
    if raw is None and implied is None:
        return None
    out = {k: v for k, v in tags.items()
           if k in KEYS or k in ("highway", "maxspeed", "name")}
    name = sign_name(raw, country) if raw else f"{country}.ts.{implied}" if country else None
    if name:
        name = figured(name, tags)
    if name:
        out["sign"] = name
    if raw:
        out["traffic_sign"] = raw
    facing = direction(tags)
    if facing:
        out["sign_direction"] = facing
    return out


def main():
    import osmium

    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--country", default="")
    ap.add_argument("--names", help="file for the sprite names the region uses, one per line")
    a = ap.parse_args()

    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    kept = named = 0
    used = set()
    try:
        for n in osmium.FileProcessor(a.pbf, osmium.osm.NODE):
            tags = node_tags(dict(n.tags), a.country.lower())
            if tags is None:
                continue
            kept += 1
            named += "sign" in tags
            if "sign" in tags:
                used.add(tags["sign"])
            writer.add_node(n.replace(tags=tags))
    finally:
        writer.close()
    if a.names:
        Path(a.names).write_text("".join(f"{n}\n" for n in sorted(used)), encoding="utf-8")
    print(f"Signs: {kept} nodes, {named} with a sprite name ({a.country or 'no country'})")


if __name__ == "__main__":
    main()
