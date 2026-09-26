#!/usr/bin/env python3
"""Železnice a lanovky: filter pustí, čo schéma chce, a navigácia jazdí po tom, čo mapa kreslí."""
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "rail", "rail.yml")
FILTER = os.path.join(_WORKERS, "rail", "filter.txt")
BUILD = os.path.join(_WORKERS, "rail", "build.sh")
SLOVNIK = os.path.join(_WORKERS, "data", "rail-routing-tags.json")

# kľúče, ktoré na body dopíše `lines.py` – predfilter ich pustiť nemusí
DOPOCITANE = {"rail_speed"}

# čo balík sľubuje v aplikácii
SLUBY = {"rail", "tram", "subway", "light_rail", "abandoned", "disused",
         "station", "halt", "level_crossing"}
# lanovky v každom stave – aj rozostavané, plánované a zrušené
SLUBY_LANOVKY = {"cable_car", "gondola", "chair_lift", "construction",
                 "proposed", "disused", "abandoned", "station"}
STAVY = {"construction:aerialway", "proposed:aerialway", "disused:aerialway",
         "abandoned:aerialway"}


def filter_keys(path):
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


def podmienky(when):
    """Dvojice kľúč → hodnoty z `include_when`, aj spod `__all__`."""
    if not when:
        return []
    if "__all__" in when:
        return [p for c in when["__all__"] for p in podmienky(c)]
    return [(k, v if isinstance(v, list) else [v]) for k, v in when.items()]


def main():
    bad = []
    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    bloky = [b for v in schema.get("layers") or [] for b in v.get("features") or []]

    pusta, triedy, lanovky, kluce_vsetky = filter_keys(FILTER), set(), set(), set()
    for b in bloky:
        kluce = set()
        for kluc, hodnoty in podmienky(b.get("include_when")):
            kluce.add(kluc)
            kluce_vsetky.add(kluc)
            if kluc == "railway":
                triedy |= set(map(str, hodnoty))
            if kluc == "aerialway":
                lanovky |= set(map(str, hodnoty))
        # pri `__all__` stačí jeden kľúč – ostatné prídu s tým istým objektom
        if kluce and not kluce & (pusta | DOPOCITANE):
            bad.append(f"{FILTER}: schéma sa pýta na {', '.join(sorted(kluce))}, "
                       f"predfilter to nepúšťa – dlaždice by vznikli bez toho.")

    for sluba in sorted(SLUBY - triedy):
        bad.append(f"{SCHEMA}: `railway={sluba}` v schéme nie je, balík ho "
                   f"pritom sľubuje.")

    for sluba in sorted(SLUBY_LANOVKY - lanovky):
        bad.append(f"{SCHEMA}: `aerialway={sluba}` v schéme nie je, balík ho "
                   f"pritom sľubuje.")
    for kluc in sorted(STAVY - kluce_vsetky):
        bad.append(f"{SCHEMA}: lanovky s `{kluc}` v schéme nie sú – stav by "
                   f"sa stratil.")
    for kluc in sorted((STAVY | {"aerialway"}) - pusta):
        bad.append(f"{FILTER}: predfilter nepúšťa `{kluc}` – lanovky by v "
                   f"dlaždiciach neboli.")

    with open(SLOVNIK, encoding="utf-8") as f:
        siet = set(json.load(f)["siet"]["railway"])
    for trieda in sorted(siet - triedy):
        bad.append(f"{SLOVNIK}: navigácia jazdí po `railway={trieda}`, ktorú "
                   f"mapa nekreslí – trasa by viedla mimo kresby.")

    with open(BUILD, encoding="utf-8") as f:
        build = f.read()
    if "rail-routing-tags.json" not in build:
        bad.append(f"{BUILD}: koľajová sieť sa nestavia s vlastným slovníkom – "
                   f"s cestným by v nej nebola ani jedna trať.")
    if " -R" in build or "--omit-referenced" in build:
        bad.append(f"{BUILD}: `-R` vyhodí členov relácií – plochy staníc zmiznú.")
    if "signs.mjs" not in build:
        bad.append(f"{BUILD}: značky krajiny sa nepečú – appka by kreslila predvolené.")
    with open(os.path.join(_WORKERS, "data", "packages.json"), encoding="utf-8") as f:
        zel = [b for b in json.load(f)["baliky"] if b["kluc"] == "zeleznice"]
    if not zel or "rail_signs" not in (zel[0].get("manifest") or []):
        bad.append("workers/data/packages.json: `zeleznice` nenesie `rail_signs` – "
                   "značky by do balíka nešli.")

    for b in bad:
        print(f"::error::{b}")
    if not bad:
        print(f"železnice ✓ ({len(bloky)} blokov, {len(triedy)} tried, "
              f"{len(lanovky)} druhov lanoviek, sieť {len(siet)} tried)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
