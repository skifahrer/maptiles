#!/usr/bin/env python3
"""Predčasne končiaci čitateľ nesmie visieť na živom producentovi.

`curl … | grep -q` : `grep -q` po prvej zhode skončí, `curl` dostane EPIPE
a `pipefail` z toho spraví nenulový pipeline, hoci grep zhodu našiel. Sú to
preteky, nie deterministická chyba – prechádzalo to roky a vyskočilo, keď za
zhodou pribudlo pár kB.

Pravidlo: rúra smie končiť len čitateľom, ktorý dočíta do EOF. Čokoľvek, čo
skončí skôr (`grep -q`, `head -n`, `sed …q`, `awk …exit`), nesmie byť za rúrou
zo živého príkazu – výstup sa najprv uloží do premennej (`head -1 <<<\"$VAR\"`).

Producenti, čo píšu jeden krátky reťazec (`printf`/`echo`), sa nehlásia.
"""
import glob
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))

# Čitatelia, ktorí končia skôr, než dočítajú vstup.
SKORY = re.compile(r"""\|\s*(
      grep\b[^|;&]*\s-[a-zA-Z]*q          # grep -q / -qE / -iq …
    | head\b                              # head -n
    | sed\b[^|;&]*(?<!\\)\bq[;}'"]        # sed …q
    | awk\b[^|;&]*\bexit\b                # awk … exit
)""", re.VERBOSE)

# Producenti, ktorí dopíšu skôr, než sa dá rúra zavrieť – tie sa neriešia.
DROBNY = re.compile(r"(printf|echo)\s")


def main():
    bad = []
    for cesta in sorted(glob.glob(os.path.join(_ROOT, "workers", "*", "*.sh"))):
        text = open(cesta, encoding="utf-8").read()
        if "pipefail" not in text:
            continue
        rel = os.path.relpath(cesta, _ROOT)
        for i, riadok in enumerate(text.splitlines(), 1):
            holy = riadok.strip()
            if holy.startswith("#") or "|" not in holy:
                continue
            m = SKORY.search(holy)
            if not m:
                continue
            # čo je PRED rúrou – producent
            producent = holy[:m.start()]
            if DROBNY.search(producent) or "<<<" in producent:
                continue
            bad.append(
                f"::error file={rel},line={i}::`{m.group(1).strip()}` končí "
                f"skôr, než producent dopíše – ten dostane EPIPE a `pipefail` "
                f"z toho spraví pád, hoci sa hodnota našla. Ulož výstup do "
                f"premennej a hľadaj v nej (`head -1 <<<\"$VAR\"`). Riadok: "
                f"{holy[:90]}"
            )
    for r in bad:
        print(r)
    print(f"rúry a predčasní čitatelia: {len(bad)} chýb")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
