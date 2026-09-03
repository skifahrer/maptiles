#!/usr/bin/env python3
"""
Kontrola „publikuje sa len na Drive". Volá ju `Kontrola · lint workflowov`.

ČO STRÁŽI. Do GitHubu nesmie ísť ani release, ani artefakt, ktorý má prežiť
beh. Všetko, čo pipeline vyrobí a chce si nechať, ide do skladu na Google Drive
(`workers/drive/store.py`) – výškové modely, skaly, tieňovanie, hotové mapy aj
medzivýsledky na pozretie.

PREČO KONTROLA A NIE LEN DOHODA. `gh release upload` je jeden riadok a keby sa
vrátil, poznalo by sa to len tým, že v Releases pribúdajú gigabajty, ktoré nikto
nečíta – a že tá istá vec leží na dvoch miestach (pravidlo 1 v CLAUDE.md).
Rovnako `retention-days: 90`: artefakt s takou retenciou je uložený výsledok,
nie prepravka medzi jobmi jedného behu.

A tretia vec, ktorá by inak bola TICHÁ: preklep v mene skladu. `--store=`
s neznámym menom neskončí chybou, ale prázdnym skladom – teda „počítaj to celé
odznova" bez jedinej červenej hlášky. Preto sa doslovné mená kontrolujú proti
`KNOWN` v `drive-store.py`.

PREČO SAMOSTATNÝ SÚBOR A NIE HEREDOC V YAMLE: `lint-workflows.yml` je nad
stropom 800 riadkov, ktorý si sám kontroluje, a veľký `run:` blok patrí do
`workers/` (pravidlo 3). Vedľajší zisk: dá sa to spustiť lokálne.

Použitie:
    python3 workers/lint/publishing.py
"""
import ast
import glob
import re
import sys

import yaml

STORE = "workers/drive/store.py"

# Hľadané príkazy sa SKLADAJÚ, nepíšu. Keby tu stáli celé, našla by táto
# kontrola samu seba a hlásila by chybu navždy – rovnako ako pri `gh cache
# delete` v `lint-workflows.yml`. Skript je totiž sám v `workers/*.py`, teda
# medzi tým, čo prehľadáva.
REL = "gh " + "release"
UP = "actions/upload" + "-artifact"
FLAG = "--store" + "="


def zdrojaky():
    """Všetko, čo môže publikovať: workflowy a workery."""
    return (sorted(glob.glob(".github/workflows/*.yml"))
            + sorted(glob.glob("workers/**/*.sh", recursive=True))
            + sorted(glob.glob("workers/**/*.py", recursive=True)))


def bez_releasov():
    """1. Nikde ani jeden SPUSTENÝ `gh release`.

    Hľadá sa VOLANIE, nie zmienka. Komentáre a docstringy o releasoch tu
    zámerne ostávajú – nesú, prečo sa to presťahovalo, a keby ich kontrola
    hlásila, prvá oprava by bola vymazať vysvetlenie.

    Preto sa v shelli a v `run:` blokoch preskakujú komentárové riadky, a
    v Pythone sa nehľadá text vôbec: tam sa `gh` volalo zoznamom argumentov
    (`["gh", "release", "upload", …]`), takže reťazec „gh release" v ňom nikdy
    nebol – bola by to kontrola, ktorá hľadá niečo iné, než čo chytá.

    `gh api /repos/…/releases` je v poriadku a nesmie sa hlásiť: presne tým
    `workers/tools/cleanup-actions.py` staré releasy MAŽE.
    """
    bad = 0

    def prezri(path, text, kde=""):
        nonlocal bad
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if REL in line:
                print(f"::error file={path}::{kde}`{REL}` publikuje do GitHub "
                      f"releasu (riadok {i}). Do releasov sa neukladá nič – "
                      f"použi `python3 {STORE}` (--put / --get / --names "
                      f"/ --rm).")
                bad += 1

    for path in sorted(glob.glob("workers/**/*.sh", recursive=True)):
        prezri(path, open(path, encoding="utf-8").read())

    for path in sorted(glob.glob(".github/workflows/*.yml")):
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for job, jd in (d.get("jobs") or {}).items():
            for st in (jd or {}).get("steps") or []:
                run = str((st or {}).get("run") or "")
                if run:
                    prezri(path, run, f"{job} / {st.get('name', '?')}: ")

    # Python: `gh` sa volá zoznamom argumentov, tak sa hľadá ten zoznam.
    for path in sorted(glob.glob("workers/**/*.py", recursive=True)):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as exc:
            print(f"::error file={path}::nedá sa rozparsovať ({exc})")
            bad += 1
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            prve = [e.value for e in node.elts[:2]
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            # `REL.split()`, nie doslovný zoznam – inak by táto kontrola
            # našla samu seba (a to sa aj stalo).
            if prve[:2] == REL.split():
                print(f"::error file={path},line={node.lineno}::volá "
                      f"`{REL}` zoznamom argumentov. Do releasov sa neukladá "
                      f"nič – použi `{STORE}` ako modul (`index`, `download`, "
                      f"`upload`) alebo príkazom.")
                bad += 1
    return bad


def artefakt_zije_den():
    """2. Artefakt smie žiť najviac jeden deň.

    Kratší je prepravka medzi jobmi jedného behu (`site-*`, `steps-*`) – tou
    si joby podávajú kusy `_site` a bez nej sa stránka nedá zlepiť. Dlhší je
    publikovanie, a to patrí do skladu `vysledky`
    (`workers/deploy/publish-results.sh`).
    """
    bad = 0
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for job, jd in (d.get("jobs") or {}).items():
            for st in (jd or {}).get("steps") or []:
                uses = str((st or {}).get("uses") or "")
                if not uses.startswith(UP):
                    continue
                dni = (st.get("with") or {}).get("retention-days")
                if dni is not None and int(dni) <= 1:
                    continue
                print(f"::error file={path}::krok '{st.get('name', '?')}' "
                      f"v jobe '{job}' ukladá artefakt s retenciou "
                      f"{dni if dni is not None else 'podľa repozitára'} dní. "
                      f"Artefakt smie byť len prepravka medzi jobmi jedného "
                      f"behu (`retention-days: 1`); čo má prežiť beh, ide do "
                      f"skladu na Drive (`workers/deploy/publish-results.sh`).")
                bad += 1
    return bad


def znama_mena():
    """3. Sklad existuje a `--store=` nemá preklep. Vracia (chyby, mená)."""
    try:
        tree = ast.parse(open(STORE, encoding="utf-8").read())
    except OSError:
        print(f"::error::chýba {STORE} – bez neho pipeline nemá kam publikovať.")
        return 1, set()
    known = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(cil, "id", "") == "KNOWN" for cil in node.targets)
                and isinstance(node.value, ast.Dict)):
            known = {k.value for k in node.value.keys}
    if not known:
        print(f"::error file={STORE}::nenašiel som v ňom KNOWN so zoznamom "
              f"skladov.")
        return 1, known

    # Doslovné meno za `--store=`; `$PREMENNÁ` sa staticky skontrolovať nedá
    # a rieši ju `known_or_die` za behu.
    pouzite = re.compile(re.escape(FLAG) + r"[\"']?([a-z][a-z0-9-]*)")
    bad = 0
    for path in zdrojaky():
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            for m in pouzite.finditer(line):
                if m.group(1) not in known:
                    print(f"::error file={path},line={i}::sklad "
                          f"`{m.group(1)}` nie je v KNOWN vo {STORE} "
                          f"({', '.join(sorted(known))}). Preklep v mene sa "
                          f"neodlíši od prázdneho skladu, takže by build ticho "
                          f"počítal všetko odznova.")
                    bad += 1
    return bad, known


def mena_hovoria_pravdu():
    """4. `*_RELEASE` v `env:` je klamstvo o mieste, kde tá vec leží."""
    bad = 0
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            m = re.match(r"\s*([A-Z][A-Z0-9_]*)_RELEASE:", line)
            if m:
                print(f"::error file={path},line={i}::`{m.group(1)}_RELEASE` "
                      f"pomenúva sklad na Drive slovom „release“. Prepíš na "
                      f"`{m.group(1)}_STORE` – meno, ktoré hovorí, kde tá vec "
                      f"naozaj je (pravidlo 2 v CLAUDE.md).")
                bad += 1
    return bad


def sklady_sa_nerozidu():
    """5. Ten istý `*_STORE` v dvoch workflowoch musí mať tú istú hodnotu.

    Sklad má PISATEĽA a ČITATEĽA a sú to spravidla dva workflowy:
    `shading-rocks.yml` do `ROCK_IMG_STORE` zapisuje, `build-map-region.yml` z neho
    číta. Keby sa tie dve konštanty rozišli, nespadne nič – čitateľ sa pozrie
    do skladu, do ktorého nikto nepíše, a povie „pre tento výrez tam nič nie
    je". To je tichý omyl (pravidlo 8) a hľadá sa zle, lebo obe strany
    vyzerajú samy o sebe správne (pravidlo 1).
    """
    kde = {}
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        d = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for k, v in (d.get("env") or {}).items():
            if k.endswith("_STORE") and isinstance(v, str) and "${" not in v:
                kde.setdefault(k, {})[path] = v
    bad = 0
    for k, m in sorted(kde.items()):
        if len(set(m.values())) > 1:
            kde_co = ", ".join(f"{p}={v}" for p, v in sorted(m.items()))
            print(f"::error::`{k}` má v rôznych workflowoch rôznu hodnotu "
                  f"({kde_co}). Jeden sklad, jedno meno – inak sa do neho "
                  f"zapisuje inde, než sa z neho číta, a beh povie len to, "
                  f"že tam nič nie je.")
            bad += 1
    return bad


def main():
    bad = (bez_releasov() + artefakt_zije_den() + mena_hovoria_pravdu()
           + sklady_sa_nerozidu())
    chyby, known = znama_mena()
    bad += chyby
    print(f"publikovanie len na Drive: {bad} chýb "
          f"({len(known)} skladov v KNOWN)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
