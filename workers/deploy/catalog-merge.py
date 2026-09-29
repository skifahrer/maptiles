#!/usr/bin/env python3
"""Zlej svoj zápis katalógu do toho, čo je medzitým vo vetve.

Trojcestne: čo tento beh oproti `--base` nezmenil, ostáva vetve. Bez toho
posledný zapisujúci job prepíše celý súbor a zmaže, čo pred sekundou zapísal
iný job toho istého behu.
"""
import argparse
import json
import sys


def zlej(zaklad, moje, ich):
    """`ich` doplnené o to, čo tento beh urobil oproti `zaklad`."""
    von = dict(ich)
    for kluc in set(zaklad) | set(moje):
        zo_zakladu, moj = zaklad.get(kluc), moje.get(kluc)
        if zo_zakladu == moj:
            continue
        if kluc not in moje:
            von.pop(kluc, None)
        elif isinstance(moj, dict) and isinstance(von.get(kluc), dict):
            von[kluc] = zlej(zo_zakladu if isinstance(zo_zakladu, dict) else {},
                             moj, von[kluc])
        else:
            von[kluc] = moj
    return von


def nacitaj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="katalóg pred zápisom")
    ap.add_argument("--mine", required=True, help="katalóg po zápise")
    ap.add_argument("--theirs", required=True, help="katalóg vo vetve")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        zaklad, moje, ich = (nacitaj(args.base), nacitaj(args.mine),
                             nacitaj(args.theirs))
    except (OSError, ValueError) as exc:
        print(f"::warning::Katalóg sa nedal zliať ({exc}) – beriem svoj zápis.")
        return 1
    if not all(isinstance(d, dict) for d in (zaklad, moje, ich)):
        print("::warning::Katalóg nie je objekt – beriem svoj zápis.")
        return 1
    von = zlej(zaklad, moje, ich)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(von, ensure_ascii=False, separators=(",", ":"),
                           sort_keys=True) + "\n")
    print("Katalóg zliaty s vetvou ✓" if von != moje
          else "Vetva sa medzitým nezmenila.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
