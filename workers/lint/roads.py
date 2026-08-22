#!/usr/bin/env python3
"""
Obmedzenia na ceste: filter pustí, čo schéma chce – a hodnota ostane reťazcom.

TRI TICHÉ VECI, na ktoré je táto kontrola:

  1. PREDFILTER A SCHÉMA SA ROZÍDU. Job `roads` číta PBF dvakrát: `osmium
     tags-filter` (workers/roads/filter.txt) a potom Planetiler
     (workers/roads/roads.yml). To isté rozhodnutie je teda na dvoch miestach
     a keď sa rozídu, Planetiler dostane PBF, v ktorom ten tag už NIE JE –
     dlaždice vzniknú, beh zazelená a v mape tá hodnota len nie je. To isté,
     čo pri krajinných prvkoch (`workers/lint/features.py`).

  2. HODNOTA SA ZMENÍ NA ČÍSLO. Lákalo by dať `maxheight: double` do
     `tag_mappings`, ale Planetiler ho parsuje cez `NumberFormat.parse`
     (planetiler-core `util/Parse.java`, riadok 143), ktorý vezme číslo ZO
     ZAČIATKU a jednotku zahodí: z `12'6"` (3,8 m) je 12 a z `50 mph`
     (80 km/h) je 50. Nula chýb v logu, len zle nakreslená mapa. Číselné smú
     byť LEN kľúče bez jednotky (`lanes`, `layer`).

  3. BLOKY PRESTANÚ BYŤ VÝLUČNÉ. Schéma má dva bloky (rozmer od z12, rýchlosť
     od z14) a druhý má `__not__` nad tým istým zoznamom. Keby ten `__not__`
     zmizol, cesta s výškou AJ rýchlosťou by vypadla DVA razy a štítok by sa
     kreslil cez seba – čo vyzerá ako pokazený font, nie ako dvojitá čiara.
     A obidva bloky musia dávať TIE ISTÉ atribúty, inak tá istá cesta nesie
     iné polia podľa toho, ktorý blok ju chytil.

Spustiť: `python3 workers/lint/roads.py`
"""
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
SCHEMA = os.path.join(_WORKERS, "roads", "roads.yml")
FILTER = os.path.join(_WORKERS, "roads", "filter.txt")

# Kľúče, ktoré SMÚ byť v `tag_mappings` číselné – celé čísla bez jednotky.
# Čokoľvek iné je bod 2 v hlavičke.
NUMERIC_OK = {"lanes", "layer"}

bad = []


def err(path, msg):
    bad.append((path, msg))


def filter_keys(path):
    """Holé kľúče z `osmium tags-filter --expressions` (bez `w/`, `nwr/`)."""
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "/" in line.split("=", 1)[0]:
                line = line.split("/", 1)[1]
            out.add(line.partition("=")[0].strip())
    return out


def wanted_keys(node, out):
    """Kľúče, na ktoré sa schéma pýta – z `include_when` aj `__not__`.

    Berú sa VŠETKY vetvy vrátane `__not__`: aj negácia sa vyhodnocuje nad
    tagom, ktorý v PBF musí byť. Keby ho filter vyhodil, `__not__` by bol vždy
    pravdivý a druhý blok by chytal aj cesty, ktoré patria prvému.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("__all__", "__any__", "__not__"):
                wanted_keys(value, out)
            elif isinstance(key, str) and not key.startswith("$"):
                out.add(key)
    elif isinstance(node, list):
        for item in node:
            wanted_keys(item, out)
    return out


def main():
    with open(SCHEMA, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    allowed = filter_keys(FILTER)

    # --- 2. hodnoty ostávajú reťazcami ---
    for key, kind in (schema.get("tag_mappings") or {}).items():
        if key not in NUMERIC_OK:
            err("workers/roads/roads.yml",
                f"`tag_mappings` mení `{key}` na `{kind}`. Planetiler parsuje "
                f"číslo cez `NumberFormat.parse`, ktorý vezme číslo zo začiatku "
                f"a JEDNOTKU ZAHODÍ – z `12'6\"` je 12 a z `50 mph` je 50, "
                f"potichu. Hodnota s jednotkou musí ísť do dlaždice ako reťazec "
                f"– štýl ju kreslí tak, ako je na tabuli, a číslo z nej "
                f"potrebuje len smerovanie, ktoré si ju parsuje samo.")

    layers = schema.get("layers") or []
    if len(layers) != 1:
        err("workers/roads/roads.yml",
            f"čakám jednu vrstvu `road_limit`, je ich {len(layers)}.")
        return report()

    blocks = layers[0].get("features") or []
    if len(blocks) != 2:
        err("workers/roads/roads.yml",
            f"čakám dva bloky (rozmer od z12, rýchlosť od z14), je ich "
            f"{len(blocks)}. Zoomy sú tu to hlavné rozhodnutie – rozpis je "
            f"v hlavičke schémy.")
        return report()

    # --- 1. filter pustí, čo schéma chce ---
    #
    # POZOR NA TO, ČO `tags-filter` ROBÍ: vyberá OBJEKTY, nie tagy. Cesta, ktorá
    # prešla na `w/maxheight`, si so sebou nesie VŠETKY svoje tagy, takže
    # `layer`, `tunnel` či `name` v `filter.txt` byť nemusia – tie sa len čítajú
    # z už vybranej cesty. Kontrolovať treba to, čo o výbere ROZHODUJE, teda
    # kľúče z `include_when`: keby jeden z nich vo filtri chýbal, cesta, ktorá
    # má LEN jeho, by sa do PBF nedostala vôbec.
    #
    # (Prvá verzia tejto kontroly to mala naopak a hlásila `layer` – teda
    # atribút, ktorý sa vezie s objektom. Falošné hlásenie je tu drahšie než
    # inde: nutká „opraviť" filter tak, že sa doň pridá kľúč, ktorý VYBERÁ,
    # a tým sa do PBF pustia aj cesty bez obmedzenia.)
    for i, block in enumerate(blocks, 1):
        keys = wanted_keys(block.get("include_when"), set())
        for key in sorted(keys):
            # `highway` berie PRVÝ priechod filtra (`w/highway`) v build.sh,
            # nie `filter.txt` – je to tá istá otázka, len o krok skôr.
            if key == "highway":
                continue
            if key not in allowed:
                err("workers/roads/filter.txt",
                    f"blok {i} schémy sa pýta na `{key}`, ale predfilter ho "
                    f"nepustí – Planetiler dostane PBF, v ktorom ten tag už "
                    f"nie je, a hodnota sa v dlaždiciach TICHO neobjaví. "
                    f"Dopíš `w/{key}`.")

    # --- 3. bloky sú výlučné a dávajú to isté ---
    second = blocks[1].get("include_when") or {}
    has_not = "__not__" in yaml.dump(second)
    if not has_not:
        err("workers/roads/roads.yml",
            "druhý blok nemá `__not__` nad zoznamom rozmerov, takže cesta "
            "s výškou AJ rýchlosťou vypadne DVA razy a štítok sa nakreslí "
            "cez seba. Bloky sa musia vylučovať.")
    if blocks[0].get("attributes") != blocks[1].get("attributes"):
        err("workers/roads/roads.yml",
            "bloky dávajú RÔZNE atribúty. Tá istá cesta by potom niesla iné "
            "polia podľa toho, ktorý blok ju chytil – použi tú istú kotvu "
            "(`*limit_attrs`).")

    zooms = sorted(b.get("min_zoom") for b in blocks)
    if zooms != [12, 14]:
        err("workers/roads/roads.yml",
            f"zoomy blokov sú {zooms}, čakám [12, 14]. Rozmer a hmotnosť majú "
            f"byť vidieť skôr než rýchlosť – rozpis v hlavičke schémy.")

    # --- 4. test na jednotky musí existovať ---
    # Je to ten test, ktorý DOKUMENTUJE rozhodnutie z bodu 2. Keby ho niekto
    # zmazal, `tag_mappings` by sa dalo „opraviť" na `double` a nič by nespadlo.
    examples = schema.get("examples") or []
    if not any("'" in str(e.get("input", {}).get("tags", {}).get("maxheight", ""))
               for e in examples):
        err("workers/roads/roads.yml",
            "medzi `examples` nie je prípad so stopami a palcami (`12'6\"`). "
            "Práve on drží rozhodnutie, že hodnota ide do dlaždice ako reťazec "
            "– bez neho sa `tag_mappings: double` vráti a nikto to nezastaví.")
    if len(examples) < 5:
        err("workers/roads/roads.yml",
            f"schéma má {len(examples)} testov. Púšťa ich "
            f"`java -jar planetiler.jar verify workers/roads/roads.yml` a je to "
            f"jediná vec, ktorá o schéme povie pravdu bez celého behu.")
    return report()


def report():
    for path, msg in bad:
        print(f"::error file={path}::{msg}")
    if bad:
        print(f"\n{len(bad)} problém(ov) v obmedzeniach na ceste.")
        return 1
    print("Obmedzenia na ceste: predfilter pustí, čo schéma chce, hodnoty "
          "ostávajú reťazcami a bloky sa vylučujú.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
