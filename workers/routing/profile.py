#!/usr/bin/env python3
"""
Z jedného profilu costing pre ktorýkoľvek motor – a hlasno o tom, čo nevie.

JEDNA OTÁZKA, JEDNO MIESTO (pravidlo 1). To, čo si používateľ vypýtal
(„autom, bez diaľnic, najviac 110, v Rakúsku známku nemám"), je napísané raz –
v `workers/data/routing-profiles.json` a `workers/data/vignettes.json`. Tento
modul z toho skladá vstup pre motor: `costing_options` pre Valhallu alebo
`custom_model` pre GraphHopper. Keby si každý motor niesol vlastný profil, boli
by to dve pravdy o jednej otázke – a rozišli by sa TICHO, lebo oba profily sú
samy o sebe platné a trasa sa spočíta. Len by jedna obchádzala diaľnicu a druhá
nie.

A ČO MOTOR NEVIE, SA MUSÍ POVEDAŤ (pravidlo 8). Nepokrytá voľba sa NEVYNECHÁ:
ide na chybový výstup, do `_nepokryte` vo výsledku a s `--strict` z nej je pád.
Ticho vynechaná voľba je presne ten druh chyby, ktorý sa nedá spozorovať –
používateľ si odškrtne „vyhnúť sa cestám I. triedy", trasa ho po nich povedie
a nič o tom nepovie.

Použitie:
    python3 workers/routing/profile.py --list
    python3 workers/routing/profile.py --mode=auto --engine=valhalla \\
        --set avoid_motorway=true --set top_speed=110
    python3 workers/routing/profile.py --mode=auto --engine=graphhopper \\
        --set avoid_primary=true --vignette SK=2026-09-30 --vignette AT=nie \\
        --date=2026-08-30
    python3 workers/routing/profile.py --check      # čo ktorý motor pokrýva
"""
import argparse
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

PROFILES = os.path.join(_DATA, "routing-profiles.json")
VIGNETTES = os.path.join(_DATA, "vignettes.json")

# `required_on` v `vignettes.json` sú OSM triedy; GraphHopper ich volá inak.
# Preklad je TU a len tu – v číselníku majú stáť OSM mená, lebo tie pozná graf.
GH_ROAD_CLASS = {
    "motorway": "MOTORWAY",
    "trunk": "TRUNK",
    "primary": "PRIMARY",
    "secondary": "SECONDARY",
    "tertiary": "TERTIARY",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def as_text(value):
    """Číslo do vlastného modelu ako text – a bez `.0` na konci.

    GraphHopper číta `limit_to` ako výraz, takže `"110.0"` prejde; v profile,
    ktorý si niekto pozrie okom, je to ale šum a pri celom čísle rovno omyl
    („zadal som 110, prečo je tam 110.0?“).
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def public(d):
    """Kľúče s `_` sú komentár a metadáta číselníka, nie záznamy."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


class Profile:
    """Profil = režim + hodnoty volieb + stav známok. Nič viac."""

    def __init__(self, profiles=None, vignettes=None):
        self.raw = profiles if profiles is not None else load(PROFILES)
        self.vig = vignettes if vignettes is not None else load(VIGNETTES)
        self.modes = public(self.raw["modes"])
        self.options = public(self.raw["options"])
        self.engines = public(self.raw["engines"])
        self.countries = public(self.vig["countries"])

    # ---------- voľby ----------

    def coerce(self, key, text):
        """Text z príkazovej riadky na hodnotu podľa `type` voľby."""
        spec = self.options[key]
        kind = spec["type"]
        if kind == "switch":
            if text.lower() in ("true", "ano", "1", "yes"):
                return True
            if text.lower() in ("false", "nie", "0", "no"):
                return False
            raise ValueError(f"voľba `{key}` je prepínač – čakám ano/nie, "
                             f"dostal som `{text}`")
        if kind in ("speed", "factor"):
            value = float(text)
        elif kind == "int":
            value = int(text)
        elif kind == "enum":
            if text not in spec["values"]:
                raise ValueError(f"voľba `{key}` pozná {spec['values']}, "
                                 f"nie `{text}`")
            return text
        else:
            raise ValueError(f"voľba `{key}` má typ `{kind}`, ktorý sa "
                             f"z príkazovej riadky zadať nedá")
        lo, hi = spec.get("range", (None, None))
        if lo is not None and not (lo <= value <= hi):
            raise ValueError(f"voľba `{key}` má byť v rozsahu {lo}–{hi}, "
                             f"dostal som {value}")
        return value

    def check_mode(self, mode):
        if mode not in self.modes:
            raise ValueError(f"režim `{mode}` neexistuje. Sú: "
                             f"{', '.join(sorted(self.modes))}")

    def check_option(self, mode, key):
        """Voľba musí byť v číselníku AJ v zozname volieb toho režimu."""
        self.check_mode(mode)
        if key not in self.options:
            raise ValueError(f"voľba `{key}` nie je v číselníku. Doplň ju do "
                             f"`workers/data/routing-profiles.json`.")
        if key not in self.modes[mode]["options"]:
            raise ValueError(
                f"voľba `{key}` sa v režime `{mode}` neponúka. Ponúkané: "
                f"{', '.join(self.modes[mode]['options'])}. Keď tam patriť má, "
                f"dopíš ju do `modes.{mode}.options` – nie do kódu.")

    # ---------- známky ----------

    def vignette_state(self, given, date):
        """Ktoré krajiny sa musia obchádzať a čo o tom treba povedať.

        TRI ODPOVEDE, NIE DVE. „Známku mám do…", „nemám" a „táto krajina
        známku nepozná" sú tri rôzne veci a stlačiť sa do dvoch nedajú: v Poľsku
        sa diaľnici netreba vyhýbať preto, že tam známka neexistuje.

        A ŠTVRTÁ MOŽNOSŤ JE „NEVIEM" – krajina, o ktorej používateľ nepovedal
        nič. Tá sa NESMIE dosadiť potichu ani na jednu stranu: „mám" by mu
        vypísalo pokutu, „nemám" by ho poslalo sto kilometrov po okreskách.
        Berie sa ako „nemám" (lacnejší omyl z tých dvoch) a HLASNO sa to
        vypíše – aplikácia sa má spýtať, nie hádať.
        """
        avoid, notes, unknown = {}, [], []
        for code, c in sorted(self.countries.items()):
            if not c.get("ma_znamku"):
                continue
            answer = given.get(code)
            if answer is None:
                unknown.append(code)
                avoid[code] = c
                continue
            if answer == "nie":
                avoid[code] = c
                continue
            if answer == "ano":
                continue
            valid_to = datetime.date.fromisoformat(answer)
            if valid_to < date:
                avoid[code] = c
                notes.append(f"{code}: známka platila do {valid_to.isoformat()}, "
                             f"jazda je {date.isoformat()} – berie sa ako bez známky")
        if unknown:
            notes.append(
                "Nepovedal si nič o známke pre: " + ", ".join(unknown) +
                ". Berú sa ako BEZ ZNÁMKY a trasa sa im vyhne. Keď ju máš, "
                "povedz to (`--vignette SK=2026-09-30` alebo `SK=ano`).")
        stale = sorted(c for c, v in self.countries.items()
                       if v.get("stav") != "overene")
        if stale:
            notes.append(
                "NEOVERENÉ ÚDAJE O ZNÁMKACH: " + ", ".join(stale) +
                ". `vignettes.json` má pri nich `stav: doplnit` – kým to tak "
                "je, nesmie to ísť do aplikácie ako fakt (pravidlo 8).")
        return avoid, notes

    # ---------- preklad do motorov ----------

    def compile(self, mode, values, vignettes, date, engine):
        self.check_mode(mode)
        spec = self.modes[mode]
        if engine not in self.engines:
            raise ValueError(f"motor `{engine}` neexistuje. Sú: "
                             f"{', '.join(sorted(self.engines))}")
        costing = spec["costing"].get(engine)
        if costing is None:
            raise ValueError(f"režim `{mode}` nemá v motore `{engine}` costing – "
                             f"dopíš ho do `modes.{mode}.costing`.")

        missing, soft = [], []
        avoid, notes = ({}, [])
        if "vignettes" in values and values["vignettes"]:
            avoid, notes = self.vignette_state(vignettes, date)

        if engine == "valhalla":
            out = self._valhalla(costing, values, avoid, missing, soft)
        else:
            out = self._graphhopper(costing, values, avoid, missing, soft)

        if spec.get("needs_gtfs"):
            notes.append(
                f"Režim `{mode}` stojí na cestovných poriadkoch (GTFS), nie na "
                f"OSM. Bez nahraného GTFS zdroja motor trasu nenájde a povie "
                f"„no route“ – nie je to chyba profilu. Viď docs/navigation.md.")
        out["_nepokryte"] = missing
        out["_priblizne"] = soft
        out["_pozn"] = notes
        return out

    def _valhalla(self, costing, values, avoid, missing, soft):
        opts = {}
        for key, value in values.items():
            spec = self.options[key]
            rule = spec.get("valhalla", {})
            if key == "vignettes":
                if value and avoid:
                    missing.append(self._miss(key, rule, extra=(
                        "Obchádzať by sa mali: " +
                        ", ".join(f"{c} ({', '.join(v['required_on'])})"
                                  for c, v in avoid.items()))))
                continue
            if "unsupported" in rule:
                if value:
                    missing.append(self._miss(key, rule))
                continue
            if not value and spec["type"] == "switch":
                continue
            if "set" in rule:
                opts.update(rule["set"])
            if "soft" in rule:
                opts.update(rule["soft"])
                soft.append({"option": key, "name": spec["name"],
                             "dovod": rule.get("note", [])})
            if "set_value" in rule:
                opts[rule["set_value"]] = value
        return {"costing": costing, "costing_options": {costing: opts}}

    def _graphhopper(self, costing, values, avoid, missing, soft):
        model = {"priority": [], "speed": []}
        for key, value in values.items():
            spec = self.options[key]
            rule = spec.get("graphhopper", {})
            if key == "vignettes":
                if value:
                    model["priority"].extend(self._gh_vignettes(rule, avoid))
                continue
            if "unsupported" in rule:
                if value:
                    missing.append(self._miss(key, rule))
                continue
            if not value and spec["type"] == "switch":
                continue
            for slot in ("priority", "speed"):
                for stmt in rule.get(slot, []):
                    model[slot].append(
                        {k: (as_text(value) if v == "{value}" else v)
                         for k, v in stmt.items()})
        model = {k: v for k, v in model.items() if v}
        # `ch.disable` MUSÍ byť pri vlastnom modeli. Contraction Hierarchies sú
        # predpočítané pre pevné váhy, takže s vlastným modelom by GraphHopper
        # vrátil trasu podľa TÝCH predpočítaných – teda ticho ignoroval celý
        # profil a vyzeralo by to, že voľby nič nerobia.
        return {"profile": costing, "custom_model": model, "ch.disable": True}

    def _gh_vignettes(self, rule, avoid):
        out = []
        for code, c in avoid.items():
            classes = [GH_ROAD_CLASS[k] for k in c["required_on"]
                       if k in GH_ROAD_CLASS]
            if not classes:
                continue
            expr = " || ".join(f"road_class == {k}" for k in classes)
            for stmt in rule["priority_template"]:
                out.append({
                    k: (v.replace("{alpha3}", c["alpha3"])
                         .replace("{classes}", expr) if isinstance(v, str) else v)
                    for k, v in stmt.items()})
        return out

    def _miss(self, key, rule, extra=None):
        spec = self.options[key]
        why = rule.get("unsupported") or ["(dôvod v číselníku nie je)"]
        item = {"option": key, "name": spec["name"], "dovod": why}
        if extra:
            item["detail"] = extra
        return item

    # ---------- prehľady ----------

    def coverage(self):
        """Ktorá voľba je v ktorom motore – matica, nie dojem."""
        rows = []
        for key, spec in sorted(self.options.items()):
            row = {"option": key, "name": spec["name"]}
            for engine in sorted(self.engines):
                rule = spec.get(engine, {})
                if "unsupported" in rule:
                    row[engine] = "nie"
                elif "soft" in rule:
                    row[engine] = "priblizne"
                elif rule:
                    row[engine] = "ano"
                else:
                    row[engine] = "chyba"
            rows.append(row)
        return rows


def print_list(p):
    print("Režimy:")
    for key, spec in p.modes.items():
        gtfs = "  [potrebuje GTFS]" if spec.get("needs_gtfs") else ""
        print(f"  {key:<11} {spec['name']}{gtfs}")
        print(f"              voľby: {', '.join(spec['options'])}")
    print("\nMotory:")
    for key, spec in p.engines.items():
        print(f"  {key:<12} {spec['name']} ({spec['lang']}, {spec['kde']})")


def print_coverage(p):
    engines = sorted(p.engines)
    head = f"{'voľba':<24}" + "".join(f"{e:<14}" for e in engines)
    print(head)
    print("-" * len(head))
    bad = 0
    for row in p.coverage():
        line = f"{row['option']:<24}"
        for e in engines:
            line += f"{row[e]:<14}"
            if row[e] == "chyba":
                bad += 1
        print(line)
    if bad:
        print(f"\n{bad}× `chyba`: voľba nemá pre motor ani mapovanie, ani "
              f"`unsupported` s dôvodom. Doplň jedno alebo druhé – mlčanie "
              f"znamená, že sa voľba ticho zahodí.")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", help="režim: auto, bicycle, pedestrian, bus, transit")
    ap.add_argument("--engine", default="valhalla", help="valhalla | graphhopper")
    ap.add_argument("--set", action="append", default=[], metavar="VOLBA=HODNOTA",
                    help="hodnota voľby, dá sa opakovať")
    ap.add_argument("--vignette", action="append", default=[], metavar="XX=DATUM",
                    help="`SK=2026-09-30`, `AT=nie`, `CZ=ano`")
    ap.add_argument("--date", help="dátum jazdy (YYYY-MM-DD), inak dnes")
    ap.add_argument("--strict", action="store_true",
                    help="nepokrytá voľba je chyba, nie varovanie")
    ap.add_argument("--list", action="store_true", help="čo sa dá vypýtať")
    ap.add_argument("--check", action="store_true",
                    help="matica: ktorá voľba je v ktorom motore")
    args = ap.parse_args()

    p = Profile()
    if args.list:
        print_list(p)
        return 0
    if args.check:
        return 1 if print_coverage(p) else 0
    if not args.mode:
        ap.error("povedz --mode (alebo --list / --check)")

    values, vignettes = {}, {}
    try:
        for item in args.set:
            key, _, text = item.partition("=")
            p.check_option(args.mode, key)
            values[key] = p.coerce(key, text)
        for item in args.vignette:
            code, _, text = item.partition("=")
            code = code.upper()
            if code not in p.countries:
                raise ValueError(f"krajinu `{code}` `vignettes.json` nepozná. "
                                 f"Doplň ju tam – nie do kódu.")
            vignettes[code] = text if text in ("ano", "nie") else \
                datetime.date.fromisoformat(text).isoformat()
        if vignettes and "vignettes" in p.modes[args.mode]["options"]:
            values.setdefault("vignettes", True)
        date = (datetime.date.fromisoformat(args.date) if args.date
                else datetime.date.today())
        out = p.compile(args.mode, values, vignettes, date, args.engine)
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2

    for note in out["_pozn"]:
        print(f"::notice::{note}", file=sys.stderr)
    for item in out["_priblizne"]:
        print(f"::warning::Voľba „{item['name']}“ je v motore `{args.engine}` "
              f"len PRIBLIŽNÁ (odradenie, nie zákaz).", file=sys.stderr)
    for item in out["_nepokryte"]:
        print(f"::error::Voľba „{item['name']}“ sa v motore `{args.engine}` "
              f"povedať NEDÁ: {' '.join(item['dovod'])}", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out["_nepokryte"] and args.strict:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
