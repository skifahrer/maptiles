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

    # --- 5. prepínač sa musí dostať až k jobu ---
    #
    # TÁ ISTÁ TICHÁ CHYBA AKO PRI `rebuild` (viď `workers/lint/rebuild.py`):
    # prepínač je vo formulári, ale nedorazí k jobu – a vtedy sa NESTANE NIČ.
    # Beh je zelený, len graf nikde nie je a nikto nepovie prečo. Ciest, kde sa
    # môže prerušiť, je päť: formulár → `options.py` → výstup jobu `plan` →
    # `with:` volaného workflowu → `secrets`.
    opts_py = os.path.join(_WORKERS, "plan", "options.py")
    if os.path.exists(opts_py):
        opts = open(opts_py, encoding="utf-8").read()
        if '"navigation_area": (' not in opts:
            err("workers/plan/options.py",
                "voľba `navigation_area` v číselníku predvolieb nie je – bez "
                "nej `plan` nevydá `opt_navigation_area` a graf by sa staval "
                "na predvolenom rozsahu, nie na vypýtanom.")
        if '"--navigation"' not in opts:
            err("workers/plan/options.py",
                "`options.py` neprijíma `--navigation`, takže sa k nemu switch "
                "z formulára nedostane a `opt_navigation` bude vždy `false`.")
        # Starý zápis vo `options` musí PADNÚŤ, nie prejsť ako neznámy kľúč
        # (a už vôbec nie ako platná voľba, ktorú nikto nečíta).
        if '"navigation": "je switch' not in opts:
            err("workers/plan/options.py",
                "`navigation` nie je medzi presunutými kľúčmi (`NEPOUZIVANE`). "
                "Kto napíše `navigation=true` do `options`, čakal by graf – "
                "a mlčky by ho nedostal.")
        m = re.search(r'"navigation_area": \("([^"]+)"', opts)
        if m and m.group(1) not in areas:
            err("workers/plan/options.py",
                f"predvolený rozsah `{m.group(1)}` nie je v číselníku "
                f"({', '.join(sorted(areas))}).")

    build = os.path.join(".github", "workflows", "build-map.yml")
    if os.path.exists(build):
        txt = open(build, encoding="utf-8").read()
        with open(build, encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        on_b = wf.get("on", wf.get(True)) or {}
        inputs = ((on_b.get("workflow_dispatch") or {}).get("inputs") or {})
        nav = inputs.get("navigation")
        if not nav:
            err(".github/workflows/build-map.yml",
                "vo formulári nie je switch `navigation` – graf sa z Build map "
                "nedá zapnúť.")
        elif nav.get("type") != "boolean":
            err(".github/workflows/build-map.yml",
                f"switch `navigation` má `type: {nav.get('type')}`, čakám "
                f"`boolean` – inak to nie je odškrtávacie pole.")
        elif nav.get("default") not in (False, "false"):
            err(".github/workflows/build-map.yml",
                "switch `navigation` je predvolene ZAPNUTÝ. Graf je celoštátny, "
                "kým mapa je kraj – pri každom builde štýlu by to boli hodiny "
                "za výsledok, ktorý sa nezmenil. Ak to má tak byť, zmeň aj "
                "túto kontrolu a napíš prečo.")
        # Strop `workflow_dispatch` je 10 inputov a je SKUTOČNÝ (actionlint na
        # jedenástom spadne). Keby sa prekročil, GitHub workflow neprijme.
        if len(inputs) > 10:
            err(".github/workflows/build-map.yml",
                f"formulár má {len(inputs)} inputov, strop je 10. Ďalší "
                f"prepínač musí ísť do voľby `options` – a niečo odtiaľ von.")
        for potrebne, preco in (
                ("--navigation=", "podanie switchu do `options.py` (a musí byť "
                                  "na OBOCH miestach, kde sa volá: v jobe "
                                  "`settings` cez env a v jobe `plan`)"),
                ("opt_navigation:", "výstup jobu `plan` – bez neho je `if:` "
                                    "volajúceho jobu vždy nepravdivé"),
                ("opt_navigation_area:", "výstup jobu `plan` s rozsahom"),
                ("./.github/workflows/navigation.yml", "volanie workflowu"),
                ("needs.plan.outputs.opt_navigation_area", "podanie rozsahu "
                 "volanému workflowu – bez neho by staval predvolený rozsah, "
                 "nie ten vypýtaný")):
            if potrebne not in txt:
                err(".github/workflows/build-map.yml",
                    f"chýba `{potrebne}` ({preco}).")
        if "OPT_NAVIGATION:" not in txt:
            err(".github/workflows/build-map.yml",
                "job `settings` nedostáva `OPT_NAVIGATION`, takže vypíše "
                "formulár, v ktorom graf chýba – a s čím beh ide, má byť "
                "vidieť skôr, než sa začne počítať (pravidlo 4).")
        # `workflow_call` NEDEDÍ secrets – bez nich sa balík nemá kam nahrať
        # a job spadne až na konci, po celej stavbe grafu.
        m = re.search(r"\n  navigacia:\n(.*?)(?=\n  [a-z0-9_-]+:\n)", txt,
                      re.S)
        if m and "secrets: inherit" not in m.group(1):
            err(".github/workflows/build-map.yml",
                "job `navigacia` nemá `secrets: inherit` – `workflow_call` "
                "secrets nededí, takže by sa graf postavil (hodiny) a až potom "
                "by sa nemal kam nahrať.")

    # --- 6. volať sa to musí dať ---
    if os.path.exists(WORKFLOW):
        with open(WORKFLOW, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        on_ = doc.get("on", doc.get(True)) or {}
        if "workflow_call" not in on_:
            err(".github/workflows/navigation.yml",
                "workflow sa nedá zavolať (`workflow_call` chýba), takže "
                "`Build map` ho zapnúť nemôže.")

    # --- 7. formulár vs. číselník ---
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
    print("Navigačný graf: rozsahy majú vlastný uzol v katalógu, PBF sa nereže, "
          "graf sa overuje celý a formulár sedí s číselníkom.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
