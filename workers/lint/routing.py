#!/usr/bin/env python3
"""
Profil navigácie musí prejsť do motora CELÝ – alebo o sebe povedať, že nie.

PREČO TO JE KONTROLA. Costing motora je slovník a **neznámy kľúč sa v ňom
ticho ignoruje** – Valhalla aj GraphHopper vrátia platnú trasu, keď im napíšeš
`top_speeed` namiesto `top_speed`. Nič nespadne, nič sa nevypíše, len trasa
nesedí s tým, čo si odškrtol. To je pravidlo 8 v čistej podobe a tá istá trieda
chyby ako neznámy `fill-pattern` v MapLibre alebo `source-layer`, ktorý schéma
nevyrába.

ČO SA STRÁŽI:

  1. Voľba, ktorú režim ponúka, musí v číselníku existovať.
  2. KAŽDÁ voľba má pre KAŽDÝ motor buď mapovanie, alebo `unsupported`
     s dôvodom. Mlčanie je zakázané – bez toho by sa nepokrytá voľba zahodila
     a `--strict` by ju nemal z čoho nájsť.
  3. Mapovanie a `unsupported` sa vylučujú. Keby stáli vedľa seba, `profile.py`
     by jedno z nich ignoroval podľa poradia `if`-ov v kóde.
  4. Kľúč costingu Valhally musí byť ZO ZOZNAMU jej skutočných volieb (nižšie).
     Toto chytí preklep, ktorý inak nechytí nikto.
  5. Výraz vlastného modelu GraphHoppera smie stáť len na zakódovaných
     hodnotách, ktoré naozaj existujú (`road_class`, `country`, …).
  6. `vignettes.json`: krajina bez známky nesmie mať `required_on` a naopak;
     každá trieda v `required_on` musí byť preložiteľná v `GH_ROAD_CLASS`
     v `profile.py` – inak by z pravidla o známke NEVYPADLO NIČ a trasa by
     krajinu bez známky pokojne prešla po diaľnici.
  7. Profil sa musí dať zložiť pre každý režim a každý motor bez pádu.

Spustiť: `python3 workers/lint/routing.py`
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


# SKUTOČNÉ VOĽBY VALHALLY. Vyzobrané zo zdrojáku (master, august 2026):
#
#   src/sif/dynamiccost.cc, src/sif/autocost.cc, src/sif/pedestriancost.cc,
#   src/sif/bicyclecost.cc – kľúče sa tam čítajú ako `"/nazov"`, takže sa
#   zoznam obnoví jedným grepom:
#
#     grep -ohE '"/[A-Za-z_/]+"' src/sif/*cost.cc | sort -u
#
# JE TO KÓPIA CUDZIEHO ZOZNAMU, a preto je tu napísané, ODKIAĽ je: keď sa
# Valhalla posunie, tento zoznam sa musí obnoviť tým grepom, nie doplniť
# ručne o to jedno meno, ktoré práve chýba.
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

# Zakódované hodnoty GraphHoppera, na ktorých smie stáť výraz vlastného
# modelu. Zdroj: docs/core/profiles.md a custom-models.md.
GH_ENCODED = {
    "road_class", "road_class_link", "road_environment", "road_access",
    "surface", "smoothness", "track_type", "toll", "hazmat", "country",
    "max_speed", "max_weight", "max_height", "max_width", "max_length",
    "average_slope", "max_slope", "hike_rating", "mtb_rating", "horse_rating",
    "foot_network", "bike_network", "get_off_bike", "lanes", "car_temporal_access",
    "true",
}


# Zástupné znaky v šablóne (`{alpha3}`, `{classes}`) sa dopĺňajú až v
# `profile.py`, takže v samotnej šablóne menami nie sú. Kontroluje sa preto
# šablóna BEZ nich a k tomu hotový výraz, ktorý z nej vypadol (bod 7) – práve
# tam sa totiž preklep v doplnenej časti prejaví.
PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")


def expr_names(expr):
    """Mená, na ktorých výraz stojí – bez operátorov, čísel a zástupných znakov."""
    return set(re.findall(r"[a-z][a-z_0-9]*", PLACEHOLDER.sub(" ", expr)))


class Lint:
    def __init__(self):
        self.bad = 0

    def err(self, path, msg):
        print(f"::error file={path}::{msg}")
        self.bad += 1


def statements(rule):
    """Všetky `if` výrazy z mapovania pre GraphHopper."""
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

    # --- 1. režimy ---
    for mode, spec in p.modes.items():
        for key in spec["options"]:
            if key not in p.options:
                lint.err(rel_prof, f"režim `{mode}` ponúka voľbu `{key}`, ktorú "
                                   f"`options` nemá. Doplň ju tam, alebo ju "
                                   f"z režimu vyhoď – takto ju `profile.py` "
                                   f"odmietne až za behu.")
        for engine in engines:
            if engine not in spec.get("costing", {}):
                lint.err(rel_prof, f"režim `{mode}` nemá costing pre motor "
                                   f"`{engine}`. Napíš meno costingu, alebo "
                                   f"`null` – ale napíš to.")

    # --- 2., 3., 4., 5. voľby ---
    for key, spec in p.options.items():
        for engine in engines:
            rule = spec.get(engine)
            if not rule:
                lint.err(rel_prof,
                         f"voľba `{key}` nemá pre motor `{engine}` ani "
                         f"mapovanie, ani `unsupported`. Mlčanie znamená, že "
                         f"sa voľba TICHO zahodí – napíš aspoň dôvod, prečo to "
                         f"ten motor nevie.")
                continue
            has_map = any(k in rule for k in
                          ("set", "soft", "set_value", "priority", "speed",
                           "priority_template"))
            if "unsupported" in rule and has_map:
                lint.err(rel_prof,
                         f"voľba `{key}` má pre `{engine}` naraz mapovanie aj "
                         f"`unsupported`. To sú dve odpovede na jednu otázku "
                         f"a `profile.py` si vyberie jednu podľa poradia "
                         f"`if`-ov – teda náhodou.")
            if "unsupported" in rule and not rule["unsupported"]:
                lint.err(rel_prof, f"voľba `{key}` je pre `{engine}` "
                                   f"`unsupported` bez dôvodu. Dôvod je to "
                                   f"jediné, čo z tej diery spraví hlásenie.")
            if engine == "valhalla":
                keys = list(rule.get("set", {})) + list(rule.get("soft", {}))
                if "set_value" in rule:
                    keys.append(rule["set_value"])
                for k in keys:
                    if k not in VALHALLA_OPTIONS:
                        lint.err(rel_prof,
                                 f"voľba `{key}` nasadzuje Valhalle "
                                 f"`{k}`, čo nie je jej voľba. Valhalla neznámy "
                                 f"kľúč TICHO ignoruje – trasa vyjde a nikto "
                                 f"nepovie, že sa voľba nepoužila. Preklep? "
                                 f"Zoznam je vo `workers/lint/routing.py`.")
            if engine == "graphhopper":
                for expr in statements(rule):
                    for name in expr_names(expr) - GH_ENCODED:
                        lint.err(rel_prof,
                                 f"voľba `{key}` stavia výraz `{expr}` na "
                                 f"`{name}`, čo nie je zakódovaná hodnota "
                                 f"GraphHoppera. Neznáme meno vo vlastnom "
                                 f"modeli je chyba požiadavky, nie trasa.")

    # --- 6. známky ---
    stavy = set(p.vig.get("_stavy", {}))
    for code, c in p.countries.items():
        if not re.fullmatch(r"[A-Z]{2}", code):
            lint.err(rel_vig, f"kľúč krajiny `{code}` nie je dvojpísmenový kód.")
        if not re.fullmatch(r"[A-Z]{3}", c.get("alpha3", "")):
            lint.err(rel_vig, f"krajina `{code}` nemá trojpísmenový `alpha3`. "
                              f"GraphHopper porovnáva `country == SVK`, takže "
                              f"bez neho z pravidla nevypadne nič.")
        if c.get("stav") not in stavy:
            lint.err(rel_vig, f"krajina `{code}` má `stav: {c.get('stav')}`, "
                              f"ktorý `_stavy` nepozná ({', '.join(sorted(stavy))}).")
        classes = c.get("required_on", [])
        if c.get("ma_znamku") and not classes:
            lint.err(rel_vig, f"krajina `{code}` známku má, ale `required_on` je "
                              f"prázdne – z pravidla by nevypadlo nič a trasa by "
                              f"tam bez známky pokojne šla po diaľnici.")
        if not c.get("ma_znamku") and classes:
            lint.err(rel_vig, f"krajina `{code}` známku nemá, ale `required_on` "
                              f"nie je prázdne. To sú dve odpovede naraz.")
        for k in classes:
            if k not in prof.GH_ROAD_CLASS:
                lint.err(rel_vig,
                         f"krajina `{code}` chce známku na `{k}`, ale "
                         f"`GH_ROAD_CLASS` vo `workers/routing/profile.py` to "
                         f"nevie preložiť – `_gh_vignettes` takú triedu "
                         f"PRESKOČÍ a pravidlo o známke ticho zredne.")

    # --- 7. profil sa musí dať zložiť ---
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
                lint.err(rel_prof, f"profil `{mode}` sa pre `{engine}` nezložil: "
                                   f"{type(e).__name__}: {e}")
                continue
            for stmt in statements(out.get("custom_model", {})):
                for name in expr_names(stmt) - GH_ENCODED:
                    lint.err(rel_prof,
                             f"`{mode}`/`{engine}`: hotový výraz `{stmt}` stojí "
                             f"na `{name}`, čo GraphHopper nepozná. Doplnenie "
                             f"šablóny vyrobilo neplatný model – trasa sa "
                             f"nespočíta a vyzerá to ako chyba servera.")
            for item in out["_nepokryte"]:
                if not item.get("dovod"):
                    lint.err(rel_prof, f"`{mode}`/`{engine}`: nepokrytá voľba "
                                       f"`{item['option']}` bez dôvodu.")

    if lint.bad:
        print(f"\n{lint.bad} problém(ov) v profile navigácie.")
        return 1
    print("Profil navigácie je celý: každá voľba má pre každý motor odpoveď, "
          "kľúče Valhally sú jej vlastné, výrazy GraphHoppera stoja na "
          "zakódovaných hodnotách a známky sa dajú preložiť.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
