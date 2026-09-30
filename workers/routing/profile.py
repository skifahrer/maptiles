#!/usr/bin/env python3
"""One profile into costing for any engine – and loud about what an engine can't do.

An option not covered is never dropped: it goes to stderr, into `_unsupported`, and
with `--strict` it fails.

Usage:
    python3 workers/routing/profile.py --list
    python3 workers/routing/profile.py --mode=auto --engine=valhalla \\
        --set avoid_motorway=true --set top_speed=110
    python3 workers/routing/profile.py --mode=auto --engine=graphhopper \\
        --set avoid_primary=true --vignette SK=2026-09-30 --vignette AT=no \\
        --date=2026-08-30
    python3 workers/routing/profile.py --check      # what each engine covers
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

# `required_on` are OSM classes; GraphHopper names them otherwise – translated only here
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
    """A number for the custom model as text – without a trailing `.0`."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def public(d):
    """`_` keys are comments and lookup metadata, not entries."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


class Profile:
    """A profile = mode + option values + vignette state. Nothing more."""

    def __init__(self, profiles=None, vignettes=None):
        self.raw = profiles if profiles is not None else load(PROFILES)
        self.vig = vignettes if vignettes is not None else load(VIGNETTES)
        self.modes = public(self.raw["modes"])
        self.options = public(self.raw["options"])
        self.engines = public(self.raw["engines"])
        self.countries = public(self.vig["countries"])

    def coerce(self, key, text):
        """Command-line text to a value by the option's `type`."""
        spec = self.options[key]
        kind = spec["type"]
        if kind == "switch":
            if text.lower() in ("true", "ano", "1", "yes"):
                return True
            if text.lower() in ("false", "nie", "0", "no"):
                return False
            raise ValueError(f"option `{key}` is a switch – expected yes/no, "
                             f"got `{text}`")
        if kind in ("speed", "factor", "size"):
            # `size` has a unit and a sensible `range`; `factor` is a unitless 0–1 weight
            value = float(text)
        elif kind == "int":
            value = int(text)
        elif kind == "enum":
            if text not in spec["values"]:
                raise ValueError(f"option `{key}` knows {spec['values']}, "
                                 f"not `{text}`")
            return text
        else:
            raise ValueError(f"option `{key}` has type `{kind}`, which can't "
                             f"be given on the command line")
        lo, hi = spec.get("range", (None, None))
        if lo is not None and not (lo <= value <= hi):
            raise ValueError(f"option `{key}` must be within {lo}–{hi}, "
                             f"got {value}")
        return value

    def check_mode(self, mode):
        if mode not in self.modes:
            raise ValueError(f"mode `{mode}` doesn't exist. There are: "
                             f"{', '.join(sorted(self.modes))}")

    def check_option(self, mode, key):
        """The option must be in the lookup AND in the mode's option list."""
        self.check_mode(mode)
        if key not in self.options:
            raise ValueError(f"option `{key}` isn't in the lookup. Add it to "
                             f"`workers/data/routing-profiles.json`.")
        if key not in self.modes[mode]["options"]:
            raise ValueError(
                f"option `{key}` isn't offered in mode `{mode}`. Offered: "
                f"{', '.join(self.modes[mode]['options'])}. If it belongs there, "
                f"add it to `modes.{mode}.options` – not to the code.")

    def vignette_state(self, given, date):
        """Which countries to avoid and what to say about it.

        Three answers plus "unknown": unsaid is taken as "none" (the cheaper mistake), loudly.
        """
        avoid, notes, unknown = {}, [], []
        for code, c in sorted(self.countries.items()):
            if not c.get("sells_vignette"):
                continue
            answer = given.get(code)
            if answer is None:
                unknown.append(code)
                avoid[code] = c
                continue
            if answer == "no":
                avoid[code] = c
                continue
            if answer == "yes":
                continue
            valid_to = datetime.date.fromisoformat(answer)
            if valid_to < date:
                avoid[code] = c
                notes.append(f"{code}: the vignette was valid until {valid_to.isoformat()}, "
                             f"the trip is {date.isoformat()} – taken as without one")
        if unknown:
            notes.append(
                "Nothing said about a vignette for: " + ", ".join(unknown) +
                ". Taken as WITHOUT ONE and the route avoids them. If you have "
                "one, say so (`--vignette SK=2026-09-30` or `SK=yes`).")
        stale = sorted(c for c, v in self.countries.items()
                       if v.get("state") != "verified")
        if stale:
            notes.append(
                "UNVERIFIED VIGNETTE DATA: " + ", ".join(stale) +
                ". `vignettes.json` has `state: unverified` for them – while it "
                "does, it must not reach the app as fact.")
        return avoid, notes

    def compile(self, mode, values, vignettes, date, engine):
        self.check_mode(mode)
        spec = self.modes[mode]
        if engine not in self.engines:
            raise ValueError(f"engine `{engine}` doesn't exist. There are: "
                             f"{', '.join(sorted(self.engines))}")
        costing = spec["costing"].get(engine)
        if costing is None:
            raise ValueError(f"mode `{mode}` has no costing in engine `{engine}` – "
                             f"add it to `modes.{mode}.costing`.")

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
                f"Mode `{mode}` stands on timetables (GTFS), not on OSM. "
                f"Without a GTFS source the engine finds no route and says "
                f"“no route” – not a profile bug. See docs/navigation.md.")
        out["_unsupported"] = missing
        out["_approximate"] = soft
        out["_notes"] = notes
        return out

    def _valhalla(self, costing, values, avoid, missing, soft):
        opts = {}
        for key, value in values.items():
            spec = self.options[key]
            rule = spec.get("valhalla", {})
            if key == "vignettes":
                if value and avoid:
                    missing.append(self._miss(key, rule, extra=(
                        "Should be avoided: " +
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
                             "why": rule.get("note", [])})
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
        # CH is precomputed for fixed weights and would silently ignore the model
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
        why = rule.get("unsupported") or ["(the lookup gives no reason)"]
        item = {"option": key, "name": spec["name"], "why": why}
        if extra:
            item["detail"] = extra
        return item

    def coverage(self):
        """Which option each engine has – a matrix, not an impression."""
        rows = []
        for key, spec in sorted(self.options.items()):
            row = {"option": key, "name": spec["name"]}
            for engine in sorted(self.engines):
                rule = spec.get(engine, {})
                if "unsupported" in rule:
                    row[engine] = "no"
                elif "soft" in rule:
                    row[engine] = "approx"
                elif rule:
                    row[engine] = "yes"
                else:
                    row[engine] = "missing"
            rows.append(row)
        return rows


def print_list(p):
    print("Modes:")
    for key, spec in p.modes.items():
        gtfs = "  [needs GTFS]" if spec.get("needs_gtfs") else ""
        print(f"  {key:<11} {spec['name']}{gtfs}")
        print(f"              options: {', '.join(spec['options'])}")
    print("\nEngines:")
    for key, spec in p.engines.items():
        print(f"  {key:<12} {spec['name']} ({spec['lang']}, {spec['where']})")


def print_coverage(p):
    engines = sorted(p.engines)
    head = f"{'option':<24}" + "".join(f"{e:<14}" for e in engines)
    print(head)
    print("-" * len(head))
    bad = 0
    for row in p.coverage():
        line = f"{row['option']:<24}"
        for e in engines:
            line += f"{row[e]:<14}"
            if row[e] == "missing":
                bad += 1
        print(line)
    if bad:
        print(f"\n{bad}× `missing`: the option has neither a mapping nor "
              f"`unsupported` with a reason for the engine. Add one – silence "
              f"means the option is dropped quietly.")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", help="mode: auto, bicycle, pedestrian, bus, transit")
    ap.add_argument("--engine", default="valhalla", help="valhalla | graphhopper")
    ap.add_argument("--set", action="append", default=[], metavar="OPTION=VALUE",
                    help="an option value, repeatable")
    ap.add_argument("--vignette", action="append", default=[], metavar="XX=DATE",
                    help="`SK=2026-09-30`, `AT=no`, `CZ=yes`")
    ap.add_argument("--date", help="trip date (YYYY-MM-DD), else today")
    ap.add_argument("--strict", action="store_true",
                    help="an unsupported option is an error, not a warning")
    ap.add_argument("--list", action="store_true", help="what can be asked for")
    ap.add_argument("--check", action="store_true",
                    help="matrix: which option each engine has")
    args = ap.parse_args()

    p = Profile()
    if args.list:
        print_list(p)
        return 0
    if args.check:
        return 1 if print_coverage(p) else 0
    if not args.mode:
        ap.error("give --mode (or --list / --check)")

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
                raise ValueError(f"`vignettes.json` doesn't know country `{code}`. "
                                 f"Add it there – not to the code.")
            text = {"ano": "yes", "nie": "no"}.get(text, text)
            vignettes[code] = text if text in ("yes", "no") else \
                datetime.date.fromisoformat(text).isoformat()
        if vignettes and "vignettes" in p.modes[args.mode]["options"]:
            values.setdefault("vignettes", True)
        date = (datetime.date.fromisoformat(args.date) if args.date
                else datetime.date.today())
        out = p.compile(args.mode, values, vignettes, date, args.engine)
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2

    for note in out["_notes"]:
        print(f"::notice::{note}", file=sys.stderr)
    for item in out["_approximate"]:
        print(f"::warning::Option “{item['name']}” is only APPROXIMATE in engine "
              f"`{args.engine}` (discouraged, not banned).", file=sys.stderr)
    for item in out["_unsupported"]:
        print(f"::error::Option “{item['name']}” CAN'T be said in engine "
              f"`{args.engine}`: {' '.join(item['why'])}", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out["_unsupported"] and args.strict:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
