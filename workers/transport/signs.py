#!/usr/bin/env python3
"""Sign nodes get `sign`, the sprite name of the first sign (`sk.ts.253-50`), for `transport.yml`."""
import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

MAPPING = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "road-signs.json")
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


def mapped_name(key, country):
    """Sprite name of a `road-signs.json` key: a value, `maxspeed=50` or `highway=stop`."""
    tag, eq, value = key.partition("=")
    if not eq:
        return sign_name(key, country)
    if tag == "highway":
        return f"{country}.ts.{code(value)}"
    return figured(f"{country}.ts.{tag}", {tag: value})


def folders(mapping=MAPPING):
    """`{country: {sprite name: sign folder}}` from `road-signs.json`, first key wins."""
    with open(mapping, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for cc, by_key in data.items():
        if cc.startswith("_"):
            continue
        names = out[cc] = {}
        for key, folder in sorted(by_key.items()):
            name = mapped_name(key, cc)
            if name:
                names.setdefault(name, folder)
    return out


def generic(country, folder):
    """Name of the home image for a folder no home key names: `sk.ts.no-vehicles`."""
    return f"{country}.ts.{folder.split('/')[1]}"


def at_home(name, home, by_country):
    """A sign coded for another country, renamed to the home country's sign of that meaning."""
    cc = name.split(".", 1)[0]
    if not home or cc == home:
        return name
    folder = (by_country.get(cc) or {}).get(name)
    if not folder:
        return name
    ours = sorted(n for n, f in (by_country.get(home) or {}).items() if f == folder)
    return ours[0] if ours else generic(home, folder)


def tagged(tags):
    """How a sign node is tagged, for people: `SK:253[50]`, `highway=stop`, `maxspeed + maxspeed=50`."""
    raw = next((tags[k] for k in KEYS if tags.get(k)), None)
    if raw is None:
        return f"highway={tags.get('highway')}"
    extra = raw if raw in FIGURES or raw in ENDS else None
    return f"{raw} + {extra}={tags[extra]}" if extra and tags.get(extra) else raw


def direction(tags):
    """Which way the sign faces: its own tag, else the key it came in."""
    for k in ("traffic_sign:direction", "direction"):
        if tags.get(k):
            return tags[k]
    for side in ("forward", "backward"):
        if tags.get(f"traffic_sign:{side}"):
            return side
    return None


def node_tags(tags, country, by_country=None):
    """Tags a sign node keeps, `sign` and `sign_direction` added; None for a node that isn't one."""
    raw = next((tags[k] for k in KEYS if tags.get(k)), None)
    implied = IMPLIED.get(tags.get("highway", ""))
    if raw is None and implied is None:
        return None
    out = {k: v for k, v in tags.items()
           if k in KEYS or k in ("highway", "maxspeed", "name")}
    name = sign_name(raw, country) if raw else f"{country}.ts.{implied}" if country else None
    if name:
        name = at_home(figured(name, tags), country, by_country or {})
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
    ap.add_argument("--pbf", required=True, help="the roads' prefiltered PBF")
    ap.add_argument("--out", required=True, help="the same PBF, sign nodes named")
    ap.add_argument("--country", default="")
    ap.add_argument("--names", help="file for the sprite names the region uses, `name<TAB>count`")
    ap.add_argument("--report", help="file for `tagged<TAB>name<TAB>count`, one row per tagging")
    ap.add_argument("--mapping", default=MAPPING)
    a = ap.parse_args()
    by_country = folders(a.mapping)

    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    kept = 0
    used = Counter()
    report = Counter()
    try:
        for o in osmium.FileProcessor(a.pbf):
            if o.is_node():
                tags = node_tags(dict(o.tags), a.country.lower(), by_country)
                if tags is not None:
                    kept += 1
                    if "sign" in tags:
                        used[tags["sign"]] += 1
                    report[(tagged(dict(o.tags)), tags.get("sign", ""))] += 1
                    o = o.replace(tags={**dict(o.tags), **tags})
                writer.add_node(o)
            elif o.is_way():
                writer.add_way(o)
            elif o.is_relation():
                writer.add_relation(o)
    finally:
        writer.close()
    if a.names:
        Path(a.names).write_text("".join(f"{n}\t{used[n]}\n" for n in sorted(used)), encoding="utf-8")
    if a.report:
        Path(a.report).write_text("".join(f"{t}\t{n}\t{c}\n" for (t, n), c in report.most_common()),
                                  encoding="utf-8")
    print(f"Signs: {kept} nodes, {sum(used.values())} with a sprite name ({a.country or 'no country'})")


if __name__ == "__main__":
    main()
