#!/usr/bin/env python3
"""
Číselník balíkov – jedna odpoveď na „čo sa publikuje" pre celý repozitár.

Zoznam samotný je v `workers/data/packages.json` (dáta, nie kód, lebo ho číta
aj aplikácia cez `maps.json`); tento modul je len prístup k nemu a odpovede,
ktoré sa z neho odvodzujú:

    zoznam()          balíky v poradí, v akom ich vidí človek
    balik(kluc)       jeden, alebo tvrdý pád s tým, čo sa dá zadať
    kluce()           len kľúče
    zrusene()         balíky, ktoré UŽ NIE SÚ – ich starý súbor sa maže
    pre_katalog()     `{kľúč: {app, symbol, popis}}` do `maps.json`

PREČO SA TO NEČÍTA PRIAMO. Súbor sa načíta RAZ (`_CACHE`) a chyba v ňom padá
s vetou, ktorá povie, kde sa opravuje – volajúci sú štyria (packer, súbory
balíkov, štafeta krajiny a kontroly) a štyri kópie `json.load` s vlastným
`except` by boli štyri rôzne hlášky o tom istom preklepe.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(os.path.dirname(_HERE), "data")
CISELNIK = os.path.join(_DATA, "packages.json")

_CACHE = None


def _nacitaj():
    global _CACHE
    if _CACHE is None:
        with open(CISELNIK, encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


def zoznam():
    """Balíky v poradí zo súboru – to je poradie, v akom ich vidí človek."""
    return list(_nacitaj().get("baliky") or [])


def kluce():
    return [b["kluc"] for b in zoznam()]


def balik(kluc):
    for b in zoznam():
        if b["kluc"] == kluc:
            return b
    raise SystemExit(f"::error::Balík `{kluc}` v {os.path.relpath(CISELNIK)} "
                     f"nie je. Sú tam: {', '.join(kluce())}.")


def zrusene():
    """Balíky, ktoré už nikto nevyrába – starý súbor sa na Drive maže."""
    return tuple(_nacitaj().get("zrusene") or ())


def regenerovatelne():
    """`{kľúč regenerovania: balík}` – čo sa dá postaviť bez celej mapy."""
    return {b["regeneruj"]: b for b in zoznam() if b.get("regeneruj")}


def pre_katalog():
    """Meno a značka každého balíka do `maps.json`.

    Aby appka vedela pomenovať a nakresliť aj balík, ktorý ešte nepozná –
    jej vlastná tabuľka je záloha pre staršie katalógy, nie jediný zdroj.
    """
    return {b["kluc"]: {"app": b["app"], "symbol": b["symbol"],
                        "popis": b["popis"]}
            for b in zoznam()}


def main():
    """`python3 workers/deploy/baliky.py [--kluce|--json]` – na pozretie."""
    if "--kluce" in sys.argv:
        print("\n".join(kluce()))
    elif "--regeneruj" in sys.argv:
        print("\n".join(regenerovatelne()))
    else:
        for b in zoznam():
            print(f"{b['kluc']:<18} {b['app']:<22} {b['symbol']:<32} {b['popis']}")


if __name__ == "__main__":
    main()
