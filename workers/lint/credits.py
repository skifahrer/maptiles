#!/usr/bin/env python3
"""Kontrola: každý balík má autorov dát a katalóg ich zapíše."""
import importlib.util
import json
import sys

CREDITS = "workers/data/credits.json"
PACKAGES = "workers/data/packages.json"
DEM = "workers/data/dem-sources.json"
POUZITIA = ("contours", "rocks", "shading")
KLUCE = {"holder", "work", "license", "license_url", "source_url", "changes"}


def nacitaj(meno, cesta):
    spec = importlib.util.spec_from_file_location(meno, cesta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[meno] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    bad = []
    with open(CREDITS, encoding="utf-8") as f:
        kredity = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    with open(PACKAGES, encoding="utf-8") as f:
        baliky = json.load(f)["baliky"]
    with open(DEM, encoding="utf-8") as f:
        modely = [k for k, v in json.load(f).items()
                  if not k.startswith("_") and isinstance(v, dict)]

    for kluc, kredit in kredity.items():
        if not kredit.get("holder"):
            bad.append(f"{CREDITS}: `{kluc}` nemá `holder`")
        if set(kredit) - KLUCE:
            bad.append(f"{CREDITS}: `{kluc}` má neznáme kľúče "
                       f"{sorted(set(kredit) - KLUCE)} – appka ich nečíta")
        # CC BY chce povedať, čo sme s dielom urobili
        if (kredit.get("license") or "").startswith("CC BY ") and kluc != "wikipedia" \
                and not kredit.get("changes"):
            bad.append(f"{CREDITS}: `{kluc}` je CC BY a nemá `changes`")

    for model in modely:
        if model not in kredity:
            bad.append(f"{CREDITS}: model `{model}` z {DEM} nemá autora")

    for b in baliky:
        zdroje = b.get("zdroje")
        if not zdroje:
            bad.append(f"{PACKAGES}: balík `{b['kluc']}` nemá `zdroje`")
            continue
        for z in zdroje:
            if z.startswith("dem:"):
                if z[4:] not in POUZITIA:
                    bad.append(f"{PACKAGES}: `{b['kluc']}` – `{z}` nie je "
                               f"{', '.join('dem:' + p for p in POUZITIA)}")
            elif z not in kredity:
                bad.append(f"{PACKAGES}: `{b['kluc']}` – zdroj `{z}` nie je v {CREDITS}")

    baliky_mod = nacitaj("deploy_baliky", "workers/deploy/baliky.py")
    # autor výpočtu ide pred dáta, z ktorých počítal
    relief = [kredity.get("autor"), kredity.get("dmr5")]
    if baliky_mod.kredity("tienovanie", {"shading": "dmr5"}) != relief:
        bad.append("baliky.kredity: tieňovanie nemenuje autora a potom ÚGKK SR")
    if baliky_mod.kredity("vrstevnice-skaly", {}) != relief:
        bad.append("baliky.kredity: kraj bez modelu nemenuje autora a predvolený DMR 5.0")
    if baliky_mod.kredity("mapa") != [kredity.get("osm")]:
        bad.append("baliky.kredity: základná mapa nemenuje OpenStreetMap")

    catalog = open("workers/deploy/catalog.py", encoding="utf-8").read()
    if catalog.count("modely=modely_kraja(man, reg)") < 2:
        bad.append("workers/deploy/catalog.py: niektorý zápis balíka nepodáva "
                   "`modely_kraja` – autori výšok by boli predvolení, nie skutoční")

    for b in bad:
        print(f"::error::{b}")
    if bad:
        sys.exit(1)
    print(f"✔ {len(baliky)} balíkov, každý s autormi dát")


if __name__ == "__main__":
    main()
