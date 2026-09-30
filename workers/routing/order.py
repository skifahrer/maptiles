#!/usr/bin/env python3
"""Node order for CCH – the one expensive part that doesn't belong on a phone."""
import argparse
import hashlib
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# below this size splitting gains nothing
FLOOR = 32
# neither half may be smaller; a narrower cut makes an empty split
BALANCE = 0.25
# cut directions, as in Inertial Flow
DIRECTIONS = [(1.0, 0.0), (0.0, 1.0), (0.7071, 0.7071), (0.7071, -0.7071)]


def order(nodes, neighbours):
    """Nodes in elimination order: both halves, then the separator."""
    out = []
    _split(sorted(nodes), neighbours, out)
    return out


def _split(group, neighbours, out):
    if len(group) <= FLOOR:
        out.extend(group)
        return
    a, b, separator = _cut(group, neighbours)
    if not a or not b:
        out.extend(group)
        return
    _split(a, neighbours, out)
    _split(b, neighbours, out)
    # the separator goes last – the whole point of nested dissection
    out.extend(separator)


def _cut(group, neighbours):
    """Of four directions, the one cutting the fewest edges."""
    in_group = set(group)
    best = None
    for dx, dy in DIRECTIONS:
        ordered = sorted(group, key=lambda u: (dx * neighbours.xy[u][1]
                                               + dy * neighbours.xy[u][0], u))
        middle = len(ordered) // 2
        first = set(ordered[:middle])
        cuts = sum(1 for u in first for v in neighbours[u]
                   if v in in_group and v not in first)
        if best is None or cuts < best[0]:
            best = (cuts, ordered, first)
    _cuts, ordered, first = best
    if min(len(first), len(ordered) - len(first)) < BALANCE * len(ordered):
        return [], [], []

    crossing = [(u, v) for u in first for v in neighbours[u]
                if v in in_group and v not in first]
    separator = _cover(crossing)
    a = [u for u in ordered if u in first and u not in separator]
    b = [u for u in ordered if u not in first and u not in separator]
    return a, b, sorted(separator)


def _cover(edges):
    """A vertex separator from the cut edges – greedy, densest node first."""
    degree = {}
    for u, v in edges:
        degree[u] = degree.get(u, 0) + 1
        degree[v] = degree.get(v, 0) + 1
    left, out = list(edges), set()
    while left:
        u = max({x for h in left for x in h}, key=lambda x: (degree[x], -x))
        out.add(u)
        left = [h for h in left if u not in h]
    return out


class Neighbours:
    """Neighbours and coordinates together – a cut asks for both."""

    def __init__(self, network):
        # a longitude degree is a third shorter here; "45°" must be 45°
        middle = (sum(lat for lat, _lon in network.nodes.values())
                  / max(1, len(network.nodes)) / 1e7)
        k = math.cos(math.radians(middle))
        self.xy = {u: (lat, lon * k) for u, (lat, lon) in network.nodes.items()}
        self._s = network.neighbours()

    def __getitem__(self, u):
        return self._s[u]


def _components(nodes, neighbours):
    """Disconnected pieces split apart; a cut across two islands isn't a cut."""
    seen, out = set(), []
    for start in sorted(nodes):
        if start in seen:
            continue
        piece, front = [], [start]
        seen.add(start)
        while front:
            u = front.pop()
            piece.append(u)
            for v in neighbours[u]:
                if v not in seen:
                    seen.add(v)
                    front.append(v)
        out.append(sorted(piece))
    out.sort(key=len, reverse=True)
    return out


def _id(rank):
    raw = ";".join(f"{u}:{r}" for u, r in sorted(rank.items())).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True,
                    help="PBF of the WHOLE area built – orders computed per "
                         "region can't be joined")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="",
                    help="what area this is – goes into the order file")
    args = ap.parse_args()

    import network as network_mod                                 # noqa: PLC0415

    t0 = time.time()
    network = network_mod.load(args.pbf)
    if not network.nodes:
        print("::error::The PBF has no road, so there is nothing to "
              "order.", file=sys.stderr)
        return 1
    neighbours = Neighbours(network)

    out = []
    for piece in _components(network.nodes, neighbours):
        out.extend(order(piece, neighbours))
    rank = {u: i for i, u in enumerate(out)}

    body = {"id": f"{_id(rank):08x}", "name": args.name, "nodes": len(rank),
            "edges": len(network.edges),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rank": rank}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    print(f"Order {body['id']}: {len(rank)} nodes in "
          f"{time.time() - t0:.0f} s → {args.out} "
          f"({os.path.getsize(args.out) / 1048576:.1f} MB)")
    print("::notice::This order belongs in EVERY archive of this run. A region "
          "built against another order must never join the others – the "
          "mismatch looks like a broken route, not another file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
