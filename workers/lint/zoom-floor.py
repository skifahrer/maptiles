#!/usr/bin/env python3
"""Vrstevnice a skaly sa nedláždia pod tým zoomom, od ktorého ich štýl kreslí.

Dno zoomu je na dvoch miestach a inak to nejde: schéma rozhoduje, čo sa
vyrobí, štýl, čo sa nakreslí. Schéma nižšie = dlaždice, ktoré nikto nekreslí;
štýl nižšie = diera v mape. Ani jedno nikto nepovie.
"""
import os
import re
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_WORKERS)

THEMES = os.path.join(_ROOT, "poc", "web", "themes.js")
CONTOURS = os.path.join(_WORKERS, "contours-rocks", "contours.yml")
ROCKS = os.path.join(_WORKERS, "contours-rocks", "rocks.yml")

# Pod týmto zoomom nemá byť v mape ani vrstevnica, ani skala: na tej mierke sa
# nedá prečítať ani jedna čiara a zo skál je sivá škvrna – a dlaždice s nimi si
# prehliadač aj tak stiahne. Nad ním je z vrstevníc povolená LEN hlavná trieda
# (`major`), ostatné dve majú vlastné, vyššie dno.
FLOOR = 11


def schema_min_zoom(path, layer, include=None):
    """`min_zoom` prvku vrstvy zo schémy Planetilera.

    `include` vyberá spomedzi viacerých prvkov ten, ktorý má daný
    `include_when` (vrstevnice majú tri triedy v jednej vrstve).
    """
    doc = yaml.safe_load(open(path))
    for lay in doc.get("layers", []):
        if lay.get("id") != layer:
            continue
        for feat in lay.get("features", []):
            when = feat.get("include_when") or {}
            if include is None or include in when.values():
                return feat.get("min_zoom")
    return None


def named_z(text, token):
    """Číslo z výrazu v štýle – buď literál, alebo meno konštanty.

    Dno zoomu je v štýle napísané ako `TERRAIN_MIN_Z` (jedno miesto pre obe
    vrstvy), takže sa meno musí dať rozviazať na hodnotu – inak by kontrola
    strážila text a nie číslo.
    """
    token = token.strip()
    if token.isdigit():
        return int(token)
    m = re.search(r"export const " + re.escape(token) + r"\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def style_min_zoom(text, layer_id):
    """`minzoom` vrstvy štýlu – hľadá sa za jej `id`."""
    m = re.search(r'id:\s*"' + re.escape(layer_id) + r'"', text)
    if not m:
        return None
    m2 = re.search(r"minzoom:\s*([A-Za-z_0-9]+)", text[m.end():m.end() + 1200])
    return named_z(text, m2.group(1)) if m2 else None


def contour_line_min_zoom(text, level):
    """`contourLine("major", …, TERRAIN_MIN_Z, …)` – dno triedy v štýle.

    Vrstvy vrstevníc štýl neskladá po jednej, ale jednou funkciou pre všetky
    tri triedy, takže sa číta jej volanie a nie `minzoom:`.
    """
    m = re.search(r'contourLine\(\s*"[^"]+"\s*,\s*"[^"]*"\s*,\s*"'
                  + re.escape(level) + r'"\s*,\s*([A-Za-z_0-9]+)', text, re.S)
    return named_z(text, m.group(1)) if m else None


def main():
    text = open(THEMES, encoding="utf-8").read()
    bad = []

    checks = [
        ("vrstevnice (trieda major)",
         schema_min_zoom(CONTOURS, "contour", include="major"),
         contour_line_min_zoom(text, "major"),
         'workers/contours-rocks/contours.yml (min_zoom triedy major) '
         'vs poc/web/themes.js (contourLine("major", …))'),
        ("skaly",
         schema_min_zoom(ROCKS, "rock"),
         style_min_zoom(text, "rock-area"),
         "workers/contours-rocks/rocks.yml (min_zoom) vs "
         "poc/web/themes.js (vrstva rock-area)"),
    ]

    for what, schema, style, kde in checks:
        if schema is None or style is None:
            bad.append(f"{what}: dno zoomu sa nedá prečítať "
                       f"(schéma={schema}, štýl={style}) – {kde}. "
                       f"Keď sa tie miesta prepisujú, uprav aj túto kontrolu.")
            continue
        if schema != style:
            bad.append(f"{what}: schéma vyrába od z{schema}, štýl kreslí od "
                       f"z{style} – to je buď platenie za dlaždice, ktoré "
                       f"nikto nevidí, alebo diera v mape. Zrovnaj {kde}.")
        elif schema < FLOOR:
            bad.append(f"{what}: dno je z{schema}, ale pod z{FLOOR} sa "
                       f"vrstevnice ani skaly nekreslia (nedá sa tam prečítať "
                       f"ani jedna čiara a podklady sú za to väčšie). "
                       f"Zdvihni ho v {kde}.")
        else:
            print(f"  ✓ {what}: od z{schema} v schéme aj v štýle")

    # Druhá polovica želania „pod z12 nech je LEN jedna vrstevnica": zvyšné dve
    # triedy musia mať dno vyššie než hlavná, inak sa na malej mierke zlejú.
    major = contour_line_min_zoom(text, "major")
    for level in ("mid", "minor"):
        z = contour_line_min_zoom(text, level)
        if z is None:
            bad.append(f"vrstevnice: triedu {level} sa v štýle nepodarilo "
                       f"nájsť – uprav kontrolu alebo štýl.")
        elif major is not None and z <= major:
            bad.append(f"vrstevnice: trieda {level} sa kreslí od z{z}, teda "
                       f"nie vyššie než hlavná (z{major}). Na malej mierke má "
                       f"byť v mape LEN hlavná vrstevnica, inak je z nich "
                       f"šmuha a podklady sú dvojnásobné.")
        else:
            print(f"  ✓ vrstevnice (trieda {level}): od z{z}, nad hlavnou")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Dno zoomu vrstevníc a skál je v schéme aj v štýle rovnaké ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
