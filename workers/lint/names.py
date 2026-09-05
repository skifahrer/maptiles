#!/usr/bin/env python3
"""Meno, ktoré worker číta, musí byť aj napísané.

Workery s pomlčkou v mene sa načítavajú cez `importlib` (`plan = _load(…)`),
takže `plan.SLOPE_CELLS_PER_S` nevidí ani `bash -n`, ani import. Skrátenie
komentárov zmazalo `KONŠTANTA = 5.1e6  # …` aj s hodnotou a beh skál padol
až na runneri po štvrťhodine – po zaplatenom sťahovaní DEM.

Stráži sa dvoje: `alias.MENO` na načítanom module a čítanie VEĽKÝCH mien
v tom istom súbore. Veľké preto, že konštanty sa tak píšu a lokálne mená nie.
"""
import ast
import builtins
import glob
import os
import sys

SUBORY = sorted(glob.glob("workers/**/*.py", recursive=True))
VSTAVANE = set(dir(builtins))


def je_konstanta(meno):
    return meno[:1].isupper() and meno.upper() == meno and meno not in VSTAVANE


def vrchne_mena(strom):
    """Mená, ktoré modul viaže navrchu – teda tie, ktoré vie dať von."""
    mena = set()
    for uzol in strom.body:
        if isinstance(uzol, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            mena.add(uzol.name)
        elif isinstance(uzol, (ast.Import, ast.ImportFrom)):
            mena.update(a.asname or a.name.split(".")[0] for a in uzol.names)
        elif isinstance(uzol, ast.AnnAssign):
            mena.update(viazane(uzol.target))
        elif isinstance(uzol, ast.AugAssign):
            mena.update(viazane(uzol.target))
        elif isinstance(uzol, ast.Assign):
            for ciel in uzol.targets:
                mena.update(viazane(ciel))
        elif isinstance(uzol, (ast.For, ast.AsyncFor)):
            mena.update(viazane(uzol.target))
        elif isinstance(uzol, (ast.If, ast.Try, ast.With, ast.While)):
            # `try: import x / except: x = None` a spol.
            mena.update(vrchne_mena(ast.Module(body=uzol.body, type_ignores=[])))
            for vetva in (getattr(uzol, "orelse", []), getattr(uzol, "finalbody", [])):
                mena.update(vrchne_mena(ast.Module(body=vetva, type_ignores=[])))
            for h in getattr(uzol, "handlers", []):
                mena.update(vrchne_mena(ast.Module(body=h.body, type_ignores=[])))
    return mena


def viazane(ciel):
    if isinstance(ciel, ast.Name):
        return {ciel.id}
    if isinstance(ciel, ast.Starred):
        return viazane(ciel.value)
    if isinstance(ciel, (ast.Tuple, ast.List)):
        return set().union(*(viazane(p) for p in ciel.elts)) if ciel.elts else set()
    return set()


def vsetky_viazane(uzol):
    """Všetko, čo sa kdekoľvek pod uzlom viaže – na miestne mená stačí."""
    mena = set()
    for p in ast.walk(uzol):
        if isinstance(p, ast.Name) and isinstance(p.ctx, (ast.Store, ast.Del)):
            mena.add(p.id)
        elif isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            mena.add(p.name)
        elif isinstance(p, (ast.Import, ast.ImportFrom)):
            mena.update(a.asname or a.name.split(".")[0] for a in p.names)
        elif isinstance(p, ast.arg):
            mena.add(p.arg)
        elif isinstance(p, ast.ExceptHandler) and p.name:
            mena.add(p.name)
        elif isinstance(p, ast.Global):
            mena.update(p.names)
    return mena


def nacitane_moduly(cesta, strom):
    """`alias = _load("meno", "…/subor.py")` → alias: cesta na ten súbor."""
    von = {}
    for uzol in ast.walk(strom):
        if not isinstance(uzol, ast.Assign) or len(uzol.targets) != 1:
            continue
        if not isinstance(uzol.targets[0], ast.Name):
            continue
        vyraz = uzol.value
        if not isinstance(vyraz, ast.Call) or not isinstance(vyraz.func, ast.Name):
            continue
        if vyraz.func.id not in ("_load", "load"):
            continue
        # posledný reťazec v argumentoch je meno súboru aj pri `os.path.join`
        subory = [t.value for a in vyraz.args for t in ast.walk(a)
                  if isinstance(t, ast.Constant) and isinstance(t.value, str)
                  and t.value.endswith(".py")]
        if not subory:
            continue
        ciel = os.path.join(os.path.dirname(cesta), subory[-1])
        if not os.path.exists(ciel):
            zhody = [f for f in SUBORY if os.path.basename(f) == subory[-1]]
            if len(zhody) != 1:
                continue
            ciel = zhody[0]
        von[uzol.targets[0].id] = ciel
    return von


def chyby_v(cesta, stromy):
    strom = stromy[cesta]
    zle = []

    moduly = nacitane_moduly(cesta, strom)
    for uzol in ast.walk(strom):
        if not isinstance(uzol, ast.Attribute) or not isinstance(uzol.ctx, ast.Load):
            continue
        if not isinstance(uzol.value, ast.Name) or uzol.value.id not in moduly:
            continue
        ciel = moduly[uzol.value.id]
        if uzol.attr not in vrchne_mena(stromy[ciel]):
            zle.append((uzol.lineno,
                        f"`{uzol.value.id}.{uzol.attr}` číta z `{ciel}`, "
                        f"ale to meno tam nie je"))

    vrchne = vrchne_mena(strom) | VSTAVANE | {"__file__", "__name__", "__doc__"}
    for funkcia in [u for u in ast.walk(strom)
                    if isinstance(u, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        miestne = vsetky_viazane(funkcia)
        for p in ast.walk(funkcia):
            if not isinstance(p, ast.Name) or not isinstance(p.ctx, ast.Load):
                continue
            if je_konstanta(p.id) and p.id not in vrchne and p.id not in miestne:
                zle.append((p.lineno, f"`{p.id}` sa číta, ale nikde sa nenastavuje"))
    return zle


def main():
    stromy = {}
    for cesta in SUBORY:
        try:
            stromy[cesta] = ast.parse(open(cesta, encoding="utf-8").read(), cesta)
        except SyntaxError as e:
            print(f"::error file={cesta},line={e.lineno}::{e.msg}")
            return 1
    bad = 0
    for cesta in SUBORY:
        for riadok, sprava in sorted(set(chyby_v(cesta, stromy))):
            print(f"::error file={cesta},line={riadok}::{sprava}. "
                  f"Skrátenie komentára nesmie zmazať riadok s hodnotou.")
            bad += 1
    print(f"mená, ktoré musia existovať: {bad} chýb")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
