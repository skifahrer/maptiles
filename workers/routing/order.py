#!/usr/bin/env python3
"""Poradie uzlov pre CCH – jediná drahá časť, ktorá nepatrí do telefónu."""
import argparse
import hashlib
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# pod touto veľkosťou už delenie nič nezískava a réžia prevyšuje úžitok
DNO = 32
# ani jedna polovica nesmie byť menšia; užší rez by dal prázdne delenie
VYVAZENIE = 0.25
# smery, v ktorých sa hľadá rez – rovnaké ako pri Inertial Flow
SMERY = [(1.0, 0.0), (0.0, 1.0), (0.7071, 0.7071), (0.7071, -0.7071)]


def poradie(uzly, susedia):
    """Uzly v poradí eliminácie: obe polovice, potom oddeľovač."""
    von = []
    _rozdel(sorted(uzly), susedia, von)
    return von


def _rozdel(skupina, susedia, von):
    if len(skupina) <= DNO:
        von.extend(skupina)
        return
    a, b, oddelovac = _rez(skupina, susedia)
    if not a or not b:
        von.extend(skupina)
        return
    _rozdel(a, susedia, von)
    _rozdel(b, susedia, von)
    # oddeľovač ide na koniec – to je celý zmysel nested dissection
    von.extend(oddelovac)


def _rez(skupina, susedia):
    """Zo štyroch smerov ten, ktorý pretne najmenej hrán."""
    v_skupine = set(skupina)
    najlepsie = None
    for dx, dy in SMERY:
        zoradene = sorted(skupina, key=lambda u: (dx * susedia.xy[u][1]
                                                  + dy * susedia.xy[u][0], u))
        stred = len(zoradene) // 2
        prve = set(zoradene[:stred])
        rezy = sum(1 for u in prve for v in susedia[u]
                   if v in v_skupine and v not in prve)
        if najlepsie is None or rezy < najlepsie[0]:
            najlepsie = (rezy, zoradene, prve)
    _rezy, zoradene, prve = najlepsie
    if min(len(prve), len(zoradene) - len(prve)) < VYVAZENIE * len(zoradene):
        return [], [], []

    hranicne = [(u, v) for u in prve for v in susedia[u]
                if v in v_skupine and v not in prve]
    oddelovac = _pokry(hranicne)
    a = [u for u in zoradene if u in prve and u not in oddelovac]
    b = [u for u in zoradene if u not in prve and u not in oddelovac]
    return a, b, sorted(oddelovac)


def _pokry(hrany):
    """Vrcholový oddeľovač z prerezaných hrán – hladivo, po najhustejšom uzle."""
    stupen = {}
    for u, v in hrany:
        stupen[u] = stupen.get(u, 0) + 1
        stupen[v] = stupen.get(v, 0) + 1
    zvysok, von = list(hrany), set()
    while zvysok:
        u = max({x for h in zvysok for x in h}, key=lambda x: (stupen[x], -x))
        von.add(u)
        zvysok = [h for h in zvysok if u not in h]
    return von


class Susedia:
    """Susedia a súradnice pohromade – rez sa pýta oboje naraz."""

    def __init__(self, siet):
        # dĺžkový stupeň je na našej šírke o tretinu kratší; bez prepočtu by
        # rez „na 45°" nebol na 45°
        stred = (sum(lat for lat, _lon in siet.uzly.values())
                 / max(1, len(siet.uzly)) / 1e7)
        k = math.cos(math.radians(stred))
        self.xy = {u: (lat, lon * k) for u, (lat, lon) in siet.uzly.items()}
        self._s = siet.susedia()

    def __getitem__(self, u):
        return self._s[u]


def _komponenty(uzly, susedia):
    """Nesúvislé kusy siete sa delia zvlášť; rez cez dva ostrovy nie je rez."""
    videne, von = set(), []
    for start in sorted(uzly):
        if start in videne:
            continue
        kus, front = [], [start]
        videne.add(start)
        while front:
            u = front.pop()
            kus.append(u)
            for v in susedia[u]:
                if v not in videne:
                    videne.add(v)
                    front.append(v)
        von.append(sorted(kus))
    von.sort(key=len, reverse=True)
    return von


def _id(rank):
    raw = ";".join(f"{u}:{r}" for u, r in sorted(rank.items())).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True,
                    help="PBF CELÉHO stavaného územia – poradie počítané po "
                         "krajoch sa spojiť nedá")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nazov", default="",
                    help="čo je to za územie – ide do súboru s poradím")
    args = ap.parse_args()

    import network                                                # noqa: PLC0415

    t0 = time.time()
    siet = network.nacitaj(args.pbf)
    if not siet.uzly:
        print("::error::V PBF nie je ani jedna cesta, takže nie je čo "
              "usporiadať.", file=sys.stderr)
        return 1
    susedia = Susedia(siet)

    von = []
    for kus in _komponenty(siet.uzly, susedia):
        von.extend(poradie(kus, susedia))
    rank = {u: i for i, u in enumerate(von)}

    telo = {"id": f"{_id(rank):08x}", "nazov": args.nazov, "uzlov": len(rank),
            "hran": len(siet.hrany),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rank": rank}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(telo, f, ensure_ascii=False)
    print(f"Poradie {telo['id']}: {len(rank)} uzlov za "
          f"{time.time() - t0:.0f} s → {args.out} "
          f"({os.path.getsize(args.out) / 1048576:.1f} MB)")
    print("::notice::Toto poradie patrí do KAŽDÉHO archívu tohto behu. Kraj "
          "postavený proti inému poradiu sa s ostatnými spojiť nesmie – "
          "nesúlad vyzerá ako pokazená trasa, nie ako iný súbor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
