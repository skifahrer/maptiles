#!/usr/bin/env python3
"""
Zaoblenie obrysu sa nesmie ticho pokaziť ani ticho vrátiť späť.

PREČO TO EXISTUJE. Vrstevnice boli „vyhladené, ale v pravidelných
intervaloch zubaté" a nikto to nemal ako povedať: dva prechody Chaikina
z každého rohu urobili menší roh, nie oblúk, a keďže rohy ostali tam, kde ich
nechal Douglas–Peucker, boli tie zvyšky PRAVIDELNE rozostupené. Build bol
zelený, dlaždice vznikli, súbor mal správnu veľkosť – bolo to vidieť len okom
(CLAUDE.md, pravidlo 8). Odvtedy sa zaobľuje limitnou krivkou a vzorkuje podľa
mriežky dlaždice; toto sú tie miesta, na ktorých sa to dá nebadane rozbiť:

  1. CESTA K SKRIPTU. `smooth-shapes.py` leží v `contours-rocks/`, ale volajú
     ho aj joby z iných priečinkov. `rocks-shading/vector.py` si ho skladal
     z `dirname(__file__)`, čiže ukazoval do priečinka, kde ten súbor NIE JE –
     a spadlo by to až po hodinách sťahovania dlaždíc.
  2. KTORÁ MRIEŽKA. Bez `--maxzoom` sa vezme predvolených 16. Vrstva, ktorá
     ide na z14, by sa vzorkovala 4× jemnejšie, než dlaždica unesie: nič by
     nespadlo, len by bola väčšia a po zaokrúhlení schodíkovitá.
  3. AKÝ PRIEHYB. Nad jedným krokom mriežky začne byť vzorkovanie samo väčšou
     chybou než zaokrúhlenie do dlaždice (±pol kroku) – vtedy sú tetivy vidieť
     ako fazety. Preto má `--sag` strop 4 (štvrtiny kroku).
  4. KONCE A PRSTENCE. Otvorená čiara musí skončiť PRESNE tam, kde skončila
     pôvodná – inak medzi dvomi kusmi tej istej vrstevnice na hranici dlaždice
     vznikne medzera. Prstenec musí ostať uzavretý, inak z plochy vypadne
     neplatný polygón.
  5. STARÉ DÁTA. Zmena tvaru sa musí prejaviť v kľúči cache (`contours=`)
     aj v mene assetu so skalami (`ROCK_ALGO`) – inak build zoberie hotové
     zubaté dlaždice a bude zelený.

Spustiť sa dá aj lokálne: `python3 workers/lint/smoothing.py`.
"""
import importlib.util
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_WORKERS)
SMOOTH = os.path.join(_WORKERS, "contours-rocks", "smooth-shapes.py")
KEYS = os.path.join(_WORKERS, "plan", "cache-keys.sh")
# Ladenie zaoblenia je v `env:` workflowu s VRSTVAMI Z VÝŠKOVÉHO MODELU –
# z buildu mapy sa presťahovali do vlastného súboru, lebo ich potrebuje aj
# pregenerovanie jednej vrstvy (dve kópie by boli dve pravdy o tom, ako
# vrstevnica vyzerá).
WF = os.path.join(_ROOT, ".github", "workflows", "dem-layers.yml")

# Kto zaobľuje a čím sa v tom súbore volá `smooth-shapes.py`. Cesta je
# relatívna k `workers/`; `volanie` je to, čím sa v tom súbore skladá príkaz.
VOLAJU = [
    ("contours-rocks/build.sh", "workers/contours-rocks/smooth-shapes.py"),
    ("contours-rocks/rock-areas.py", "smooth-shapes.py"),
    ("rocks-shading/vector.py", "smooth-shapes.py"),
]

sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    bad = []
    sm = load("smooth_shapes", SMOOTH)

    # ---------- 1. cesta k skriptu a 2./3. čo sa mu podáva ----------
    for rel, _ in VOLAJU:
        src = open(os.path.join(_WORKERS, rel)).read()
        if "smooth-shapes.py" not in src:
            bad.append(f"`workers/{rel}` už `smooth-shapes.py` nevolá. Ak sa "
                       f"zaoblenie presunulo inam, oprav aj tento zoznam – "
                       f"dve kópie zaobľovania sa raz rozídu a jedna vrstva "
                       f"bude hladká inak než druhá.")
            continue
        for prep in ("--maxzoom", "--sag"):
            if prep not in src:
                bad.append(f"`workers/{rel}` volá `smooth-shapes.py` bez "
                           f"`{prep}`. Bez `--maxzoom` sa mlčky vezme z16 "
                           f"a vrstva na nižšom zoome sa vzorkuje jemnejšie, "
                           f"než dlaždica unesie; bez `--sag` sa nedá vypnúť "
                           f"ani nastaviť priehyb.")
    # Cesta z INÉHO priečinka nesmie ísť cez `dirname(__file__)` – tam ten
    # súbor nie je. `rocks-shading/vector.py` na tom raz stál.
    ext = open(os.path.join(_WORKERS, "rocks-shading", "vector.py")).read()
    m = re.search(r"os\.path\.join\(([^)]*?)\"smooth-shapes\.py\"", ext, re.S)
    if not m or "contours-rocks" not in m.group(1):
        bad.append("`workers/rocks-shading/vector.py` si cestu k "
                   "`smooth-shapes.py` neskladá cez `contours-rocks` – ten "
                   "súbor je tam a nikde inde. Krok by spadol na "
                   "FileNotFoundError až po hodinách sťahovania dlaždíc.")

    # Ktorý maxzoom sa podáva ktorej vrstve. Zámena je tichá: vrstevnice by sa
    # vzorkovali podľa mriežky skál a naopak. Hľadá sa PRIAMO ten argument,
    # nie meno premennej kdekoľvek v okolí – to isté meno stojí aj v hláške
    # o riadok vyššie, takže by kontrola prešla aj vtedy, keď sa argument
    # stratí.
    # `build.sh` a `rocks.sh` sú JEDEN skript rozdelený kvôli stropu 800
    # riadkov (druhá polovica sa číta cez `.`): argument vrstevníc stojí
    # v prvej, argument skál v druhej. Čítajú sa preto spolu – hľadať každý
    # zvlášť by znamenalo vedieť, v ktorej polovici má ktorý byť, a to sa
    # pri ďalšom delení rozíde.
    build = "".join(
        open(os.path.join(_WORKERS, "contours-rocks", n)).read()
        for n in ("build.sh", "rocks.sh"))
    for co, arg in (("vrstevníc", '--maxzoom="$OPT_CONTOUR_MAXZOOM"'),
                    ("skál", '--maxzoom="$OPT_ROCK_MAXZOOM"')):
        if arg not in build:
            bad.append(f"V `workers/contours-rocks/build.sh` ani v jeho druhej "
                       f"polovici `rocks.sh` nie je `{arg}` – zaoblenie {co} "
                       f"by sa riadilo mriežkou inej vrstvy (alebo predvolenou "
                       f"z16). Tichý rozdiel v hustote bodov, ktorý build nemá "
                       f"ako povedať.")

    # ---------- 3. priehyb ostáva pod krokom mriežky ----------
    wf = open(WF).read()
    for kluc in ("CONTOUR_SMOOTH", "ROCK_SMOOTH"):
        m = re.search(rf'^\s*{kluc}:\s*"(\d+)"', wf, re.M)
        if not m:
            bad.append(f"V `dem-layers.yml` nie je `{kluc}` – bez neho sa "
                       f"zaoblenie riadi predvolenou hodnotou skriptu a "
                       f"formulár o nej klame.")
            continue
        sag = int(m.group(1))
        if sag > 4:
            bad.append(f"`{kluc}` je {sag}, čiže priehyb {sag / 4:.2f} kroku "
                       f"mriežky dlaždice. Nad jedným krokom je vzorkovanie "
                       f"väčšou chybou než zaokrúhlenie do dlaždice (±pol "
                       f"kroku) a tetivy vidno ako fazety.")

    # ---------- 4. konce a prstence ----------
    # Otvorená čiara: konce sa nesmú pohnúť ANI O MILIMETER. Keby sa hli,
    # dva kusy tej istej vrstevnice by na hranici dlaždice prestali sadnúť
    # na seba a v mape by bola medzera – a nikto by nič nepovedal.
    ciara = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0), (30.0, 0.0)]
    out = sm.curve_line(ciara, 0.05)
    if tuple(out[0]) != ciara[0] or tuple(out[-1]) != ciara[-1]:
        bad.append(f"Zaoblená čiara nezačína a nekončí tam, kde pôvodná "
                   f"({out[0]} … {out[-1]} namiesto {ciara[0]} … "
                   f"{ciara[-1]}). Na hranici dlaždice z toho bude medzera.")
    if len(out) <= len(ciara):
        bad.append("Zaoblenie čiary nepridalo ani bod – roh sa nezaoblil.")

    # Prstenec: musí ostať uzavretý.
    prstenec = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    ring = sm.curve_ring(prstenec, 0.05)
    if tuple(ring[0]) != tuple(ring[-1]):
        bad.append(f"Zaoblený prstenec nie je uzavretý ({ring[0]} vs "
                   f"{ring[-1]}) – z plochy vypadne neplatný polygón.")

    # Priehyb naozaj drží pod toleranciou: hrubo vzorkovaná krivka sa nesmie
    # od tej istej krivky vzorkovanej nahusto odchýliť viac, než sa žiadalo.
    # Meria sa VZDIALENOSŤ OD KRIVKY, nie uhol medzi tetivami – uhol závisí od
    # toho, ako husto body ležia, a práve to je tu premenná.
    def vzdialenost(bod, ciara):
        x, y = bod
        best = float("inf")
        for (x0, y0), (x1, y1) in zip(ciara, ciara[1:]):
            dx, dy = x1 - x0, y1 - y0
            n2 = dx * dx + dy * dy
            t = 0.0 if n2 == 0 else max(0.0, min(
                1.0, ((x - x0) * dx + (y - y0) * dy) / n2))
            best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
        return best

    roh = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    for tol in (0.5, 0.05, 0.005):
        hruba = sm.curve_line(roh, tol)
        presna = sm.curve_line(roh, tol / 100.0)
        worst = max(vzdialenost(b, hruba) for b in presna)
        if worst > tol * 1.2:
            bad.append(f"Pri tolerancii {tol} m sa vzorkovaná krivka odchyľuje "
                       f"od svojho presného priebehu o {worst:.3f} m – "
                       f"vzorkovanie nedrží priehyb, ktorý sľubuje, a v mape "
                       f"z toho budú fazety.")

    # Jemnejšia tolerancia nesmie dať menej bodov (inak by „presnejšie"
    # znamenalo hrubšie).
    hrubo = len(sm.curve_line([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], 1.0))
    jemne = len(sm.curve_line([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], 0.01))
    if jemne <= hrubo:
        bad.append(f"Desaťkrát jemnejšia tolerancia dala {jemne} bodov proti "
                   f"{hrubo} – vzorkovanie sa neriadi priehybom.")

    # ---------- 5. krok mriežky je jedno číslo ----------
    for z in (11, 14, 16):
        krok = cell.tile_grid_m(z)
        cakane = cell.tile_m_per_px(z) * cell.TILE_PX / cell.TILE_EXTENT
        if abs(krok - cakane) > 1e-12:
            bad.append(f"`cell.tile_grid_m({z})` nesedí s pixelom dlaždice – "
                       f"krok mriežky a veľkosť pixela sú jedna otázka.")
    if cell.TILE_EXTENT != 4096:
        bad.append(f"`cell.TILE_EXTENT` je {cell.TILE_EXTENT}. Planetiler "
                   f"`extent` meniť nevie, je to 4096 – iné číslo by znamenalo, "
                   f"že sa vzorkuje podľa mriežky, ktorá neexistuje.")

    # ---------- 6. staré dáta sa nesmú vrátiť ----------
    keys = open(KEYS).read()
    if not re.search(r'echo "contours=contours-v(\d+)-', keys):
        bad.append("V `workers/plan/cache-keys.sh` nie je verzia v kľúči "
                   "`contours=`. Zmena tvaru vrstevníc sa bez nej neprejaví – "
                   "cache vráti tie staré a build bude zelený.")
    if not re.search(r"^\s*ROCK_ALGO:\s*v\d+", wf, re.M):
        bad.append("V `dem-layers.yml` nie je `ROCK_ALGO: v<číslo>` – meno "
                   "assetu so skalami by potom nenieslo TVAR obrysu a sklad by "
                   "vrátil staré zubaté skaly.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print("Zaoblenie: cesta k skriptu sedí, každé volanie vie svoju mriežku, "
          "priehyb drží a konce ostávajú ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
