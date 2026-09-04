#!/usr/bin/env python3
"""
Hranice území: filter pustí, čo schéma chce – a v dlaždici je MENO.

TRI TICHÉ VECI, na ktoré je táto kontrola:

  1. PREDFILTER A SCHÉMA SA ROZÍDU. Job `hranice` číta PBF dvakrát (`osmium
     tags-filter` nad `workers/boundaries/filter.txt`, potom Planetiler nad
     `boundaries.yml`). To isté rozhodnutie je teda na dvoch miestach a keď sa
     rozídu, Planetiler dostane PBF, v ktorom ten tag už NIE JE – dlaždice
     vzniknú, beh zazelená a tá úroveň hraníc v nich len nie je.

  2. FILTER PRESTANE DOŤAHOVAŤ ČLENOV RELÁCIÍ. Hranica obce je v OSM RELÁCIA,
     ktorej členmi sú cesty – a tie samy `boundary=administrative` nemajú.
     Bez `-r` v `osmium tags-filter` teda z PBF vypadne geometria, Planetiler
     nemá z čoho zložiť polygón a vrstva je PRÁZDNA pri zelenom behu. Je to
     jediná vrstva v tejto pipeline, kde na tom stojí všetko.

  3. Z DLAŽDICE ZMIZNE `name`. Kvôli tomu vrstva existuje: hranica vo vrstve
     `boundary` OpenMapTiles je čiara BEZ MENA územia, ktoré ohraničuje, takže
     sa z nej nedá povedať, v ktorej obci nejaký bod je. Balík by sa volal
     `hranice`, vážil by menej a niesol by presne to, čo mapa má aj tak.

Spustiť: `python3 workers/lint/boundaries.py`
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "boundaries", "boundaries.yml")
FILTER = os.path.join(_WORKERS, "boundaries", "filter.txt")
BUILD = os.path.join(_WORKERS, "boundaries", "build.sh")

# Úrovne, ktoré vrstva SĽUBUJE. Číslo → čo to je u nás (inde iné – preto ide
# do dlaždice číslo a nie naše meno; rozpis v hlavičke schémy).
UROVNE = {"2": "štát", "4": "kraj", "6": "okres", "8": "obec"}

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
    chce = set()
    for b in bloky:
        podmienka = b.get("include_when") or {}
        for kus in podmienka.get("__all__", [podmienka]):
            chce |= set(kus.keys()) if isinstance(kus, dict) else set()
    chce.discard("admin_level")     # je to spresnenie, nie výber objektu
    chyba = sorted(chce - pusta)
    if chyba:
        err(f"{FILTER}: schéma sa pýta na {', '.join(chyba)}, ale predfilter "
            f"to nepúšťa (pozná {', '.join(sorted(pusta))}). Planetiler by "
            f"dostal PBF, v ktorom ten tag už nie je – dlaždice by vznikli, "
            f"beh by bol zelený a tá časť hraníc by v nich jednoducho nebola.")

    # ---- 2. filter doťahuje členov relácií ----
    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    if " -r " not in build.split("tags-filter", 1)[-1].split("\n", 1)[0] + " ":
        err(f"{BUILD}: `osmium tags-filter` beží bez `-r`, takže z PBF "
            f"vypadnú ČLENOVIA relácií. Hranica obce je relácia, ktorej "
            f"členovia `boundary=administrative` nemajú – Planetiler by nemal "
            f"z čoho zložiť polygón a vrstva by bola prázdna pri zelenom behu.")
    if "r/boundary=administrative" not in open(FILTER, encoding="utf-8").read():
        err(f"{FILTER}: `r/boundary=administrative` tu nie je. Meno aj úroveň "
            f"územia nesie RELÁCIA, nie jej cesty – bez nej sú v dlaždici "
            f"čiary bez toho, kvôli čomu vrstva existuje.")

    # ---- 3. každý blok nesie meno ----
    for i, b in enumerate(bloky, start=1):
        atr = {a.get("key") for a in (b.get("attributes") or [])
               if isinstance(a, dict)}
        if "name" not in atr:
            err(f"{SCHEMA}: blok {i} nedáva `name`. Presne to je rozdiel proti "
                f"vrstve `boundary` v základnej mape – bez mena je to zase len "
                f"čiara a otázka „v ktorej obci som“ ostane bez odpovede.")

    # ---- 3b. všetky štyri úrovne v schéme sú ----
    uroven_v_scheme = set()
    for b in bloky:
        podmienka = b.get("include_when") or {}
        for kus in podmienka.get("__all__", [podmienka]):
            if isinstance(kus, dict) and "admin_level" in kus:
                hodnoty = kus["admin_level"]
                uroven_v_scheme |= set(map(
                    str, hodnoty if isinstance(hodnoty, list) else [hodnoty]))
    for uroven, co in UROVNE.items():
        if uroven not in uroven_v_scheme:
            err(f"{SCHEMA}: úroveň `admin_level={uroven}` ({co}) v schéme nie "
                f"je. Balík sľubuje hranice štátu, kraja, okresu aj obce – "
                f"chýbajúca úroveň sa pozná až vtedy, keď sa niekto spýta, "
                f"v ktorom okrese je.")
    return hotovo()


def hotovo():
    for b in bad:
        print(f"::error::{b}")
    if bad:
        print(f"\n{len(bad)} problém(ov) v hraniciach území.")
        return 1
    print("Hranice území: predfilter pustí, čo schéma chce, doťahuje členov "
          "relácií, v dlaždici je meno a všetky štyri úrovne sú v schéme.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
