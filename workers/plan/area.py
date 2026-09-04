#!/usr/bin/env python3
"""
Vyrieši input `area` na bbox, kľúč a meno – na jednom mieste.

Potrebuje to `plan` (aby vedel, čo sa má zrkadliť), `check-dem` (aby vedel,
čo hľadať v releasi), `contours` (aby vedel, čo počítať) aj mirror ÚGKK.
Kým to bolo napísané v shelli vnútri jedného kroku, nedalo sa to zdieľať.

Vstup je buď názov pohoria z workers/data/areas.json, alebo bbox `W,S,E,N`,
alebo prázdno (= celý región). Vždy sa pretne s bboxom regiónu: mimo neho
nie sú ani dáta, ani mapa.

TESTOVACÍ REŽIM (`--test-km2`): z výrezu sa vyreže malý štvorec okolo jeho
stredu. Zmysel je jediný – rýchlosť ladenia. Skaly, vrstevnice aj tieňovanie
na celom pohorí sú desiatky minút, na 4 km² sú to jednotky minút,
takže sa dá prah alebo interval otestovať za jeden beh a nie za jeden obed.
Kľúč dostane príponu `_test4`, aby si testovací výsledok nikdy nesadol do
tej istej cache ani na ten istý asset ako ostrý.

Použitie:
    python3 workers/plan/area.py --region-bbox=W,S,E,N --area=vysoke_tatry
    → key=…, name=…, bbox=…, km2=… na stdout vo formáte key=value
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

# Koľko metrov je jeden stupeň. Zemepisná dĺžka sa krát kosínus šírky –
# na 49° je stupeň dĺžky len asi dve tretiny stupňa šírky.
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# KOĽKO TERÉNU SA POČÍTA EŠTE ZA HRANICOU REGIÓNU – dnes 0.
#
# PREČO 0. Kým sa hranica kraja brala z `.poly` osm.fr, bola zaokrúhlená na
# ~550 m a okolo hranice rozšírená, takže dve susedné mapy na seba nemuseli
# nadväzovať; riešilo sa to tým, že sa polygón NAFÚKOL o 2 500 m von a mapy sa
# v tom páse prekrývali. Odkedy sa hranica číta presne z OSM relácie
# (`workers/plan/boundary.py`), je prekryv zbytočný: susedné kraje zdieľajú tie
# isté cesty hranice, takže na seba nadväzujú samy od seba – a nafúknutie by
# už len robilo presne to, čomu sa vyhýbame, teda mapu, vrstevnice, skaly aj
# tieňovanie kilometre vnútri susedného kraja a za štátnou hranicou.
#
# PREČO TU TÁ KONŠTANTA VÔBEC OSTÁVA. Sú to dve veci naraz:
#   * `pad_bbox` ňou nafukuje OKNO, z ktorého sa čítajú vrstvy z výškového
#     modelu (`dem_bbox`). Pri `area: cely_region` je to bbox z
#     `workers/data/regions.json`, teda tesný obdĺžnik okolo polygónu – a
#     `-cutline` v ňom nesmie vytŕčať von z okna. S 0 je okno presne ten
#     obdĺžnik a to je správne; keby sa raz presah zase zapol, musí sa okno
#     zväčšiť s ním, inak by presah na DEM vrstvách nebolo vidieť.
#   * číslo sa nesie v MENÁCH uložených vrstiev (tieňovanie, skaly), aby po
#     jeho zmene nevrátil sklad tú starú, orezanú po inom – stráži to
#     `workers/lint/border-overlap.py`.
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

    Stred je stred výrezu, ak `at` nehovorí inak (`lon,lat`). Keď by štvorec
    vyliezol von, posunie sa dovnútra – nie oreže: polovičný testovací výrez
    by mal inú plochu než akú si pýtal a čísla z behu by neplatili.
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

    # Väčší štvorec než samotný výrez nemá zmysel dorábať – vtedy je testovací
    # výrez celý výrez a je to v poriadku.
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

    # OKNO PRE VRSTVY Z DEM. `BORDER_BUFFER_M` je dnes 0, takže je to presne
    # bbox regiónu a hranicu z neho vyreže až `-cutline` (rozpis pri tej
    # konštante). Volanie tu ostáva preto, že keby sa presah za hranicu raz
    # zase zapol, musí sa okno zväčšiť SPOLU s ním – inak by `-cutline`
    # siahal ďalej, než kam okno vôbec siaha, a na DEM vrstvách by presah
    # nebolo vidieť.
    region = pad_bbox([float(v) for v in args.region_bbox.split(",")],
                      BORDER_BUFFER_M)
    raw = (args.area or "").strip()
    # Vo formulári sa „celý región" nedá vyjadriť prázdnou položkou výberu,
    # tak má vlastný názov. Tu je to to isté ako prázdno.
    if raw == "cely_region":
        raw = ""

    if not raw:
        key, name, bbox = "cely", "celý región", region
    elif "," in raw:
        # Hash v kľúči, lebo kľúč ide do mien cache aj assetov: dva rôzne
        # vlastné výrezy sa pod spoločným „vyrez" prepisovali navzájom.
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

    # Prienik s regiónom – mimo neho nie sú ani dáta, ani mapa.
    w, s = max(region[0], bbox[0]), max(region[1], bbox[1])
    e, n = min(region[2], bbox[2]), min(region[3], bbox[3])
    if e <= w or n <= s:
        print(f"::error::Výrez '{raw}' neleží v regióne ({args.region_bbox}) – "
              f"neprekrývajú sa. Vyber iný región alebo iný výrez.",
              file=sys.stderr)
        return 1

    out = []
    if args.test_km2 > 0:
        # Celý výrez ide von tiež: obrázok „kde to je" potrebuje okolie,
        # inak je to štvorec bez kontextu.
        out.append(f"full_bbox={w},{s},{e},{n}")
        out.append(f"full_km2={bbox_km2(w, s, e, n):.0f}")
        try:
            w, s, e, n = test_square([w, s, e, n], args.test_km2, args.test_at)
        except ValueError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        # Do kľúča, nie len do mena: kľúč je v menách cache aj assetov
        # a testovací výsledok sa nesmie tváriť ako ostrý.
        #
        # `cely` je ale SENTINEL („žiadny výrez, ber celý región"), nie meno
        # územia. Prípona by z neho spravila meno – a tým by sa prepla podoba
        # výškového modelu: `dem-target.py` dáva na kľúč `cely` dlaždice, na
        # čokoľvek iné výrez v plnom rozlíšení. Testovací beh by tak počítal
        # z 1 m modelu to, čo ostrý počíta z 5 m dlaždíc, a nepreveril by
        # presne tú cestu, kvôli ktorej sa spúšťa. Kolízia tu nehrozí:
        # dlaždice sú pomenované podľa stupňov a kľúč regiónu (z ktorého sa
        # robia mená cache a assetov) príponu `_test4` nesie tak či tak.
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
