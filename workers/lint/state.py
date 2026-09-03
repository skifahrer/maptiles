#!/usr/bin/env python3
"""
Kontrola: dávka „Build map state" stavia to isté, čo by si postavil ručne.

PREČO. Dávka je formulár pred formulárom – zdroje výšok, prah skál, `rebuild`
aj `options` cez ňu len prechádzajú do behov jednotlivých krajov
(`workers/state/relay.sh`). To je presne ten druh vrstvy, ktorá sa rozíde
ticho:

  * do formulára kraja pribudne zdroj výšok a do dávky nie – kto ho zvolí
    v jednom kraji, v dávke ho nemá a nič mu to nepovie;
  * nastavenie sa v dávke PÝTA, ale `relay.sh` ho behu kraja nepodá – celá
    krajina sa postaví s predvolenými hodnotami a bude zelená;
  * do dávky pribudne krajina, ktorá v číselníku kraje nemá – po jej zvolení
    dávka nemá čo spustiť.

Ani jedno by beh nezhodilo, a práve preto to má strážiť lint.

Čo sa NEKONTROLUJE a je to zámer: `area` a `publish_pages` dávka nemá a mať
nesmie – výrez (pohorie) pre osem krajov nedáva zmysel a Pages unesú jednu
mapu, takže osem behov za sebou by stránku osemkrát prepísalo. Že ich
`relay.sh` podáva natvrdo, sa kontroluje nižšie.

Spustiť sa dá aj lokálne:
    python3 workers/lint/state.py
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
# Vstupy dávky, ktoré NIE SÚ nastavením mapy: krajina je to, čo sa stavia,
# `pokracovanie` je štafetový kolík. Zvyšok musí sedieť s formulárom kraja.
VLASTNE = {"country", "pokracovanie"}
# Čo dávka podáva natvrdo a prečo (viď hlavičku). Kontroluje sa, že to
# v `relay.sh` naozaj stojí – inak by sa osem behov pobilo o Pages.
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

# ---------- 1. formulár dávky sedí s formulárom kraja ----------
# Nie „obsahuje to isté", ale „hodnoty sú tie isté": keby dávka ponúkala
# zdroj výšok, ktorý kraj nepozná, beh kraja by spadol až na kontrole volieb –
# po tom, čo dávka spustila osem behov.
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

# Opačný smer: čo formulár kraja má a dávka nie. `area` a `publish_pages` tam
# nepatria zámerne (viď hlavičku), `region` je to, čo dávka práve dopĺňa.
for meno in region_in:
    if meno in state_in or meno in NATVRDO or meno == "region":
        continue
    chyba(STATE, f"Formulár kraja má `{meno}`, dávka nie. Buď ho dopýtaj, "
                 f"alebo ho podávaj natvrdo a dopíš do `NATVRDO` "
                 f"v {os.path.basename(__file__)} aj s dôvodom – "
                 f"inak sa celá krajina postaví s predvolenou hodnotou "
                 f"a nikto sa to z behu nedozvie.")

# ---------- 2. čo sa pýta, to sa aj podáva ----------
# Vstup, ktorý `relay.sh` nepodá ďalej, je tichá lož: formulár sa spýtal,
# beh kraja dostal default.
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

# ---------- 3. výber krajín sedí s číselníkom ----------
# `type: choice` sa v YAMLe nedá generovať, ale dá sa strážiť, aby zoznam
# nezostarol – to isté, čo robí „Kontrola · lint workflowov" s pohoriami.
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

# ---------- 4. štafeta si spúšťa samu seba ----------
# Bez toho reťaz skončí prvým krajom – a skončí ZELENÁ.
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
