#!/usr/bin/env python3
"""
Navigačný graf: rozsah, jeho uzol v katalógu a to, čo sa v ňom NESMIE stratiť.

ŠTYRI TICHÉ VECI, na ktoré je táto kontrola:

  1. DVA ROZSAHY V JEDNOM UZLE KATALÓGU. `admin_level: 2` spraví z `country`
     v `regions.json` aj uzol v `maps.json`, takže keby `navigacia_slovensko`
     a `navigacia_slovensko_susedia` mali spoločné `country: navigacia`, druhý
     beh by položku prvého PREPÍSAL – balíky na Drive by ležali oba a katalóg
     by poznal len jeden. To isté rozhodnutie ako `svet_basic` (pravidlo 2:
     meno je sľub o rozsahu). Presne toto sa pri prvej verzii aj stalo.

  2. REZANÝ PBF. Graf sa nesmie stavať z výrezu: hrana, ktorej chýba druhý
     koniec, je slepá ulica a trasa cez ňu neprejde – ale graf sa postaví
     a beh zazelená. `pbf.sh` preto nesmie rezať.

  3. STRATENÝ `admins.sqlite`. Bez neho Valhalla nevie, v ktorej krajine hrana
     leží: nefunguje `country_crossing_penalty`, strana jazdy sa hádá
     a diaľničná známka po krajinách nemá na čom stáť. A nefunguje TICHO –
     trasa sa spočíta, len je iná. `graph.sh` ho musí kontrolovať.

  4b. GRAF KRAJA, KTORÝ MLČÍ O SVOJEJ HRANICI. Kraj sa stavia z REZANÉHO PBF
     (mapa je mapa kraja a navigácia je za ten istý kraj), takže trasa v ňom
     končí na hranici – a keď to `graf.json` nepovie, nedá sa to odlíšiť od
     pokazeného grafu. Rovnako musí platiť, že ten graf stavia ten istý
     skript a že sa do balíka `-linie.zip` (kam graf od spojenia balíkov
     patrí – k trasám a obmedzeniam, ktoré sú tá istá sieť) naozaj dostane.

  4. KRAJINA MIMO `vignettes.json`. Rozsah, ktorý pokrýva krajinu, o ktorej
     `vignettes.json` nevie, znamená, že sa v nej voľba `vignettes` nespýta
     na nič – a mlčanie sa nedá odlíšiť od „známku tam netreba".

A k tomu to, čo stráži aj `world.py`: zoznam vo formulári (`choice`) GitHub zo
súboru prečítať nevie, takže sa musí písať dvakrát – a keď sa rozíde, nový
rozsah sa jednoducho nedá vybrať.

Spustiť: `python3 workers/lint/navigation.py`
"""
import json
import os
import re
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

AREAS = os.path.join(_DATA, "routing-areas.json")
REGIONS = os.path.join(_DATA, "regions.json")
VIGNETTES = os.path.join(_DATA, "vignettes.json")
WORKFLOW = os.path.join(".github", "workflows", "navigation.yml")
# Druhý rozsah toho istého grafu: JEDEN KRAJ, a graf ide vedľa mapy toho kraja
# do balíka `-linie.zip`. Volá ho `build-map-region.yml` cez `workflow_call`
# (vlastný súbor, lebo ten je pri strope 128 KiB).
REGION_WORKFLOW = os.path.join(".github", "workflows", "navigation-region.yml")
BUILD_MAP = os.path.join(".github", "workflows", "build-map-region.yml")
PBF_SH = os.path.join(_WORKERS, "routing", "pbf.sh")
GRAPH_SH = os.path.join(_WORKERS, "routing", "graph.sh")

# Čo musí byť v balíku, aby sa v telefóne dalo naozaj navigovať. Zoznam je
# TU aj v `graph.sh`, a je to zámer: tam sa kontroluje BEH (súbor vznikol),
# tu sa kontroluje SKRIPT (kontrola z neho nezmizla).
POVINNE = ("valhalla_tiles.tar", "valhalla.json", "admins.sqlite",
           "timezones.sqlite")

bad = []


def err(path, msg):
    bad.append((path, msg))


def main():
    with open(AREAS, encoding="utf-8") as f:
        areas = json.load(f)["areas"]
    with open(REGIONS, encoding="utf-8") as f:
        regions = json.load(f)
    with open(VIGNETTES, encoding="utf-8") as f:
        countries = {k: v for k, v in json.load(f)["countries"].items()}

    rel_areas = "workers/data/routing-areas.json"
    rel_regions = "workers/data/regions.json"

    # --- 1. uzol v katalógu ---
    for key, area in areas.items():
        rk = area.get("region_key")
        if rk not in regions:
            err(rel_areas,
                f"rozsah `{key}` má `region_key: {rk}`, ktorý v `regions.json` "
                f"nie je – `publish-map.py` by z neho nevedel poskladať cestu "
                f"na Drive a balík by skončil v `ostatne/`.")
            continue
        r = regions[rk]
        if r.get("admin_level") != 2:
            err(rel_regions,
                f"`{rk}` má `admin_level: {r.get('admin_level')}`. Graf nie je "
                f"mapa kraja – s inou hodnotou by mu `publish-map.py` pridal "
                f"úroveň kraja, ktorá v ňom nie je.")
        if r.get("country") != rk:
            err(rel_regions,
                f"`{rk}` má `country: {r.get('country')}`, čo NIE JE jeho kľúč. "
                f"Pri `admin_level: 2` je `country` zároveň uzol v `maps.json`, "
                f"takže dva rozsahy s tým istým `country` si položku navzájom "
                f"PREPÍŠU: balíky na Drive ostanú oba, katalóg bude poznať "
                f"posledný. Daj `country: {rk}` – to isté ako `svet_basic`.")
        # --- 4. krajiny musia byť známe pri známkach ---
        for c in area.get("countries") or []:
            if c not in countries:
                err(rel_areas,
                    f"rozsah `{key}` pokrýva `{c}`, ale `vignettes.json` tú "
                    f"krajinu nepozná – voľba `vignettes` sa v nej nespýta na "
                    f"nič a mlčanie sa nedá odlíšiť od „známku tam netreba“.")
        if not area.get("pbf"):
            err(rel_areas, f"rozsah `{key}` nemá ani jeden PBF.")

    # --- 2., 3. skripty ---
    if os.path.exists(PBF_SH):
        pbf = open(PBF_SH, encoding="utf-8").read()
        # Komentáre preč – slovo „reže“ je v hlavičke práve preto, že sa NEREŽE.
        kod = re.sub(r"^[ \t]*#.*$", "", pbf, flags=re.M)
        for zle in ("osmium extract", "--polygon", "--bbox"):
            if zle in kod:
                err("workers/routing/pbf.sh",
                    f"skript reže PBF (`{zle}`). Graf sa z výrezu stavať "
                    f"nesmie: hrana, ktorej chýba druhý koniec, je slepá "
                    f"ulica a trasa cez ňu neprejde – graf sa pritom postaví "
                    f"a beh zazelená.")
        if "osmium merge" not in kod and any(
                len(a.get("pbf") or []) > 1 for a in areas.values()):
            err("workers/routing/pbf.sh",
                "číselník má rozsah s viacerými extraktmi, ale skript ich "
                "nezlieva `osmium merge`. Zreťaziť PBF sa nedá (každý má "
                "vlastnú hlavičku) a duplicitné uzly na hraniciach by z grafu "
                "spravili dve nespojené siete.")
    else:
        err("workers/routing/pbf.sh", "skript neexistuje.")

    if os.path.exists(GRAPH_SH):
        graph = open(GRAPH_SH, encoding="utf-8").read()
        for f in POVINNE:
            if f not in graph:
                err("workers/routing/graph.sh",
                    f"skript nekontroluje `{f}`. Obraz Valhally môže dobehnúť "
                    f"s nulou aj vtedy, keď ten súbor nevyrobil – a nekompletný "
                    f"graf sa prejaví ako „trasa sa nenašla“, teda ako chyba "
                    f"aplikácie, nie ako chyba buildu.")
        if "valhalla" not in graph or "--version" not in graph:
            err("workers/routing/graph.sh",
                "skript nezisťuje verziu Valhally. Graf a knižnica, ktorá ho "
                "čítá v telefóne, si musia sedieť; nesúlad verzií vyzerá ako "
                "pokazená trasa, nie ako nesúlad verzií.")
    else:
        err("workers/routing/graph.sh", "skript neexistuje.")

    # --- 5. graf kraja: existuje, stavia ho ten istý skript a POVIE,
    #        že trasa v ňom končí na hranici ---
    # Graf z REZANÉHO PBF je presne to, čo `pbf.sh` robiť nesmie (kontrola 2) –
    # tu je to zámer, lebo navigácia kraja je za ten istý kraj ako jeho mapa.
    # Preto to musí byť NAPÍSANÉ v balíku: bez toho sa „trasa cez hranicu
    # nejde" nedá odlíšiť od pokazeného grafu, a to je ten istý tichý omyl,
    # len z druhej strany.
    if os.path.exists(REGION_WORKFLOW):
        wtext = open(REGION_WORKFLOW, encoding="utf-8").read()
        if "workers/routing/graph.sh" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "graf kraja sa nestavia `workers/routing/graph.sh`. Druhý "
                "skript by bol druhá pravda o tom, ako sa graf stavia a čo sa "
                "v ňom kontroluje – a kontrola štyroch súborov vyššie by na "
                "neho nedosiahla.")
        if "name: navigacia-graf" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "graf sa neodkladá ako artefakt `navigacia-graf`. Do balíka "
                "sa dostane jedine cezeň – `site-*` sa zlieva do `_site` pred "
                "nahratím na Pages a graf tam nemá čo robiť.")
        # GRAF KRAJA STOJÍ NA PBF KRAJA – na tom istom, z akého je mapa.
        # Odkedy je to PBF rezané PRESNE na hranicu kraja
        # (`workers/plan/boundary.py`), je to zároveň jediné, čo drží
        # navigáciu „len za tento kraj": keby si job stiahol iný extrakt
        # (štátny, susedov), graf by ticho pokrýval viac než mapa nad ním
        # a `graf.json` by o sebe tvrdil `rozsah: region`.
        if "ROUTING_PBF: data/region.osm.pbf" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "graf kraja sa nestavia z `data/region.osm.pbf` "
                "(`ROUTING_PBF`). To PBF je rezané presne na hranicu kraja, "
                "takže je to jediné, čo drží navigáciu za ten istý kraj ako "
                "mapu – iný extrakt by graf ticho rozšíril za hranicu a "
                "`graf.json` by pritom hlásil `rozsah: region`.")
        if "name: pbf" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "job si nesťahuje artefakt `pbf` z prípravy, takže nemá "
                "z čoho graf postaviť – alebo si extrakt zháňa sám, čo je "
                "druhá pravda o tom, za aké územie navigácia je.")
        if os.path.exists(BUILD_MAP):
            bm = open(BUILD_MAP, encoding="utf-8").read()
            if "navigation-region.yml" not in bm:
                err(".github/workflows/build-map-region.yml",
                    "build mapy nevolá `navigation-region.yml`, takže sa "
                    "k mape kraja nepostaví graf – a nikto to nepovie: mapa "
                    "je v poriadku, len sa v nej nedá nikam doviezť a "
                    "balík `cesty` je o polovicu ľahší, než má byť.")
            if "name: navigacia-graf" not in bm:
                err(".github/workflows/build-map-region.yml",
                    "graf sa pri balení nesťahuje (`navigacia-graf`). Job ho "
                    "postaví, artefakt vznikne a do balíka sa nedostane – "
                    "presne ten druh tichého omylu, ktorý vidno až v telefóne.")

    else:
        err(".github/workflows/navigation-region.yml", "workflow neexistuje.")

    if os.path.exists(GRAPH_SH):
        graph = open(GRAPH_SH, encoding="utf-8").read()
        for f in POVINNE:
            if f not in graph:
                err("workers/routing/graph.sh",
                    f"skript nekontroluje `{f}`. Obraz Valhally môže dobehnúť "
                    f"s nulou aj vtedy, keď ten súbor nevyrobil – a nekompletný "
                    f"graf sa prejaví ako „trasa sa nenašla“, teda ako chyba "
                    f"aplikácie, nie ako chyba buildu.")
        if "valhalla" not in graph or "--version" not in graph:
            err("workers/routing/graph.sh",
                "skript nezisťuje verziu Valhally. Graf a knižnica, ktorá ho "
                "čítá v telefóne, si musia sedieť; nesúlad verzií vyzerá ako "
                "pokazená trasa, nie ako nesúlad verzií.")
    else:
        err("workers/routing/graph.sh", "skript neexistuje.")

    # --- 5. graf kraja: existuje, stavia ho ten istý skript a POVIE,
    #        že trasa v ňom končí na hranici ---
    # Graf z REZANÉHO PBF je presne to, čo `pbf.sh` robiť nesmie (kontrola 2) –
    # tu je to zámer, lebo navigácia kraja je za ten istý kraj ako jeho mapa.
    # Preto to musí byť NAPÍSANÉ v balíku: bez toho sa „trasa cez hranicu
    # nejde" nedá odlíšiť od pokazeného grafu, a to je ten istý tichý omyl,
    # len z druhej strany.
    if os.path.exists(REGION_WORKFLOW):
        wtext = open(REGION_WORKFLOW, encoding="utf-8").read()
        if "workers/routing/graph.sh" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "graf kraja sa nestavia `workers/routing/graph.sh`. Druhý "
                "skript by bol druhá pravda o tom, ako sa graf stavia a čo sa "
                "v ňom kontroluje – a kontrola štyroch súborov vyššie by na "
                "neho nedosiahla.")
        if "name: navigacia-graf" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "graf sa neodkladá ako artefakt `navigacia-graf`. Do balíka "
                "sa dostane jedine cezeň – `site-*` sa zlieva do `_site` pred "
                "nahratím na Pages a graf tam nemá čo robiť.")
        # GRAF KRAJA STOJÍ NA PBF KRAJA – na tom istom, z akého je mapa.
        # Odkedy je to PBF rezané PRESNE na hranicu kraja
        # (`workers/plan/boundary.py`), je to zároveň jediné, čo drží
        # navigáciu „len za tento kraj": keby si job stiahol iný extrakt
        # (štátny, susedov), graf by ticho pokrýval viac než mapa nad ním
        # a `graf.json` by o sebe tvrdil `rozsah: region`.
        if "ROUTING_PBF: data/region.osm.pbf" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "graf kraja sa nestavia z `data/region.osm.pbf` "
                "(`ROUTING_PBF`). To PBF je rezané presne na hranicu kraja, "
                "takže je to jediné, čo drží navigáciu za ten istý kraj ako "
                "mapu – iný extrakt by graf ticho rozšíril za hranicu a "
                "`graf.json` by pritom hlásil `rozsah: region`.")
        if "name: pbf" not in wtext:
            err(".github/workflows/navigation-region.yml",
                "job si nesťahuje artefakt `pbf` z prípravy, takže nemá "
                "z čoho graf postaviť – alebo si extrakt zháňa sám, čo je "
                "druhá pravda o tom, za aké územie navigácia je.")
        if os.path.exists(BUILD_MAP):
            bm = open(BUILD_MAP, encoding="utf-8").read()
            if "navigation-region.yml" not in bm:
                err(".github/workflows/build-map-region.yml",
                    "build mapy nevolá `navigation-region.yml`, takže sa "
                    "k mape kraja nepostaví graf – a nikto to nepovie: mapa "
                    "je v poriadku, len sa v nej nedá nikam doviezť a "
                    "balík `cesty` je o polovicu ľahší, než má byť.")
            if "name: navigacia-graf" not in bm:
                err(".github/workflows/build-map-region.yml",
                    "graf sa pri balení nesťahuje (`navigacia-graf`). Job ho "
                    "postaví, artefakt vznikne a do balíka sa nedostane – "
                    "presne ten druh tichého omylu, ktorý vidno až v telefóne.")

    else:
        err(".github/workflows/navigation-region.yml", "workflow neexistuje.")

    # --- 5b. graf má VLASTNÝ balík a v základnej mape ani v `cesty` nie je ---
    # Kým sa balil dovnútra mapy, bol argument „jednotky až desiatky MB proti
    # stovkám za dlaždice". Namerané: 170 až 190 MB grafu v 283 MB mape, čiže
    # dve tretiny „základnej mapy" bola sieť, po ktorej sa jazdí. Zo základnej
    # mapy je preto von a je to VLASTNÝ balík vedľa `cesty` – tá je kreslená
    # dopravná sieť v desiatkach MB, takže by z jedného balíka bolo deväť
    # desatín graf a kto chce sieť len vidieť, sťahoval by ho tak či tak.
    #
    # Odkedy zoznam balíkov drží číselník (`workers/data/packages.json`),
    # kontroluje sa on: balík `navigacia` v ňom musí byť a musí sa skladať
    # z priečinka `routing`, nie z výberu podľa mien (sú to štyri súbory,
    # ktoré si musia sedieť – prvý ďalší od Valhally by ticho vypadol a trasa
    # by „len nešla"). ČO v tom balíku naozaj skončí, overuje
    # `workers/lint/packaging.py` nad naozaj zabalenými ZIPmi.
    ciselnik = os.path.join(_WORKERS, "data", "packages.json")
    if os.path.exists(ciselnik):
        with open(ciselnik, encoding="utf-8") as f:
            baliky = {b["kluc"]: b for b in json.load(f).get("baliky") or []}
        nav = baliky.get("navigacia")
        if not nav:
            err("workers/data/packages.json",
                "balík `navigacia` v číselníku nie je – graf kraja sa postaví "
                "a nikam sa nenahrá, a katalóg o ňom nepovie nič, takže si ho "
                "appka nemá ako vypýtať.")
        elif nav.get("priecinok") != "routing":
            err("workers/data/packages.json",
                "balík `navigacia` sa neskladá z priečinka `routing`. Graf sú "
                "štyri súbory, ktoré si musia sedieť, plus `graf.json` – keby "
                "sa vyberali menami, prvý ďalší súbor od Valhally by z balíka "
                "ticho vypadol a trasa by „len nešla“.")
        cesty = baliky.get("cesty")
        if not cesty:
            err("workers/data/packages.json",
                "balík `cesty` v číselníku nie je. Bez neho ostane otázka "
                "„chcem siete, po ktorých sa dá cestovať, a nie zvyšok mapy“ "
                "bez odpovede – a graf je odpoveď na inú otázku.")
        elif "transport" not in (cesty.get("manifest") or []):
            err("workers/data/packages.json",
                "balík `cesty` neberie `transport` z manifestu. Bez dopravnej "
                "siete je to prázdny balík so sľubom v mene.")
        elif cesty.get("priecinok") == "routing":
            err("workers/data/packages.json",
                "balík `cesty` zase priberá graf. `cesty` je KRESLENÁ dopravná "
                "sieť (desiatky MB), graf je 170 až 190 MB – v jednom balíku "
                "by z neho bolo deväť desatín.")
    else:
        err("workers/data/packages.json", "číselník balíkov neexistuje.")

    if os.path.exists(GRAPH_SH):
        graph = open(GRAPH_SH, encoding="utf-8").read()
        if "hranica" not in graph:
            err("workers/routing/graph.sh",
                "`graf.json` nehovorí, kam trasa v tom grafe smie. Graf kraja "
                "je z REZANÉHO PBF, takže trasa v ňom končí na hranici – "
                "a mlčanie sa dá čítať ako pokazený graf, nie ako rozsah.")
        if "REGION_KEY" not in graph:
            err("workers/routing/graph.sh",
                "skript nepozná `REGION_KEY`, teda graf za jeden kraj. Build "
                "mapy by musel mať vlastný – dve pravdy o tom istom.")

    # --- 6. formulár vs. číselník ---
    if os.path.exists(WORKFLOW):
        with open(WORKFLOW, encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        on = wf.get("on", wf.get(True)) or {}
        inp = ((on.get("workflow_dispatch") or {}).get("inputs") or {})
        opts = set((inp.get("area") or {}).get("options") or [])
        if opts != set(areas):
            err(".github/workflows/navigation.yml",
                f"výber `area` vo formulári má {sorted(opts)}, číselník "
                f"{sorted(areas)}. `choice` GitHub zo súboru prečítať nevie, "
                f"takže sa to píše dvakrát – a rozsah, ktorý vo výbere nie je, "
                f"sa nedá vybrať.")
    else:
        err(".github/workflows/navigation.yml", "workflow neexistuje.")

    for path, msg in bad:
        print(f"::error file={path}::{msg}")
    if bad:
        print(f"\n{len(bad)} problém(ov) v navigačnom grafe.")
        return 1
    print("Navigačný graf: rozsahy majú vlastný uzol v katalógu, celoštátny "
          "PBF sa nereže, graf kraja o svojej hranici hovorí a má vlastný "
          "balík vedľa dopravnej siete, graf sa overuje celý a formulár sedí "
          "s číselníkom.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
