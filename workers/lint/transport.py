#!/usr/bin/env python3
"""
Dopravná sieť: filter pustí, čo schéma chce – a balík naozaj nesie sieť.

ŠTYRI TICHÉ VECI, na ktoré je táto kontrola:

  1. PREDFILTER A SCHÉMA SA ROZÍDU. Job `transport` číta PBF dvakrát: `osmium
     tags-filter` (workers/transport/filter.txt) a potom Planetiler
     (workers/transport/transport.yml). To isté rozhodnutie je teda na dvoch
     miestach a keď sa rozídu, Planetiler dostane PBF, v ktorom ten tag už NIE
     JE – dlaždice vzniknú, beh zazelená a tá trieda v sieti len nie je. To
     isté, čo pri obmedzeniach na ceste (`workers/lint/roads.py`).

  2. ZO SIETE VYPADNE CELÁ RODINA. Vrstva sľubuje „všetko, po čom sa dá
     cestovať". Keby z nej vypadli železnice alebo trajekty, balík by sa volal
     rovnako, vážil by menej a nikto by sa nedozvedel, že v ňom chýba spôsob
     dopravy – meno je sľub o rozsahu (pravidlo 2). Kontroluje sa preto, že
     schéma naozaj berie všetky štyri rodiny: `highway`, `railway`, `route`
     (trajekt) a `aerialway`.

  3. DO SIETE SA VRÁTI, PO ČOM SA ÍSŤ NEDÁ. `railway=abandoned`, `disused`,
     `razed`, `construction`, `proposed` a `platform` sú v OSM koľajnice,
     ktoré tam nie sú (alebo nie sú trať) – v sieti nemajú čo robiť a ich
     pridanie by nespadlo na ničom.

  4. `class` A `druh` PRESTANÚ BYŤ Z TOHO, ČÍM SA BLOK TRAFIL. Sú to
     `match_value` a `match_key` Planetileru; keby ich niekto vypísal ručne
     pri každom bloku, bola by to druhá kópia zoznamu tried z `include_when`
     a rozišla by sa s ním pri prvej pridanej triede.

Spustiť: `python3 workers/lint/transport.py`
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "transport", "transport.yml")
FILTER = os.path.join(_WORKERS, "transport", "filter.txt")
SUBORY = os.path.join(_WORKERS, "deploy", "subory.py")

# Rodiny dopravy, ktoré vrstva SĽUBUJE. Kľúč → čím to je v OSM.
RODINY = {
    "highway": "cesty (od diaľnice po schody)",
    "railway": "železnice, električky a metro",
    "route": "trajekty a prievozy",
    "aerialway": "lanovky a vleky",
}

# Hodnoty `railway`, po ktorých sa ísť NEDÁ – v sieti nemajú čo robiť.
NEPREJAZDNE = {"abandoned", "disused", "razed", "construction", "proposed",
               "platform", "razed", "dismantled"}

bad = []


def err(msg):
    bad.append(msg)


def filter_keys(path):
    """Holé kľúče z `osmium tags-filter --expressions` (bez `w/`, `nwr/`)."""
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "/" in line.split("=", 1)[0]:
                line = line.split("/", 1)[1]
            out.add(line.split("=", 1)[0].strip())
    return out


def main():
    for path in (SCHEMA, FILTER, SUBORY):
        if not os.path.exists(path):
            print(f"::error::{path} neexistuje.")
            return 1

    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    vrstvy = schema.get("layers") or []
    bloky = [b for v in vrstvy for b in (v.get("features") or [])]
    if not bloky:
        err(f"{SCHEMA}: schéma nemá ani jeden blok – vrstva by bola prázdna.")
        return hotovo()

    # ---- 1. predfilter pustí, čo schéma chce ----
    pusta = filter_keys(FILTER)
    chce = set()
    for b in bloky:
        chce |= set((b.get("include_when") or {}).keys())
    chyba = sorted(chce - pusta)
    if chyba:
        err(f"{FILTER}: schéma sa pýta na {', '.join(chyba)}, ale predfilter "
            f"to nepúšťa (pozná {', '.join(sorted(pusta))}). Planetiler by "
            f"dostal PBF, v ktorom ten tag už nie je – dlaždice by vznikli, "
            f"beh by bol zelený a tá časť siete by v nich jednoducho nebola.")

    # ---- 2. všetky štyri rodiny dopravy sú v sieti ----
    for kluc, popis in RODINY.items():
        if kluc not in chce:
            err(f"{SCHEMA}: v sieti nie sú {popis} (`{kluc}`). Vrstva sľubuje "
                f"„všetko, po čom sa dá cestovať“ – balík by sa volal rovnako, "
                f"vážil menej a nikto by sa nedozvedel, že v ňom chýba celý "
                f"spôsob dopravy.")

    # ---- 3. neprejazdné koľajnice v sieti nie sú ----
    for b in bloky:
        hodnoty = (b.get("include_when") or {}).get("railway")
        if not hodnoty:
            continue
        if not isinstance(hodnoty, list):
            hodnoty = [hodnoty]
        zle = sorted(set(map(str, hodnoty)) & NEPREJAZDNE)
        if zle:
            err(f"{SCHEMA}: v sieti je `railway={', '.join(zle)}` – po tom sa "
                f"ísť nedá (zrušená alebo rozobraná trať, nástupište). Vrstva "
                f"je „po čom sa dá cestovať“, nie „čo v OSM má koľajnice“.")

    # ---- 4. `class` a `druh` sú z toho, čím sa blok trafil ----
    for i, b in enumerate(bloky, start=1):
        atr = {a.get("key"): a for a in (b.get("attributes") or [])
               if isinstance(a, dict)}
        for kluc, typ in (("class", "match_value"), ("druh", "match_key")):
            a = atr.get(kluc)
            if a is None:
                err(f"{SCHEMA}: blok {i} nedáva `{kluc}`. Bez neho sa v sieti "
                    f"nedá povedať, čo tá čiara je.")
            elif a.get("type") != typ:
                err(f"{SCHEMA}: blok {i} má `{kluc}` inak než `type: {typ}` – "
                    f"vypísaný ručne je to druhá kópia zoznamu tried "
                    f"z `include_when` a rozíde sa s ním pri prvej pridanej "
                    f"triede.")

    # ---- 5. vrstva sa naozaj dostane do balíka `linie` ----
    # Postaviť ju a nezabaliť je presne ten tichý omyl, pre ktorý balík
    # existuje: `-linie.zip` by vážil desiatky kB namiesto desiatok MB a na
    # ničom by to nebolo vidieť. (`workers/lint/packaging.py` overuje to isté
    # nad NAOZAJ zabalenými ZIPmi; tu je to lacná poistka pri každom pushi.)
    with open(SUBORY, encoding="utf-8") as f:
        sub = f.read()
    if "-transport.pmtiles" not in sub:
        err(f"{SUBORY}: `-transport.pmtiles` sa do žiadneho balíka neberie. "
            f"Vrstva by sa postavila, nahrala na Pages a do balíka `linie` by "
            f"sa nedostala – ten by sľuboval dopravnú sieť a niesol dve "
            f"pomocné vrstvy.")
    return hotovo()


def hotovo():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problém(ov) v dopravnej sieti.")
        return 1
    print("Dopravná sieť: predfilter pustí, čo schéma chce, v sieti sú cesty, "
          "železnice, trajekty aj lanovky, neprejazdné koľajnice v nej nie sú "
          "a `class` s `druh` idú z toho, čím sa blok trafil.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
