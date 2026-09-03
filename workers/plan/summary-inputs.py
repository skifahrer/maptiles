#!/usr/bin/env python3
"""
Blok „Nastavenia tohto behu" do súhrnu behu – píše ho job `settings`, teda
úplne prvý job behu (`workers/plan/settings.sh`).

PREČO: formulár *Run workflow* sa vždy otvorí s predvolenými hodnotami –
GitHub si nepamätá, s čím si beh spustil naposledy, a ani to nevie: hodnoty
z minulého behu nie sú nikde v API. Keď teda chceš beh zopakovať a zmeniť
jedinú vec (typicky `rebuild`), ostatné polia musíš nastaviť znova – a nemáš
ich odkiaľ odpísať, lebo v Actions ich vidno len ako rozklikávací detail
behu. Toto je ten zoznam, na jednom mieste a na skopírovanie.

NA ZAČIATKU, NIE NA KONCI. Bol to posledný krok súhrnu, čiže sa dal prečítať
až po dobehnutí – a keď beh po hodine spadol, nedal sa prečítať vôbec. Zoznam,
z ktorého sa beh opakuje, treba práve vtedy, keď sa niečo pokazilo.

Predvolené hodnoty sa čítajú z workflowu, nie sú tu napísané druhýkrát –
inak by sa raz rozišli a súhrn by tvrdil, že si nič nemenil. Čo je iné než
default, je označené: presne tie polia treba pri opakovaní prekliknúť.

`--with-env` pridá druhú tabuľku: `env:` celého workflowu, teda tie
nastavenia, ktoré vo formulári NIE SÚ a menia sa prepísaním workflowu
(prahy skál, hladenie vrstevníc, mená skladov, rozpočty na vrstvy). Kľúče
sa čítajú z workflowu a hodnoty z PROSTREDIA, takže je vidieť to, s čím beh
naozaj ide, nie to, čo je napísané v súbore.

HODNOTY SO SECRETOM SA NEVYPISUJÚ. Repozitár je public, takže súhrn behu
vidí ktokoľvek – a `GDRIVE_CREDENTIALS` či `DRIVE_REFRESH` je prístup na
celý Drive vlastníka. Maskovanie GitHubu platí na log, na súhrn sa naň
spoliehať netreba: čo je v YAMLe `secrets.*`, sa nahradí značkou už tu.

Použitie:
    python3 workers/plan/summary-inputs.py \\
        --inputs="$INPUTS_JSON" --workflow=.github/workflows/build-map-region.yml \\
        --with-env
"""
import argparse
import json
import os
import sys

import yaml


def defaults(path):
    """Predvolené hodnoty inputov priamo z workflowu → {pole: hodnota}."""
    with open(path) as f:
        doc = yaml.safe_load(f)
    # `on:` YAML načíta ako True (je to booleanovské kľúčové slovo), takže
    # sa kľúč hľadá oboma spôsobmi – rovnako to robí aj „Kontrola · lint workflowov".
    on = doc[[k for k in doc if k is True or k == "on"][0]]
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
    return {k: text(v.get("default", "")) for k, v in inputs.items()}


def env_table(path):
    """`env:` workflowu → riadky tabuľky s hodnotou, s akou beh naozaj ide.

    Kľúče sú z workflowu, hodnoty z prostredia: `${{ vars.DRIVE_CLIENT }}`
    napísané v YAMLe nehovorí nič o tom, čo v tom behu naozaj je. Keď
    premenná v prostredí nie je (skript sa púšťa lokálne), ukáže sa surová
    hodnota zo súboru – a je označená, nech sa to nepomýli.

    Čo je v YAMLe `secrets.*`, sa nevypisuje vôbec (súhrn behu je verejný).
    """
    with open(path) as f:
        doc = yaml.safe_load(f)
    riadky = []
    for k, raw in (doc.get("env") or {}).items():
        raw = text(raw)
        if "secrets." in raw:
            riadky.append((k, "*(secret – nevypisuje sa)*"))
            continue
        v = os.environ.get(k)
        if v is None:
            riadky.append((k, f"`{raw}` *(zo súboru)*" if raw else "*(prázdne)*"))
        else:
            riadky.append((k, f"`{v}`" if v else "*(prázdne)*"))
    return riadky


def text(v):
    """Hodnota na text tak, ako ju vidí beh.

    `type: boolean` je v YAMLe naozajstný boolean, takže by z neho Python
    spravil „True" – ale v `inputs` behu je to reťazec „true". Bez tohto by
    každý switch v tabuľke svietil ako zmenený, hoci je na predvolenej
    hodnote.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="",
                    help="JSON s hodnotami inputov behu (toJSON(inputs))")
    ap.add_argument("--workflow", default=".github/workflows/build-map-region.yml")
    ap.add_argument("--with-env", action="store_true",
                    help="pridať aj tabuľku `env:` workflowu (nastavenia, "
                         "ktoré vo formulári nie sú)")
    args = ap.parse_args()

    try:
        values = json.loads(args.inputs or "{}")
    except json.JSONDecodeError as e:
        print(f"::warning::Nastavenia behu sa nepodarilo prečítať ({e}).",
              file=sys.stderr)
        values = {}

    try:
        deflt = defaults(args.workflow)
    except (OSError, KeyError, TypeError) as e:
        print(f"::warning::Predvolené hodnoty sa nepodarilo prečítať ({e}).",
              file=sys.stderr)
        deflt = {}

    riadky, zmenene = [], []
    for k, v in values.items():
        v = text(v)
        d = deflt.get(k)
        if d is None:
            # Default sa nepodarilo prečítať – povedať „default" by bola
            # výmysel; hodnota samotná je aj tak to hlavné, čo tu treba.
            stav = "—"
        elif v == d:
            stav = "default"
        else:
            stav = "**iné než default**"
            zmenene.append(k)
        riadky.append("| `{}` | {} | {} |".format(
            k, f"`{v}`" if v else "*(prázdne)*", stav))

    out = []
    if riadky:
        out += ["## Formulár, z ktorého beh vyšiel", "",
                "| pole | hodnota | |", "|---|---|---|"] + riadky + [""]
        if zmenene:
            out += ["Formulár *Run workflow* sa vždy otvorí s predvolenými "
                    "hodnotami, takže pri opakovaní behu treba znova nastaviť: "
                    + ", ".join(f"**{k}**" for k in zmenene) + ".", ""]
        elif deflt:
            out += ["Všetko na predvolených hodnotách – taký beh sa opakuje "
                    "samotným *Run workflow*, nič netreba prekliknúť.", ""]

    # Druhá tabuľka: čo vo formulári NIE JE. Bez nej sa z behu nedá zistiť,
    # s akým prahom skál alebo do ktorého skladu vlastne išiel – a to sú
    # presne tie čísla, na ktoré sa človek pýta, keď výsledok vyzerá inak,
    # než čakal.
    if args.with_env:
        try:
            env = env_table(args.workflow)
        except (OSError, KeyError, TypeError) as e:
            print(f"::warning::`env:` workflowu sa nepodarilo prečítať ({e}).",
                  file=sys.stderr)
            env = []
        if env:
            out += ["## Nastavenia workflowu (`env:`)", "",
                    "Vo formulári nie sú – menia sa zmenou "
                    f"`{args.workflow}`.", "",
                    "| nastavenie | hodnota |", "|---|---|"]
            out += [f"| `{k}` | {v} |" for k, v in env] + [""]

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
