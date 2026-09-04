#!/usr/bin/env python3
"""
Kontrola: výber `rebuild` naozaj prepočíta to, čo sľubuje.

PREČO. `rebuild` je jediná páka, ktorou sa dá povedať „nepoužívaj cache, spočítaj
to nanovo". Keď sľúbi vrstvu a tá sa aj tak vráti z cache, beh je ZELENÝ
a výsledok je ten starý – teda pravidlo 8 v čistej podobe. Rozísť sa to vie
tromi tichými spôsobmi:

  * hodnota vo formulári, ktorú `workers/plan/options.py` nepozná (alebo naopak
    hodnota v `REBUILD`, ktorú formulár neponúka – tú si nikto nevyberie);
  * príznak v `REBUILD`, ktorý nikto nevydá ako výstup jobu `plan`, takže sa
    k jobu, ktorý má prepočítať, nedostane a ostane prázdny;
  * `rebuild: skaly` pri `rock_source: tienovanie`. Skaly vtedy nepočíta sklon
    z výškového modelu, ale podpipeline `Dáta · tieňované skaly` – a tá si
    odkladá rozrobené obrysy. Bez `fresh=1` na ne nadviaže, takže „pregenerovať
    skaly" vráti výsledok predošlého behu.

MENO VO FORMULÁRI JE SLOVENSKÉ MENO VRSTVY. Výber sa kedysi volal `teren`,
kým tú istú vrstvu vyberá `shading_source` („Tieňovanie a 3D terén"), balík je
`-tienovanie.zip` a v katalógu je `terrain_source`. Kto ju chcel prepočítať,
hľadal v zozname „tieňovanie" a usúdil, že sa nedá. Staré meno preto ostáva
prijímané ako alias (`REBUILD_ALIAS`), ale nesmie sa ponúkať – dve mená pre
jednu vec vo formulári sú horšie než jedno.

Spustiť sa dá aj lokálne:
    python3 workers/lint/rebuild.py
"""
import importlib.util
import sys

import yaml

WORKFLOW = ".github/workflows/build-map-region.yml"
# Vrstvy z výškového modelu (a s nimi podpipeline skál z tieňovania) sa
# z buildu presťahovali do vlastného workflowu – volá ho aj pregenerovanie
# jednej vrstvy, takže by druhá kópia bola druhá pravda o tom, či sa cache
# naozaj zahodí.
VRSTVY = ".github/workflows/dem-layers.yml"
OPTIONS = "workers/plan/options.py"

bad = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    opts = load("plan_options", OPTIONS)
except Exception as exc:                      # noqa: BLE001 – čokoľvek je chyba
    print(f"::error::{OPTIONS} sa nedá načítať: {exc!r}")
    sys.exit(1)

try:
    wf = yaml.safe_load(open(WORKFLOW, encoding="utf-8"))
    vrstvy = yaml.safe_load(open(VRSTVY, encoding="utf-8"))
    # Príznak musí byť ČÍTANÝ, a číta ho ktorýkoľvek z tých dvoch súborov:
    # build ho podáva ďalej, vrstvy ho používajú.
    text = (open(WORKFLOW, encoding="utf-8").read()
            + open(VRSTVY, encoding="utf-8").read())
except (OSError, ValueError) as exc:
    print(f"::error::{WORKFLOW} alebo {VRSTVY} sa nedá prečítať: {exc}")
    sys.exit(1)

# `on` je v YAMLe pravdivostná hodnota `True` – preto sa hľadá oboje.
on = wf.get("on") or wf.get(True) or {}
inputs = ((on.get("workflow_dispatch") or {}).get("inputs") or {})
vo_formulari = list((inputs.get("rebuild") or {}).get("options") or [])

if not vo_formulari:
    bad.append(f"{WORKFLOW}: input `rebuild` nemá výber hodnôt – nedá sa "
               f"z formulára povedať, čo prepočítať nanovo.")

zname = set(opts.REBUILD)
alias = set(getattr(opts, "REBUILD_ALIAS", {}))

for v in vo_formulari:
    if v in alias:
        bad.append(f"{WORKFLOW}: `rebuild` ponúka `{v}`, čo je staré meno pre "
                   f"`{opts.REBUILD_ALIAS[v]}`. Prijímať sa má (beh sa opakuje "
                   f"tlačidlom Re-run s pôvodnými hodnotami), ponúkať nie – "
                   f"dve mená pre jednu vec sú vo formulári horšie než jedno.")
    elif v not in zname:
        bad.append(f"{WORKFLOW}: `rebuild` ponúka `{v}`, ktoré {OPTIONS} "
                   f"nepozná (pozná {sorted(zname)}) – beh by spadol hneď "
                   f"v prípravnom jobe.")

for v in sorted(zname - set(vo_formulari)):
    bad.append(f"{OPTIONS}: `REBUILD` pozná `{v}`, ale formulár v {WORKFLOW} "
               f"to neponúka – hodnotu, ktorá sa nedá vybrať, nikto "
               f"nepoužije.")

# ---- príznak sa musí dostať z `plan` do jobu, ktorý prepočítava ----
plan_outputs = ((wf.get("jobs") or {}).get("plan") or {}).get("outputs") or {}
for flag in opts.REBUILD_FLAGS:
    if f"opt_{flag}" not in plan_outputs:
        bad.append(f"{WORKFLOW}: job `plan` nevydáva `opt_{flag}`, takže sa "
                   f"príznak k jobu, ktorý má prepočítať, nedostane – "
                   f"pregenerovanie by ticho nespravilo nič.")
    elif f"needs.plan.outputs.opt_{flag}" not in text:
        bad.append(f"{WORKFLOW}: `opt_{flag}` nikto nečíta "
                   f"(`needs.plan.outputs.opt_{flag}`) – výber v formulári by "
                   f"sľúbil prepočet, ktorý sa nekoná.")

# ---- skaly z tieňovania: `rebuild: skaly` musí zahodiť aj rozrobené obrysy ----
sr = ((vrstvy.get("jobs") or {}).get("shading-rocks") or {}).get("with") or {}
sr_options = str(sr.get("options", ""))
if not sr_options:
    bad.append(f"{VRSTVY}: job `shading-rocks` nedostáva `options`, takže mu "
               f"nemá ako povedať `fresh=1`.")
else:
    if "fresh=1" not in sr_options:
        bad.append(f"{VRSTVY}: `shading-rocks` nedostáva `fresh=1` nikdy – "
                   f"nadviaže na rozrobené obrysy z predošlého behu aj vtedy, "
                   f"keď si vyberieš pregenerovanie.")
    if "opt_rocks_rebuild" not in sr_options:
        bad.append(f"{VRSTVY}: `rebuild: skaly` sa do `shading-rocks` "
                   f"nedostane (`options` nespomína `opt_rocks_rebuild`). Pri "
                   f"`rock_source: tienovanie` sa sklon nepočíta vôbec – obrysy "
                   f"robí táto podpipeline a bez `fresh=1` vráti tie staré. "
                   f"Beh je pri tom zelený.")

for b in bad:
    print(f"::error::{b}")
print(f"výber `rebuild`: {len(bad)} chýb")
sys.exit(1 if bad else 0)
