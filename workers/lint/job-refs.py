#!/usr/bin/env python3
"""
`needs.<job>.outputs.<x>` musí ukazovať na výstup, ktorý ten job naozaj vydá.

PREČO. Neexistujúci výstup nie je chyba behu – GitHub ho vyhodnotí ako PRÁZDNY
REŤAZEC. Job teda dostane `''` namiesto hodnoty, `if:` na ňom vyjde nepravdivo,
vrstva sa nepridá a beh zazelená. To je pravidlo 8: tichý omyl je horší než pád.

BOL TO INLINE BLOK V `lint-workflows.yml` a presunul sa sem, keď sa ukázalo, že
nevie o volaných workflowoch (pravidlo 3: veľký `run:` patrí do `workers/`).

ČO SA STRÁŽI:

  1. `needs.<job>` musí byť v `needs:` toho jobu. Bez toho je hodnota prázdna
     rovnako spoľahlivo, ako keby výstup neexistoval.
  2. Výstup musí existovať – a POZOR, hľadá sa na DVOCH miestach:
       * pri obyčajnom jobe v jeho `outputs:`,
       * pri jobe s `uses: ./.github/workflows/X.yml` v tom volanom súbore,
         v `on.workflow_call.outputs`. Volaný job vo volajúcom žiadne
         `outputs:` nemá a nikdy mať nebude, takže kontrola, ktorá pozerá len
         tam, by ho hlásila VŽDY – a to je horšie než nekontrolovať: falošné
         hlásenie sa buď vypne, alebo sa „opraví" tým, že sa výstup pridá
         nasilu tam, kam nepatrí. (Presne to sa stalo pri `roads.yml`.)

Spustiť: `python3 workers/lint/job-refs.py`
"""
import glob
import os
import re
import sys

import yaml


def load(path):
    """YAML bez zakomentovaných riadkov.

    Kontrola je z časti TEXTOVÁ (hľadá `needs.…` v celom súbore), takže by inak
    našla odkaz aj v komentári, ktorý ju samu popisuje – presne to sa už raz
    stalo. Zahadzujú sa len celé zakomentované riadky, nie `#` uprostred
    príkazu, kde môže byť súčasťou textu.
    """
    txt = open(path, encoding="utf-8").read()
    txt = re.sub(r"^[ \t]*#.*$", "", txt, flags=re.M)
    return txt, (yaml.safe_load(txt) or {})


def call_outputs(uses):
    """Výstupy volaného workflowu, alebo None, keď to nie je lokálne volanie.

    `on:` sa v YAMLe načíta ako boolean `True` (je to v jazyku áno/nie), takže
    sa kľúč hľadá pod oboma menami – inak by tá vetva ticho vracala prázdno
    a kontrola by bola zase falošná.
    """
    if not isinstance(uses, str) or not uses.startswith("./"):
        return None
    # `removeprefix`, NIE `lstrip("./")`: `lstrip` berie ZNAKY, nie predponu,
    # takže z `./.github/workflows/roads.yml` spraví `github/workflows/…` –
    # bez tej bodky súbor neexistuje, výstupy vyjdú prázdne a kontrola hlási
    # chybu, ktorá tam nie je.
    path = uses.split("@", 1)[0].removeprefix("./")
    if not os.path.exists(path):
        return {}
    _, doc = load(path)
    on = doc.get("on", doc.get(True)) or {}
    return ((on.get("workflow_call") or {}).get("outputs") or {})


def main():
    errs = 0
    for path in sorted(glob.glob(".github/workflows/*.yml")):
        txt, doc = load(path)
        jobs = doc.get("jobs") or {}
        starts = {}
        for j in jobs:
            m = re.search(r"^  " + re.escape(j) + r":$", txt, re.M)
            if m:
                starts[j] = m.start()
        if not starts:
            continue

        def job_of(pos):
            return max(((j, p) for j, p in starts.items() if p < pos),
                       key=lambda x: x[1])[0]

        for m in re.finditer(
                r"needs\.([a-zA-Z0-9_-]+)\.(outputs\.([a-zA-Z0-9_]+)|result)",
                txt):
            tgt, cur = m.group(1), job_of(m.start())
            needs = jobs[cur].get("needs") or []
            if isinstance(needs, str):
                needs = [needs]
            if tgt not in needs:
                print(f"::error file={path}::job '{cur}' používa needs.{tgt}, "
                      f"ale nemá ho v needs")
                errs += 1
                continue
            key = m.group(3)
            if not key:
                continue
            declared = jobs[tgt].get("outputs") or {}
            called = call_outputs(jobs[tgt].get("uses"))
            if called is not None:
                # Job je volanie iného workflowu – jeho výstupy sú TAM.
                declared = called
            if key not in declared:
                kde = (f" (volá `{jobs[tgt]['uses']}`, výstup musí byť v jeho "
                       f"`on.workflow_call.outputs`)" if called is not None
                       else "")
                print(f"::error file={path}::job '{tgt}' nemá výstup '{key}' "
                      f"(chce ho '{cur}'){kde}")
                errs += 1
    print(f"odkazov medzi jobmi: {errs} chýb")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
