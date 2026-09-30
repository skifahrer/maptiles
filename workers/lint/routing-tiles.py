#!/usr/bin/env python3
"""What the dictionary lacks never reaches the phone – and nobody says so.

  1. dictionary: every key has exactly one kind and enumerated values are valid;
  2. the class a way is taken into the graph by also travels;
  3. a profile option stands on a `key=value` the dictionary knows;
  4. a country selling a vignette is among the `country` values;
  5. a tile body writes and reads back the same, height profile included;
  6. a dense tile is cut deeper until its body fits the budget;
  7. a run's archives (when given): one dictionary, one order, tiles within
     the budget, and the neighbours' overlap must agree.
"""
import argparse
import gzip
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
REL_TAGS = "workers/data/routing-tags.json"


def load(name, filename, folder):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_WORKERS, folder, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Lint:
    def __init__(self):
        self.bad = 0

    def err(self, path, msg):
        print(f"::error file={path}::{msg}")
        self.bad += 1


def try_body(fmt, lint, height=False, profile=False):
    """Writing and reading must give the same – or the archive reads as another graph."""
    h = (420, 380) if height else (0, 0)
    d = {"height": height, "order": True, "dictionary_id": 0x01020304,
         "order_id": 0x05060708, "zxy": [9, 283, 175],
         "bbox": [1, -2, 3, 4],
         "nodes": [(10, 490000000, 190000000, h[0], 1),
                   (2000000000000, 490010000, 190020000, h[1], 9)],
         "edges": [{"from": 0, "to": 1, "tagset": 0, "length_cm": 1234,
                    "direction": fmt.D_FORWARD, "geom": [(490005000, 190010000)],
                    "profile": [4200, 4190, 4150, 4020, 3860, 3800]
                               if profile else []}],
         "tagsets": [[(0, 1), (4, 0)]], "strings": ["Hlavná"],
         "restrictions": [{"kind": 0, "exceptions": 3, "edges": [(10, 20), (20, 30)]}],
         "border": [1]}
    try:
        back = fmt.read(fmt.write(d))
    except Exception as e:                                        # noqa: BLE001
        lint.err("workers/routing/format.py",
                 f"a tile body can't be read back: {type(e).__name__}: {e}")
        return
    for key, expected in d.items():
        if back[key] != expected:
            lint.err("workers/routing/format.py",
                     f"field `{key}` changed through writing and reading "
                     f"({expected} → {back[key]}). The phone would read another "
                     f"graph there and a route would come out – just a different one.")
    if back["profile"] != profile:
        lint.err("workers/routing/format.py",
                 f"the profile flag reads back as {back['profile']}, it should be "
                 f"{profile} – the phone would either miss the climb or look for "
                 f"a block the body doesn't have.")


def _dense_network(fmt, step=0.01, grid=24):
    nodes, edges = {}, []
    for i in range(grid):
        for j in range(grid):
            nodes[i * 100 + j] = (int((48.10 + i * step) * 1e7),
                                  int((17.05 + j * step) * 1e7))
    for i in range(grid):
        for j in range(grid - 1):
            a, b = i * 100 + j, i * 100 + j + 1
            edges.append({"from": a, "to": b, "geom": [nodes[b]],
                          "length_cm": 74000, "direction": fmt.D_FORWARD,
                          "tags": {"highway": "residential",
                                   "name": f"Ulica {a}"}})
    restrictions = [{"kind": 0, "exceptions": 0, "via": 1, "edges": [(0, 1), (1, 2)]}]
    return SimpleNamespace(nodes=nodes, edges=edges, restrictions=restrictions)


def try_split(fmt, lint):
    """A dense tile is cut deeper until its body fits the budget."""
    tiles = load("routing_tiles", "tiles.py", "routing")
    dictionary = tiles.tags_mod.dictionary()
    network = _dense_network(fmt)
    budget = 1500
    bodies = tiles.split(network, dictionary, "SK", tiles.Order(), budget=budget)

    edges, restrictions = 0, 0
    for zxy, body in bodies.items():
        z, x, y = zxy
        if len(body) > budget and z < tiles.ZOOM_MAX:
            lint.err("workers/routing/tiles.py",
                     f"tile {z}/{x}/{y} has {len(body)} B, above the {budget} B "
                     f"budget, and wasn't split. The archive would fail the same "
                     f"check that guards it in the build.")
        d = fmt.read(gzip.decompress(body))
        edges += len(d["edges"])
        restrictions += len(d["restrictions"])
        for depth in range(tiles.ZOOM, z):
            if (depth, x >> (z - depth), y >> (z - depth)) in bodies:
                lint.err("workers/routing/tiles.py",
                         f"tile {z}/{x}/{y} is in the archive together with its "
                         f"ancestor at z{depth} – the phone would load the same "
                         f"edges twice.")
    if edges != len(network.edges):
        lint.err("workers/routing/tiles.py",
                 f"splitting yielded {edges} of {len(network.edges)} edges. "
                 f"A road lost in the split is in no tile.")
    if restrictions != len(network.restrictions):
        lint.err("workers/routing/tiles.py",
                 f"splitting yielded {restrictions} of {len(network.restrictions)} "
                 f"restrictions – a route would take a forbidden turn.")
    if not any(z > tiles.ZOOM for z, _, _ in bodies):
        lint.err("workers/routing/tiles.py",
                 f"a network over the budget stayed whole at z{tiles.ZOOM}; the "
                 f"split didn't run and every dense tile would fail the build.")


def check_dictionary(dictionary, raw, lint):
    for key, spec in raw["keys"].items():
        kinds = [k for k in ("from_network", "access", "values", "number", "free")
                 if spec.get(k)]
        if len(kinds) != 1:
            lint.err(REL_TAGS, f"key `{key}` has kinds {kinds or '—'}; it needs "
                               f"exactly one. Two kinds mean two encodings of "
                               f"the same value.")
    for key in dictionary.keys:
        values = dictionary.values[key]
        if dictionary.kind[key] == "values" and not values:
            lint.err(REL_TAGS, f"key `{key}` is enumerated but has not a single "
                               f"value – every one is dropped.")
        if len(set(values)) != len(values):
            lint.err(REL_TAGS, f"key `{key}` has a value twice. The index would "
                               f"point at the first and the second couldn't be "
                               f"written.")
    for key in dictionary.network:
        if dictionary.kind.get(key) != "values":
            lint.err(REL_TAGS, f"`network` takes ways by `{key}`, but that key "
                               f"doesn't travel. A user would turn off a road type "
                               f"the archive lacks, and the route would keep "
                               f"using it.")


def profile_against_dictionary(dictionary, lint):
    with open(os.path.join(_DATA, "routing-profiles.json"), encoding="utf-8") as f:
        options = json.load(f)["options"]
    for option, spec in options.items():
        if not isinstance(spec, dict):
            continue
        for pair in spec.get("osm") or []:
            key, _, value = pair.partition("=")
            if dictionary.index(key) is None:
                lint.err(REL_TAGS,
                         f"option `{option}` stands on `{pair}`, but key `{key}` "
                         f"doesn't go into the tile. On the phone the option has "
                         f"nothing to lean on and quietly does nothing.")
            elif dictionary.value_index(key, value) is None:
                lint.err(REL_TAGS,
                         f"option `{option}` stands on `{pair}`, but `{value}` "
                         f"isn't among the values of `{key}`. `tiles.py` drops "
                         f"it and the option does nothing.")


def vignettes_against_dictionary(dictionary, lint):
    with open(os.path.join(_DATA, "vignettes.json"), encoding="utf-8") as f:
        countries = json.load(f)["countries"]
    for code, c in countries.items():
        if not c.get("sells_vignette"):
            continue
        if dictionary.value_index("country", code) is None:
            lint.err(REL_TAGS,
                     f"`{code}` sells a motorway vignette, but isn't among the "
                     f"`country` values. An edge would say nothing of its country "
                     f"and the vignette would have nothing to apply to.")


def archives(paths, dictionary, fmt, lint):
    try:
        from pmtiles.reader import MmapSource, Reader, all_tiles
    except ImportError:
        lint.err("workers/lint/routing-tiles.py",
                 "archives are to be checked, but `pmtiles` isn't in this "
                 "environment (`pip install pmtiles`).")
        return
    orders, content = {}, {}
    for path in paths:
        with open(path, "rb") as f:
            r = Reader(MmapSource(f))
            graph = (r.metadata() or {}).get("graph")
            if not graph:
                lint.err(path, "the archive has no `graph` in its metadata, so it "
                               "names neither its format nor its dictionary. A "
                               "version mismatch then looks like a broken route.")
                continue
            if graph.get("dictionary") != f"{dictionary.id:08x}":
                lint.err(path, f"the archive is built against dictionary "
                               f"`{graph.get('dictionary')}`, while the repository "
                               f"has `{dictionary.id:08x}`. A tag index would point "
                               f"at another value – build the archive again.")
            orders.setdefault(graph.get("order"), []).append(path)
            for (z, x, y), body in all_tiles(MmapSource(f)):
                if len(body) > fmt.BUDGET_KB * 1024:
                    lint.err(path, f"tile {z}/{x}/{y} has {len(body)//1024} kB, "
                                   f"above the {fmt.BUDGET_KB} kB budget.")
                try:
                    d = fmt.read(gzip.decompress(body))
                except Exception as e:                            # noqa: BLE001
                    lint.err(path, f"tile {z}/{x}/{y} can't be read: "
                                   f"{type(e).__name__}: {e}")
                    continue
                if d["zxy"] != [z, x, y]:
                    lint.err(path, f"tile {z}/{x}/{y} calls itself {d['zxy']} "
                                   f"inside – the archive would join in the "
                                   f"wrong place.")
                _tagsets(path, z, x, y, d, dictionary, lint)
                _profile(path, z, x, y, d, lint)
                content.setdefault((z, x, y), {})[path] = d
    if len(orders) > 1:
        lint.err("workers/routing/order.py",
                 "archives of one run have different node orders: "
                 + "; ".join(f"{o or 'none'} → {', '.join(map(os.path.basename, p))}"
                             for o, p in orders.items())
                 + ". They must not be joined and the client has to refuse it.")
    _overlap(content, dictionary, lint)


def _tagsets(path, z, x, y, d, dictionary, lint):
    for i, ts in enumerate(d["tagsets"]):
        for key_idx, code in ts:
            if key_idx >= len(dictionary.keys):
                lint.err(path, f"tile {z}/{x}/{y}, tag set {i} has key {key_idx}, "
                               f"which the dictionary lacks.")
                continue
            key = dictionary.keys[key_idx]
            if dictionary.kind[key] == "values" and code >= len(dictionary.values[key]):
                lint.err(path, f"tile {z}/{x}/{y}: `{key}` has value {code}, but "
                               f"the dictionary has {len(dictionary.values[key])}.")
            if dictionary.kind[key] == "free" and code >= len(d["strings"]):
                lint.err(path, f"tile {z}/{x}/{y}: `{key}` points at string "
                               f"{code}, which the tile lacks.")


def _profile(path, z, x, y, d, lint):
    """Samples follow the edge length and the ends must match the nodes."""
    if not d["profile"]:
        return
    step_m = d["step_dm"] / 10
    for i, e in enumerate(d["edges"]):
        p = e.get("profile")
        if not p:
            continue
        length = e["length_cm"] / 100
        expected = int(length // step_m) + 1
        if length - int(length // step_m) * step_m > 0.01:
            expected += 1
        # edge length is haversine, samples are laid out flat – the gap is one sample
        if abs(len(p) - expected) > 1:
            lint.err(path, f"tile {z}/{x}/{y}, edge {i} is {length:.0f} m long "
                           f"and has {len(p)} samples of {step_m:g} m; {expected} "
                           f"were expected. The phone lays samples by the step, "
                           f"so it would stretch or shrink the profile.")
            continue
        if not d["height"]:
            continue
        for end, sample in ((e["from"], p[0]), (e["to"], p[-1])):
            node = d["nodes"][end][3]
            if abs(round(sample / 10) - node) > 1:
                lint.err(path, f"tile {z}/{x}/{y}, edge {i} ends at "
                               f"{sample / 10:.0f} m, but its node has {node} m. "
                               f"The climb would jump by the difference at every "
                               f"junction.")
                return


def _overlap(content, dictionary, lint):
    """Two archives must tell the same edge the same way – or they can't be joined."""
    shared, conflicts = 0, 0
    for zxy, by_archive in content.items():
        if len(by_archive) < 2:
            continue
        shared += 1
        paths = list(by_archive)
        first = _edges_by_id(by_archive[paths[0]], dictionary)
        for other in paths[1:]:
            second = _edges_by_id(by_archive[other], dictionary)
            differ = [k for k in set(first) & set(second) if first[k] != second[k]]
            if differ:
                conflicts += 1
                lint.err(other, f"tile {zxy[0]}/{zxy[1]}/{zxy[2]} is also in "
                                f"{os.path.basename(paths[0])} and {len(differ)} "
                                f"shared edges differ between them. The phone joins "
                                f"them by OSM id, so it would pick one of two truths.")
            conflicts += _nodes(zxy, paths[0], by_archive[paths[0]],
                                other, by_archive[other], lint)
    if shared and not conflicts:
        print(f"  neighbour overlap: {shared} shared tiles, edges agree")


def _edges_by_id(d, dictionary):
    out = {}
    for e in d["edges"]:
        key = (d["nodes"][e["from"]][0], d["nodes"][e["to"]][0])
        out[key] = (e["length_cm"], e["direction"], len(e.get("profile") or []),
                    _tags(d, e["tagset"], dictionary))
    return out


def _nodes(zxy, first_path, a, second_path, b, lint):
    """The same node must have the same coordinates and rank in both archives."""
    first = {u[0]: (u[1], u[2], u[4]) for u in a["nodes"]}
    second = {u[0]: (u[1], u[2], u[4]) for u in b["nodes"]}
    ordered = a["order"] and b["order"]
    differ = [osm for osm in set(first) & set(second)
              if first[osm][:2] != second[osm][:2]
              or (ordered and first[osm][2] != second[osm][2])]
    if not differ:
        return 0
    lint.err(second_path, f"tile {zxy[0]}/{zxy[1]}/{zxy[2]} is also in "
                          f"{os.path.basename(first_path)} and {len(differ)} shared "
                          f"nodes differ between them. The rank is computed over "
                          f"the whole area, so a difference means two orders "
                          f"under one `id`.")
    return 1


def _tags(d, i, dictionary):
    """A string index holds in one tile only, so its value is compared."""
    out = []
    for key_idx, code in sorted(d["tagsets"][i]):
        key = (dictionary.keys[key_idx] if key_idx < len(dictionary.keys)
               else key_idx)
        free = dictionary.kind.get(key) == "free" and code < len(d["strings"])
        out.append((key, d["strings"][code] if free else code))
    return tuple(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="*",
                    help="the run's `.pmtiles` – without them only the lookup is checked")
    args = ap.parse_args()

    lint = Lint()
    fmt = load("routing_format", "format.py", "routing")
    tags = load("routing_tags", "tags.py", "routing")
    dictionary = tags.dictionary()
    with open(os.path.join(_DATA, "routing-tags.json"), encoding="utf-8") as f:
        raw = json.load(f)

    if len(set(fmt.RESTRICTION_KINDS)) != len(fmt.RESTRICTION_KINDS):
        lint.err("workers/routing/format.py", "`RESTRICTION_KINDS` has a kind "
                                              "twice – the index would point at "
                                              "the first.")
    if len(set(fmt.EXCEPTIONS)) != len(fmt.EXCEPTIONS):
        lint.err("workers/routing/format.py", "`EXCEPTIONS` has a vehicle twice.")

    check_dictionary(dictionary, raw, lint)
    profile_against_dictionary(dictionary, lint)
    vignettes_against_dictionary(dictionary, lint)
    try_body(fmt, lint)
    try_body(fmt, lint, height=True)
    try_body(fmt, lint, height=True, profile=True)
    try_split(fmt, lint)
    if args.archives:
        archives(args.archives, dictionary, fmt, lint)

    if lint.bad:
        print(f"\n{lint.bad} problem(s) in the routing tiles.")
        return 1
    print(f"The routing tiles are whole: dictionary `{dictionary.id:08x}` "
          f"v{dictionary.version} ({len(dictionary.keys)} keys) covers every profile "
          f"option and every vignette country, a tile body reads back the same"
          + (f", {len(args.archives)} archive(s) agree." if args.archives else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
