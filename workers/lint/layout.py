#!/usr/bin/env python3
"""Workery ležia v priečinku podľa jobu – a presne jednu úroveň hlboko.

Pri presune z plochého zoznamu ticho prestali platiť kontroly, ktoré si cesty
hľadali vzorom `workers/*.sh`: lomku nechytí ani jeden a všetky prešli na
prázdnom zozname.

  1. v `workers/` samotnom nesmie ležať spustiteľný worker;
  2. hĺbka je presne jedna úroveň – moduly si spoločné veci hľadajú cez
     `os.path.dirname(_HERE)`, čo je `workers/` len z `workers/<job>/`;
  3. priečinok musí byť známy: nový job dopíš sem aj do tabuľky v CLAUDE.md.
"""
import os
import sys

# Priečinok = job (alebo workflow, ktorý ten job volá). Musí sedieť s tabuľkou
# v CLAUDE.md („Ako je usporiadané workers/") – dva zoznamy toho istého sa raz
# rozídu, tak je jeden z nich tu a druhý je odkaz naň.
ZNAME = {
    "data": "číselníky (areas, regions, dem-sources)",
    "lib": "čo patrí viacerým jobom (watch, planetiler, png, rozpočet)",
    "plan": "joby `settings`, `plan` a `keys`",
    "dem": "job `check-dem` a doplnenie modelu",
    "drive": "Google Drive: DMR 5.0, sklad, cache, prihlásenie",
    "contours-rocks": "joby `contours` a `rocks`",
    "rocks-shading": "workflow „Dáta · tieňované skaly“",
    "terrain": "job `terrain`",
    "trails": "job `trails`",
    "features": "job `features`",
    "transport": "workflow „Mapa · dopravná sieť“ (transport.yml)",
    "boundaries": "workflow „Mapa · hranice území“ (boundaries.yml)",
    "water": "workflow „Mapa · vodstvo“ (water.yml)",
    "search": "job `search` (vyhľadávací index)",
    "routing": "profil navigácie (costing pre Valhallu / GraphHopper)",
    "tiles": "job `tiles`",
    "wiki": "workflow „Build wiki“ (wiki.yml)",
    "world": "workflow „Build svet“ (world-map.yml)",
    "state": "workflow „Build map state“ (dávka krajov krajiny)",
    "assets": "job `assets`",
    "styles": "štýly pre web aj iOS",
    "deploy": "job `deploy` a publikovanie",
    "lint": "kontroly, ktoré púšťa lint-workflows.yml",
    "tools": "mimo buildu (upratovanie)",
}
PRIPONY = (".py", ".sh", ".mjs")

bad = 0
korene = sorted(f for f in os.listdir("workers")
                if os.path.isfile(os.path.join("workers", f)))
for f in korene:
    if f.endswith(PRIPONY):
        print(f"::error file=workers/{f}::worker leží priamo vo `workers/`, "
              f"nie v priečinku podľa jobu. Presuň ho do `workers/<job>/` – "
              f"kontroly (dĺžka súboru, env krokov, publikovanie) hľadajú "
              f"`workers/<job>/*` a na tento by sa ticho nepozreli.")
        bad += 1

for meno in sorted(os.listdir("workers")):
    cesta = os.path.join("workers", meno)
    if not os.path.isdir(cesta) or meno == "__pycache__":
        continue
    if meno not in ZNAME:
        print(f"::error file={cesta}::neznámy priečinok `{meno}`. Priečinok je "
              f"job – dopíš ho do ZNAME v tomto skripte a do tabuľky "
              f"v CLAUDE.md, alebo súbory presuň k jobu, ktorému patria.")
        bad += 1
        continue
    for koren, _, subory in os.walk(cesta):
        if "__pycache__" in koren:
            continue
        hlbka = koren.count(os.sep)
        for s in subory:
            if not s.endswith(PRIPONY):
                continue
            if hlbka > 1:  # workers/<job> = 1
                print(f"::error file={os.path.join(koren, s)}::worker je hlbšie "
                      f"než `workers/<job>/`. Moduly si spoločné veci hľadajú "
                      f"cez `os.path.dirname(_HERE)`, a to znamená `workers/` "
                      f"len pri hĺbke jedna – z druhej úrovne mieri `_DATA` "
                      f"vedľa.")
                bad += 1

pocty = {m: len([s for s in os.listdir(os.path.join("workers", m))
                 if s.endswith(PRIPONY)])
         for m in ZNAME if os.path.isdir(os.path.join("workers", m))}
print("workery podľa jobu: "
      + ", ".join(f"{m} {n}" for m, n in sorted(pocty.items()) if n))
print(f"usporiadanie workers/: {bad} chýb")
sys.exit(1 if bad else 0)
