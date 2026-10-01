#!/usr/bin/env python3
"""Track sections end only at a switch onto the same kind of track."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "rail"))
from sections import Sections  # noqa: E402

MAIN = {"railway": "rail", "usage": "main", "gauge": "1435", "voltage": "3000",
        "frequency": "0"}


def network():
    s = Sections(crossings={31})
    places = {n: (n * 0.001, 0.0) for n in range(1, 10)}
    places.update({30: (0.05, 0.01), 31: (0.05, 0.0), 32: (0.05, -0.01),
                   40: (0.04, 0.0), 42: (0.06, 0.0)})
    def add(way, tags, refs):
        s.add(way, tags, refs, [places.get(r) for r in refs])
    add(1, dict(MAIN, maxspeed="120"), [1, 2, 3, 4, 5])
    add(2, MAIN, [3, 10, 11])
    add(3, {"railway": "rail", "service": "siding", "gauge": "1435"}, [4, 20, 21])
    add(4, dict(MAIN, maxspeed="80"), [5, 6, 7])
    add(5, dict(MAIN, voltage="25000"), [7, 8])
    add(6, {"railway": "tram"}, [30, 31, 32])
    add(7, {"railway": "tram"}, [40, 31, 42])
    s.solve()
    return s


def main():
    s = network()
    one = s.split(1)
    bad = []
    if [refs for refs, _ in one] != [[1, 2, 3], [3, 4, 5]]:
        bad.append(f"a main line is cut at the switch onto another main line, not {one}")
    if one[0][1] == one[1][1]:
        bad.append("both sides of a switch onto the same kind fell into one section")
    if one[1][1] != s.split(4)[0][1]:
        bad.append("a change of speed ended a section")
    if s.split(3)[0][0] != [4, 20, 21] or len(s.split(1)) != 2:
        bad.append("a siding off a main line cut it")
    if s.split(2)[0][1] in (one[0][1], one[1][1]):
        bad.append("the branch shares a section with the line it leaves")
    if s.split(5)[0][1] == s.split(4)[0][1]:
        bad.append("another voltage stayed in the same section")
    tram_a, tram_b = s.split(6), s.split(7)
    if len({sec for _, sec in tram_a}) != 1 or len({sec for _, sec in tram_b}) != 1:
        bad.append("a diamond crossing cut a track that runs straight over it")
    if tram_a[0][1] == tram_b[0][1]:
        bad.append("two tracks over a diamond crossing became one section")
    for b in bad:
        print(f"::error::workers/rail/sections.py: {b}")
    if not bad:
        print("rail sections ✓")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
