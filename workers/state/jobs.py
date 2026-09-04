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

DVE CESTY, A JE TO ZÁMER. Nie každá vrstva sa dá pregenerovať rovnako lacno:

  VLASTNÝ BALÍK Z PBF (`body`, `linie`, `navigacia`) ide cez „Mapa ·
  Pregeneruj vrstvu kraja" (`regenerate-region.yml`). Tie vrstvy sa počítajú
  z toho istého OSM PBF ako mapa a nič iné z buildu nepotrebujú, takže sa dá
  postaviť LEN tá vrstva a na Drive prepísať LEN jej balík
  (`publish-map.py --only=…`, ktorý položku v katalógu doplní, nie prepíše).
  Trvá to minúty namiesto hodín a mapy sa to nedotkne.

  VRSTVY Z VÝŠKOVÉHO MODELU (`vrstevnice`, `skaly`, `tienovanie`) idú cez
  celý „Mapa · Build map region" s `rebuild`. Nie preto, že by sa nechcelo:
  potrebujú sklad DEM, jeho doplnenie (`check-dem` a päť `mirror-*` jobov),
  kľúče cache aj orez na výrez – a to je polovica toho workflowu. Druhá kópia
  toho všetkého by bola presne ten druh dvoch právd, ktorý sa raz rozíde
  a vrstevnice by z nej vyšli inak než z buildu. `rebuild` je páka, ktorá na
  presne toto existuje: zahodí cache tej jednej vrstvy a zvyšok behu ju má
  z nej. Stojí to celý build kraja – to je cena za jednu pravdu o tom, ako
  vrstevnice vznikajú.

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
            "test": ("TEST", "false"),
            "options": ("OPTIONS", ""),
        },
    },
    "build-map-region.yml": {
        "meno": "Mapa · Build map region",
        "podava": {
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
    # LÍNIE A NAVIGÁCIA SÚ JEDNA VOĽBA, lebo sú JEDEN BALÍK. Značené trasy,
    # obmedzenia na ceste a graf Valhally je tá istá cestná a chodníková sieť
    # z toho istého PBF – raz nakreslená a raz zjazdná – a `-linie.zip` nesie
    # všetky tri. Samostatná voľba „navigácia" by znamenala `--only=linie`
    # s balíkom, v ktorom je len graf: trasy a obmedzenia by z neho ticho
    # vypadli. Rozpis je v hlavičke `workers/deploy/subory.py`.
    "linie": {
        "meno": "Línie z OSM",
        "popis": "značené trasy, obmedzenia na ceste a navigačný graf "
                 "(Valhalla) – balík `-linie.zip`",
        "balik": "linie",
        "workflow": "regenerate-region.yml",
        "inputs": {"co": "linie"},
    },
    # Ďalej vrstvy z výškového modelu. Idú celým buildom kraja – rozpis prečo
    # je v hlavičke súboru. `area: cely_region` a `publish_pages: false` sú
    # natvrdo z toho istého dôvodu ako v dávke „Build map state": výrez
    # (pohorie) pre osem krajov nedáva zmysel a Pages unesú JEDNU mapu.
    "vrstevnice": {
        "meno": "Vrstevnice",
        "popis": "izolínie z výškového modelu – balík `-vrstevnice-skaly.zip` "
                 "(cez celý build kraja, `rebuild: vrstevnice`)",
        "balik": "vrstevnice-skaly",
        "workflow": "build-map-region.yml",
        "inputs": {"rebuild": "vrstevnice", "area": "cely_region",
                   "publish_pages": "false"},
    },
    "skaly": {
        "meno": "Skaly",
        "popis": "skalné plochy zo sklonu modelu – balík "
                 "`-vrstevnice-skaly.zip` (cez celý build kraja, "
                 "`rebuild: skaly`)",
        "balik": "vrstevnice-skaly",
        "workflow": "build-map-region.yml",
        "inputs": {"rebuild": "skaly", "area": "cely_region",
                   "publish_pages": "false"},
    },
    "tienovanie": {
        "meno": "Tieňovanie a 3D terén",
        "popis": "výškové dlaždice – balík `-tienovanie.zip` (cez celý build "
                 "kraja, `rebuild: tienovanie`)",
        "balik": "tienovanie",
        "workflow": "build-map-region.yml",
        "inputs": {"rebuild": "tienovanie", "area": "cely_region",
                   "publish_pages": "false"},
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
