#!/usr/bin/env python3
"""Random junction pairs and Valhalla's answers to them – an outside opinion for the app."""
import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# roads open to cars and walkers alike – a pair should have an answer for both
SHARED = {"primary", "secondary", "tertiary", "unclassified", "residential",
          "primary_link", "secondary_link", "tertiary_link", "living_street"}
PROFILES = {"car": "auto", "foot": "pedestrian"}


def air_m(a, b):
    la1, lo1 = math.radians(a[0] / 1e7), math.radians(a[1] / 1e7)
    la2, lo2 = math.radians(b[0] / 1e7), math.radians(b[1] / 1e7)
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def junctions(network):
    out = set()
    for h in network.edges:
        if dict(h["tags"]).get("highway") in SHARED:
            out.add(h["from"])
            out.add(h["to"])
    return sorted(out)


def pairs(network, n, seed, min_m, max_m):
    nodes = junctions(network)
    rnd = random.Random(seed)
    out, tries = [], 0
    while len(out) < n and tries < n * 200:
        tries += 1
        a, b = rnd.choice(nodes), rnd.choice(nodes)
        d = air_m(network.nodes[a], network.nodes[b])
        if a != b and min_m <= d <= max_m:
            out.append((a, b, d))
    return out


def route(server, a, b, costing):
    body = {"locations": [{"lat": a[0] / 1e7, "lon": a[1] / 1e7},
                          {"lat": b[0] / 1e7, "lon": b[1] / 1e7}],
            "costing": costing, "units": "kilometers",
            "directions_type": "none"}
    req = urllib.request.Request(f"{server}/route", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            s = json.load(r)["trip"]["summary"]
        return {"m": round(s["length"] * 1000), "s": round(s["time"])}
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
        except Exception:                                         # noqa: BLE001
            err = {}
        return {"error": err.get("error_code", e.code),
                "message": err.get("error", str(e))}


def wait(server, seconds=120):
    until = time.time() + seconds
    while time.time() < until:
        try:
            with urllib.request.urlopen(f"{server}/status", timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:                                         # noqa: BLE001
            time.sleep(2)
    raise SystemExit(f"Valhalla at {server} doesn't answer")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True, help="the same PBF the archive is from")
    ap.add_argument("--out", required=True)
    ap.add_argument("--region-key", required=True)
    ap.add_argument("--valhalla", default="http://localhost:8002")
    ap.add_argument("--valhalla-version", default="")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--min-km", type=float, default=2.0)
    ap.add_argument("--max-km", type=float, default=40.0)
    args = ap.parse_args()

    import network as network_mod                                 # noqa: PLC0415
    network = network_mod.load(args.pbf)
    chosen = pairs(network, args.n, args.seed, args.min_km * 1000, args.max_km * 1000)
    print(f"Network: {len(network.nodes)} junctions, {len(chosen)} pairs "
          f"{args.min_km}–{args.max_km} km")
    wait(args.valhalla)

    out, no_route = [], {k: 0 for k in PROFILES}
    for i, (a, b, d) in enumerate(chosen, 1):
        z = {"from": a, "to": b,
             "from_lat": network.nodes[a][0] / 1e7, "from_lon": network.nodes[a][1] / 1e7,
             "to_lat": network.nodes[b][0] / 1e7, "to_lon": network.nodes[b][1] / 1e7,
             "air_m": round(d)}
        for key, costing in PROFILES.items():
            z[key] = route(args.valhalla, network.nodes[a], network.nodes[b], costing)
            if "error" in z[key]:
                no_route[key] += 1
        out.append(z)
        if i % 25 == 0:
            print(f"  {i}/{len(chosen)}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"region": args.region_key, "valhalla": args.valhalla_version,
                   "seed": args.seed, "count": len(out), "no_route": no_route,
                   "pairs": out}, f, ensure_ascii=False, indent=1)
    print(f"{args.out}: {len(out)} pairs, no route by car {no_route['car']}, "
          f"on foot {no_route['foot']}")


if __name__ == "__main__":
    main()
