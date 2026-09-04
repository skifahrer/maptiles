#!/usr/bin/env python3
"""Vyrieši input `area` na bbox, kľúč a meno – na jednom mieste.

Potrebuje to `plan`, `check-dem`, `contours` aj mirror ÚGKK. Vstup je názov
pohoria z `workers/data/areas.json`, bbox `W,S,E,N`, alebo prázdno (celý
región); vždy sa pretne s bboxom regiónu.

`--test-km2` vyreže malý štvorec okolo stredu výrezu – kvôli rýchlosti ladenia.
Kľúč dostane príponu `_test4`, aby si testovací výsledok nesadol do cache ani
na asset ostrého behu.

Použitie:
    python3 workers/plan/area.py --region-bbox=W,S,E,N --area=vysoke_tatry
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

# stupeň dĺžky sa krát kosínus šírky – na 49° je to asi dve tretiny
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# koľko terénu sa počíta ešte za hranicou regiónu – dnes 0.
#
# Kým sa hranica brala z `.poly` osm.fr, bola zaokrúhlená a rozšírená, tak sa
# polygón nafukoval a mapy sa v tom páse prekrývali. Odkedy sa číta presne
# z OSM relácie, susedné kraje na seba nadväzujú samy od seba.
#
# Konštanta ostáva z dvoch dôvodov: `pad_bbox` ňou nafukuje okno pre vrstvy
# z DEM (`-cutline` v ňom nesmie vytŕčať von), a číslo sa nesie v menách
# uložených vrstiev, nech sklad nevráti tú starú, orezanú po inom.
BORDER_BUFFER_M = 0


def bbox_km2(w, s, e, n):
    return ((e - w) * M_PER_DEG_LON * math.cos(math.radians((s + n) / 2))
            * (n - s) * M_PER_DEG_LAT) / 1e6


def pad_bbox(bbox, meters):
    """Obdĺžnik zväčšený o `meters` na každú stranu (stupne podľa šírky)."""
    w, s, e, n = bbox
    dlat = meters / M_PER_DEG_LAT
    dlon = meters / (M_PER_DEG_LON * math.cos(math.radians((s + n) / 2)))
    return [w - dlon, s - dlat, e + dlon, n + dlat]


def test_square(bbox, km2, at=""):
    """Malý štvorec s plochou ~`km2` vnútri `bbox`.

    Keď by vyliezol von, posunie sa dovnútra – nie oreže: polovičný výrez by
    mal inú plochu, než akú si pýtal.
    """
    w, s, e, n = bbox
    clon = (w + e) / 2.0
    clat = (s + n) / 2.0
    if at.strip():
        parts = [float(v) for v in at.split(",")]
        if len(parts) != 2:
            raise ValueError(f"test_at musí byť `lon,lat`, nie „{at}“")
        clon, clat = parts

    strana_m = math.sqrt(km2 * 1e6)
    dlat = strana_m / M_PER_DEG_LAT / 2.0
    dlon = strana_m / (M_PER_DEG_LON * math.cos(math.radians(clat))) / 2.0

    # väčší štvorec než samotný výrez nemá zmysel dorábať
    if 2 * dlon >= (e - w) or 2 * dlat >= (n - s):
        return [w, s, e, n]

    clon = min(max(clon, w + dlon), e - dlon)
    clat = min(max(clat, s + dlat), n - dlat)
    return [clon - dlon, clat - dlat, clon + dlon, clat + dlat]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region-bbox", required=True)
    ap.add_argument("--area", default="")
    ap.add_argument("--areas", default="workers/data/areas.json")
    ap.add_argument("--test-km2", type=float, default=0.0,
                    help="testovací režim: vyrezať štvorec s približne toľkými "
                         "km² okolo stredu výrezu (0 = vypnuté)")
    ap.add_argument("--test-at", default="",
                    help="stred testovacieho štvorca ako `lon,lat` "
                         "(prázdne = stred výrezu)")
    ap.add_argument("--out", default="", help="kam zapísať (default stdout)")
    args = ap.parse_args()

    # okno pre vrstvy z DEM. `BORDER_BUFFER_M` je 0, takže je to presne bbox
    # regiónu a hranicu z neho vyreže `-cutline`. Volanie ostáva preto, že keby
    # sa presah zase zapol, okno sa musí zväčšiť spolu s ním.
    region = pad_bbox([float(v) for v in args.region_bbox.split(",")],
                      BORDER_BUFFER_M)
    raw = (args.area or "").strip()
    # vo formulári sa „celý región" nedá vyjadriť prázdnou položkou výberu
    if raw == "cely_region":
        raw = ""

    if not raw:
        key, name, bbox = "cely", "celý región", region
    elif "," in raw:
        # hash v kľúči, lebo kľúč ide do mien cache aj assetov: dva rôzne
        # vlastné výrezy sa pod spoločným „vyrez" prepisovali navzájom
        h = hashlib.sha1(raw.encode()).hexdigest()[:6]
        key, name = f"vyrez_{h}", f"vlastný výrez {raw}"
        bbox = [float(v) for v in raw.split(",")]
    else:
        areas = json.load(open(args.areas))
        if raw not in areas or raw.startswith("_"):
            known = ", ".join(k for k in areas if not k.startswith("_"))
            print(f"::error::Neznámy výrez '{raw}'. Známe výrezy "
                  f"({args.areas}): {known}. Alebo zadaj bbox W,S,E,N.",
                  file=sys.stderr)
            return 1
        key = re.sub(r"[^a-zA-Z0-9]", "_", raw)
        name = areas[raw]["name"]
        bbox = areas[raw]["bbox"]

    # prienik s regiónom – mimo neho nie sú ani dáta, ani mapa
    w, s = max(region[0], bbox[0]), max(region[1], bbox[1])
    e, n = min(region[2], bbox[2]), min(region[3], bbox[3])
    if e <= w or n <= s:
        print(f"::error::Výrez '{raw}' neleží v regióne ({args.region_bbox}) – "
              f"neprekrývajú sa. Vyber iný región alebo iný výrez.",
              file=sys.stderr)
        return 1

    out = []
    if args.test_km2 > 0:
        # celý výrez ide von tiež: obrázok „kde to je" potrebuje okolie
        out.append(f"full_bbox={w},{s},{e},{n}")
        out.append(f"full_km2={bbox_km2(w, s, e, n):.0f}")
        try:
            w, s, e, n = test_square([w, s, e, n], args.test_km2, args.test_at)
        except ValueError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        # do kľúča, nie len do mena: testovací výsledok sa nesmie tváriť ako
        # ostrý. `cely` je ale sentinel („žiadny výrez"), nie meno územia –
        # prípona by z neho spravila meno a prepla podobu výškového modelu.
        if key != "cely":
            key = f"{key}_test{args.test_km2:g}"
            if args.test_at.strip():
                key += "_" + hashlib.sha1(args.test_at.encode()).hexdigest()[:4]
        name = f"{name} – test {args.test_km2:g} km²"
        out.append("test=1")
        out.append(f"test_km2={args.test_km2:g}")

    km2 = bbox_km2(w, s, e, n)
    out += [f"key={key}", f"name={name}", f"bbox={w},{s},{e},{n}",
            f"km2={km2:.0f}", f"cells_1m={km2 * 1e6:.0f}",
            f"center={(w + e) / 2:.5f},{(s + n) / 2:.5f}"]
    text = "\n".join(out) + "\n"
    if args.out:
        with open(args.out, "a") as f:
            f.write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
