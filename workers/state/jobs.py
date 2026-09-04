#!/usr/bin/env python3
"""
Čo sa dá pregenerovať v celej krajine – a čím sa to nad jedným krajom spustí.

„Mapa · Regenerate state" je tá istá štafeta ako „Build map state", len nad
krajom nespúšťa CELÝ build, ale JEDNU vec: body, línie, navigáciu, vrstevnice,
skaly alebo tieňovanie. Tento súbor je číselník tých vecí – jedno miesto, ktoré
vie, čo sa dá vybrať, ktorý workflow to nad krajom spraví a s akými poľami.

PREČO ČÍSELNÍK A NIE `case` V SKRIPTE. Tú istú otázku si kladú tri miesta:
formulár dávky (`co` je `type: choice`, teda zoznam v YAMLe), štafeta
(`workers/state/regenerate.sh`, ktorá beh kraja spúšťa) a súhrn behu. Keby si
na ňu odpovedalo každé samo, pribudnutá voľba by vo formulári bola a štafeta
by na nej spadla – alebo horšie: spustila by niečo iné, než si vybral, a beh
by bol zelený. Zoznam vo formulári sa generovať nedá (`choice` v YAMLe je
zoznam), ale dá sa strážiť – robí to `workers/lint/regenerate.py`.

VŠETKO IDE JEDNOU CESTOU: „Mapa · Pregeneruj vrstvu kraja"
(`regenerate-region.yml`) postaví LEN tú jednu vec a na Drive prepíše LEN jej
balík (`publish-map.py --only=…`, ktorý položku v katalógu doplní, nie
prepíše). Mapy, dlaždíc ani Pages sa to nedotkne.

Ceny sú ale rôzne a je dobré to vedieť dopredu:

  Z PBF (`body`, `linie`, `navigacia`) sú to MINÚTY na kraj – tie vrstvy sa
  počítajú z toho istého OSM PBF ako mapa a nič iné nepotrebujú.

  Z VÝŠKOVÉHO MODELU (`vrstevnice`, `skaly`, `tienovanie`) sú to desiatky
  minút až hodiny: treba sklad DEM, prípadne ho doplniť, prečítať ho a nad
  ním trasovať. Robí to `dem-layers.yml` – TEN ISTÝ workflow, aký volá build
  mapy, takže sa vrstva z pregenerovania nemá ako rozísť s tou z buildu.
  Ušetrí sa proti celému buildu všetko ostatné: dlaždice, ikonky, štýl,
  kontrola webu, Pages a prepísanie ostatných balíkov na Drive.

VRSTEVNICE A SKALY SÚ JEDEN BALÍK (`-vrstevnice-skaly.zip`), takže sa pri
oboch voľbách počítajú OBE – len tá druhá sa vezme z cache. Balík sa
prepisuje celý a polovica nová s polovicou chýbajúcou by bola balík, ktorý
sľubuje vrstvu, ktorú nenesie.

Použitie:
    python3 workers/state/jobs.py --zoznam            # kľúče, v poradí formulára
    python3 workers/state/jobs.py --workflow=body     # čo sa nad krajom spustí
    python3 workers/state/jobs.py --meno=body         # meno toho workflowu
    python3 workers/state/jobs.py --popis=body        # čo to pregeneruje
    python3 workers/state/jobs.py --polia=body        # `-f` polia, po riadkoch
"""
import argparse
import os
import sys

# ---------- kam sa to nad krajom posiela ----------
# `podava` sú polia, ktoré cieľový workflow prevezme z FORMULÁRA DÁVKY:
# `input: (premenná prostredia, predvolená hodnota)`. Podávajú sa CELÉ
# a zakaždým – články štafety sú samostatné behy a beh, ktorý by ich nedostal,
# by pregeneroval s predvolenými hodnotami a bol by pri tom zelený. To isté
# pravidlo (a ten istý dôvod) ako v `workers/state/relay.sh`.
CIELE = {
    "regenerate-region.yml": {
        "meno": "Mapa · Pregeneruj vrstvu kraja",
        "podava": {
            # Zdroje výšok a prah sklonu majú význam len pre vrstvy
            # z výškového modelu; pri `body`, `linie` a `navigacia` ich ten
            # workflow prijme a nepoužije. Podávajú sa aj tak VŽDY a všetky:
            # zoznam podľa `co` by bol štvrté miesto, kde sa rozhoduje, čo tá
            # voľba znamená – a to je presne to, čo sa raz rozíde.
            "contour_source": ("CONTOUR_SOURCE", "dmr5"),
            "rock_source": ("ROCK_SOURCE", "dmr5"),
            "shading_source": ("SHADING_SOURCE", "dmr5"),
            "rock_slope": ("ROCK_SLOPE", "50"),
            "test": ("TEST", "false"),
            "options": ("OPTIONS", ""),
        },
    },
}

# ---------- čo sa dá pregenerovať ----------
# PORADIE JE PORADIE FORMULÁRA a ide od najlacnejšieho k najdrahšiemu: body
# a línie sú minúty, vrstevnice a tieňovanie hodiny. Kto formulár otvorí,
# má hore to, čo si pustí najčastejšie.
#
# `balik` je meno balíka na Drive, ktorý sa tým prepíše (`` = základná mapa) –
# je to to isté meno, aké pozná `workers/deploy/publish-map.py`, a práve preto
# sa tu píše: podľa neho sa dá v súhrne aj v katalógu povedať, čo sa zmenilo.
JOBS = {
    "body": {
        "meno": "Body z OSM",
        "popis": "pramene, jaskyne, rozhľadne, parkoviská a ďalšie bodové "
                 "prvky – balík `-body.zip`",
        "balik": "body",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "body"},
    },
    # LÍNIE SÚ TRI VRSTVY V JEDNOM BALÍKU: celá dopravná sieť (cesty od
    # diaľnice po schody, železnice, trajekty, lanovky), značené trasy
    # a obmedzenia na ceste. Pregenerujú sa VŠETKY TRI naraz, lebo `--only`
    # prepisuje balík CELÝ – jedna nová vrstva a dve chýbajúce by z neho
    # spravili balík, ktorý sľubuje, čo nenesie.
    "linie": {
        "meno": "Dopravná sieť a línie z OSM",
        "popis": "cesty, železnice, trajekty a lanovky, značené trasy "
                 "a obmedzenia na ceste – balík `-linie.zip`",
        "balik": "linie",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "linie"},
    },
    # NAVIGÁCIA JE VLASTNÁ VOĽBA, lebo je VLASTNÝ BALÍK. Chvíľu bola časťou
    # `linie` (tá istá sieť, raz nakreslená a raz zjazdná), ale graf kraja
    # váži 170 až 190 MB proti desiatkam za tie tri kreslené vrstvy – v jednom
    # balíku by z neho bolo deväť desatín. Rozpis je v hlavičke
    # `workers/deploy/subory.py`. Je to zároveň jediná vec, ktorá sa mení pri
    # zdvihnutí verzie Valhally, a prestavovať kvôli nej dopravnú sieť by bolo
    # zbytočné.
    "navigacia": {
        "meno": "Navigačný graf (Valhalla)",
        "popis": "graf pre trasovanie v tomto kraji – balík `-navigacia.zip`",
        "balik": "navigacia",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "navigacia"},
    },
    # Ďalej vrstvy z výškového modelu. Sú drahšie (sklad DEM, čítanie
    # a trasovanie), ale cesta je tá istá – `dem-layers.yml`, čiže ten istý
    # workflow, aký nad nimi púšťa build mapy.
    "vrstevnice": {
        "meno": "Vrstevnice",
        "popis": "izolínie z výškového modelu – balík "
                 "`-vrstevnice-skaly.zip` (skaly v ňom prídu z cache)",
        "balik": "vrstevnice-skaly",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "vrstevnice"},
    },
    "skaly": {
        "meno": "Skaly",
        "popis": "skalné plochy zo sklonu modelu – balík "
                 "`-vrstevnice-skaly.zip` (vrstevnice v ňom prídu z cache)",
        "balik": "vrstevnice-skaly",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "skaly"},
    },
    "tienovanie": {
        "meno": "Tieňovanie a 3D terén",
        "popis": "výškové dlaždice pre tieňovanie a 3D – balík "
                 "`-tienovanie.zip`",
        "balik": "tienovanie",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "tienovanie"},
    },
}


def job(kluc):
    """Položka číselníka, alebo tvrdý pád s tým, čo sa dá zadať."""
    if kluc not in JOBS:
        print(f"::error::Pregenerovať sa dá {', '.join(JOBS)} – „{kluc}“ "
              f"nepoznám. Zoznam drží {os.path.relpath(__file__)}.",
              file=sys.stderr)
        sys.exit(1)
    return JOBS[kluc]


def polia(kluc, env=None):
    """`-f` polia pre beh nad jedným krajom: {input: hodnota}.

    `region` tu NIE JE – ten dopĺňa štafeta, lebo sa mení s každým článkom.
    """
    env = os.environ if env is None else env
    j = job(kluc)
    out = dict(j["inputs"])
    for meno, (premenna, predvolene) in CIELE[j["workflow"]]["podava"].items():
        out[meno] = env.get(premenna) or predvolene
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zoznam", action="store_true",
                    help="kľúče, ktoré sa dajú pregenerovať")
    ap.add_argument("--workflow", default="", help="workflow nad jedným krajom")
    ap.add_argument("--meno", default="", help="meno toho workflowu")
    ap.add_argument("--popis", default="", help="čo tá voľba pregeneruje")
    ap.add_argument("--polia", default="",
                    help="`-f` polia behu nad krajom, po riadkoch `kľúč=hodnota`")
    args = ap.parse_args()

    if args.zoznam:
        print("\n".join(JOBS))
    elif args.workflow:
        print(job(args.workflow)["workflow"])
    elif args.meno:
        print(CIELE[job(args.meno)["workflow"]]["meno"])
    elif args.popis:
        j = job(args.popis)
        print(f"{j['meno']} – {j['popis']}")
    elif args.polia:
        # Po riadkoch, `kľúč=hodnota`: hodnota môže mať medzery (`options`),
        # takže ju číta `while IFS= read -r` a nie rozpad na slová.
        for k, v in polia(args.polia).items():
            print(f"{k}={v}")
    else:
        ap.error("zadaj --zoznam, --workflow=, --meno=, --popis= alebo --polia=")


if __name__ == "__main__":
    main()
