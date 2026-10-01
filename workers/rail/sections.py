"""Track sections: one kind of track from a switch of that kind to the next."""
import math
from array import array
from collections import defaultdict

KINDS = {"rail", "narrow_gauge", "light_rail", "subway", "tram", "monorail", "funicular",
         "preserved", "miniature"}
# a piece's number is its way id × STRIDE + its place on the way
STRIDE = 1000


def kind(tags):
    """Gauge, use, voltage and frequency; speed may differ along a section."""
    railway = tags.get("railway")
    if railway not in KINDS:
        return None
    return (railway, tags.get("usage"), tags.get("service"), tags.get("gauge"),
            tags.get("voltage"), tags.get("frequency"))


def bearing(origin, to):
    return math.atan2(to[1] - origin[1], (to[0] - origin[0]) * math.cos(math.radians(origin[1])))


def straightest(arms):
    """The two pairs of four arms that run on most nearly straight."""
    a, b, c, d = arms
    def bend(p, q):
        return abs(math.pi - abs((p[1] - q[1] + math.pi) % (2 * math.pi) - math.pi))
    pairings = [((a, b), (c, d)), ((a, c), (b, d)), ((a, d), (b, c))]
    return min(pairings, key=lambda pair: bend(*pair[0]) + bend(*pair[1]))


class Sections:
    def __init__(self, crossings=()):
        self.crossings = set(crossings)
        self.ways = {}
        self.places = {}
        self.coords = {}
        self.parent = {}
        self.pieces = {}
        self.spans = {}
        self.boxes = {}

    def add(self, way_id, tags, refs, places=None):
        """`places` are (lon, lat) per ref, or None where the location is unknown."""
        what = kind(tags)
        if what is None or len(refs) < 2:
            return
        self.ways[way_id] = (what, list(refs))
        places = places or [None] * len(refs)
        self.coords[way_id] = array("d", (c for p in places for c in (p or (math.nan,) * 2)))
        for i, ref in enumerate(refs):
            if ref in self.crossings and places:
                for j in (i - 1, i, i + 1):
                    if 0 <= j < len(refs) and places[j]:
                        self.places[refs[j]] = places[j]

    def solve(self):
        arms = defaultdict(int)
        for what, refs in self.ways.values():
            for i, ref in enumerate(refs):
                arms[ref, what] += 1 if i in (0, len(refs) - 1) else 2

        ends = defaultdict(list)
        for way_id, (what, refs) in self.ways.items():
            cuts = [i for i in range(1, len(refs) - 1) if arms[refs[i], what] >= 3]
            bounds = [0] + cuts + [len(refs) - 1]
            runs = [refs[s:e + 1] for s, e in zip(bounds, bounds[1:])]
            self.pieces[way_id] = runs
            for k, run in enumerate(runs):
                piece = way_id * STRIDE + min(k, STRIDE - 1)
                self.parent[piece] = piece
                self.spans[piece] = (way_id, bounds[k], bounds[k + 1])
                ends[run[0], what].append((piece, run[1]))
                ends[run[-1], what].append((piece, run[-2]))

        for (node, _), out in ends.items():
            if len(out) == 2:
                self.join(out[0][0], out[1][0])
            elif len(out) == 4 and node in self.crossings:
                self.cross(node, out)

        for piece, (way_id, start, end) in self.spans.items():
            xy = self.coords[way_id][2 * start:2 * end + 2]
            lons = [v for v in xy[0::2] if not math.isnan(v)]
            lats = [v for v in xy[1::2] if not math.isnan(v)]
            if not lons:
                continue
            section = self.root(piece)
            box = self.boxes.get(section, (math.inf, math.inf, -math.inf, -math.inf))
            self.boxes[section] = (min(box[0], *lons), min(box[1], *lats),
                                   max(box[2], *lons), max(box[3], *lats))

    def cross(self, node, out):
        """A diamond crossing is no switch: each track runs on straight over it."""
        origin = self.places.get(node)
        if origin is None or any(nxt not in self.places for _, nxt in out):
            return
        arms = [(piece, bearing(origin, self.places[nxt])) for piece, nxt in out]
        for p, q in straightest(arms):
            self.join(p[0], q[0])

    def root(self, piece):
        while self.parent[piece] != piece:
            self.parent[piece] = self.parent[self.parent[piece]]
            piece = self.parent[piece]
        return piece

    def join(self, a, b):
        a, b = self.root(a), self.root(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)

    def box(self, section):
        """West, south, east and north of the whole section, for the app to frame it."""
        box = self.boxes.get(section)
        return ",".join(f"{v:.5f}" for v in box) if box else None

    def split(self, way_id):
        """The way's pieces as (refs, section), or None for a way without one."""
        runs = self.pieces.get(way_id)
        if runs is None:
            return None
        return [(run, self.root(way_id * STRIDE + min(k, STRIDE - 1)))
                for k, run in enumerate(runs)]
