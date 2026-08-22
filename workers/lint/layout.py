#!/usr/bin/env python3
"""
Workery ležia v priečinku podľa jobu – a presne jednu úroveň hlboko.

PREČO TO JE KONTROLA. Keď sa `workers/` presúvalo z plochého zoznamu do
priečinkov, ticho prestali platiť kontroly, ktoré si cesty hľadali vzorom
`workers/*.sh` alebo regexom `workers/[\\w.-]+\\.sh`. Ani jeden z nich nechytí
lomku, takže `workers/dem/check.sh` im nesedel a všetky prešli na prázdnom
zozname – zelené, hoci nepozreli na nič. To je presne ten druh tichého omylu,
ktorý je horší než pád (pravidlo 8).

ČO SA STRÁŽI:

  1. V `workers/` samotnom nesmie ležať spustiteľný worker. Keď tam niekto
     pridá nový skript „len nateraz", vypadne zo všetkých kontrol naraz.
  2. Hĺbka je presne jedna úroveň. Python moduly si spoločné veci hľadajú cez
     `os.path.dirname(_HERE)`, čo znamená `workers/` len vtedy, keď skript sedí
     v `workers/<job>/`. Z druhej úrovne by to ukázalo o priečinok vedľa
     a `_DATA` by mierilo do neexistujúceho miesta.
  3. Priečinok musí byť známy – nie preklep. Nový job = dopíš ho sem aj do
     tabuľky v CLAUDE.md, nech tie dva zoznamy ostanú jeden.

Spustiť sa dá aj lokálne: `python3 workers/lint/layout.py`.
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
    "search": "job `search` (vyhľadávací index)",
    "routing": "profil navigácie (costing pre Valhallu / GraphHopper)",
    "tiles": "job `tiles`",
    "wiki": "workflow „Build wiki“ (wiki.yml)",
    "world": "workflow „Build svet“ (world-map.yml)",
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
