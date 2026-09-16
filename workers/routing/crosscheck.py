#!/usr/bin/env python3
"""Náhodné dvojice križovatiek a Valhallina odpoveď na ne – vonkajší názor pre appku."""
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

# cesty, po ktorých smie auto aj chodec – dvojica má mať odpoveď pre oboch
SPOLOCNE = {"primary", "secondary", "tertiary", "unclassified", "residential",
            "primary_link", "secondary_link", "tertiary_link", "living_street"}
PROFILY = {"auto": "auto", "chodec": "pedestrian"}


def vzdusna_m(a, b):
    la1, lo1 = math.radians(a[0] / 1e7), math.radians(a[1] / 1e7)
    la2, lo2 = math.radians(b[0] / 1e7), math.radians(b[1] / 1e7)
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def krizovatky(siet):
    von = set()
    for h in siet.hrany:
        if dict(h["tagy"]).get("highway") in SPOLOCNE:
            von.add(h["od"])
            von.add(h["do"])
    return sorted(von)


def dvojice(siet, n, seed, min_m, max_m):
    uzly = krizovatky(siet)
    rnd = random.Random(seed)
    von, pokusy = [], 0
    while len(von) < n and pokusy < n * 200:
        pokusy += 1
        a, b = rnd.choice(uzly), rnd.choice(uzly)
        d = vzdusna_m(siet.uzly[a], siet.uzly[b])
        if a != b and min_m <= d <= max_m:
            von.append((a, b, d))
    return von


def trasa(server, od, do, costing):
    telo = {"locations": [{"lat": od[0] / 1e7, "lon": od[1] / 1e7},
                          {"lat": do[0] / 1e7, "lon": do[1] / 1e7}],
            "costing": costing, "units": "kilometers",
            "directions_type": "none"}
    req = urllib.request.Request(f"{server}/route", data=json.dumps(telo).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            s = json.load(r)["trip"]["summary"]
        return {"m": round(s["length"] * 1000), "s": round(s["time"])}
    except urllib.error.HTTPError as e:
        try:
            chyba = json.load(e)
        except Exception:                                         # noqa: BLE001
            chyba = {}
        return {"chyba": chyba.get("error_code", e.code),
                "sprava": chyba.get("error", str(e))}


def pockaj(server, sekund=120):
    do = time.time() + sekund
    while time.time() < do:
        try:
            with urllib.request.urlopen(f"{server}/status", timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:                                         # noqa: BLE001
            time.sleep(2)
    raise SystemExit(f"Valhalla na {server} neodpovedá")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True, help="to isté PBF, z akého je archív")
    ap.add_argument("--out", required=True)
    ap.add_argument("--region-key", required=True)
    ap.add_argument("--valhalla", default="http://localhost:8002")
    ap.add_argument("--valhalla-version", default="")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--min-km", type=float, default=2.0)
    ap.add_argument("--max-km", type=float, default=40.0)
    args = ap.parse_args()

    import network                                                # noqa: PLC0415
    siet = network.nacitaj(args.pbf)
    pary = dvojice(siet, args.n, args.seed, args.min_km * 1000, args.max_km * 1000)
    print(f"Sieť: {len(siet.uzly)} križovatiek, {len(pary)} dvojíc "
          f"{args.min_km}–{args.max_km} km")
    pockaj(args.valhalla)

    von, bez = [], {k: 0 for k in PROFILY}
    for i, (a, b, d) in enumerate(pary, 1):
        z = {"od": a, "do": b,
             "od_lat": siet.uzly[a][0] / 1e7, "od_lon": siet.uzly[a][1] / 1e7,
             "do_lat": siet.uzly[b][0] / 1e7, "do_lon": siet.uzly[b][1] / 1e7,
             "vzdusna_m": round(d)}
        for kluc, costing in PROFILY.items():
            z[kluc] = trasa(args.valhalla, siet.uzly[a], siet.uzly[b], costing)
            if "chyba" in z[kluc]:
                bez[kluc] += 1
        von.append(z)
        if i % 25 == 0:
            print(f"  {i}/{len(pary)}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"kraj": args.region_key, "valhalla": args.valhalla_version,
                   "seed": args.seed, "dvojic": len(von), "bez_trasy": bez,
                   "dvojice": von}, f, ensure_ascii=False, indent=1)
    print(f"{args.out}: {len(von)} dvojíc, bez trasy auto {bez['auto']}, "
          f"chodec {bez['chodec']}")


if __name__ == "__main__":
    main()
