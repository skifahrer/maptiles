#!/usr/bin/env python3
"""Kontrola: dávka „Build map state" stavia to isté, čo by si postavil ručne.

Formulár pred formulárom – nastavenia cezeň len prechádzajú do behov krajov.
Rozíde sa to ticho: zdroj výšok, ktorý dávka nemá; nastavenie, ktoré sa pýta
a `relay.sh` ho nepodá; krajina bez krajov v číselníku.

`area` a `publish_pages` dávka nemá zámerne – výrez pre osem krajov nedáva
zmysel a osem behov by stránku osemkrát prepísalo.
"""
import json
import os
import re
import sys

import yaml

STATE = ".github/workflows/build-map-state.yml"
REGION = ".github/workflows/build-map-region.yml"
RELAY = "workers/state/relay.sh"
QUEUE = "workers/state/queue.py"
REGIONS = "workers/data/regions.json"
OPTIONS_PY = "workers/plan/options.py"
# vstupy dávky, ktoré nie sú nastavením mapy
VLASTNE = {"country", "pokracovanie"}
# čo dávka podáva natvrdo – inak by sa osem behov pobilo o Pages
NATVRDO = {"area": "cely_region", "publish_pages": "false"}

bad = 0


def chyba(subor, text):
    global bad
    bad += 1
    print(f"::error file={subor}::{text}")


def inputs(path):
    d = yaml.safe_load(open(path)) or {}
    on = d[[k for k in d if k is True or k == "on"][0]]
    return (on.get("workflow_dispatch") or {}).get("inputs") or {}


if not os.path.exists(STATE):
    print(f"::error::{STATE} neexistuje – dávka krajiny je preč.")
    sys.exit(1)

state_in = inputs(STATE)
region_in = inputs(REGION)
relay = open(RELAY).read()

# 1. formulár dávky sedí s formulárom kraja – nie „obsahuje to isté", ale
# „hodnoty sú tie isté"
for meno, spec in state_in.items():
    if meno in VLASTNE:
        continue
    if meno not in region_in:
        chyba(STATE, f"Dávka pýta `{meno}`, ale formulár kraja ({REGION}) "
                     f"taký vstup nemá – nemá ho komu podať.")
        continue
    a, b = spec or {}, region_in[meno] or {}
    for kluc in ("type", "default", "options"):
        if a.get(kluc) != b.get(kluc):
            chyba(STATE, f"Vstup `{meno}`: dávka má {kluc}={a.get(kluc)!r}, "
                         f"kraj {kluc}={b.get(kluc)!r}. Dávka je ten istý "
                         f"formulár o úroveň vyššie – iná predvoľba alebo iný "
                         f"zoznam znamená, že celá krajina vyjde inak než "
                         f"jeden kraj postavený ručne.")

# opačný smer: `area` a `publish_pages` tam nepatria zámerne, `region` dopĺňa dávka
for meno in region_in:
    if meno in state_in or meno in NATVRDO or meno == "region":
        continue
    chyba(STATE, f"Formulár kraja má `{meno}`, dávka nie. Buď ho dopýtaj, "
                 f"alebo ho podávaj natvrdo a dopíš do `NATVRDO` "
                 f"v {os.path.basename(__file__)} aj s dôvodom – "
                 f"inak sa celá krajina postaví s predvolenou hodnotou "
                 f"a nikto sa to z behu nedozvie.")

# 2. čo sa pýta, to sa aj podáva – nepodaný vstup je tichá lož
for meno in state_in:
    if meno in VLASTNE:
        continue
    if not re.search(rf"-f {re.escape(meno)}=", relay):
        chyba(RELAY, f"Dávka pýta `{meno}`, ale `relay.sh` ho behu kraja "
                     f"nepodáva (`-f {meno}=`) – celá krajina by sa postavila "
                     f"s predvolenou hodnotou, a zelená.")

for meno, hodnota in NATVRDO.items():
    if not re.search(rf"-f {re.escape(meno)}={re.escape(hodnota)}\b", relay):
        chyba(RELAY, f"`relay.sh` nepodáva `-f {meno}={hodnota}`. Práve tým sa "
                     f"dávka od jedného kraja líši a natvrdo to je zámer – "
                     f"rozpis je v hlavičke workflowu.")

# 3. výber krajín sedí s číselníkom – `type: choice` sa generovať nedá, len strážiť
sys.path.insert(0, os.path.dirname(os.path.abspath(QUEUE)))
regions = json.load(open(REGIONS))
KRAJ_LEVEL = 4
maju_kraje = [k for k, v in regions.items()
              if v.get("admin_level") != KRAJ_LEVEL
              and any(r.get("country") == k and r.get("admin_level") == KRAJ_LEVEL
                      for r in regions.values())]
ponuka = ((state_in.get("country") or {}).get("options")) or []
if ponuka != maju_kraje:
    chyba(STATE, f"Výber `country` je {ponuka}, podľa {REGIONS} má byť "
                 f"{maju_kraje} (krajiny, ktoré nejaký kraj naozaj majú). "
                 f"Krajina bez krajov je voľba, po ktorej dávka nemá čo "
                 f"spustiť.")

# 3b. dávka nepočíta to, čo už raz vzniklo: osem krajov × tri vrstvy z DEM je
# väčšina toho dňa. Kontroluje sa, že `relay.sh` dopĺňa `reuse_layers=true`
# aj že to `options.py` pozná.
VOLBA = "reuse_layers"
if f"{VOLBA}=true" not in relay:
    chyba(RELAY, f"`relay.sh` nedopĺňa behu kraja `{VOLBA}=true`. Dávka by "
                 f"potom v každom kraji počítala vrstevnice, skaly aj "
                 f"tieňovanie odznova, hoci s tými istými nastaveniami už "
                 f"raz vznikli – a je to väčšina dňa, ktorý dávka trvá.")
if f'"{VOLBA}"' not in open(OPTIONS_PY).read():
    chyba(OPTIONS_PY, f"`{VOLBA}` nie je medzi známymi voľbami, ale `relay.sh` "
                      f"ho podáva – každý kraj dávky by spadol na „neznáma "
                      f"voľba“ hneď v prípravnom jobe.")

# 4. štafeta si spúšťa samu seba – bez toho reťaz skončí prvým krajom, zelená
if "gh workflow run \"$SELF\"" not in relay:
    chyba(RELAY, "`relay.sh` si nespúšťa ďalší svoj beh (`gh workflow run "
                 "\"$SELF\"`). Bez toho dávka postaví prvý kraj a tvári sa, "
                 "že je hotová.")
if not re.search(r"timeout-minutes:\s*(\d+)", open(STATE).read()):
    chyba(STATE, "Job štafety nemá `timeout-minutes`. Strop jobu je 6 h "
                 "a čakanie na kraj má v skripte 5 h – bez stropu by sa "
                 "úsek, ktorý sa zasekol, držal bežca celých šesť.")
else:
    minut = int(re.search(r"timeout-minutes:\s*(\d+)", open(STATE).read()).group(1))
    if minut > 360:
        chyba(STATE, f"`timeout-minutes: {minut}` je nad stropom jobu (360). "
                     f"GitHub ho zabije skôr, než sa spustí ďalší článok.")

print(f"dávka krajiny: {bad} chýb ({len(state_in)} vstupov formulára, "
      f"{len(maju_kraje)} krajín s krajmi)")
sys.exit(1 if bad else 0)
