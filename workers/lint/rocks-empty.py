#!/usr/bin/env python3
"""Prázdne skaly z padnutého výpočtu sa nesmú uložiť ako hotová vrstva."""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_WORKERS)
ROCKS = os.path.join(_WORKERS, "contours-rocks", "rocks.sh")
SITE = os.path.join(_WORKERS, "contours-rocks", "site.sh")
PLAN = os.path.join(_WORKERS, "contours-rocks", "rock-plan.py")
FLOW = os.path.join(_ROOT, ".github", "workflows", "dem-layers.yml")
MARKER = "contours-out/rock-failed.txt"


def main():
    bad = []
    rocks = open(ROCKS, encoding="utf-8").read()
    site = open(SITE, encoding="utf-8").read()
    plan = open(PLAN, encoding="utf-8").read()
    flow = open(FLOW, encoding="utf-8").read()

    if not re.search(rf">\s*{re.escape(MARKER)}", rocks):
        bad.append(f"workers/contours-rocks/rocks.sh nezaznačí pád výpočtu do "
                   f"`{MARKER}`. Bez tej stopy sa prázdna vrstva uloží ako "
                   f"hotová a kraj ostane bez skál, kým platí kľúč cache.")

    # krok sa hľadá podľa toho, čo ukladá, nie podľa mena: meno je preklep
    ulozenie = [ln for ln in flow.splitlines()
                if "if:" in ln
                and "steps.hotove.outputs.pocitaj == 'true'" in ln
                and "contours-out/rock" in ln]
    if not ulozenie:
        bad.append("v .github/workflows/dem-layers.yml sa nedá nájsť krok, "
                   "ktorý ukladá skaly do cache – oprav túto kontrolu spolu "
                   "s workflowom.")
    else:
        for podmienka, preco in (
                ("hashFiles('contours-out/rocks.pmtiles') != ''",
                 "beh, ktorý sa k dlaždiciam vôbec nedostal (napr. pád "
                 "v sklone), sa uloží ako hotová vrstva"),
                (f"hashFiles('{MARKER}') == ''",
                 "prázdna vrstva z padnutého výpočtu sa uloží ako hotová")):
            if not any(podmienka in ln for ln in ulozenie):
                bad.append(f"ukladanie skál do cache v dem-layers.yml nemá "
                           f"podmienku `{podmienka}` – {preco} a ďalšie behy "
                           f"ju vezmú z cache.")

    if MARKER not in site:
        bad.append(f"workers/contours-rocks/site.sh sa nepozerá na `{MARKER}` "
                   f"– prázdny `.pmtiles` pôjde do mapy aj do balíka a tam sa "
                   f"nedá odlíšiť od kraja, v ktorom skaly nie sú.")

    if "capture_output=True" in plan and not re.search(r"raise\s+ChybaPrikazu",
                                                       plan):
        bad.append("workers/contours-rocks/rock-plan.py zahadzuje stderr "
                   "spustených príkazov – z pádu ogr2ogr ostane len „exit "
                   "status 1\" a nie je podľa čoho ho opraviť.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Skaly: pád výpočtu sa zaznačí, neuloží sa do cache, nejde do mapy "
          "a v logu je aj stderr ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
