#!/usr/bin/env python3
"""Copies line colour and number from `type=route` relations onto their tracks.

Also adds speed change points (`rail_speed`, `rail_speed_prev`), the track bearing
at a signal (`rail_bearing`), the widest gauge in mm (`rail_gauge`) and the track section
(`rail_section`), splitting a way at the switches that bound one.
"""
import argparse
import math
import re
from pathlib import Path

import osmium

from sections import Sections, kind as section_kind

# lines whose colour belongs on the track
ROUTES = {"tram", "subway", "light_rail", "monorail", "train", "railway", "funicular"}
# a city line beats a train on the same track
PRIORITY = {"tram": 0, "subway": 0, "light_rail": 0, "monorail": 0, "funicular": 1}
# lines where speed counts – not sidings or city tracks
FAST = {"rail", "narrow_gauge"}
# tracks that give a signal its bearing
TRACKS = FAST | {"light_rail", "subway", "tram", "monorail", "funicular", "preserved"}
NUMBER = re.compile(r"^(\d+(?:\.\d+)?)\s*(mph)?$")


def speed(value):
    """`maxspeed` in whole km/h; `80;60` takes the first, `none` and others nothing."""
    if not value:
        return None
    match = NUMBER.match(value.split(";")[0].strip())
    if not match:
        return None
    km = float(match.group(1)) * (1.609344 if match.group(2) else 1)
    return int(round(km))


def gauge(value):
    """Widest gauge in mm from `gauge`; `1435;1520` is 1520, `standard` nothing."""
    numbers = [int(c) for c in re.findall(r"\d+", value or "")]
    return max(numbers) if numbers else None


def bearing(a, b):
    """Bearing from `a` to `b` in degrees, 0 is north."""
    f1, f2 = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lon - a.lon)
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def speed_changes(ends):
    """Node where exactly two lines of different speed meet → (before, after).

    End meeting start follows the way direction; otherwise lower to higher."""
    changes = {}
    for node, records in ends.items():
        if len(records) != 2:
            continue
        (v1, r1), (v2, r2) = records
        if v1 == v2:
            continue
        if {r1, r2} == {"end", "start"}:
            before, after = (v1, v2) if r1 == "end" else (v2, v1)
        else:
            before, after = min(v1, v2), max(v1, v2)
        changes[node] = (before, after)
    return changes


class Lines(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.colour = {}
        self.numbers = {}
        # node → [(speed, "end"|"start")] from main line ends
        self.ends = {}
        # signal → the direction it applies to; and the track bearing there
        self.signals = {}
        self.bearing = {}
        self.sections = Sections()
        self.top_way = 0

    def node(self, n):
        if n.tags.get("railway") == "signal":
            self.signals[n.id] = n.tags.get("railway:signal:direction", "forward")
        if n.tags.get("railway") == "railway_crossing":
            self.sections.crossings.add(n.id)

    def way(self, w):
        self.top_way = max(self.top_way, w.id)
        nodes = w.nodes
        if section_kind(w.tags):
            self.sections.add(w.id, w.tags, [nd.ref for nd in nodes],
                              [(nd.lon, nd.lat) if nd.location.valid() else None
                               for nd in nodes])
        kind = w.tags.get("railway")
        if kind not in TRACKS:
            return
        if kind in FAST and "service" not in w.tags and len(nodes) > 1:
            v = speed(w.tags.get("maxspeed"))
            if v:
                self.ends.setdefault(nodes[0].ref, []).append((v, "start"))
                self.ends.setdefault(nodes[-1].ref, []).append((v, "end"))
        for i, nd in enumerate(nodes):
            direction = self.signals.get(nd.ref)
            if direction not in ("forward", "backward") or nd.ref in self.bearing:
                continue
            a, b = nodes[max(i - 1, 0)], nodes[min(i + 1, len(nodes) - 1)]
            if a.ref == b.ref or not (a.location.valid() and b.location.valid()):
                continue
            angle = bearing(a.location, b.location) + (180 if direction == "backward" else 0)
            self.bearing[nd.ref] = int(round(angle)) % 360

    def relation(self, r):
        t = r.tags
        if t.get("type") != "route" or t.get("route") not in ROUTES:
            return
        colour = t.get("colour")
        number = t.get("ref")
        order = PRIORITY.get(t.get("route"), 2)
        for m in r.members:
            if m.type != "w":
                continue
            if colour and order < self.colour.get(m.ref, (9, ""))[0]:
                self.colour[m.ref] = (order, colour)
            if number:
                self.numbers.setdefault(m.ref, set()).add(number)


class Rewrite(osmium.SimpleHandler):
    def __init__(self, lines, changes, writer):
        super().__init__()
        self.lines = lines
        self.changes = changes
        self.w = writer
        self.changed = 0
        self.split = 0
        # extra pieces of split ways, written after every way
        self.extra = []
        self.next_id = lines.top_way + 1

    def node(self, n):
        change = self.changes.get(n.id)
        angle = self.lines.bearing.get(n.id)
        if change is None and angle is None:
            self.w.add_node(n)
            return
        new_tags = dict(n.tags)
        if change:
            new_tags["rail_speed_prev"], new_tags["rail_speed"] = map(str, change)
        if angle is not None:
            new_tags["rail_bearing"] = str(angle)
        self.w.add_node(n.replace(tags=new_tags))

    def way(self, w):
        colour = self.lines.colour.get(w.id)
        numbers = self.lines.numbers.get(w.id)
        mm = gauge(w.tags.get("gauge"))
        pieces = self.lines.sections.split(w.id)
        if not colour and not numbers and not mm and not pieces:
            self.w.add_way(w)
            return
        new_tags = dict(w.tags)
        if colour and "colour" not in new_tags:
            new_tags["colour"] = colour[1]
        if numbers:
            new_tags["route_ref"] = ";".join(sorted(numbers, key=lambda c: (len(c), c)))
        if mm:
            new_tags["rail_gauge"] = str(mm)
        self.changed += bool(colour or numbers)
        if not pieces:
            self.w.add_way(w.replace(tags=new_tags))
            return
        self.split += len(pieces) > 1
        for k, (refs, section) in enumerate(pieces):
            tags = dict(new_tags, rail_section=str(section))
            if k == 0:
                self.w.add_way(w.replace(tags=tags, nodes=refs))
            else:
                self.extra.append(w.replace(id=self.next_id, tags=tags, nodes=refs))
                self.next_id += 1

    def flush(self):
        for way in self.extra:
            self.w.add_way(way)
        self.extra = []

    def relation(self, r):
        self.flush()
        self.w.add_relation(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    lines = Lines()
    lines.apply_file(a.pbf, locations=True, idx="flex_mem")
    changes = speed_changes(lines.ends)
    lines.sections.solve()
    Path(a.out).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(a.out)
    try:
        rewrite = Rewrite(lines, changes, writer)
        rewrite.apply_file(a.pbf)
        rewrite.flush()
    finally:
        writer.close()
    print(f"Lines: {rewrite.changed} tracks got a line colour or number")
    print(f"Sections: {len(lines.sections.ways)} tracks, {rewrite.split} split at a switch")
    print(f"Speed changes at {len(changes)} points, {len(lines.bearing)} signals "
          f"have a bearing")


if __name__ == "__main__":
    main()
