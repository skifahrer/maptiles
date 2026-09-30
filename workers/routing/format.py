#!/usr/bin/env python3
"""The `RTIL` routing tile body – writing and reading in one place."""
import struct

MAGIC = b"RTIL"
VERSION = 1

# header `flags`: a field absent from the archive isn't encoded at all
F_HEIGHT = 1
F_ORDER = 2
# the profile block comes AFTER `border`, so an older reader stops before it – no version bump
F_PROFILE = 4

# profile step in decimetres: 5 m; rounding to metres would be noisier than the terrain
STEP_DM = 50

# an edge runs along the way's nodes, against them, or both
D_FORWARD = 1
D_BACKWARD = 2

# index = what is in the tile; never reorder without a format version
RESTRICTION_KINDS = [
    "no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn",
    "no_entry", "no_exit",
    "only_left_turn", "only_right_turn", "only_straight_on", "only_u_turn",
]

# `except=bicycle;psv` – one bit per vehicle the restriction spares
EXCEPTIONS = ["foot", "bicycle", "psv", "hgv", "motorcar", "moped",
              "motorcycle", "emergency"]

# cap per tile; above it a phone can't hold the pieces in memory sensibly
BUDGET_KB = 1024


def sample_count(length_m, step_m):
    """Samples in an edge profile – the last sits on its end, not on a step."""
    if length_m <= 0:
        return 0
    whole = int(length_m // step_m)
    return whole + (2 if length_m - whole * step_m > 0.01 else 1)


def zigzag(n):
    return (n << 1) ^ (n >> 63) if n < 0 else n << 1


class Writer:
    def __init__(self):
        self.b = bytearray()

    def u(self, n):
        if n < 0:
            raise ValueError(f"no varint for a negative number: {n}")
        while True:
            b = n & 0x7F
            n >>= 7
            self.b.append(b | 0x80 if n else b)
            if not n:
                return

    def z(self, n):
        self.u((n << 1) ^ (n >> 63) if n < 0 else n << 1)

    def byte(self, n):
        self.b.append(n & 0xFF)

    def text(self, s):
        raw = s.encode("utf-8")
        self.u(len(raw))
        self.b += raw


class Reader:
    def __init__(self, b):
        self.b, self.i = b, 0

    def u(self):
        n, shift = 0, 0
        while True:
            x = self.b[self.i]
            self.i += 1
            n |= (x & 0x7F) << shift
            if not x & 0x80:
                return n
            shift += 7

    def z(self):
        n = self.u()
        return -(n + 1) // 2 if n & 1 else n // 2

    def byte(self):
        self.i += 1
        return self.b[self.i - 1]

    def text(self):
        n = self.u()
        self.i += n
        return self.b[self.i - n:self.i].decode("utf-8")


def write(tile):
    """A tile as a dict of fields → body bytes (not yet gzipped)."""
    w = Writer()
    w.b += MAGIC
    w.byte(VERSION)
    profiles = [h.get("profile") or [] for h in tile["edges"]]
    has_profile = any(profiles)
    flags = ((F_HEIGHT if tile["height"] else 0)
             | (F_ORDER if tile["order"] else 0)
             | (F_PROFILE if has_profile else 0))
    w.byte(flags)
    w.b += struct.pack(">II", tile["dictionary_id"], tile["order_id"])
    for v in tile["zxy"]:
        w.u(v)
    for v in tile["bbox"]:
        w.z(v)

    nodes = tile["nodes"]
    w.u(len(nodes))
    _column_z(w, [u[0] for u in nodes], delta=True)
    _column_z(w, [u[1] for u in nodes], delta=True)
    _column_z(w, [u[2] for u in nodes], delta=True)
    if tile["height"]:
        _column_z(w, [u[3] for u in nodes], delta=True)
    if tile["order"]:
        for u in nodes:
            w.u(u[4])

    edges = tile["edges"]
    w.u(len(edges))
    for h in edges:
        w.u(h["from"])
    for h in edges:
        w.u(h["to"])
    for h in edges:
        w.u(h["tagset"])
    for h in edges:
        w.u(h["length_cm"])
    for h in edges:
        w.byte(h["direction"])
    for h in edges:
        w.u(len(h["geom"]))
    for h in edges:
        lat, lon = nodes[h["from"]][1], nodes[h["from"]][2]
        for glat, glon in h["geom"]:
            w.z(glat - lat)
            w.z(glon - lon)
            lat, lon = glat, glon

    w.u(len(tile["tagsets"]))
    for ts in tile["tagsets"]:
        w.u(len(ts))
        for key_idx, value in ts:
            w.u(key_idx)
            w.u(value)

    w.u(len(tile["strings"]))
    for s in tile["strings"]:
        w.text(s)

    w.u(len(tile["restrictions"]))
    for z in tile["restrictions"]:
        w.u(z["kind"])
        w.u(z["exceptions"])
        w.u(len(z["edges"]))
        for a, b in z["edges"]:
            w.u(a)
            w.u(b)

    w.u(len(tile["border"]))
    for i in tile["border"]:
        w.u(i)

    if has_profile:
        _write_profiles(w, profiles, tile.get("step_dm") or STEP_DM)
    return bytes(w.b)


def _write_profiles(w, profiles, step_dm):
    """Heights along edges every `step_dm`, in decimetres – the body's last block."""
    w.u(step_dm)
    w.u(len(profiles))
    for p in profiles:
        w.u(len(p))
    _column_z(w, [p[0] for p in profiles if p], delta=True)
    for p in profiles:
        prev = p[0] if p else 0
        for v in p[1:]:
            w.z(v - prev)
            prev = v


def read(raw):
    """Body bytes → the same dict `write` took."""
    if raw[:4] != MAGIC:
        raise ValueError("the tile body doesn't start with `RTIL` – not a "
                         "routing tile")
    r = Reader(raw)
    r.i = 4
    version = r.byte()
    if version != VERSION:
        raise ValueError(f"the tile is format v{version}, this code reads "
                         f"v{VERSION}")
    flags = r.byte()
    dictionary_id, order_id = struct.unpack(">II", raw[r.i:r.i + 8])
    r.i += 8
    zxy = [r.u() for _ in range(3)]
    bbox = [r.z() for _ in range(4)]

    n = r.u()
    ids = _read_column(r, n, delta=True)
    lats = _read_column(r, n, delta=True)
    lons = _read_column(r, n, delta=True)
    heights = (_read_column(r, n, delta=True) if flags & F_HEIGHT
               else [0] * n)
    rank = [r.u() for _ in range(n)] if flags & F_ORDER else [0] * n
    nodes = list(zip(ids, lats, lons, heights, rank))

    m = r.u()
    frm = [r.u() for _ in range(m)]
    to = [r.u() for _ in range(m)]
    tagset = [r.u() for _ in range(m)]
    length = [r.u() for _ in range(m)]
    direction = [r.byte() for _ in range(m)]
    counts = [r.u() for _ in range(m)]
    edges = []
    for i in range(m):
        lat, lon = nodes[frm[i]][1], nodes[frm[i]][2]
        geom = []
        for _ in range(counts[i]):
            lat += r.z()
            lon += r.z()
            geom.append((lat, lon))
        edges.append({"from": frm[i], "to": to[i], "tagset": tagset[i],
                      "length_cm": length[i], "direction": direction[i],
                      "geom": geom, "profile": []})

    tagsets = []
    for _ in range(r.u()):
        tagsets.append([(r.u(), r.u()) for _ in range(r.u())])
    strings = [r.text() for _ in range(r.u())]

    restrictions = []
    for _ in range(r.u()):
        kind, exceptions = r.u(), r.u()
        restrictions.append({"kind": kind, "exceptions": exceptions,
                             "edges": [(r.u(), r.u()) for _ in range(r.u())]})
    border = [r.u() for _ in range(r.u())]

    step_dm = STEP_DM
    if flags & F_PROFILE:
        step_dm = _read_profiles(r, edges)

    return {"version": version, "height": bool(flags & F_HEIGHT),
            "order": bool(flags & F_ORDER),
            "profile": bool(flags & F_PROFILE), "step_dm": step_dm,
            "dictionary_id": dictionary_id, "order_id": order_id,
            "zxy": zxy, "bbox": bbox, "nodes": nodes, "edges": edges,
            "tagsets": tagsets, "strings": strings, "restrictions": restrictions,
            "border": border}


def _read_profiles(r, edges):
    """The profile block into `edges[i]["profile"]`; returns the step in decimetres."""
    step_dm = r.u()
    count = r.u()
    if count != len(edges):
        raise ValueError(f"the profile block speaks of {count} edges, the tile "
                         f"has {len(edges)}")
    counts = [r.u() for _ in range(count)]
    firsts, prev = [], 0
    for n in counts:
        if n:
            prev += r.z()
            firsts.append(prev)
        else:
            firsts.append(None)
    for h, n, start in zip(edges, counts, firsts):
        if not n:
            h["profile"] = []
            continue
        p = [start]
        for _ in range(n - 1):
            p.append(p[-1] + r.z())
        h["profile"] = p
    return step_dm


def _column_z(w, values, delta):
    prev = 0
    for v in values:
        w.z(v - prev if delta else v)
        if delta:
            prev = v


def _read_column(r, n, delta):
    out, prev = [], 0
    for _ in range(n):
        v = r.z() + (prev if delta else 0)
        out.append(v)
        prev = v
    return out
