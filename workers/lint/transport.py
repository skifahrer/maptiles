#!/usr/bin/env python3
"""
Dopravná sieť: filter pustí, čo schéma chce – a balík naozaj nesie sieť.

ŠESŤ TICHÝCH VECÍ, na ktoré je táto kontrola:

  1. PREDFILTER A SCHÉMA SA ROZÍDU. Job `transport` číta PBF dvakrát: `osmium
     tags-filter` (workers/transport/filter.txt) a potom Planetiler
     (workers/transport/transport.yml). To isté rozhodnutie je teda na dvoch
     miestach a keď sa rozídu, Planetiler dostane PBF, v ktorom ten tag už NIE
     JE – dlaždice vzniknú, beh zazelená a tá trieda v sieti len nie je. To
     isté, čo pri krajinných prvkoch (`workers/lint/features.py`).

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

  4. ZO SIETE TICHO VYPADNE TRIEDA. `include_when` je biela listina, takže
     trieda, ktorá v nej nie je, sa do dlaždíc nedostane a nepovie o tom nič.

  5. OBMEDZENIA NA CESTE Z NEJ VYPADNÚ. Výška podjazdu, šírka, hmotnosť
     a rýchlosť mali chvíľu vlastnú vrstvu (`-roads.pmtiles`) a sú tu preto,
     že boli atribútmi tých istých ciest. Keby zmizli, „obmedzenia sú
     v balíku `cesty`“ by prestalo platiť a nikto by to nezbadal: sieť sa
     nakreslí rovnako, len bez nich. A HODNOTY MUSIA OSTAŤ REŤAZCOM –
     `tag_mappings` s `double` z „12'6\"" spraví 12 metrov TICHO (rozpis
     v hlavičke schémy).

  6. `class` A `druh` PRESTANÚ BYŤ Z TOHO, ČÍM SA BLOK TRAFIL. Sú to
     `match_value` a `match_key` Planetileru; keby ich niekto vypísal ručne
     pri každom bloku, bola by to druhá kópia zoznamu tried z `include_when`
     a rozišla by sa s ním pri prvej pridanej triede.

Spustiť: `python3 workers/lint/transport.py`
"""
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "transport", "transport.yml")
FILTER = os.path.join(_WORKERS, "transport", "filter.txt")
CISELNIK = os.path.join(_WORKERS, "data", "packages.json")

# Rodiny dopravy, ktoré vrstva SĽUBUJE. Kľúč → čím to je v OSM.
RODINY = {
    "highway": "cesty (od diaľnice po schody)",
    "railway": "železnice, električky a metro",
    "route": "trajekty a prievozy",
    "aerialway": "lanovky a vleky",
}

# Obmedzenia na ceste, ktoré sú odteraz atribútmi siete (mali vlastnú vrstvu).
# Kľúč → čo sa stane, keď vypadne.
OBMEDZENIA = {
    "maxheight": "výška podjazdu",
    "maxheight_physical": "nameraná výška podjazdu, keď tabuľa chýba",
    "maxwidth": "šírka",
    "maxweight": "hmotnosť",
    "maxspeed": "maximálna rýchlosť",
    "lanes": "počet jazdných pruhov",
    "width": "šírka cesty",
    "incline": "stúpanie",
}

# Tie z nich, ktoré NESMÚ byť číslom: hodnota nesie jednotku (`3.8 m`,
# `12'6"`, `50 mph`) a Planetiler by z nej vzal číslo zo začiatku a zvyšok
# zahodil – TICHO, s platnou dlaždicou a zeleným behom.
RETAZCE = {"maxheight", "maxheight_physical", "maxwidth", "maxweight",
           "maxspeed", "width", "incline"}

# Hodnoty `railway`, po ktorých sa ísť NEDÁ – v sieti nemajú čo robiť.
NEPREJAZDNE = {"abandoned", "disused", "razed", "construction", "proposed",
               "platform", "razed", "dismantled"}

# Triedy, ktoré vrstva sľubuje; chýba tu, po čom sa ísť nedá a plochy s bodmi.
PREJAZDNE = {
    "highway": {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
        "tertiary_link", "unclassified", "residential", "living_street",
        "pedestrian", "road", "busway", "bus_guideway", "escape", "raceway",
        "track", "path", "footway", "cycleway", "bridleway", "steps",
        "corridor", "via_ferrata", "elevator", "ladder", "service",
    },
    "railway": {
        "rail", "narrow_gauge", "light_rail", "subway", "tram", "monorail",
        "funicular", "preserved", "miniature",
    },
    "route": {"ferry"},
    "aerialway": {
        "cable_car", "gondola", "mixed_lift", "chair_lift", "drag_lift",
        "t-bar", "j-bar", "platter", "rope_tow", "magic_carpet", "zip_line",
        "goods",
    },
}

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
    for path in (SCHEMA, FILTER, CISELNIK):
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

    # ---- 4. sľúbené triedy sú naozaj v schéme ----
    v_scheme = {}
    for b in bloky:
        for kluc, hodnoty in (b.get("include_when") or {}).items():
            if not isinstance(hodnoty, list):
                hodnoty = [hodnoty]
            v_scheme.setdefault(kluc, set()).update(map(str, hodnoty))
    for kluc, sluby in PREJAZDNE.items():
        chyba = sorted(sluby - v_scheme.get(kluc, set()))
        if chyba:
            err(f"{SCHEMA}: v sieti nie je `{kluc}=" + ", ".join(chyba) +
                "`. `include_when` je biela listina, takže tá trieda sa do "
                "dlaždíc nedostane – filter ju pustí, schéma zahodí, balík je "
                "len o niečo menší a beh zelený.")

    # ---- 5. obmedzenia na ceste sú atribútmi siete a sú reťazcom ----
    tag_mappings = schema.get("tag_mappings") or {}
    for i, b in enumerate(bloky, start=1):
        # Len cestné bloky – `maxheight` na lanovke ani na trajekte nie je
        # a vyžadovať ho tam by znamenalo atribút, ktorý nikdy nevznikne.
        if "highway" not in (b.get("include_when") or {}):
            continue
        atr = {a.get("key") for a in (b.get("attributes") or [])
               if isinstance(a, dict)}
        chyba = sorted(set(OBMEDZENIA) - atr)
        if chyba:
            err(f"{SCHEMA}: cestný blok {i} nenesie "
                f"{', '.join(f'`{k}` ({OBMEDZENIA[k]})' for k in chyba)}. "
                f"Obmedzenia na ceste vlastnú vrstvu UŽ NEMAJÚ – sú atribútmi "
                f"tejto siete, takže keď vypadnú odtiaľto, nie sú nikde. "
                f"Sieť sa pritom nakreslí rovnako a beh bude zelený.")
    for kluc in sorted(RETAZCE):
        if kluc in tag_mappings:
            err(f"{SCHEMA}: `{kluc}` je v `tag_mappings` ako "
                f"`{tag_mappings[kluc]}`. Tá hodnota nesie v OSM jednotku "
                f"(`3.8 m`, `12'6\"`, `50 mph`) a Planetiler z nej vezme "
                f"číslo zo začiatku a zvyšok zahodí – z 3,8 m je 12 m a "
                f"nespadne pri tom nič. Nechaj ju reťazcom.")

    # ---- 6. `class` a `druh` sú z toho, čím sa blok trafil ----
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

    # ---- 7. vrstva sa naozaj dostane do balíka `cesty` ----
    # Postaviť ju a nezabaliť je presne ten tichý omyl, pre ktorý balík
    # existuje: `-cesty.zip` by vážil desiatky kB namiesto desiatok MB a na
    # ničom by to nebolo vidieť. Balíky drží číselník, tak sa pozeráme doňho.
    # (`workers/lint/packaging.py` overuje to isté nad NAOZAJ zabalenými
    # ZIPmi; tu je to lacná poistka pri každom pushi.)
    with open(CISELNIK, encoding="utf-8") as f:
        baliky = {b["kluc"]: b for b in json.load(f).get("baliky") or []}
    cesty = baliky.get("cesty") or {}
    if "transport" not in (cesty.get("manifest") or []) or \
            "-transport.pmtiles" not in (cesty.get("pripony") or []):
        err(f"{CISELNIK}: balík `cesty` neberie dopravnú sieť (`transport` "
            f"v `manifest`, `-transport.pmtiles` v `pripony`). Vrstva by sa "
            f"postavila, nahrala na Pages a do balíka by sa nedostala – ten "
            f"by sľuboval dopravnú sieť a bol by prázdny.")
    return hotovo()


def hotovo():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problém(ov) v dopravnej sieti.")
        return 1
    print("Dopravná sieť: predfilter pustí, čo schéma chce, v sieti sú cesty, "
          "železnice, trajekty aj lanovky, každá sľúbená trieda je v schéme, "
          "neprejazdné koľajnice v nej nie sú, "
          "obmedzenia na ceste v nej sú a ostali reťazcom, `class` s `druh` "
          "idú z toho, čím sa blok trafil, a balík `cesty` ju naozaj nesie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
