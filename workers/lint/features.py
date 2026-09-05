#!/usr/bin/env python3
"""Kontrola: čo si schéma krajinných prvkov vyžiada, to jej predfilter pustí.

Job `features` číta PBF trikrát: predfilter (`filter.txt`) a nad jeho výstupom
dva behy Planetileru (`features.yml`, `points.yml`). To isté rozhodnutie je
tak na troch miestach a rozídené je tiché – Planetiler dostane PBF, v ktorom
tie objekty vôbec nie sú, a vyrobí dlaždice bez nich.

Kontroluje sa, že každý `include_when` v oboch schémach má v predfiltri holý
kľúč alebo kľúč so svojou hodnotou. Naopak to neplatí zámerne: filter smie
byť širší.
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
# Obe schémy čítajú z toho istého predfiltrovaného PBF (rozpis vyššie), takže
# obe musia proti tomu istému `filter.txt` sedieť – kontrola ide cez zoznam,
# nie cez dve kópie tela funkcie, ktoré by sa raz rozišli.
SCHEMAS = [os.path.join(_WORKERS, "features", "features.yml"),
           os.path.join(_WORKERS, "features", "points.yml")]
FILTER = os.path.join(_WORKERS, "features", "filter.txt")

bad = []


def filter_tags(path):
    """`{kľúč: {hodnoty} alebo None}` z `osmium tags-filter --expressions`.

    `None` znamená „celý kľúč" (`nwr/embankment`) – vtedy je jedno, akú má
    hodnotu. Typy objektov (`nwr/`, `w/`) sa zahodia: schéma si geometriu
    vyberá sama a filter je aj tak širší.
    """
    out = {}
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "/" in line.split("=", 1)[0]:
                line = line.split("/", 1)[1]
            key, _, values = line.partition("=")
            key = key.strip()
            if not values:
                out[key] = None
                continue
            if out.get(key, "x") is None:
                continue                      # celý kľúč už prešiel
            out.setdefault(key, set()).update(
                v.strip() for v in values.split(",") if v.strip())
    return out


def schema_tags(path):
    """`[(kľúč, hodnota, kde)]` zo všetkých `include_when` v schéme."""
    with open(path) as f:
        data = yaml.safe_load(f)
    out = []
    for layer in data.get("layers") or []:
        for feat in layer.get("features") or []:
            when = feat.get("include_when")
            if not isinstance(when, dict):
                continue
            for key, value in when.items():
                values = value if isinstance(value, list) else [value]
                for v in values:
                    out.append((key, v, layer.get("id", "?")))
    return out


tags = filter_tags(FILTER)
requirements = 0
for schema in SCHEMAS:
    kratke = os.path.relpath(schema, _WORKERS)
    reqs = schema_tags(schema)
    requirements += len(reqs)
    for key, value, layer_id in reqs:
        if key in tags and tags[key] is None:
            continue                          # holý kľúč pustí všetko
        # `true` nie je hodnota tagu, ale „tag je prítomný" (`embankment=yes`,
        # `cutting=yes`, `mountain_pass=yes`) – stačí, že filter pozná kľúč.
        if value is True:
            if key not in tags:
                bad.append(f"{kratke} (vrstva `{layer_id}`) chce prítomnosť "
                           f"tagu `{key}`, ale predfilter ten kľúč vôbec "
                           f"nepozná – objekty s ním sa do PBF pre "
                           f"Planetiler nedostanú a v dlaždiciach ticho "
                           f"nebudú.")
            continue
        if key not in tags:
            bad.append(f"{kratke} (vrstva `{layer_id}`) chce `{key}={value}`, "
                       f"ale predfilter kľúč `{key}` vôbec nepozná – "
                       f"v dlaždiciach tá trieda ticho nebude. Dopíš ho do "
                       f"workers/features/filter.txt.")
        elif value not in tags[key]:
            bad.append(f"{kratke} (vrstva `{layer_id}`) chce `{key}={value}`, "
                       f"ale predfilter pri `{key}` púšťa len "
                       f"{', '.join(sorted(tags[key]))} – tá trieda bude "
                       f"v dlaždiciach ticho chýbať.")

for b in bad:
    print(f"::error file=workers/features/filter.txt::{b}")
print(f"krajinné prvky: {len(bad)} chýb "
      f"({requirements} požiadaviek schém proti predfiltru)")
sys.exit(1 if bad else 0)
