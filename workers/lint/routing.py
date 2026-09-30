#!/usr/bin/env python3
"""A navigation profile must reach the engine whole – or say that it doesn't.

An engine's costing silently ignores unknown keys, so every option has a mapping
or an `unsupported` reason, Valhalla keys are real ones, GraphHopper expressions
stand on encoded values, vignettes translate, and every profile compiles.
"""
import datetime
import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")


def load(name, filename, folder):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_WORKERS, folder, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Valhalla's real options (master, August 2026), refreshed by the grep, not by hand:
#   grep -ohE '"/[A-Za-z_/]+"' src/sif/*cost.cc | sort -u
VALHALLA_OPTIONS = {
    "alley_factor", "alley_penalty", "avoid_bad_surfaces", "bicycle_type",
    "bss_rent_cost", "bss_rent_penalty", "bss_return_cost", "bss_return_penalty",
    "closure_factor", "country_crossing_cost", "country_crossing_penalty",
    "cycling_speed", "destination_only_penalty", "disable_hierarchy_pruning",
    "driveway_factor", "elevator_penalty", "exclude_bridges",
    "exclude_cash_only_tolls", "exclude_ferries", "exclude_highways",
    "exclude_tolls", "exclude_tunnels", "exclude_unpaved",
    "expand_within_distance", "ferry_cost", "fixed_speed", "gate_cost",
    "gate_penalty", "height", "hierarchy_limits", "ignore_access",
    "ignore_closures", "ignore_construction", "ignore_non_vehicular_restrictions",
    "ignore_oneways", "ignore_restrictions", "include_hot", "length",
    "maneuver_penalty", "max_distance", "max_grade", "max_hiking_difficulty",
    "max_up_transitions", "mode_factor", "multimodal_start_end_max_distance",
    "name", "private_access_penalty", "rail_ferry_cost", "restriction_probability",
    "service_factor", "service_penalty", "shortest", "sidewalk_factor",
    "speed_penalty_factor", "speed_types", "step_penalty", "toll_booth_cost",
    "toll_booth_penalty", "top_speed", "transit_start_end_max_distance",
    "transit_transfer_max_distance", "type", "use_distance", "use_ferry",
    "use_highways", "use_hills", "use_lit", "use_living_streets",
    "use_rail_ferry", "use_roads", "use_tracks", "walking_speed",
    "walkway_factor", "weight", "width",
}

# GraphHopper's encoded values; source: docs/core/profiles.md, custom-models.md
GH_ENCODED = {
    "road_class", "road_class_link", "road_environment", "road_access",
    "surface", "smoothness", "track_type", "toll", "hazmat", "country",
    "max_speed", "max_weight", "max_height", "max_width", "max_length",
    "average_slope", "max_slope", "hike_rating", "mtb_rating", "horse_rating",
    "foot_network", "bike_network", "get_off_bike", "lanes", "car_temporal_access",
    "true",
}


# placeholders are filled in profile.py; the template and the result are both checked
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")


def expr_names(expr):
    """Names an expression stands on – without operators, numbers and placeholders."""
    return set(re.findall(r"[a-z][a-z_0-9]*", PLACEHOLDER.sub(" ", expr)))


class Lint:
    def __init__(self):
        self.bad = 0

    def err(self, path, msg):
        print(f"::error file={path}::{msg}")
        self.bad += 1


def statements(rule):
    """Every `if` expression of a GraphHopper mapping."""
    out = []
    for slot in ("priority", "speed", "priority_template"):
        for stmt in rule.get(slot, []) or []:
            if isinstance(stmt, dict) and isinstance(stmt.get("if"), str):
                out.append(stmt["if"])
    return out


def main():
    lint = Lint()
    prof = load("routing_profile", "profile.py", "routing")
    p = prof.Profile()
    rel_prof = "workers/data/routing-profiles.json"
    rel_vig = "workers/data/vignettes.json"

    engines = sorted(p.engines)

    # 1. modes
    for mode, spec in p.modes.items():
        for key in spec["options"]:
            if key not in p.options:
                lint.err(rel_prof, f"mode `{mode}` offers option `{key}`, which "
                                   f"`options` lacks. Add it there, or drop it "
                                   f"from the mode – otherwise `profile.py` "
                                   f"refuses it only at run time.")
        for engine in engines:
            if engine not in spec.get("costing", {}):
                lint.err(rel_prof, f"mode `{mode}` has no costing for engine "
                                   f"`{engine}`. Write the costing name, or "
                                   f"`null` – but write it.")

    # 2.–5. options
    for key, spec in p.options.items():
        for engine in engines:
            rule = spec.get(engine)
            if not rule:
                lint.err(rel_prof,
                         f"option `{key}` has neither a mapping nor `unsupported` "
                         f"for engine `{engine}`. Silence means the option is "
                         f"dropped QUIETLY – at least give the reason the engine "
                         f"can't.")
                continue
            has_map = any(k in rule for k in
                          ("set", "soft", "set_value", "priority", "speed",
                           "priority_template"))
            if "unsupported" in rule and has_map:
                lint.err(rel_prof,
                         f"option `{key}` has both a mapping and `unsupported` "
                         f"for `{engine}`. Two answers to one question, and "
                         f"`profile.py` picks by `if` order – by chance.")
            if "unsupported" in rule and not rule["unsupported"]:
                lint.err(rel_prof, f"option `{key}` is `unsupported` for "
                                   f"`{engine}` without a reason. The reason is "
                                   f"what turns that hole into a report.")
            if engine == "valhalla":
                keys = list(rule.get("set", {})) + list(rule.get("soft", {}))
                if "set_value" in rule:
                    keys.append(rule["set_value"])
                for k in keys:
                    if k not in VALHALLA_OPTIONS:
                        lint.err(rel_prof,
                                 f"option `{key}` sets Valhalla's `{k}`, which "
                                 f"isn't one of its options. Valhalla ignores an "
                                 f"unknown key QUIETLY – the route comes out and "
                                 f"nobody says the option went unused. A typo? "
                                 f"The list is in `workers/lint/routing.py`.")
            if engine == "graphhopper":
                for expr in statements(rule):
                    for name in expr_names(expr) - GH_ENCODED:
                        lint.err(rel_prof,
                                 f"option `{key}` builds expression `{expr}` on "
                                 f"`{name}`, which isn't a GraphHopper encoded "
                                 f"value. An unknown name in a custom model is a "
                                 f"request error, not a route.")

    # 6. vignettes
    states = set(p.vig.get("_states", {}))
    for code, c in p.countries.items():
        if not re.fullmatch(r"[A-Z]{2}", code):
            lint.err(rel_vig, f"country key `{code}` isn't a two-letter code.")
        if not re.fullmatch(r"[A-Z]{3}", c.get("alpha3", "")):
            lint.err(rel_vig, f"country `{code}` has no three-letter `alpha3`. "
                              f"GraphHopper compares `country == SVK`, so "
                              f"without it the rule yields nothing.")
        if c.get("state") not in states:
            lint.err(rel_vig, f"country `{code}` has `state: {c.get('state')}`, "
                              f"which `_states` doesn't know ({', '.join(sorted(states))}).")
        classes = c.get("required_on", [])
        if c.get("sells_vignette") and not classes:
            lint.err(rel_vig, f"country `{code}` sells a vignette, but `required_on` "
                              f"is empty – the rule yields nothing and a route "
                              f"without one would happily take the motorway.")
        if not c.get("sells_vignette") and classes:
            lint.err(rel_vig, f"country `{code}` sells no vignette, but `required_on` "
                              f"isn't empty. Two answers at once.")
        for k in classes:
            if k not in prof.GH_ROAD_CLASS:
                lint.err(rel_vig,
                         f"country `{code}` wants a vignette on `{k}`, but "
                         f"`GH_ROAD_CLASS` in `workers/routing/profile.py` can't "
                         f"translate it – `_gh_vignettes` SKIPS such a class and "
                         f"the vignette rule quietly thins.")

    # 7. every profile compiles
    date = datetime.date(2026, 1, 1)
    for mode, spec in p.modes.items():
        values = {}
        for key in spec["options"]:
            o = p.options[key]
            if o["type"] == "switch":
                values[key] = True
            elif o["type"] == "vignettes":
                values[key] = True
            elif o.get("default") is not None:
                values[key] = o["default"]
            elif o["type"] in ("speed", "factor", "int", "size"):
                values[key] = o.get("range", [1])[0]
        for engine in engines:
            if not spec.get("costing", {}).get(engine):
                continue
            try:
                out = p.compile(mode, dict(values), {}, date, engine)
            except Exception as e:                       # noqa: BLE001
                lint.err(rel_prof, f"profile `{mode}` didn't compile for `{engine}`: "
                                   f"{type(e).__name__}: {e}")
                continue
            for stmt in statements(out.get("custom_model", {})):
                for name in expr_names(stmt) - GH_ENCODED:
                    lint.err(rel_prof,
                             f"`{mode}`/`{engine}`: the finished expression `{stmt}` "
                             f"stands on `{name}`, which GraphHopper doesn't know. "
                             f"Filling the template made an invalid model – no "
                             f"route computes and it looks like a server error.")
            for item in out["_unsupported"]:
                if not item.get("why"):
                    lint.err(rel_prof, f"`{mode}`/`{engine}`: unsupported option "
                                       f"`{item['option']}` without a reason.")

    if lint.bad:
        print(f"\n{lint.bad} problem(s) in the navigation profile.")
        return 1
    print("The navigation profile is whole: every option has an answer for every "
          "engine, Valhalla keys are its own, GraphHopper expressions stand on "
          "encoded values and vignettes translate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
