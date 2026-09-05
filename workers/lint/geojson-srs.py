#!/usr/bin/env python3
"""GeoJSON výstup nesmie dostať SRS – inak metre ticho zmenia na stupne.

Ovládač GeoJSON prepočítava do WGS84 vždy, keď vrstva vie, v čom je, takže
`-a_srs EPSG:3035` metre neoznačí, ale zmení na stupne – a ogr2ogr skončí
úspechom. Pipeline na to doplatila dvakrát: skaly mali 1e-9 m² a filter ich
všetky vyhodil; únia švov vyšla ako 0,00 km² z 3570 km² a zahodila sa.

  1. žiadny worker nepíše GeoJSON s `-a_srs` ani `-t_srs`;
  2. prepínače sú napísané, nie vlepené z premennej – práve cez `*srs_args`
     sa to sem raz dostalo;
  3. `po_blokoch` `<SRS>` z okna bloku vyhadzuje;
  4. `zlep_svy` si výsledok únie overí, takže návrat do stupňov by bol hlasný.
"""
import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)

# Mená ovládačov, ktoré prepočítavajú do WGS84. `GPKG` ani `GeoPackage` medzi
# nimi nie sú – tam `-a_srs` naozaj len OZNAČÍ a nič neprepočíta.
GEOJSON = ("GeoJSON", "GeoJSONSeq")
SRS_FLAGS = ("-a_srs", "-t_srs")


def python_subory():
    for koren, _, subory in os.walk(_WORKERS):
        for meno in sorted(subory):
            if meno.endswith(".py"):
                yield os.path.join(koren, meno)


def kusy(zoznam):
    """Prvky zoznamu: reťazcové konštanty, alebo `None` pri všetkom ostatnom."""
    von = []
    for prvok in zoznam.elts:
        if isinstance(prvok, ast.Constant) and isinstance(prvok.value, str):
            von.append(prvok.value)
        elif isinstance(prvok, ast.Starred):
            von.append(None)
        else:
            von.append("")   # f-string, premenná – jeden prvok, nie diera
    return von


def main():
    bad = []

    # ---------- 1. a 2. príkazy, ktoré píšu GeoJSON ----------
    najdene = 0
    for cesta in python_subory():
        rel = os.path.relpath(cesta, os.path.dirname(_WORKERS))
        try:
            strom = ast.parse(open(cesta).read(), filename=cesta)
        except SyntaxError as exc:
            bad.append(f"`{rel}` sa nedá prečítať ({exc}).")
            continue
        for uzol in ast.walk(strom):
            if not isinstance(uzol, ast.List):
                continue
            prvky = kusy(uzol)
            texty = [p for p in prvky if p]
            if not any(t.endswith("ogr2ogr") or t == "gdal_contour"
                       for t in texty):
                continue
            # Píše sa GeoJSON? Rozhoduje `-f <ovládač>`, presne ako v príkaze.
            format_ = None
            for i, p in enumerate(prvky[:-1]):
                if p == "-f":
                    format_ = prvky[i + 1]
            if format_ not in GEOJSON:
                continue
            najdene += 1
            riadok = uzol.lineno
            for vlajka in SRS_FLAGS:
                if vlajka in texty:
                    bad.append(
                        f"`{rel}:{riadok}` píše {format_} a podáva `{vlajka}`. "
                        f"Ovládač GeoJSON podľa neho súradnice PREPOČÍTA do "
                        f"WGS84 – z metrov budú stupne, ogr2ogr skončí úspechom "
                        f"a nepovie nič. Nechaj výstup bez SRS (bloky ho preto "
                        f"z okna vyhadzujú) a SRS priraď až tam, kde sa nič "
                        f"neprepočítava – pri prepise do GPKG.")
            # Rozpitvaný zoznam je problém len pri `ogr2ogr` – `gdal_contour`
            # `-a_srs` ani nepozná a `*urovne`/`*atributy` sú v ňom prahy
            # a mená stĺpcov, nie prepínače súradnicovej sústavy.
            if None in prvky and any(t.endswith("ogr2ogr") for t in texty):
                bad.append(
                    f"`{rel}:{riadok}` píše {format_}, ale prepínače si vlepuje "
                    f"z premennej (`*…`), takže sa nedá prečítať, či medzi nimi "
                    f"nie je `-a_srs`. Presne takto sa sem `-a_srs` raz dostal. "
                    f"Napíš prepínače priamo do zoznamu.")
    if not najdene:
        bad.append("Nenašiel sa ani jeden príkaz, ktorý píše GeoJSON. Buď sa "
                   "premenoval ovládač, alebo sa príkazy skladajú inak – "
                   "a kontrola potom nestráži nič.")

    # ---------- 3. a 4. dve miesta, na ktorých to stojí ----------
    bloky = os.path.join(_WORKERS, "lib", "contour-blocks.py")
    src = open(bloky).read()
    if not re.search(r"<SRS\[\^>\]\*>", src):
        bad.append("`workers/lib/contour-blocks.py` už z okna bloku nevyhadzuje "
                   "`<SRS>`. `gdal_contour` by potom písal stupne, plocha každej "
                   "skaly by vyšla rádovo 1e-9 m² a filter by ich vyhodil "
                   "všetky – pri zelenom behu (31245134321, 31426542010).")

    telo = src.split("def zlep_svy", 1)
    if len(telo) < 2:
        bad.append("`workers/lib/contour-blocks.py` už nemá `zlep_svy` – ak sa "
                   "zlepovanie švov presunulo inam, presuň aj túto kontrolu.")
    elif "skontroluj_metricke(" not in telo[1]:
        bad.append("`zlep_svy` si výsledok únie neoveruje "
                   "`skontroluj_metricke()`. Bez toho je návrat do stupňov "
                   "tichý: únia vyjde správne, plocha sa prepočíta ako nula "
                   "a zahodí sa ako „stratená“ – s hláškou, ktorá posiela "
                   "hľadať chybu do GEOSu (beh 32300347626).")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print(f"GeoJSON výstup bez SRS: {najdene} príkazov skontrolovaných, bloky "
          f"`<SRS>` vyhadzujú a únia švov si jednotky overuje ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
