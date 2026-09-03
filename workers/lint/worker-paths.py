#!/usr/bin/env python3
"""
Každá cesta na worker musí ukazovať na súbor, ktorý existuje.

PREČO TO JE KONTROLA. Pri presune `workers/` do priečinkov podľa jobu sa
prepísali cesty napísané celé (`workers/<meno>.py` → `workers/<job>/<meno>.py`),
ale nie tie, ktoré si skript skladá AŽ ZA BEHU:

    HERE="$(dirname "$0")"
    python3 "$HERE/<meno>.py"          # kým bol skript v workers/, sedelo to

Po presune z toho bol `workers/<job>/<meno>.py` a taký súbor nie je. Nič to
nechytilo: `bash -n` vidí syntax, nie cesty, a lokálne to nikto nespustí, lebo
skript chce env z workflowu. Spadlo to až na runneri – a nie na jednom kroku,
ale na štyroch jobov naraz (beh 31412152523: `check-dem`, `contours`,
`terrain`, a `deploy` za nimi).

ČO SA STRÁŽI: `$HERE/x`, `$WORKERS/x`, `$(dirname "$0")/x` a celé `workers/…`
cesty vo všetkých workeroch aj workflowoch. Komentáre sa vyhadzujú – texty
o chybách (aj tá hlavička hore) o zlých cestách píšu zámerne.

A DRUHÁ POLOVICA TEJ ISTEJ OTÁZKY: skript, ktorý existuje, ale nemá príznak
`+x`, dopadne rovnako – workflow ho púšťa priamo (`run: workers/<job>/x.sh`),
takže bash vráti „Permission denied" a kód 126, súrodenca 127 od chýbajúceho
súboru. Beh 31947366438 na tom zhodil mapu sveta v prvom kroku: nový
`workers/world/build.sh` prišiel do repozitára ako `100644`, čo na ničom
inom vidieť nie je – v diffe je to jeden riadok hlavičky a lokálne to nikto
nespustí, lebo skript chce env z workflowu.

VÝNIMKA SÚ KUSY, KTORÉ SA `source`-UJÚ. `.sh`, ktorý si iný skript číta cez
`.`, nie je krok, ale kus toho skriptu: beží v jeho shelli a berie si jeho
premenné (`contours-rocks/rocks.sh` je druhá polovica `build.sh`). Sám by
spadol na prvom riadku,
takže `+x` na ňom nie je záruka, ale sľub, ktorý sa nedá dodržať – a preto sa
od neho nevyžaduje.

Spustiť sa dá aj lokálne: `python3 workers/lint/worker-paths.py`.
"""
import glob
import os
import re
import sys

PRIP = r"(?:py|sh|mjs|json|txt|yml)"


def bez_komentarov(text, styl):
    """`#` pre shell a python, `//` a `/* */` pre JS. Reťazce sa nerozlišujú –
    na cesty to stačí a je to o rád menej kódu než parser."""
    if styl == "js":
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(re.sub(r"//.*$", "", r) for r in text.split("\n"))
    von = []
    for r in text.split("\n"):
        # `#` v strede riadku býva aj v reťazci; berieme len celoriadkové
        # komentáre a koncové za medzerou, čo pokrýva, ako sa tu píše.
        r = re.sub(r"(^|\s)#.*$", r"\1", r)
        von.append(r)
    return "\n".join(von)


def chyby_v(path, text, styl):
    here = os.path.dirname(path)
    workers = os.path.dirname(here)
    t = bez_komentarov(text, styl)
    zle = []

    # --- shell: $HERE/x, $WORKERS/x, $(dirname "$0")/x ---
    prem = {"HERE": here, "WORKERS": workers}
    for m in re.finditer(r'\$\{?(HERE|WORKERS)\}?/([\w./-]+\.' + PRIP + r')', t):
        cesta = os.path.normpath(os.path.join(prem[m.group(1)], m.group(2)))
        if not os.path.exists(cesta):
            zle.append((f"${m.group(1)}/{m.group(2)}", cesta))
    for m in re.finditer(r'\$\(dirname "\$0"\)/([\w./-]+\.' + PRIP + r')', t):
        cesta = os.path.normpath(os.path.join(here, m.group(1)))
        if not os.path.exists(cesta):
            zle.append((f'$(dirname "$0")/{m.group(1)}', cesta))

    # --- python: os.path.join(_HERE | _WORKERS | _DATA | _DRIVE, "…") ---
    # Toto bola druhá polovica tej istej chyby: cesty sa skladajú aj tu a pri
    # presune sa im zmenil základ. Kontroluje sa doslovné volanie – premenná
    # v argumente sa staticky rozlúsknuť nedá a nikto ju tu ani nepoužíva.
    baza = {"_HERE": here, "_WORKERS": workers,
            "_DATA": os.path.join(workers, "data"),
            "_DRIVE": os.path.join(workers, "drive")}
    for m in re.finditer(
            r'os\.path\.join\(\s*(_HERE|_WORKERS|_DATA|_DRIVE)\s*,\s*'
            r'((?:"[\w.-]+"\s*,\s*)*"[\w.-]+\.' + PRIP + r'")\s*\)', t):
        casti = re.findall(r'"([^"]+)"', m.group(2))
        cesta = os.path.normpath(os.path.join(baza[m.group(1)], *casti))
        if not os.path.exists(cesta):
            zle.append((f"os.path.join({m.group(1)}, {m.group(2)})", cesta))

    # --- JS: join(<základ odvodený z import.meta.url>, "…") ---
    # Základ býva aj v premennej (`SELF`, `root`), a tá si k nemu môže pridať
    # `".."` – takže sa NEDÁ predpokladať, že je to vlastný priečinok. Najprv
    # sa prečíta, ako je tá premenná definovaná, a až potom sa cesta skladá.
    # Koreň repozitára je odteraz o DVE úrovne vyššie než `workers/<job>/` –
    # práve na tom spadol beh 31413580102.
    if styl == "js":
        SAM = r'dirname\(\s*fileURLToPath\(\s*import\.meta\.url\s*\)\s*\)'
        zaklady = {}
        for m in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*' + SAM + r'\s*;', t):
            zaklady[m.group(1)] = here
        for m in re.finditer(
                r'(?:const|let|var)\s+(\w+)\s*=\s*join\(\s*' + SAM + r'\s*,\s*'
                r'((?:"[\w.-]+"\s*,?\s*)+)\)\s*;', t):
            zaklady[m.group(1)] = os.path.normpath(
                os.path.join(here, *re.findall(r'"([^"]+)"', m.group(2))))
        vzory = [(SAM, here)] + [(re.escape(k), v) for k, v in zaklady.items()]
        for vzor, baza in vzory:
            for m in re.finditer(
                    r'join\(\s*' + vzor + r'\s*,\s*'
                    r'((?:"[\w.-]+"\s*,\s*)*"[\w.-]+\.' + PRIP + r'")\s*\)', t):
                casti = re.findall(r'"([^"]+)"', m.group(1))
                cesta = os.path.normpath(os.path.join(baza, *casti))
                if not os.path.exists(cesta):
                    zle.append((f"join(…, {m.group(1)})", cesta))

    # --- python: load("meno", "modul.py") ---
    # Moduly sa kvôli pomlčke v mene načítavajú cez `importlib` a `load()` si
    # cestu vnútri sám lepí na `_HERE`. Volanie teda vyzerá ako holé meno –
    # a keď sused skončí v inom priečinku, neexistuje. `os.pardir` sa berie
    # tiež: tak sa volá do vedľajšieho jobu.
    if styl == "py":
        for m in re.finditer(
                r'load\(\s*"[\w_]+"\s*,\s*((?:os\.path\.join\(\s*)?'
                r'(?:os\.pardir\s*,\s*)?(?:"[\w.-]+"\s*,?\s*)+\)?)\s*\)', t):
            arg = m.group(1)
            casti = re.findall(r'"([^"]+)"', arg)
            if not casti or not casti[-1].endswith(".py"):
                continue
            baza = os.path.join(here, os.pardir) if "os.pardir" in arg else here
            cesta = os.path.normpath(os.path.join(baza, *casti))
            if not os.path.exists(cesta):
                zle.append((f"load(…, {arg})", cesta))

    # --- celé `workers/…` cesty ---
    for m in re.finditer(r'(?<![\w/.])workers/[\w./-]+\.' + PRIP, t):
        if not os.path.exists(m.group(0)):
            zle.append((m.group(0), m.group(0)))
    return zle


def citane():
    """`.sh`, ktoré si iný skript ČÍTA cez `.` (source), nie púšťa.

    Nie je to spustiteľný krok, ale KUS INÉHO SKRIPTU: beží v jeho shelli,
    berie si jeho premenné a svoje mu podáva späť. Také súbory vznikajú tam,
    kde skript prerástol strop 800 riadkov (`contours-rocks/rocks.sh` je druhá
    polovica `build.sh`), alebo kde tú istú vec robia dve pipeline
    (`state/estafeta.sh` je jadro oboch štafiet). Spustiť sa nedajú – bez
    premenných volajúceho by spadli na prvom riadku – takže `+x` na nich nie
    je záruka, ale sľub, ktorý sa nedá dodržať.

    Hľadá sa `. workers/…` a `source workers/…` v skriptoch bez komentárov:
    zakomentované volanie nie je volanie.
    """
    out = set()
    for f in glob.glob("workers/**/*.sh", recursive=True):
        t = bez_komentarov(open(f, encoding="utf-8").read(), "sh")
        for m in re.finditer(r"(?:^|\s)(?:\.|source)\s+(workers/[\w./-]+\.sh)",
                             t, re.M):
            out.add(m.group(1))
    return out


def nespustitelne():
    """`workers/**/*.sh` bez príznaku `+x` – workflow ich púšťa priamo.

    Vracia zoznam ciest. Kontroluje sa KAŽDÝ skript, nielen ten, na ktorý sa
    dá nájsť `run:` vo workflowe: skripty si volajú aj samy navzájom
    (`world/build.sh` púšťa `lib/planetiler.sh` aj `assets/glyphs.sh`) a
    „zatiaľ ho nikto nevolá" je stav, ktorý o priečinok ďalej prestane platiť.
    Výnimkou sú kusy, ktoré sa `source`-ujú (viď `citane`) – tie sa nepúšťajú
    a nemajú sa ani dať.
    """
    fragmenty = citane()
    return sorted(f for f in glob.glob("workers/**/*.sh", recursive=True)
                  if f not in fragmenty and not os.access(f, os.X_OK))


def main():
    bad = 0
    for f in nespustitelne():
        print(f"::error file={f}::skript nemá príznak `+x`, takže `run: {f}` "
              f"skončí na „Permission denied“ (kód 126). Priečinok je job, "
              f"súbor je krok a kroky sa púšťajú priamo – naprav to cez "
              f"`git update-index --chmod=+x {f}` (samotný `chmod` mimo git "
              f"index nestačí).")
        bad += 1
    subory = ([(f, "sh") for f in glob.glob("workers/**/*.sh", recursive=True)]
              + [(f, "py") for f in glob.glob("workers/**/*.py", recursive=True)]
              + [(f, "js") for f in glob.glob("workers/**/*.mjs", recursive=True)]
              + [(f, "sh") for f in glob.glob(".github/workflows/*.yml")]
              + [(f, "sh") for f in glob.glob(".github/actions/*/action.yml")])
    for path, styl in sorted(subory):
        for zapis, cesta in chyby_v(path, open(path, encoding="utf-8").read(), styl):
            print(f"::error file={path}::`{zapis}` ukazuje na `{cesta}`, "
                  f"a taký súbor nie je. Priečinok je job, súbor je krok – "
                  f"sused sa volá `$HERE/<krok>`, iný job "
                  f"`$WORKERS/<job>/<krok>`.")
            bad += 1
    print(f"cesty na workery: {bad} chýb")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
