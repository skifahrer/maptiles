#!/usr/bin/env python3
"""Hranice území: filter pustí, čo schéma chce – a v dlaždici je meno.

Tri tiché veci:

  1. predfilter (`filter.txt`) a schéma (`boundaries.yml`) sa rozídu;
  2. filter prestane doťahovať členov relácií – hranica obce je relácia,
     ktorej členmi sú cesty bez `boundary=administrative`, takže s `-R`
     nemá Planetiler z čoho zložiť polygón a vrstva je prázdna;
  3. z dlaždice zmizne `name` – kvôli tomu vrstva existuje (vrstva `boundary`
     v OpenMapTiles je čiara bez mena územia).
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
            f"takže z PBF vypadnú ČLENOVIA relácií. Hranica obce je relácia, "
            f"ktorej členovia `boundary=administrative` nemajú – Planetiler by "
            f"nemal z čoho zložiť polygón a vrstva by bola prázdna pri "
            f"zelenom behu. Bez toho prepínača ich osmium doťahuje sám.")
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
