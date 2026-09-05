#!/usr/bin/env python3
"""Výpis priečinka na Drive musí rozuzliť skratky, nie ich preskočiť.

`listing` zahadzovala každú položku bez `size` – správne pri Google-natívnych
dokumentoch, lenže skratka `size` tiež nemá a ozajstný súbor za ňou je.
Sonnyho 1″ priečinok je z nich celý (15 dlaždíc = 15 skratiek) a hláška pritom
vinila zdieľanie priečinka.

Staticky sa to overiť nedá, takže sa `listing` pustí nad napodobeninou.
Sťahovať sa musí cieľ (`id` aj `size` z neho) a nesúlad mien musí varovať.
"""
import importlib.util
import io
import os
import sys
import types
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)


def nacitaj():
    """`folder.py` bez toho, aby sa čokoľvek pýtalo Drive."""
    spec = importlib.util.spec_from_file_location(
        "folder_pod_testom", os.path.join(_WORKERS, "drive", "folder.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def napodobenina(folder, ciele):
    """Priečinok ako ho vracia Drive: dva ozajstné súbory a dve skratky."""
    strana = {"files": [
        {"id": "r1", "name": "_Readme.txt", "size": "3805",
         "mimeType": "text/plain", "ownedByMe": False},
        {"id": "s1", "name": "N49E020.zip", "mimeType": folder.SHORTCUT_MIME,
         "ownedByMe": False,
         "shortcutDetails": {"targetId": "t1",
                             "targetMimeType": "application/zip"}},
        # Skratka, ktorej cieľ je zmazaný – Drive vtedy `targetId` nepošle.
        {"id": "s2", "name": "N49E021.zip", "mimeType": folder.SHORTCUT_MIME,
         "ownedByMe": False, "shortcutDetails": {}},
    ]}
    folder.auth = types.SimpleNamespace(
        api_get=lambda creds, path: strana,
        file_info=lambda creds, fid: ciele[fid])


def main():
    folder = nacitaj()
    ciel = {"id": "t1", "name": "N49E020.zip", "size": "10952932",
            "mimeType": "application/zip", "ownedByMe": True}
    napodobenina(folder, {"t1": ciel})

    zle = []
    files, skipped = folder.listing(None, "fake")
    mena = {f["name"]: f for f in files}

    if "N49E020.zip" not in mena:
        zle.append("skratka sa nerozuzlila – `listing` dlaždicu zahodila, "
                   "hoci cieľ existuje (to je tá chyba, kvôli ktorej "
                   "kontrola vznikla)")
    else:
        polozka = mena["N49E020.zip"]
        if polozka["id"] != "t1":
            zle.append(f"sťahovalo by sa `{polozka['id']}` (skratka) namiesto "
                       f"cieľa `t1` – skratka sa stiahnuť nedá")
        if polozka["size"] != 10952932:
            zle.append(f"veľkosť {polozka['size']} nie je z cieľa "
                       f"(má byť 10952932)")
        if not polozka["owned"]:
            zle.append("`owned` sa neberie z cieľa – denný strop sťahovania "
                       "visí na vlastníkovi CIEĽA, nie skratky")

    if not any("bez cieľa" in s for s in skipped):
        zle.append("rozbitá skratka (bez `targetId`) sa nepreskočila "
                   "s vysvetlením – volajúci by nevedel, čo v priečinku chýba")

    # Cieľ s iným menom: meno dlaždice je sľub o tom, ktoré územie v nej je.
    napodobenina(folder, {"t1": dict(ciel, name="N48E020.zip")})
    log = io.StringIO()
    with redirect_stdout(log):
        folder.listing(None, "fake")
    if "::warning::" not in log.getvalue():
        zle.append("skratka na súbor s INÝM menom nevarovala – z toho vyjde "
                   "dlaždica s dátami z iného stupňa a nikto sa to nedozvie")

    for chyba in zle:
        print(f"::error file=workers/drive/folder.py::{chyba}")
    print(f"skratky na Drive: {len(zle)} chýb")
    return 1 if zle else 0


if __name__ == "__main__":
    sys.exit(main())
