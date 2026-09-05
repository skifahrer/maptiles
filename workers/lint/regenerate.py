#!/usr/bin/env python3
"""Kontrola: dávka „Regenerate state" pregeneruje to, čo sľubuje.

Formulár pred formulárom, ktorý si navyše vyberá, ČO sa pregeneruje, a podľa
toho spúšťa dve rôzne pipeline. Rozíde sa to ticho a beh ostane zelený:
voľba, ktorú číselník nepozná (štafeta spadne až po spustení), pole navyše
(beh kraja spadne hneď na vstupe, osemkrát za sebou), nastavenie, ktoré sa
pýta a nepodáva (celá krajina s predvolenými hodnotami), balík, ktorý packer
nepozná, rozídené podiely na rozpočte, a voľba, ktorú ani jeden job nespomína
(beh dobehne zelený a nespraví nič).
"""
import importlib.util
import json
import os
import re
import sys

import yaml

STATE = ".github/workflows/regenerate-state.yml"
REGION = ".github/workflows/regenerate-region.yml"
BUILD = ".github/workflows/build-map-region.yml"
RELAY = "workers/state/regenerate.sh"
JADRO = "workers/state/estafeta.sh"
JOBS = "workers/state/jobs.py"
CISELNIK = "workers/data/packages.json"
with open(CISELNIK, encoding="utf-8") as _f:
    ZNAME_BALIKY = {b["kluc"] for b in json.load(_f).get("baliky") or []}
REGIONS = "workers/data/regions.json"
WF_DIR = ".github/workflows"
# vstupy dávky, ktoré nie sú nastavením behu
VLASTNE = {"country", "co", "pokracovanie"}
# podiely na rozpočte musia byť rovnaké ako v builde – `env:` sa nededí
PODIELY = ("BUDGET_TRAILS_PCT", "BUDGET_FEATURES_PCT", "BUDGET_TRANSPORT_PCT",
           "BUDGET_BOUNDARIES_PCT", "BUDGET_WATER_PCT",
           "BUDGET_CONTOURS_PCT", "BUDGET_ROCKS_PCT", "BUDGET_TERRAIN_PCT")
KRAJ_LEVEL = 4

bad = 0


def chyba(subor, text):
    global bad
    bad += 1
    print(f"::error file={subor}::{text}")


def wf(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def inputs(data):
    # `on` je v YAMLe pravdivostná hodnota `True`
    on = data.get("on") or data.get(True) or {}
    return (on.get("workflow_dispatch") or {}).get("inputs") or {}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


for path in (STATE, REGION, RELAY, JADRO, JOBS):
    if not os.path.exists(path):
        print(f"::error::{path} neexistuje – dávka pregenerovania je preč.")
        sys.exit(1)

jobs = load("state_jobs", JOBS)
state = wf(STATE)
region = wf(REGION)
build = wf(BUILD)
state_in = inputs(state)
region_in = inputs(region)
build_in = inputs(build)
relay = open(RELAY, encoding="utf-8").read()

# 1. formulár dávky ponúka presne to, čo číselník pozná
ponuka = list((state_in.get("co") or {}).get("options") or [])
if ponuka != list(jobs.JOBS):
    chyba(STATE, f"Výber `co` je {ponuka}, podľa {JOBS} má byť "
                 f"{list(jobs.JOBS)}. Voľba, ktorú číselník nepozná, spadne "
                 f"až v behu; vec, ktorá je v číselníku a nie vo formulári, "
                 f"si nikto nevyberie.")

# 2. to isté pre formulár nad jedným krajom – ani viac, ani menej
cez_kraj = [k for k, v in jobs.JOBS.items()
            if v["workflow"] == os.path.basename(REGION)]
ponuka_kraj = list((region_in.get("co") or {}).get("options") or [])
if ponuka_kraj != cez_kraj:
    chyba(REGION, f"Výber `co` je {ponuka_kraj}, podľa {JOBS} má byť "
                  f"{cez_kraj} (to, čo cez tento workflow naozaj chodí). "
                  f"Dávka by inak spustila beh s hodnotou, ktorú tento "
                  f"formulár nepozná – a ten spadne hneď na vstupe.")

# 3. číselník podáva len to, čo cieľový formulár má
# prázdne prostredie zámerne: kontroluje sa tvar, nie vyplnené hodnoty
for kluc, j in jobs.JOBS.items():
    ciel = os.path.join(WF_DIR, j["workflow"])
    if not os.path.exists(ciel):
        chyba(JOBS, f"`{kluc}` sa má spustiť workflowom `{j['workflow']}`, "
                    f"ktorý neexistuje ({ciel}).")
        continue
    ciel_in = inputs(wf(ciel))
    if "region" not in ciel_in:
        chyba(JOBS, f"`{j['workflow']}` nemá vstup `region`, ale štafeta mu "
                    f"ho podáva – dávka nemá ako povedať, ktorý kraj to je.")
    for meno, hodnota in jobs.polia(kluc, env={}).items():
        spec = ciel_in.get(meno)
        if spec is None:
            chyba(JOBS, f"`{kluc}` podáva `{j['workflow']}` pole `{meno}`, "
                        f"ktoré ten formulár nemá – beh kraja by spadol hneď "
                        f"na vstupe.")
            continue
        volby = spec.get("options")
        if volby and hodnota not in volby:
            chyba(JOBS, f"`{kluc}` podáva `{meno}={hodnota}`, ale "
                        f"`{j['workflow']}` ponúka {volby}.")
    # balík, ktorý packer nepozná, spadne až na `--only`; zoznam drží číselník
    if j["balik"] not in ZNAME_BALIKY:
        chyba(JOBS, f"`{kluc}` sľubuje balík `{j['balik']}`, ktorý "
                    f"{CISELNIK} nepozná – beh by spadol na `--only`.")

# 3b. každú voľbu niekto naozaj robí
# voľba, ktorú ani jeden job nespomína, je najtichšia chyba: všetky joby sa
# preskočia a beh je zelený
region_text = open(REGION, encoding="utf-8").read()
for kluc in ponuka_kraj:
    if f"inputs.co == '{kluc}'" not in region_text:
        chyba(REGION, f"Voľbu `{kluc}` nespomína ani jedna podmienka jobu "
                      f"(`inputs.co == '{kluc}'`) – beh by ju prijal, "
                      f"preskočil všetky joby a skončil zelený bez toho, aby "
                      f"čokoľvek pregeneroval.")

# 4. čo sa pýta, to sa aj podáva – nepodaný vstup je tichá lož
for meno in state_in:
    if meno == "pokracovanie":
        continue
    if not re.search(rf"-f {re.escape(meno)}=", relay):
        chyba(RELAY, f"Dávka pýta `{meno}`, ale `regenerate.sh` ho ďalšiemu "
                     f"článku štafety nepodáva (`-f {meno}=`) – reťaz by od "
                     f"druhého kraja pregenerovala niečo iné, a zelená.")

# nastavenia musia ísť aj do behu kraja – cez číselník
podava = {m for c in jobs.CIELE.values() for m in c["podava"]}
for meno in state_in:
    if meno in VLASTNE or meno in podava:
        continue
    chyba(JOBS, f"Dávka pýta `{meno}`, ale ani jeden cieľ v `CIELE` ho behu "
                f"kraja nepodáva – celá krajina by sa pregenerovala "
                f"s predvolenou hodnotou a nikto sa to z behu nedozvie.")

# 5. nastavenia sedia s formulárom kraja – nie „obsahuje to isté", ale
# „hodnoty sú tie isté"
for meno, spec in state_in.items():
    if meno in VLASTNE:
        continue
    vzor = build_in.get(meno) or region_in.get(meno)
    if vzor is None:
        chyba(STATE, f"Dávka pýta `{meno}`, ale ani formulár kraja "
                     f"({BUILD}), ani {REGION} taký vstup nemá – nemá ho "
                     f"komu podať.")
        continue
    for kluc in ("type", "default", "options"):
        if (spec or {}).get(kluc) != (vzor or {}).get(kluc):
            chyba(STATE, f"Vstup `{meno}`: dávka má {kluc}="
                         f"{(spec or {}).get(kluc)!r}, formulár kraja "
                         f"{kluc}={(vzor or {}).get(kluc)!r}. Dávka je ten "
                         f"istý formulár o úroveň vyššie.")

# 6. kraje sa ponúkajú tie isté ako v builde
a = list((region_in.get("region") or {}).get("options") or [])
b = list((build_in.get("region") or {}).get("options") or [])
if a != b:
    chyba(REGION, f"Výber `region` je {a}, build mapy ponúka {b}. Kraj, "
                  f"ktorý sa dá postaviť, sa musí dať aj pregenerovať – inak "
                  f"v ňom vrstva ostarne a nikto sa to nedozvie.")

# 7. výber krajín sedí s číselníkom regiónov
regions = json.load(open(REGIONS, encoding="utf-8"))
maju_kraje = [k for k, v in regions.items()
              if v.get("admin_level") != KRAJ_LEVEL
              and any(r.get("country") == k
                      and r.get("admin_level") == KRAJ_LEVEL
                      for r in regions.values())]
ponuka_kr = list((state_in.get("country") or {}).get("options") or [])
if ponuka_kr != maju_kraje:
    chyba(STATE, f"Výber `country` je {ponuka_kr}, podľa {REGIONS} má byť "
                 f"{maju_kraje} (krajiny, ktoré nejaký kraj naozaj majú).")

# 8. podiely na rozpočte sa nerozišli s buildom
def env_hodnoty(data):
    return {k: str(v) for k, v in (data.get("env") or {}).items()}


e_reg, e_build = env_hodnoty(region), env_hodnoty(build)
for k in PODIELY:
    if k not in e_reg:
        chyba(REGION, f"`env:` nemá `{k}`, ale skript vrstvy ho číta – "
                      f"podiel by bol prázdny a `$(( … ))` by spadlo.")
    elif e_reg[k] != e_build.get(k):
        chyba(REGION, f"`{k}` je tu {e_reg[k]!r}, v {BUILD} "
                      f"{e_build.get(k)!r}. `env:` workflowu sa nededí, takže "
                      f"je napísaný dvakrát – a keď sa rozídu, tá istá vrstva "
                      f"varuje z pregenerovania inak než z buildu.")

# 9. štafeta si spúšťa samu seba a stojí na spoločnom jadre
if 'gh workflow run "$SELF"' not in relay:
    chyba(RELAY, "`regenerate.sh` si nespúšťa ďalší svoj beh "
                 "(`gh workflow run \"$SELF\"`). Bez toho dávka pregeneruje "
                 "prvý kraj a tvári sa, že je hotová.")
if os.path.basename(JADRO) not in relay:
    chyba(RELAY, f"`regenerate.sh` nevychádza z {JADRO}. Druhá kópia štafety "
                 f"by sa raz rozišla práve v tom, či reťaz pokračuje.")

text = open(STATE, encoding="utf-8").read()
m = re.search(r"timeout-minutes:\s*(\d+)", text)
if not m:
    chyba(STATE, "Job štafety nemá `timeout-minutes`. Strop jobu je 6 h "
                 "a čakanie na kraj má v skripte 5 h – bez stropu by sa úsek, "
                 "ktorý sa zasekol, držal bežca celých šesť.")
elif int(m.group(1)) > 360:
    chyba(STATE, f"`timeout-minutes: {m.group(1)}` je nad stropom jobu (360). "
                 f"GitHub ho zabije skôr, než sa spustí ďalší článok.")

print(f"dávka pregenerovania: {bad} chýb ({len(jobs.JOBS)} vecí na "
      f"pregenerovanie, {len(state_in)} vstupov formulára)")
sys.exit(1 if bad else 0)
