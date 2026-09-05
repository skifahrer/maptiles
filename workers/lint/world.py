#!/usr/bin/env python3
"""Mapa sveta: štýl kreslí presne tie vrstvy a od tých zoomov, ktoré schéma robí.

Ten istý pár čísel na dvoch miestach ako pri vrstevniciach (`zoom-floor.py`):
`world.yml` hovorí, čo sa vyrobí, `style.mjs`, čo sa nakreslí. A k tomu meno
vrstvy – zlý `source-layer` MapLibre nekomentuje, v mape len nič nie je.

  1. každý `source-layer` v štýle je vrstva schémy;
  2. každá vrstva schémy je v štýle aspoň raz nakreslená;
  3. najnižší `minzoom` v štýle sa rovná najnižšiemu `min_zoom` v schéme.

Platí to pre každú podobu (`variant`) zvlášť; podoby si kontrola vypýta
z `workers/world/variant.py`, takže nová je automaticky kontrolovaná.

Bod 3 je zámerne o dne vrstvy, nie o každej triede: v schéme je staging po
triedach, v štýle po vrstvách a filtroch.
"""
import json
import os
import subprocess
import sys
import tempfile

import yaml

SCHEMA = "workers/world/world.yml"
STYLE = "workers/world/style.mjs"

sys.path.insert(0, os.path.join("workers", "world"))
import variant as podoby_mod  # noqa: E402

bad = []

doc = yaml.safe_load(open(SCHEMA, encoding="utf-8"))
raw = podoby_mod.nacitaj()
podoby = podoby_mod.podoby(raw)


def dna(vrstvy):
    """Dno vrstvy v schéme: najnižší `min_zoom` spomedzi jej prvkov."""
    out = {}
    for lay in doc.get("layers") or []:
        if lay["id"] not in vrstvy:
            continue
        zoomy = [f.get("min_zoom", 0) for f in (lay.get("features") or [])]
        out[lay["id"]] = min(zoomy) if zoomy else 0
    return out


for nazov, podoba in sorted(podoby.items()):
    # Vrstvy, ktoré podoba pýta a schéma nemá, spadnú už tu – s vetou o tom,
    # ktoré to sú.
    try:
        podoby_mod.schema_pre(podoba["layers"], doc)
    except SystemExit as exc:
        bad.append(f"podoba `{nazov}`: {exc}")
        continue
    schema_min = dna(podoba["layers"])
    print(f"podoba `{nazov}`: vrstvy "
          + ", ".join(f"{k} od z{v}" for k, v in sorted(schema_min.items())))

    with tempfile.TemporaryDirectory() as tmp:
        hotovo = subprocess.run(
            ["node", STYLE, f"--out={tmp}", f"--variant={nazov}"],
            capture_output=True, text=True, check=False)
        if hotovo.returncode != 0:
            print(f"::error file={STYLE}::štýl podoby `{nazov}` sa nedá "
                  f"vygenerovať: {hotovo.stderr.strip() or hotovo.stdout.strip()}")
            sys.exit(1)
        subory = sorted(f for f in os.listdir(tmp) if f.endswith(".json"))
        if not subory:
            print(f"::error file={STYLE}::podoba `{nazov}` nevyrobila ani "
                  f"jeden štýl.")
            sys.exit(1)

        for meno in subory:
            with open(os.path.join(tmp, meno), encoding="utf-8") as f:
                styl = json.load(f)
            style_min = {}
            for lay in styl.get("layers") or []:
                src = lay.get("source-layer")
                if not src:
                    continue        # `background` nemá zdroj
                z = lay.get("minzoom", 0)
                style_min[src] = min(style_min.get(src, z), z)

            for src, z in sorted(style_min.items()):
                if src not in schema_min:
                    bad.append(
                        f"podoba `{nazov}`, {meno}: vrstva štýlu má `source-layer: {src}`, ktorý "
                        f"tá podoba nemá (má {sorted(schema_min)}). MapLibre na to "
                        f"nepovie nič – tá vrstva v mape jednoducho nebude.")
                elif z != schema_min[src]:
                    preco = ("mapa má v tých zoomoch dieru"
                             if z < schema_min[src]
                             else "platia sa dlaždice, ktoré nikto nekreslí")
                    bad.append(
                        f"podoba `{nazov}`, {meno}: `{src}` sa kreslí od z{z}, ale schéma ju robí od "
                        f"z{schema_min[src]} – {preco}. Zrovnaj `minzoom` v "
                        f"{STYLE} s `min_zoom` v {SCHEMA}.")
            for src in schema_min:
                if src not in style_min:
                    bad.append(
                        f"podoba `{nazov}`, {meno}: schéma robí vrstvu `{src}`, ale štýl ju nekreslí "
                        f"ani raz. Buď ju dokresli, alebo ju zo schémy vyhoď – "
                        f"inak sú to dlaždice, za ktoré nikto nič nedostane.")

for b in bad:
    print(f"::error::{b}")
print(f"mapa sveta (schéma × štýl × {len(podoby)} podoby): {len(bad)} chýb")
sys.exit(1 if bad else 0)
