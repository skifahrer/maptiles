#!/usr/bin/env python3
"""
Jedna odpoveď na otázku „z ktorého skladu a ktoré súbory“ – pre celý build.

PREČO EXISTUJE. Tú istú otázku si kladú DVE miesta a musia si odpovedať
rovnako:

  check-dem (build-map-region.yml)   čo hľadať v sklade a či to treba doplniť
  workers/dem/fetch.sh        čo naozaj stiahnuť

Kým bola odpoveď napísaná dvakrát, rozišli sa – a presne to zhodilo beh
31307163093. `dmr5` má dve podoby a rozhoduje medzi nimi rozsah; `check-dem`
si tú vetvu vyhodnotil pre všetky tri vrstvy podľa `area`, ale job
s tieňovaním volá `fetch-dem.sh` BEZ kľúča výrezu, takže sťahuje dlaždice.
Kontrola teda povedala „chýba `ugkk-vysoke_tatry.tif` v dem-ugkk“, doplnenie
sa spustilo na dem-ugkk – a tieňovanie potom spadlo na tom, že v dem-dmr5
nie je ani jedna dlaždica. Dve pravdy o jednej veci; odteraz je pravda tu.

SKLAD JE PRIEČINOK NA DRIVE, nie GitHub release – celý rozpis je vo
`workers/drive/store.py`. Mená súborov sú tie isté, aké mali assety releasov,
lebo meno je sľub o rozsahu.

DVE PODOBY DMR 5.0. Je to jeden a ten istý 1 m LiDAR od ÚGKK, len ho nemá
zmysel držať dvakrát: pri 1 m má jedna 1°×1° dlaždica ~48 GB a runner má
voľných ~60 GB, takže sa nemá kde ani rozbaliť, nieto zlepiť do mozaiky.
(Kým sa ukladalo do releasov, hranicu určoval ich 2 GB strop na asset; na
Drive taký strop nie je, ale runner ostal ten istý.)

    kľúč výrezu (`area`)   ugkk-<vyrez>.tif v dem-ugkk    plné 1 m
    bez výrezu (`cely`)    N49E019.tif … v dem-dmr5-v2    prevzorkované na 5 m

ROZHODUJE KĽÚČ VÝREZU, NIČ INÉ. Vrstva sa nepýta – pýta sa len ten, kto
volá: vrstevnice a skaly podávajú `AREA_KEY`, tieňovanie nie (robí sa na
celý región, kde 1 m neexistuje). Tým pádom stačí, aby volajúci podal to
isté, čo podá `fetch-dem.sh`, a rozísť sa to nemá ako.

`sonny` a `dmr35` sú vždy dlaždice – výrezovú podobu nemajú a `--area-key`
sa pri nich ignoruje.

Použitie:
    python3 workers/dem/target.py --source=dmr5 --bbox=19.9,49.0,20.4,49.3
    python3 workers/dem/target.py --source=dmr5 --area-key=vysoke_tatry

Výstup je `key=value` na stdout (rovnaký tvar ako GITHUB_OUTPUT):

    form=tiles | area
    store=dem-dmr5-v2
    assets=N49E019.tif N49E020.tif      (prázdne = bbox nie je známy)
    mirror=dmr5:tiles:19,49,21,50       otlačok toho, čo treba doplniť
    degrees=19,49,21,50                 okno pre doplnenie, na celé stupne
    label=…                             na výpis do logu
"""
import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Priečinok = job, súbor = krok; spoločné veci ležia o úroveň vyššie.
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # číselníky (areas, regions, zdroje)

# Meno skladu sa dá prebiť z prostredia – workflow si ich drží ako env, aby
# sa dal celý build presmerovať na testovací sklad bez zmeny v JSONe.
ENV_TILES = {"sonny": "DEM_STORE", "sonny1": "SONNY1_STORE",
             "dmr35": "DMR35_STORE", "dmr5": "DMR5_STORE"}
ENV_AREA = {"dmr5": "UGKK_STORE"}

# Zdroje, ktoré majú aj výrezovú podobu (jeden COG na pohorie v plnom
# rozlíšení). Ostatné sú vždy dlaždice.
HAS_AREA_FORM = ("dmr5",)


def tiles_for(bbox):
    """Bbox → mená 1°×1° dlaždíc podľa juhozápadného rohu (konvencia SRTM).

    Ten istý výpočet bol donedávna napísaný trikrát (check-dem, fetch-dem.sh
    a tu) – a stačí, aby sa jeden z nich pomýlil o jednu dlaždicu, a build
    kontroluje niečo iné, než sťahuje.
    """
    w, s, e, n = bbox
    out = []
    for lat in range(math.floor(s), math.floor(n) + 1):
        for lon in range(math.floor(w), math.floor(e) + 1):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            out.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return out


def degrees_box(bbox):
    """Bbox rozšírený na celé stupne – teda presne na tie dlaždice, ktoré
    pretína.

    Doplnenie musí čítať CELÝ stupeň, nie len prienik s bboxom. Dlaždica sa
    volá podľa stupňa a build si ju podľa toho hľadá, takže `N49E020.tif`,
    ktorá pokrýva dva kilometre štvorcové, by v ďalšom behu prešla kontrolou
    („je tam“) a tieňovanie by ticho skončilo v polovici mapy.
    """
    w, s, e, n = bbox
    return (math.floor(w), math.floor(s), math.ceil(e), math.ceil(n))


def target(source, area_key, bbox, sources_path=None):
    src = (source or "sonny").strip()
    key = (area_key or "cely").strip()
    path = sources_path or os.path.join(_DATA, "dem-sources.json")
    meta = json.load(open(path)).get(src) or {}
    label = meta.get("label", src)

    if src in HAS_AREA_FORM and key and key != "cely":
        rel = os.environ.get(ENV_AREA.get(src, ""), "") or \
            meta.get("store_area", "dem-ugkk")
        asset = f"ugkk-{key}.tif"
        return {
            "form": "area",
            "store": rel,
            "assets": asset,
            "mirror": f"{src}:area:{key}",
            "degrees": "",
            "label": f"{label} – výrez {key}, plné rozlíšenie",
        }

    rel = os.environ.get(ENV_TILES.get(src, ""), "") or \
        meta.get("store", "dem-sonny")
    if not bbox:
        # Vlastný región bez bboxu: zoznam dlaždíc sa nedá zistiť. Volajúci
        # si s prázdnym zoznamom poradí sám (kontrola sa vtedy pýta len na to,
        # či je v sklade vôbec niečo).
        return {"form": "tiles", "store": rel, "assets": "",
                "mirror": f"{src}:tiles", "degrees": "",
                "label": f"{label} – dlaždice"}
    deg = degrees_box(bbox)
    return {
        "form": "tiles",
        "store": rel,
        "assets": " ".join(f"{t}.tif" for t in tiles_for(bbox)),
        "mirror": f"{src}:tiles:" + ",".join(str(v) for v in deg),
        "degrees": ",".join(str(v) for v in deg),
        "label": f"{label} – dlaždice",
    }


def parse_bbox(text):
    text = (text or "").strip()
    if not text:
        return None
    vals = [float(v) for v in text.split(",")]
    if len(vals) != 4:
        raise SystemExit(f"::error::bbox musí mať 4 čísla W,S,E,N: „{text}“")
    return tuple(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--area-key", default="cely",
                    help="`cely` alebo prázdne = bez výrezu (dlaždicová podoba)")
    ap.add_argument("--bbox", default="", help="W,S,E,N vo WGS84")
    ap.add_argument("--sources", default=None)
    ap.add_argument("--out", default="", help="kam zapísať (napr. GITHUB_OUTPUT)")
    args = ap.parse_args()

    res = target(args.source, args.area_key, parse_bbox(args.bbox), args.sources)
    lines = "".join(f"{k}={v}\n" for k, v in res.items())
    sys.stdout.write(lines)
    if args.out:
        with open(args.out, "a") as f:
            f.write(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
