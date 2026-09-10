#!/usr/bin/env python3
"""Navigácia: rozsah, jeho uzol v katalógu a čo sa v nej nesmie stratiť.

Dve rôzne veci pod jedným menom, tak sú tu obe:

  * SMEROVACIA SIEŤ KRAJA (`<kraj>-routing.pmtiles`, balík `navigacia`) – to,
    čo ide do telefónu; rozpis v `docs/routing-tiles.md`;
  * GRAF VALHALLY nad celým štátom (`navigation.yml`) – referenčná stavba,
    proti ktorej sa nový motor krížom kontroluje. Po krajoch sa už nestavia.

Tiché veci:
  1. dva rozsahy v jednom uzle katalógu – druhý beh by položku prvého
     prepísal a katalóg by poznal len jeden z dvoch balíkov na Drive;
  2. celoštátny graf sa nesmie stavať z rezaného PBF: hrana bez druhého konca
     je slepá ulica, ale graf sa postaví a beh zazelená;
  3. bez `admins.sqlite` Valhalla nevie, v ktorej krajine hrana leží;
  4. rozsah pokrývajúci krajinu mimo `vignettes.json` sa na známku nespýta;
  5. sieť kraja musí stáť na PBF mapy, mať vlastný balík a byť v manifeste;
  6. poradie uzlov: kľúč cache musí na oboch stranách znieť rovnako, inak
     archívy ticho a navždy chodia bez neho;
  7. formulár GitHub zoznam zo súboru prečítať nevie, takže sa píše dvakrát.
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
CISELNIK = os.path.join(_DATA, "packages.json")
WORKFLOW = os.path.join(".github", "workflows", "navigation.yml")
ORDER_WORKFLOW = os.path.join(".github", "workflows", "routing-order.yml")
REGION_WORKFLOW = os.path.join(".github", "workflows", "navigation-region.yml")
BUILD_MAP = os.path.join(".github", "workflows", "build-map-region.yml")
SITE_SH = os.path.join(_WORKERS, "deploy", "site.sh")
PBF_SH = os.path.join(_WORKERS, "routing", "pbf.sh")
GRAPH_SH = os.path.join(_WORKERS, "routing", "graph.sh")
BUILD_SH = os.path.join(_WORKERS, "routing", "build.sh")

# zoznam je tu aj v graph.sh zámerne: tam sa kontroluje beh (súbor vznikol),
# tu skript (kontrola z neho nezmizla)
POVINNE = ("valhalla_tiles.tar", "valhalla.json", "admins.sqlite",
           "timezones.sqlite")

bad = []


def err(path, msg):
    bad.append((path, msg))


def celostatny_graf(areas, regions, countries):
    """Valhalla nad celým štátom – referenčná stavba, ktorá ostáva."""
    rel_areas = "workers/data/routing-areas.json"
    rel_regions = "workers/data/regions.json"

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
        for c in area.get("countries") or []:
            if c not in countries:
                err(rel_areas,
                    f"rozsah `{key}` pokrýva `{c}`, ale `vignettes.json` tú "
                    f"krajinu nepozná – voľba `vignettes` sa v nej nespýta na "
                    f"nič a mlčanie sa nedá odlíšiť od „známku tam netreba“.")
        if not area.get("pbf"):
            err(rel_areas, f"rozsah `{key}` nemá ani jeden PBF.")

    if os.path.exists(PBF_SH):
        pbf = open(PBF_SH, encoding="utf-8").read()
        # komentáre preč – v hlavičke je slovo „reže" práve preto, že sa nereže
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

    if not os.path.exists(GRAPH_SH):
        err("workers/routing/graph.sh",
            "skript neexistuje. Graf Valhally sa síce po krajoch už nestavia, "
            "ale ostáva ako REFERENČNÁ stavba – bez nej sa nový motor nemá "
            "proti čomu skontrolovať.")
        return
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
            "číta, si musia sedieť; nesúlad verzií vyzerá ako pokazená trasa, "
            "nie ako nesúlad verzií.")
    if "hranica" not in graph:
        err("workers/routing/graph.sh",
            "`graf.json` nehovorí, kam trasa v tom grafe smie – a mlčanie sa "
            "dá čítať ako pokazený graf, nie ako rozsah.")


def siet_kraja():
    """`<kraj>-routing.pmtiles`: PBF mapy, vlastný balík, manifest, kontrola."""
    if not os.path.exists(BUILD_SH):
        err("workers/routing/build.sh", "skript neexistuje – kraj by ostal "
                                        "bez smerovacej siete.")
    else:
        build = open(BUILD_SH, encoding="utf-8").read()
        if "data/region.osm.pbf" not in build:
            err("workers/routing/build.sh",
                "sieť kraja sa nestavia z `data/region.osm.pbf`. To PBF je "
                "rezané presne na hranicu kraja, takže je to jediné, čo drží "
                "navigáciu za ten istý kraj ako mapu – iný extrakt by ju ticho "
                "rozšíril za hranicu.")
        if "workers/routing/tiles.py" not in build:
            err("workers/routing/build.sh",
                "archív nestavia `workers/routing/tiles.py`. Druhý skript by "
                "bol druhá pravda o tom, čo je v archíve a v akom formáte.")
        if "workers/lint/routing-tiles.py" not in build:
            err("workers/routing/build.sh",
                "hotový archív sa neoveruje `workers/lint/routing-tiles.py`. "
                "Rozbitý archív sa v telefóne prejaví ako „trasa sa nenašla“, "
                "teda ako chyba aplikácie – a beh by pritom bol zelený.")
        if "tags.py --filter" not in build:
            err("workers/routing/build.sh",
                "predfilter PBF si nepýta zoznam tried zo slovníka "
                "(`tags.py --filter`). Druhý zoznam sa rozíde a rozíde sa "
                "ticho: trieda vypadne z archívu a profil ju ponúka ďalej.")

    if not os.path.exists(REGION_WORKFLOW):
        err(".github/workflows/navigation-region.yml", "workflow neexistuje.")
        return
    wtext = open(REGION_WORKFLOW, encoding="utf-8").read()
    # komentáre preč – v hlavičke je `graph.sh` práve preto, že sa už nevolá
    kod = re.sub(r"^[ \t]*#.*$", "", wtext, flags=re.M)
    if "workers/routing/build.sh" not in kod:
        err(".github/workflows/navigation-region.yml",
            "kraj sa nestavia `workers/routing/build.sh`.")
    if "workers/routing/graph.sh" in kod:
        err(".github/workflows/navigation-region.yml",
            "kraj zase stavia graf Valhally. Ten vážil 176 – 192 MB na kraj "
            "a na hranici kraja končil; nahradili ho dlaždice so značkami "
            "(`docs/navigation.md` §10). Celoštátny `navigation.yml` ostáva.")
    if "name: site-navigacia" not in wtext:
        err(".github/workflows/navigation-region.yml",
            "archív sa neodkladá ako `site-navigacia`. Do `_site` – a teda do "
            "manifestu aj do balíka – sa dostane jedine cezeň; `deploy` "
            "zlieva práve `site-*`.")
    if "name: pbf" not in wtext:
        err(".github/workflows/navigation-region.yml",
            "job si nesťahuje artefakt `pbf` z prípravy, takže nemá z čoho "
            "sieť postaviť – alebo si extrakt zháňa sám, čo je druhá pravda "
            "o tom, za aké územie navigácia je.")

    if os.path.exists(BUILD_MAP):
        bm = open(BUILD_MAP, encoding="utf-8").read()
        if "navigation-region.yml" not in bm:
            err(".github/workflows/build-map-region.yml",
                "build mapy nevolá `navigation-region.yml`, takže sa k mape "
                "kraja nepostaví smerovacia sieť – a nikto to nepovie: mapa "
                "je v poriadku, len sa v nej nedá nikam doviezť.")
        if "ROUTING_ENABLED" not in bm:
            err(".github/workflows/build-map-region.yml",
                "manifestu sa nehovorí, či sieť vznikla (`ROUTING_ENABLED`). "
                "Balík `navigacia` sa potom skladá len podľa mien súborov, "
                "a keď sieť nevznikla, tvári sa mapa, že v nej je.")

    if os.path.exists(SITE_SH):
        site = open(SITE_SH, encoding="utf-8").read()
        if "routing:" not in site:
            err("workers/deploy/site.sh",
                "manifest nenesie `routing`. Manifest je jediné miesto, ktoré "
                "vie, čo v mape naozaj je – bez neho sa balík `navigacia` "
                "skladá zo zálohy podľa prípony mena.")


def poradie(areas, regions):
    """Poradie uzlov: počíta ho vlastný workflow a build kraja si ho vezme.

    Kľúč cache je jediná väzba medzi nimi a je to REŤAZEC na dvoch miestach –
    keď sa rozíde, build kraja proste nikdy nič nenájde, archívy pôjdu bez
    poradia a nespadne pri tom nič.
    """
    rel_regions = "workers/data/regions.json"
    for kluc, r in regions.items():
        oblast = r.get("routing_area")
        if oblast and oblast not in areas:
            err(rel_regions,
                f"`{kluc}` má `routing_area: {oblast}`, ktoré vo "
                f"`workers/data/routing-areas.json` nie je. Build kraja by "
                f"hľadal poradie, ktoré nikto nepočíta.")

    if not os.path.exists(ORDER_WORKFLOW):
        err(".github/workflows/routing-order.yml",
            "workflow neexistuje. Poradie uzlov sa počíta nad CELÝM územím, "
            "takže ho beh kraja vyrobiť nemôže – bez tohto workflowu ho "
            "nevyrobí nikto a archívy pôjdu bez neho.")
        return
    ord_text = open(ORDER_WORKFLOW, encoding="utf-8").read()
    for skript, preco in (
            ("workers/routing/pbf.sh",
             "druhý zdroj PBF by bol druhá pravda o tom, nad akým územím sa "
             "poradie počíta"),
            ("workers/routing/order.py",
             "poradie musí rátať ten istý kód, ktorého id ide do archívu")):
        if skript not in ord_text:
            err(".github/workflows/routing-order.yml",
                f"workflow nepoužíva `{skript}` – {preco}.")

    kluce = {ORDER_WORKFLOW: _kluc_cache(ord_text)}
    if os.path.exists(REGION_WORKFLOW):
        kluce[REGION_WORKFLOW] = _kluc_cache(
            open(REGION_WORKFLOW, encoding="utf-8").read())
    chyba = [f for f, k in kluce.items() if not k]
    for f in chyba:
        err(f, "nie je v ňom kľúč cache s poradím uzlov (`routing-order-…`). "
               "Poradie sa medzi behmi prenáša jedine ním.")
    hodnoty = {k for k in kluce.values() if k}
    if len(hodnoty) > 1:
        err(".github/workflows/routing-order.yml",
            f"kľúč cache s poradím znie na každej strane inak ({sorted(hodnoty)}). "
            f"Build kraja potom nenájde nič, archívy pôjdu bez poradia – "
            f"a nespadne pri tom nič.")


def _kluc_cache(text):
    """Predpona kľúča cache s poradím – bez `run_id`, ten je zámerne rôzny."""
    m = re.search(r"key: (routing-order-[a-z0-9-]*)", text)
    return m.group(1).rstrip("-") if m else ""


def balik():
    """Vlastný balík vedľa kreslenej dopravnej siete, nie v nej ani v mape."""
    if not os.path.exists(CISELNIK):
        err("workers/data/packages.json", "číselník balíkov neexistuje.")
        return
    with open(CISELNIK, encoding="utf-8") as f:
        baliky = {b["kluc"]: b for b in json.load(f).get("baliky") or []}
    nav = baliky.get("navigacia")
    if not nav:
        err("workers/data/packages.json",
            "balík `navigacia` v číselníku nie je – sieť sa postaví a nikam sa "
            "nenahrá, a katalóg o nej nepovie nič, takže si ju appka nemá ako "
            "vypýtať.")
    else:
        if "routing" not in (nav.get("manifest") or []):
            err("workers/data/packages.json",
                "balík `navigacia` neberie `routing` z manifestu – je to "
                "prázdny balík so sľubom v mene.")
        if "-routing.pmtiles" not in (nav.get("pripony") or []):
            err("workers/data/packages.json",
                "balík `navigacia` nemá zálohu podľa prípony "
                "(`-routing.pmtiles`). Pregenerovanie jednej vrstvy beží bez "
                "manifestu, takže by z neho vyšiel prázdny ZIP.")
        if nav.get("priecinok"):
            err("workers/data/packages.json",
                "balík `navigacia` sa skladá z priečinka. Graf Valhally to "
                "potreboval (štyri súbory, ktoré si musia sedieť); smerovacia "
                "sieť je jeden archív a patrí do manifestu ako ostatné vrstvy.")
    cesty = baliky.get("cesty")
    if not cesty:
        err("workers/data/packages.json",
            "balík `cesty` v číselníku nie je. Bez neho ostane otázka „chcem "
            "siete, po ktorých sa dá cestovať, a nie zvyšok mapy“ bez odpovede "
            "– a smerovacia sieť je odpoveď na inú otázku.")
    elif "transport" not in (cesty.get("manifest") or []):
        err("workers/data/packages.json",
            "balík `cesty` neberie `transport` z manifestu. Bez dopravnej "
            "siete je to prázdny balík so sľubom v mene.")
    elif "routing" in (cesty.get("manifest") or []):
        err("workers/data/packages.json",
            "balík `cesty` zase priberá smerovaciu sieť. `cesty` je KRESLENÁ "
            "sieť („kadiaľ sa dá ísť“), smerovacia sieť je iná otázka („doveź "
            "ma tam“) – a kto chce sieť len vidieť, sťahoval by aj ju.")


def formular(areas):
    """Výber rozsahu vo formulári sa musí zhodovať s číselníkom."""
    for cesta in (WORKFLOW, ORDER_WORKFLOW):
        rel = cesta.replace(os.sep, "/")
        if not os.path.exists(cesta):
            err(rel, "workflow neexistuje.")
            continue
        with open(cesta, encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        on = wf.get("on", wf.get(True)) or {}
        inp = ((on.get("workflow_dispatch") or {}).get("inputs") or {})
        opts = set((inp.get("area") or {}).get("options") or [])
        if opts != set(areas):
            err(rel,
                f"výber `area` vo formulári má {sorted(opts)}, číselník "
                f"{sorted(areas)}. `choice` GitHub zo súboru prečítať nevie, "
                f"takže sa to píše dvakrát – a rozsah, ktorý vo výbere nie je, "
                f"sa nedá vybrať.")


def main():
    with open(AREAS, encoding="utf-8") as f:
        areas = json.load(f)["areas"]
    with open(REGIONS, encoding="utf-8") as f:
        regions = json.load(f)
    with open(VIGNETTES, encoding="utf-8") as f:
        countries = json.load(f)["countries"]

    celostatny_graf(areas, regions, countries)
    siet_kraja()
    poradie(areas, regions)
    balik()
    formular(areas)

    for path, msg in bad:
        print(f"::error file={path}::{msg}")
    if bad:
        print(f"\n{len(bad)} problém(ov) v navigácii.")
        return 1
    print("Navigácia: sieť kraja stojí na PBF mapy, má vlastný balík "
          "v manifeste a beh ju overí; poradie uzlov má vlastný workflow "
          "a obe strany kľúča cache znejú rovnako; celoštátny graf Valhally "
          "ostáva ako referenčná stavba, jeho PBF sa nereže a formuláre "
          "sedia s číselníkom.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
