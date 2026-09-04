#!/usr/bin/env python3
"""
Vodstvo: filter pustí, čo schéma chce – a meno je na tom istom prvku.

ŠTYRI TICHÉ VECI, na ktoré je táto kontrola:

  1. PREDFILTER A SCHÉMA SA ROZÍDU. Job `vodstvo` číta PBF dvakrát (`osmium
     tags-filter` nad `workers/water/filter.txt`, potom Planetiler nad
     `water.yml`). Keď sa rozídu, Planetiler dostane PBF, v ktorom ten tag už
     NIE JE – dlaždice vzniknú, beh zazelená a tá trieda vody v nich len nie
     je.

  2. FILTER PRESTANE DOŤAHOVAŤ ČLENOV RELÁCIÍ. Veľké jazerá a priehrady sú
     MULTIPOLYGÓNY, ktorých členovia `natural=water` nemajú. `osmium
     tags-filter` ich doťahuje sám; s `-R` (`--omit-referenced`) by po Domaši
     v dlaždiciach ticho neostalo nič.

  3. Z DLAŽDICE ZMIZNE `name`. Kvôli tomu vrstva existuje: v OpenMapTiles je
     meno vody vo VLASTNEJ vrstve (`water_name`) mimo geometrie, takže „daj mi
     rieky s menami“ znamená spájať dve vrstvy. Tu je meno na tom istom prvku
     a je to celý rozdiel.

  4. MORE SA ZAČNE KRESLIŤ AKO PLOCHA. Plocha oceánu v OSM neexistuje –
     skladá sa až z pobrežných čiar celej planéty, takže z rezaného PBF kraja
     by vzniklo more, ktoré končí na hranici výrezu. `natural=coastline` preto
     MUSÍ ísť ako čiara; plochu kreslí základná mapa z `water_polygons`
     Planetileru.

Spustiť: `python3 workers/lint/water.py`
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "water", "water.yml")
FILTER = os.path.join(_WORKERS, "water", "filter.txt")
BUILD = os.path.join(_WORKERS, "water", "build.sh")

# Čo vrstva SĽUBUJE – „rieky, jazerá, more“. Trieda → čím to je v OSM.
SLUBY = {
    "river": "rieky",
    "stream": "potoky",
    "water": "jazerá, priehrady a rybníky (`natural=water`)",
    "coastline": "more (pobrežná čiara)",
}

bad = []


def err(msg):
    bad.append(msg)


def filter_keys(path):
    """Holé kľúče z `osmium tags-filter --expressions` (bez `n/`, `w/`, `r/`)."""
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


def prepinace_filtra(build):
    """Prepínače SKUTOČNÉHO `osmium tags-filter`, nie zmienok v komentároch.

    Číta sa celý príkaz aj s pokračovaním na ďalších riadkoch (`\\`), lebo
    prepínač môže stáť aj tam. Hľadať len prvý výskyt slova v súbore je málo:
    prvá zmienka je dnes v hlavičke a kontrola by potom čítala komentár.
    """
    riadky = build.splitlines()
    for i, r in enumerate(riadky):
        if r.lstrip().startswith("#") or "osmium tags-filter" not in r:
            continue
        prikaz = [r]
        while prikaz[-1].rstrip().endswith("\\") and i + 1 < len(riadky):
            i += 1
            prikaz.append(riadky[i])
        return " " + " ".join(prikaz) + " "
    return ""


def main():
    for path in (SCHEMA, FILTER, BUILD):
        if not os.path.exists(path):
            print(f"::error::{path} neexistuje.")
            return 1

    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    bloky = [b for v in (schema.get("layers") or [])
             for b in (v.get("features") or [])]
    if not bloky:
        err(f"{SCHEMA}: schéma nemá ani jeden blok – vrstva by bola prázdna.")
        return hotovo()

    # ---- 1. predfilter pustí, čo schéma chce ----
    pusta = filter_keys(FILTER)
    chce, triedy = set(), set()
    for b in bloky:
        podmienka = b.get("include_when") or {}
        chce |= set(podmienka.keys())
        for hodnoty in podmienka.values():
            triedy |= set(map(str, hodnoty if isinstance(hodnoty, list)
                              else [hodnoty]))
    chyba = sorted(chce - pusta)
    if chyba:
        err(f"{FILTER}: schéma sa pýta na {', '.join(chyba)}, ale predfilter "
            f"to nepúšťa (pozná {', '.join(sorted(pusta))}). Planetiler by "
            f"dostal PBF, v ktorom ten tag už nie je – dlaždice by vznikli, "
            f"beh by bol zelený a tá časť vodstva by v nich nebola.")

    # ---- 2. filter doťahuje členov relácií ----
    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    prepinace = prepinace_filtra(build)
    if not prepinace:
        err(f"{BUILD}: `osmium tags-filter` tu nie je – bez predfiltra číta "
            f"Planetiler celý región a táto kontrola nemá čo overiť.")
    # `-r` NEEXISTUJE. osmium pozná len `-R`/`--omit-referenced` (opačný
    # význam), na `-r` skončí s „unrecognised option“ a job padne hneď.
    if " -r " in prepinace:
        err(f"{BUILD}: `osmium tags-filter -r` – taký prepínač osmium nemá "
            f"a skončí na ňom s „unrecognised option“. Členov relácií "
            f"doťahuje sám, netreba o ne žiadať.")
    if " -R " in prepinace or "--omit-referenced" in prepinace:
        err(f"{BUILD}: `osmium tags-filter` beží s `-R`/`--omit-referenced`, "
            f"takže z PBF vypadnú ČLENOVIA relácií. Veľké jazerá a priehrady "
            f"sú multipolygóny, ktorých členovia `natural=water` nemajú – po "
            f"Domaši by v dlaždiciach ticho neostalo nič. Bez toho prepínača "
            f"ich osmium doťahuje sám.")

    # ---- 3. meno je na tom istom prvku ----
    for i, b in enumerate(bloky, start=1):
        atr = {a.get("key") for a in (b.get("attributes") or [])
               if isinstance(a, dict)}
        if "name" not in atr:
            err(f"{SCHEMA}: blok {i} nedáva `name`. Presne to je rozdiel proti "
                f"OpenMapTiles, kde meno vody leží vo vlastnej vrstve mimo "
                f"geometrie – bez neho je to zase len modrá čiara.")

    # ---- 3b. čo vrstva sľubuje, v nej naozaj je ----
    for trieda, co in SLUBY.items():
        if trieda not in triedy:
            err(f"{SCHEMA}: v schéme nie sú {co} (`{trieda}`). Balík sľubuje "
                f"„rieky, jazerá a more“ – vypadnutú triedu vidno až vtedy, "
                f"keď sa niekto pozrie, kadiaľ tečie.")

    # ---- 4. pobrežie ide ako čiara, nie ako plocha ----
    for i, b in enumerate(bloky, start=1):
        podmienka = b.get("include_when") or {}
        hodnoty = podmienka.get("natural") or []
        if not isinstance(hodnoty, list):
            hodnoty = [hodnoty]
        if "coastline" in map(str, hodnoty) and b.get("geometry") != "line":
            err(f"{SCHEMA}: blok {i} berie `natural=coastline` ako "
                f"`{b.get('geometry')}`. Plocha oceánu v OSM neexistuje – "
                f"skladá sa z pobrežných čiar celej planéty, takže z rezaného "
                f"PBF kraja by vzniklo more, ktoré končí na hranici výrezu. "
                f"Plochu kreslí základná mapa z `water_polygons`.")
    return hotovo()


def hotovo():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problém(ov) vo vodstve.")
        return 1
    print("Vodstvo: predfilter pustí, čo schéma chce, doťahuje členov relácií, "
          "meno je na tom istom prvku a pobrežie ide ako čiara.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
