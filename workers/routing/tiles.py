#!/usr/bin/env python3
"""Junction graph → `<region>-routing.pmtiles`: tiles with tags, not costs."""
import argparse
import gzip
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import tags as tags_mod                                           # noqa: E402

# the map's grid, so neighbouring regions' border tiles line up by z/x/y
ZOOM = 9
# a dense city won't fit the budget, so its tile is cut deeper
ZOOM_MAX = 13
E7 = 1e7


def default_step():
    """The default profile step – one number for `format.py` and `--help`."""
    return fmt.STEP_DM / 10


def tile_at(lat_e7, lon_e7, z=ZOOM):
    lat, lon = lat_e7 / E7, lon_e7 / E7
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    f = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1.0 - math.asinh(math.tan(f)) / math.pi) / 2.0 * n)
    return z, min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def window(z, x, y):
    """The tile's box in e7 (west, south, east, north)."""
    n = 2.0 ** z
    w = x / n * 360.0 - 180.0
    e = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (round(w * E7), round(south * E7), round(e * E7), round(north * E7))


class Tile:
    def __init__(self, zxy, dictionary):
        self.zxy = zxy
        self.dictionary = dictionary
        self.nodes = {}                # osm id -> (lat, lon, height, rank)
        self.edges = []
        self.restrictions = []
        self._tagsets = {}
        self._strings = {}

    def tagset(self, tags):
        """The tag set's index; equal sets are in the archive once."""
        items = []
        for key, value in tags.items():
            i = self.dictionary.index(key)
            kind = self.dictionary.kind[key]
            if kind == tags_mod.ENUMERATED:
                code = self.dictionary.value_index(key, value)
            elif kind == tags_mod.NUMBER:
                code = fmt.zigzag(int(value))
            else:
                code = self._strings.setdefault(value, len(self._strings))
            items.append((i, code))
        items.sort()
        key = tuple(items)
        return self._tagsets.setdefault(key, len(self._tagsets))

    def body(self, dictionary_id, order_id, with_order, with_height=False,
             step_dm=fmt.STEP_DM):
        order = sorted(self.nodes)
        idx = {osm: i for i, osm in enumerate(order)}
        nodes = [(osm, *self.nodes[osm]) for osm in order]
        lat_min = min(u[1] for u in nodes)
        lat_max = max(u[1] for u in nodes)
        lon_min = min(u[2] for u in nodes)
        lon_max = max(u[2] for u in nodes)
        for h in self.edges:
            for lat, lon in h["geom"]:
                lat_min, lat_max = min(lat_min, lat), max(lat_max, lat)
                lon_min, lon_max = min(lon_min, lon), max(lon_max, lon)

        w, s, e, n = window(*self.zxy)
        border = [i for i, u in enumerate(nodes)
                  if not (w <= u[2] <= e and s <= u[1] <= n)]

        return fmt.write({
            "height": with_height,
            "order": with_order,
            "dictionary_id": dictionary_id,
            "order_id": order_id,
            "zxy": list(self.zxy),
            "bbox": [lon_min, lat_min, lon_max, lat_max],
            "nodes": nodes,
            "step_dm": step_dm,
            "edges": [{"from": idx[h["from"]], "to": idx[h["to"]],
                       "tagset": h["tagset"], "length_cm": h["length_cm"],
                       "direction": h["direction"], "geom": h["geom"],
                       "profile": h.get("profile") or []} for h in self.edges],
            "tagsets": [list(k) for k, _ in
                        sorted(self._tagsets.items(), key=lambda kv: kv[1])],
            "strings": [s for s, _ in
                        sorted(self._strings.items(), key=lambda kv: kv[1])],
            "restrictions": self.restrictions,
            "border": border,
        })


def by_tile(network, edges, restrictions, z):
    """An edge belongs to its first node's tile – a property of OSM, not the region."""
    groups = {}
    for h in edges:
        lat, lon = network.nodes[h["from"]]
        groups.setdefault(tile_at(lat, lon, z), ([], []))[0].append(h)
    for r in restrictions:
        lat, lon = network.nodes[r["via"]]
        group = groups.get(tile_at(lat, lon, z))
        if group is None:
            continue
        group[1].append(r)
    return groups


def build(zxy, edges, restrictions, network, dictionary, country, order):
    d = Tile(zxy, dictionary)
    heights = network_heights(network)
    for h in edges:
        tags = dict(h["tags"])
        if country:
            tags["country"] = country
        for ref in (h["from"], h["to"]):
            if ref not in d.nodes:
                d.nodes[ref] = (*network.nodes[ref], heights.get(ref, 0),
                                order.rank(ref))
        d.edges.append({"from": h["from"], "to": h["to"], "geom": h["geom"],
                        "length_cm": h["length_cm"], "direction": h["direction"],
                        "profile": h.get("profile"), "tagset": d.tagset(tags)})
    for r in restrictions:
        d.restrictions.append({"kind": r["kind"], "exceptions": r["exceptions"],
                               "edges": r["edges"]})
    return d


def network_heights(network):
    """Node heights when the network has them – else no column is written."""
    return getattr(network, "heights", None) or {}


def sample_heights(network, dem, step_m=0.0):
    """Heights from the model; when that fails, the archive goes without and says so."""
    import heights                                                # noqa: PLC0415
    t0 = time.time()
    try:
        if step_m > 0:
            from_model, from_neighbours, none, with_prof, no_prof = \
                heights.fill_with_profiles(network, dem, step_m)
        else:
            from_model, from_neighbours, none = heights.fill(network, dem)
            with_prof, no_prof = 0, len(network.edges)
    except Exception as e:                                        # noqa: BLE001
        print(f"::warning::Heights from {dem} couldn't be sampled ({e}) – the "
              f"archive goes without them.")
        return
    print(f"Heights: {from_model} nodes from the model, {from_neighbours} from "
          f"neighbours ({time.time() - t0:.0f} s)")
    if step_m > 0:
        print(f"Profile every {step_m:g} m: {with_prof} edges, {no_prof} without")
    if none:
        print(f"::warning::{none} of {len(network.nodes)} nodes have no height, "
              f"not even from a neighbour – model {dem} doesn't cover them; they "
              f"are 0 m in the archive.")
    if step_m > 0 and no_prof:
        print(f"::warning::{no_prof} of {len(network.edges)} edges have no height "
              f"profile – model {dem} doesn't cover them and their climb comes "
              f"only from the end heights.")


def split(network, dictionary, country, order, budget=None, step_dm=fmt.STEP_DM):
    """z9 tiles; one whose body won't fit the budget is cut deeper.

    The same grid is split, so a child lies wholly in its z9 and that `z/x/y`
    then holds nothing – the phone finds no tile there and descends.
    """
    cap = fmt.BUDGET_KB * 1024 if budget is None else budget
    with_height = bool(network_heights(network))
    bodies = {}
    queue = list(by_tile(network, network.edges, network.restrictions, ZOOM).items())
    while queue:
        zxy, (edges, restrictions) = queue.pop()
        d = build(zxy, edges, restrictions, network, dictionary, country, order)
        body = gzip.compress(
            d.body(dictionary.id, order.id, bool(order), with_height, step_dm), 9)
        if len(body) > cap and zxy[0] < ZOOM_MAX:
            queue.extend(by_tile(network, edges, restrictions, zxy[0] + 1).items())
            continue
        bodies[zxy] = body
    return bodies


class Order:
    """A rank per node – also for a node the order doesn't have."""

    def __init__(self, path=""):
        self.id, self._rank = 0, {}
        if path:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            self.id = int(raw["id"], 16)
            self._rank = {int(k): v for k, v in raw["rank"].items()}
        self._end = len(self._rank)

    def __bool__(self):
        return bool(self._rank)

    def rank(self, osm_id):
        """A node added after the order goes last by OSM id – still a GLOBAL order.

        OSM ids are world-wide, so two regions give a node the same number.
        """
        r = self._rank.get(osm_id)
        return r if r is not None else self._end + osm_id

    def missing(self, nodes):
        return sum(1 for u in nodes if u not in self._rank)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--region-key", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--country", default="",
                    help="the archive's ISO country code – input for the vignette")
    ap.add_argument("--order", default="",
                    help="node order file from workers/routing/order.py")
    ap.add_argument("--dem", default="",
                    help="elevation model mosaic (VRT) – heights and profiles")
    ap.add_argument("--dictionary", default="",
                    help="another tag dictionary, e.g. workers/data/rail-routing-tags.json")
    ap.add_argument("--profile-step", type=float, default=default_step(),
                    help="edge height profile step in metres; 0 = none")
    args = ap.parse_args()

    import network as network_mod                                 # noqa: PLC0415

    dictionary = tags_mod.dictionary(args.dictionary or None)
    if args.country and dictionary.value_index("country", args.country) is None:
        print(f"::error::Country `{args.country}` isn't in `country` of "
              f"workers/data/routing-tags.json, so it wouldn't get into the "
              f"archive and the vignette would have nothing to stand on.",
              file=sys.stderr)
        return 1

    t0 = time.time()
    network = network_mod.load(args.pbf, dictionary)
    print(f"Network: {network.ways} ways → {len(network.nodes)} junctions, "
          f"{len(network.edges)} edges, {len(network.restrictions)} restrictions "
          f"({time.time() - t0:.0f} s)")

    if args.dem:
        sample_heights(network, args.dem, args.profile_step)
    else:
        print("::warning::The archive goes WITHOUT NODE HEIGHTS (`--dem`): bicycle "
              "and walker cost as if the region were flat, and the route shows a "
              "dash instead of the climb.")

    order = Order(args.order)
    if args.order:
        missing = order.missing(network.nodes)
        if missing:
            print(f"::warning::{missing} of {len(network.nodes)} nodes aren't in the "
                  f"order from {args.order} – the network changed since it was "
                  f"computed. They rank last by OSM id, so archives still join; "
                  f"if there are many, recompute the order "
                  f"(workflow “Routing · node order”).")
    else:
        print("::warning::The archive goes WITHOUT A NODE ORDER (`--order`). Routes "
              "still compute, but the phone must work out the order itself – the "
              "one expensive part of CCH that doesn't belong on a phone "
              "(docs/navigation.md §11).")

    step_dm = max(1, int(round(args.profile_step * 10)))
    bodies = split(network, dictionary, args.country, order, step_dm=step_dm)
    if not bodies:
        print("::warning::This area has no road one could take – no routing "
              "archive is made.")
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    zoom_max = max(z for z, _, _ in bodies)
    split_count = sum(1 for z, _, _ in bodies if z > ZOOM)

    big = sorted(((len(b), zxy) for zxy, b in bodies.items()), reverse=True)
    over = [(n, zxy) for n, zxy in big if n > fmt.BUDGET_KB * 1024]
    for n, zxy in over:
        print(f"::warning::Tile {zxy[0]}/{zxy[1]}/{zxy[2]} is "
              f"{n // 1024} kB, above the {fmt.BUDGET_KB} kB budget even "
              f"at z{ZOOM_MAX}, and isn't split further. The lever is the tag "
              f"dictionary (workers/data/routing-tags.json).")

    graph = {
        "scope": "region",
        "key": args.region_key,
        "name": args.name or args.region_key,
        "format": "rtil",
        "format_version": fmt.VERSION,
        "dictionary": f"{dictionary.id:08x}",
        "dictionary_version": dictionary.version,
        "order": f"{order.id:08x}" if order else None,
        "country": args.country or None,
        "zoom": ZOOM,
        "zoom_max": zoom_max,
        "split": split_count,
        "tiles": len(bodies),
        "nodes": len(network.nodes),
        "edges": len(network.edges),
        "restrictions": len(network.restrictions),
        "height": bool(network_heights(network)),
        "profile": bool(args.profile_step) and any(h.get("profile")
                                                   for h in network.edges),
        "profile_step_m": args.profile_step or None,
        "multimodal": False,
        # neighbours' border tiles share z/x/y; the phone joins them by OSM id
        "joining": "by OSM node id; neighbours' border tiles overlap and join "
                   "by features, not by tiles",
        # a dense tile is replaced by its children, its own z/x/y holds nothing
        "splitting": "no tile at z/x/y means descend a zoom, down to zoom_max",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run": os.environ.get("GITHUB_RUN_NUMBER", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }

    # imported here, so a lint without pmtiles can import the tiler
    from pmtiles.tile import (Compression, TileType,                # noqa: PLC0415
                              zxy_to_tileid)
    from pmtiles.writer import Writer                               # noqa: PLC0415

    with open(args.out, "wb") as f:
        wr = Writer(f)
        for zxy in sorted(bodies, key=lambda t: zxy_to_tileid(*t)):
            wr.write_tile(zxy_to_tileid(*zxy), bodies[zxy])
        w = min(window(*z)[0] for z in bodies)
        s = min(window(*z)[1] for z in bodies)
        e = max(window(*z)[2] for z in bodies)
        n = max(window(*z)[3] for z in bodies)
        wr.finalize(
            {"tile_type": TileType.UNKNOWN, "tile_compression": Compression.GZIP,
             "min_zoom": ZOOM, "max_zoom": zoom_max,
             "min_lon_e7": w, "min_lat_e7": s, "max_lon_e7": e, "max_lat_e7": n,
             "center_zoom": ZOOM, "center_lon_e7": (w + e) // 2,
             "center_lat_e7": (s + n) // 2},
            {"name": os.path.basename(args.out).removesuffix(".pmtiles"),
             "format": "rtil",
             "description": "Routing network with tags – the phone computes the cost",
             "graph": graph},
        )

    size = os.path.getsize(args.out)
    print(json.dumps(graph, ensure_ascii=False, indent=2))
    print(f"{args.out}: {len(bodies)} tiles (z{ZOOM}–z{zoom_max}, {split_count} "
          f"split), {size / 1048576:.1f} MB, "
          f"largest {big[0][0] // 1024} kB")
    dropped = network.dropped.most_common(10)
    if dropped:
        print("Values outside the dictionary (dropped): "
              + ", ".join(f"{k}×{n}" for k, n in dropped))
    if network.skipped:
        print("Skipped: "
              + ", ".join(f"{k}×{n}" for k, n in network.skipped.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
