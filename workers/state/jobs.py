#!/usr/bin/env python3
"""
Čo sa dá pregenerovať v celej krajine – a čím sa to nad jedným krajom spustí.

„Mapa · Regenerate state" je tá istá štafeta ako „Build map state", len nad
krajom nespúšťa CELÝ build, ale JEDEN BALÍK: body záujmu, cesty a chodníky,
hranice, vodstvo, navigáciu, vrstevnice, skaly alebo tieňovanie. Ktoré balíky
sú, drží číselník `workers/data/packages.json`; tento súbor k nim dopĺňa to,
čo je vec dávky – poradie vo formulári, vetu do súhrnu a ktorý workflow to nad
krajom spraví.

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

  Z PBF (`body`, `cesty`, `hranice`, `vodstvo`, `navigacia`) sú to MINÚTY na
  kraj – tie vrstvy sa počítajú z toho istého OSM PBF ako mapa a nič iné
  nepotrebujú.

  Z VÝŠKOVÉHO MODELU (`vrstevnice`, `skaly`, `tienovanie`) sú to desiatky
  minút až hodiny: treba sklad DEM, prípadne ho doplniť, prečítať ho a nad
  ním trasovať. Robí to `dem-layers.yml` – TEN ISTÝ workflow, aký volá build
  mapy, takže sa vrstva z pregenerovania nemá ako rozísť s tou z buildu.
  Ušetrí sa proti celému buildu všetko ostatné: dlaždice, ikonky, štýl,
  kontrola webu, Pages a prepísanie ostatných balíkov na Drive.

ZÁKLADNÁ MAPA A ČLÁNKY Z WIKIPÉDIE TU NIE SÚ. Mapa je celý build (dlaždice
Planetilerom nad celým PBF, štýl, ikonky) – pregenerovať „len ju" znamená
spustiť „Mapa · Build map region"; a značené trasy, ktoré v nej cestujú, sú
preto tiež jej vec. Články majú vlastnú pipeline („Mapa · Build wiki") s inou
sieťou a inou životnosťou.

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
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)


def _load(name, cesta):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    spec = importlib.util.spec_from_file_location(name, cesta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_baliky = _load("deploy_baliky", os.path.join(_WORKERS, "deploy", "baliky.py"))

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
            # z výškového modelu; pri vrstvách z PBF ich ten
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
# ODVODENÉ Z ČÍSELNÍKA BALÍKOV, nie napísané druhýkrát. Ktoré balíky sú, drží
# `workers/data/packages.json` (kľúč `regeneruj` hovorí, čo sa dá postaviť bez
# celého buildu mapy) – tento súbor k tomu dopĺňa len to, čo je vec DÁVKY:
# poradie vo formulári, vetu do súhrnu a to, ktorý workflow sa nad krajom
# spustí.
#
# Kým bol zoznam napísaný aj tu, znamenal nový balík dve úpravy a zabudnutá
# druhá bola tichá jedným smerom (voľba vo formulári, ktorú packer nepozná,
# spadne až v behu) a hlučná druhým. Teraz je tu jediná vec, ktorú číselník
# nevie: ako drahé to je a čo o tom povedať človeku.
#
# PORADIE JE PORADIE FORMULÁRA a ide od najlacnejšieho k najdrahšiemu: body
# a cesty sú minúty, vrstevnice a tieňovanie hodiny. Kto formulár otvorí, má
# hore to, čo si pustí najčastejšie.
CENA = {
    # kľúč: (meno, čo to je, veta o cene)
    "body": ("Body záujmu",
             "pramene, jaskyne, rozhľadne, pamiatky a ďalšie bodové prvky"),
    "cesty": ("Cesty a chodníky",
              "celá dopravná sieť z OSM aj s obmedzeniami na ceste (výška "
              "podjazdu, hmotnosť, rýchlosť)"),
    "hranice": ("Hranice a názvy území",
                "hranice štátu, kraja, okresu a obce aj s ich menami"),
    "vodstvo": ("Vodstvo",
                "rieky, potoky, jazerá, priehrady a more aj s ich menami"),
    "navigacia": ("Navigačný graf (Valhalla)",
                  "graf pre trasovanie v tomto kraji"),
    "vrstevnice": ("Vrstevnice",
                   "izolínie z výškového modelu (skaly v balíku prídu "
                   "z cache)"),
    "skaly": ("Skaly",
              "skalné plochy zo sklonu modelu (vrstevnice v balíku prídu "
              "z cache)"),
    "tienovanie": ("Tieňovanie a 3D terén",
                   "výškové dlaždice pre tieňovanie a 3D"),
}

# `skaly` nie je vlastný balík – je to druhá polovica `vrstevnice-skaly`
# a v číselníku preto vlastný `regeneruj` nemá. Vo formulári vlastnú voľbu MÁ:
# obe vrstvy sa počítajú z toho istého DEM a pregenerovať sa dá každá zvlášť
# (tá druhá príde z cache za sekundy), len balík sa prepisuje CELÝ.
ALIAS = {"skaly": "vrstevnice-skaly"}


def _postav():
    """`{kľúč: {meno, popis, balík, workflow, inputs}}` z číselníka a `CENA`."""
    z_ciselnika = _baliky.regenerovatelne()
    out = {}
    for kluc, (meno, co) in CENA.items():
        b = z_ciselnika.get(kluc)
        balik = b["kluc"] if b else ALIAS.get(kluc)
        if not balik:
            raise SystemExit(
                f"::error::`{kluc}` je v CENA, ale v číselníku balíkov "
                f"({_baliky.CISELNIK}) preň nie je `regeneruj` ani alias – "
                f"formulár by ponúkal voľbu, ktorú packer nepozná a beh by "
                f"spadol na `--only`.")
        out[kluc] = {
            "meno": meno,
            "popis": f"{co} – balík `-{balik}.zip`",
            "balik": balik,
            "workflow": "regenerate-region.yml",
            "inputs": {"co": kluc},
        }
    return out


JOBS = _postav()


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
