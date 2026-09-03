#!/usr/bin/env python3
"""
Poradie krajov pre „Build map state" – ktoré regióny krajina má a v akom
poradí sa stavajú.

PREČO VLASTNÝ SKRIPT A NIE ZOZNAM V WORKFLOWE. Kraje sú v číselníku
(`workers/data/regions.json`), lebo ich pozná aj `publish-map.py` (cesta na
Drive), `plan` (PBF z osm.fr) aj katalóg. Napísať ich druhýkrát do workflowu
by znamenalo, že pribudnutý kraj sa postaví ručne, ale dávka o ňom nevie –
a nikto sa to z behu nedozvie, lebo dávka skončí zelená s o jeden kraj menej.

ČO JE KRAJ. Položka číselníka s `admin_level: 4` a `country` rovným krajine.
`admin_level: 2` sú samotné krajiny a rozsahy, ktoré mapou nie sú (mapa
sveta, navigačné grafy) – tie do dávky nepatria a spoznať ich podľa mena by
bolo pravidlo napísané v skripte namiesto v dátach.

PORADIE JE PORADIE ČÍSELNÍKA, nie abeceda. Číselník ide od západu na východ
(bratislavský → košický), takže dávka postupuje po mape a v zozname behov je
vidieť, kde je. Abeceda by to isté zamiešala bez úžitku.

Použitie:
    python3 workers/state/queue.py --kraje=slovensko    # kraje, po riadkoch
    python3 workers/state/queue.py --krajiny            # čo sa dá zadať
"""
import argparse
import json
import os
import sys

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data")
REGIONS = os.path.join(_DATA, "regions.json")
# Kraj je `admin_level: 4`. Konštanta, a nie číslo v podmienke: to isté číslo
# rozhoduje aj o tom, či má balík na Drive úroveň kraja (`publish-map.py`).
KRAJ_LEVEL = 4


def nacitaj():
    with open(REGIONS) as f:
        return json.load(f)


def kraje(regions, krajina):
    """Kľúče krajov danej krajiny v poradí číselníka."""
    return [k for k, v in regions.items()
            if v.get("country") == krajina
            and v.get("admin_level") == KRAJ_LEVEL]


def krajiny(regions):
    """Krajiny, ktoré nejaké kraje MAJÚ – teda tie, čo sa dajú zadať.

    Krajina bez krajov (mapa sveta) by vo formulári bola voľba, po ktorej
    dávka nemá čo spustiť; to je horšie než ju neponúknuť.
    """
    return [k for k, v in regions.items()
            if v.get("admin_level") != KRAJ_LEVEL and kraje(regions, k)]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kraje", default="", help="krajina – vypíš jej kraje")
    ap.add_argument("--krajiny", action="store_true",
                    help="vypíš krajiny, ktoré nejaké kraje majú")
    args = ap.parse_args()

    regions = nacitaj()
    if args.krajiny:
        print("\n".join(krajiny(regions)))
        return
    if not args.kraje:
        ap.error("zadaj --kraje=<krajina> alebo --krajiny")
    zoznam = kraje(regions, args.kraje)
    if not zoznam:
        # Tvrdá chyba, nie prázdny výstup: dávka by inak skončila zelená
        # a bez jediného postaveného kraja.
        print(f"::error::Krajina „{args.kraje}“ nemá v {REGIONS} ani jeden "
              f"kraj (`admin_level: {KRAJ_LEVEL}`). Zadať sa dá: "
              f"{', '.join(krajiny(regions)) or '(nič)'}.", file=sys.stderr)
        sys.exit(1)
    print("\n".join(zoznam))


if __name__ == "__main__":
    main()
