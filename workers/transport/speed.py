#!/usr/bin/env python3
"""Ways get `speed_context`; where it changes along a road, a computed sign point goes to GeoJSON."""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "routing"))
import context                                                    # noqa: E402

# how far past the junction the sign stands, so it doesn't sit on the crossing
SIGN_M = 15
RADIUS_M = 6371000.0
# a town sign is better evidence than a junction this near it
NEAR_TOWN_M = 250
# how much of each side of a town sign is measured against built-up land
SIDE_M = 300
# a village side needs this much more built-up land than the other
SIDE_MARGIN = 0.2
SIGN_KEYS = ("traffic_sign", "traffic_sign:forward", "traffic_sign:backward")


def continues(a, b):
    """Whether way `b` carries on the road `a` is, not a side street off it."""
    for key in ("ref", "name"):
        if a.get(key) and a.get(key) == b.get(key):
            return True
    return a.get("highway") == b.get("highway")


def enterable(tags, at_start):
    """Whether a car may drive into the way from the end it meets the junction at."""
    oneway = tags.get("oneway", "")
    if oneway in ("yes", "true", "1") or tags.get("junction") in ("roundabout", "circular"):
        return at_start
    if oneway in ("-1", "reverse"):
        return not at_start
    return True


def _metres(a, b):
    (lon1, lat1), (lon2, lat2) = a, b
    f1, f2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((f2 - f1) / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _bearing(a, b):
    (lon1, lat1), (lon2, lat2) = a, b
    f1, f2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return round(math.degrees(math.atan2(y, x))) % 360


def along(line, metres):
    """The point `metres` along a `[(lon, lat), …]` line, and the heading there."""
    walked = 0.0
    for a, b in zip(line, line[1:]):
        step = _metres(a, b)
        if step > 0 and walked + step >= metres:
            f = (metres - walked) / step
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), _bearing(a, b)
        walked += step
    return line[-1], _bearing(line[-2], line[-1])


def signs(ways, contexts):
    """A sign at the start of each stretch whose context differs from the road it carries on."""
    ends = defaultdict(list)
    for wid, way in ways.items():
        if wid in contexts:
            ends[way["refs"][0]].append((wid, True))
            ends[way["refs"][-1]].append((wid, False))
    out = []
    for meeting in ends.values():
        for wid, at_start in meeting:
            way = ways[wid]
            if "maxspeed" in way["tags"] or not enterable(way["tags"], at_start):
                continue
            entered = contexts[wid]
            if not any(contexts[other] != entered and continues(ways[other]["tags"], way["tags"])
                       for other, _ in meeting if other != wid):
                continue
            line = way["line"] if at_start else way["line"][::-1]
            length = sum(_metres(a, b) for a, b in zip(line, line[1:]))
            point, heading = along(line, min(SIGN_M, length / 2))
            out.append({"way": wid, "point": point, "direction": heading, "context": entered})
    return out


def town_sign(tags):
    """`(begin|end, facing)` of a village's town sign, else None; facing is `forward`, `backward` or None."""
    if not any("city_limit" in tags.get(k, "").split(";") for k in SIGN_KEYS):
        return None
    facing = tags.get("traffic_sign:direction") or tags.get("direction")
    for side in ("forward", "backward"):
        if not facing and tags.get(f"traffic_sign:{side}"):
            facing = side
    kind = "end" if tags.get("city_limit") == "end" else "begin"
    return kind, facing if facing in ("forward", "backward") else None


def clip(line, metres):
    """The first `metres` of a line."""
    out, walked = [line[0]], 0.0
    for a, b in zip(line, line[1:]):
        if walked >= metres:
            break
        out.append(b)
        walked += _metres(a, b)
    return out


def village_side(town, sides, built_up):
    """`forward` or `backward`: the sign's facing says it, else the side with clearly more built-up land."""
    kind, facing = town
    if facing:
        # a begin sign faces the traffic entering the village, an end sign the traffic leaving it
        return facing if kind == "begin" else {"forward": "backward", "backward": "forward"}[facing]
    if len(sides) < 2:
        return None
    ahead, behind = built_up.shares([clip(sides["forward"], SIDE_M), clip(sides["backward"], SIDE_M)])
    if abs(ahead - behind) < SIDE_MARGIN:
        return None
    return "forward" if ahead > behind else "backward"


def town_signs(ways, contexts, towns, built_up):
    """A sign each way from a town sign on a road: the village's context in, the open road's out."""
    out = []
    for wid, way in ways.items():
        kind = way["road"][0]
        if wid not in contexts or kind not in ("road", "motorroad") or "maxspeed" in way["tags"]:
            continue
        for i, ref in enumerate(way["refs"]):
            if ref not in towns:
                continue
            sides = {"forward": way["line"][i:], "backward": way["line"][:i + 1][::-1]}
            sides = {k: v for k, v in sides.items() if len(v) > 1}
            village = village_side(towns[ref], sides, built_up)
            if village is None:
                continue
            for side, line in sides.items():
                if not enterable(way["tags"], side == "forward"):
                    continue
                length = sum(_metres(a, b) for a, b in zip(line, line[1:]))
                point, heading = along(line, min(SIGN_M, length / 2))
                out.append({"way": wid, "point": point, "direction": heading,
                            "context": context.name(kind, side == village)})
    return out


def merged(junction, town):
    """The town signs, and the junction signs no town sign stands near."""
    return town + [s for s in junction
                   if all(_metres(s["point"], t["point"]) > NEAR_TOWN_M for t in town)]


def read(pbf):
    """Motor ways as `{id: way}` with tags, node refs and the line, and town signs as `{node: sign}`."""
    import osmium

    class Ways(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways = {}
            self.towns = {}

        def node(self, n):
            found = town_sign(dict(n.tags))
            if found:
                self.towns[n.id] = found

        def way(self, w):
            tags = dict(w.tags)
            road = context.road(tags)
            if not road or len(w.nodes) < 2:
                return
            try:
                line = [(n.location.lon, n.location.lat) for n in w.nodes]
            except osmium.InvalidLocationError:
                return
            self.ways[w.id] = {"tags": tags, "road": road, "refs": [n.ref for n in w.nodes],
                               "line": line}

    h = Ways()
    h.apply_file(pbf, locations=True, idx="flex_mem")
    return h.ways, h.towns


def classify(ways, built_up):
    """`{way id: context}`, the share inside built-up land measured where no tag says it."""
    unsure = [wid for wid, w in ways.items()
              if w["road"][1] is None and w["road"][0] != "living_street"]
    shares = built_up.shares([ways[wid]["line"] for wid in unsure])
    urban = {wid: share >= context.URBAN_SHARE for wid, share in zip(unsure, shares)}
    return {wid: context.name(w["road"][0], urban.get(wid, w["road"][1] == "urban"))
            for wid, w in ways.items()}


def rewrite(pbf, out, contexts):
    """`out` is `pbf` with `speed_context` on every motor way."""
    import osmium

    class Rewrite(osmium.SimpleHandler):
        def __init__(self, writer):
            super().__init__()
            self.w = writer

        def node(self, n):
            self.w.add_node(n)

        def way(self, w):
            found = contexts.get(w.id)
            self.w.add_way(w.replace(tags={**dict(w.tags), "speed_context": found}) if found else w)

        def relation(self, r):
            self.w.add_relation(r)

    Path(out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(out)
    try:
        Rewrite(writer).apply_file(pbf)
    finally:
        writer.close()


def geojson(found, country):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [round(s["point"][0], 7), round(s["point"][1], 7)]},
         "properties": {"kind": "speed", "speed_context": s["context"], "country": country,
                        "direction": s["direction"], "osm_way": s["way"]}}
        for s in found]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True, help="the roads' prefiltered PBF")
    ap.add_argument("--out", required=True, help="the same PBF, motor ways with `speed_context`")
    ap.add_argument("--signs", required=True, help="GeoJSON of the computed sign points")
    ap.add_argument("--country", default="", help="the region's ISO code, which the app's law is read by")
    a = ap.parse_args()

    ways, towns = read(a.pbf)
    built_up = context.BuiltUp(context.built_up_areas(a.pbf))
    contexts = classify(ways, built_up)
    rewrite(a.pbf, a.out, contexts)
    found = merged(signs(ways, contexts), town_signs(ways, contexts, towns, built_up))
    # Planetiler's GeoJSON reader dies on an empty `features` list, not on an empty file
    Path(a.signs).write_text(json.dumps(geojson(found, a.country.upper())) if found else "",
                             encoding="utf-8")
    counted = Counter(contexts.values())
    print(f"Speed context: {len(contexts)} ways ("
          + ", ".join(f"{k}×{n}" for k, n in counted.most_common())
          + f"), {len(found)} computed signs, {len(towns)} town signs")


if __name__ == "__main__":
    main()
