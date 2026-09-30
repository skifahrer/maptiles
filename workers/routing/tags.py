#!/usr/bin/env python3
"""Routing tag dictionary – the one way into `workers/data/routing-tags.json`."""
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
LOOKUP = os.path.join(os.path.dirname(_HERE), "data", "routing-tags.json")

# key kinds; a tile value is encoded by them
ENUMERATED, NUMBER, FREE = "values", "number", "free"

# the id hashes the former Slovak names, so no published archive is orphaned
_ID_KIND = {ENUMERATED: "hodnoty", NUMBER: "cislo", FREE: "volny"}
_ID_KEY = {"country": "krajina"}


class Dictionary:
    """Keys and values allowed into a tile – in the order that is their index."""

    def __init__(self, path=LOOKUP):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.version = raw["version"]
        self.network = {k: v for k, v in raw["network"].items() if not k.startswith("_")}
        access = raw["_access"]["values"]

        self.keys = []                     # order = the key's index in the tile
        self.kind = {}
        self.values = {}
        for key, spec in raw["keys"].items():
            if spec.get("from_network"):
                kind, values = ENUMERATED, list(self.network[key])
            elif spec.get("access"):
                kind, values = ENUMERATED, list(access)
            elif spec.get(ENUMERATED):
                kind, values = ENUMERATED, list(spec[ENUMERATED])
            elif spec.get(NUMBER):
                kind, values = NUMBER, []
            elif spec.get(FREE):
                kind, values = FREE, []
            else:
                raise SystemExit(
                    f"::error file=workers/data/routing-tags.json::key "
                    f"`{key}` has no kind (`values`, `number`, `free`, "
                    f"`access` or `from_network`). Without one it can't be encoded "
                    f"or read – the phone would read another number there.")
            self.keys.append(key)
            self.kind[key] = kind
            self.values[key] = values
        self._idx = {k: i for i, k in enumerate(self.keys)}
        self._vidx = {k: {v: i for i, v in enumerate(vs)}
                      for k, vs in self.values.items()}
        self.id = _id(self.version, self.network, self.keys, self.kind, self.values)

    def index(self, key):
        return self._idx.get(key)

    def value_index(self, key, value):
        return self._vidx.get(key, {}).get(value)

    def road_class(self, tags):
        """What makes the way a road – `(key, value)`, or `None`."""
        for key, values in self.network.items():
            v = tags.get(key)
            if v in values:
                return key, v
        return None

    def pick(self, tags):
        """Tags that travel; an unknown value is dropped and returned apart."""
        out, dropped = {}, []
        for key, v in tags.items():
            kind = self.kind.get(key)
            if kind is None:
                continue
            v = v.strip()
            if kind == ENUMERATED:
                if key in self._vidx and v in self._vidx[key]:
                    out[key] = v
                else:
                    dropped.append((key, v))
            elif kind == NUMBER:
                try:
                    out[key] = str(int(v))
                except ValueError:
                    dropped.append((key, v))
            elif v:
                out[key] = v
        return out, dropped


def _id(version, network, keys, kind, values):
    """The dictionary id from its content – a hand-written one wouldn't move on change."""
    body = {
        "verzia": version,
        "siet": {k: list(v) for k, v in network.items()},
        "kluce": [[_ID_KEY.get(k, k), _ID_KIND[kind[k]], values[k]] for k in keys],
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=False,
                     separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


_CACHE = {}
RAIL = os.path.join(os.path.dirname(_HERE), "data", "rail-routing-tags.json")


def dictionary(path=None):
    path = path or os.environ.get("ROUTING_TAGS") or LOOKUP
    if path not in _CACHE:
        _CACHE[path] = Dictionary(path)
    return _CACHE[path]


def export(s=None):
    """The dictionary as the app needs it – keys in index order, with `id`."""
    s = s or dictionary()
    return {"version": s.version, "id": f"{s.id:08x}",
            "network": {k: list(v) for k, v in s.network.items()},
            "keys": [[k, s.kind[k], s.values[k]] for k in s.keys]}


def filter_expressions(s=None):
    """PBF prefilter for `osmium tags-filter` – from `network`, not a second list."""
    s = s or dictionary()
    lines = [f"w/{key}={','.join(values)}"
             for key, values in s.network.items()]
    # turn restrictions; `tags-filter` pulls members itself (without `-R`)
    lines.append("r/type=restriction")
    return lines


def _path_from_argv(argv):
    for i, a in enumerate(argv):
        if a.startswith("--dictionary="):
            return a.split("=", 1)[1]
        if a == "--dictionary" and i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    s = dictionary(_path_from_argv(sys.argv[1:]))
    if "--filter" in sys.argv[1:]:
        print("\n".join(filter_expressions(s)))
        sys.exit(0)
    if "--export" in sys.argv[1:]:
        print(json.dumps(export(s), ensure_ascii=False, indent=1))
        sys.exit(0)
    print(f"dictionary v{s.version}, id {s.id:08x}, {len(s.keys)} keys")
    for key in s.keys:
        n = len(s.values[key])
        print(f"  {s.index(key):2d}  {key:22s} {s.kind[key]:8s}"
              f"{f' ({n} values)' if n else ''}")
    sys.exit(0)
