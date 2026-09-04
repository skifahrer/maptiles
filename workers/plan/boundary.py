#!/usr/bin/env python3
"""PRESNÁ hranica kraja a štátu – z OSM dát, nie z rozšíreného `.poly` osm.fr.

`.poly` z osm.fr má body zaokrúhlené na mriežku 0,005° (≈ 550 m) a osm.fr si
polygón okolo hranice sám rozširuje – susedné kraje sa v ňom prekrývajú o 2–4 km.

Tu sa hranica berie priamo z OSM relácie (`boundary=administrative` +
`admin_level`), teda z tých istých dát, z akých je mapa. Kraj (4) sa ešte
pretne so štátom (2) – čo v OSM vytŕča za štátnu hranicu, nemá byť v mape kraja.

Číta sa z PBF, ktoré si beh aj tak sťahuje: ďalší server by bol druhá pravda
o hranici. `osmium extract -s smart -S types=multipolygon,boundary` dopĺňa
členov hraničných relácií, takže v rezanom PBF sú hranice celé.

Z relácie robí polygón `osmium export` sám (skladá plochy z `type=multipolygon`
aj `type=boundary`); filtruje sa pred ním, nech sa neskladajú hranice obcí.

Použitie ako modul (volá ho `region-poly.py`):
    hranice = boundary.hranice_z_pbf("data/region.osm.pbf")
    rings, stav = boundary.uprav(boundary.vyber(hranice, "Prešovský kraj", 4),
                                 boundary.vyber(hranice, "Slovensko", 2))

Alebo z príkazového riadka:
    python3 workers/plan/boundary.py --pbf=data/region.osm.pbf
"""
import json
import os
import subprocess
import sys
import tempfile

# štát (2) a kraj (4) – nič iné táto pipeline nereže a hranice obcí sú tisíce
# plôch, ktoré by nikto nepoužil
ADMIN_LEVELS = (2, 4)

# o koľko metrov sa hranica smie odchýliť pri zjednodušení pred rezom.
# `osmium extract --polygon` testuje každý uzol proti každej úsečke, takže
# presná hranica by rez z rodiča predĺžila rádovo osemnásobne. Pri 10 m je
# stále o dva rády presnejšia než mriežka osm.fr.
OREZ_TOLERANCIA_M = 10

# keď sa `osmium` zasekne, má to spadnúť a nie držať job do stropu 360 minút
TIMEOUT_S = 1800


def log(msg):
    print(msg, flush=True)


# ---------- geometria: GeoJSON ↔ prstence ----------
# Jedna odpoveď pre celý priečinok `plan/`. (`workers/lib/region-mask.py` má
# vlastnú kópiu – je v inom priečinku a má v mene pomlčku.)

def rings_from_geojson(data):
    """GeoJSON dict (Polygon/MultiPolygon) → `[(prstenec, je_diera)]`."""
    out = []
    for feat in data.get("features") or []:
        geom = feat.get("geometry") or {}
        polys = ([geom.get("coordinates")] if geom.get("type") == "Polygon"
                 else geom.get("coordinates") or [])
        for poly in polys:
            for i, ring in enumerate(poly or []):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) >= 3:
                    out.append((pts, i > 0))
    return out


def geojson_from_rings(rings):
    """Prstence → GeoJSON. Diery idú k poslednému vonkajšiemu prstencu.

    Je to zjednodušenie: `.poly` neurčuje, ku ktorému obrysu diera patrí.
    Pri `-cutline` by diera v nesprávnom polygóne nič nepokazila – gdalwarp
    berie úniu, takže by len nebola dierou.
    """
    polys, holes = [], []
    for ring, hole in rings:
        closed = ring if ring[0] == ring[-1] else ring + [ring[0]]
        coords = [[round(x, 6), round(y, 6)] for x, y in closed]
        (holes if hole else polys).append(coords)
    if not polys:
        return None
    shapes = [[p] for p in polys]
    for h in holes:
        shapes[-1].append(h)
    geom = ({"type": "Polygon", "coordinates": shapes[0]} if len(shapes) == 1
            else {"type": "MultiPolygon", "coordinates": shapes})
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": geom}]}


def ogr2ogr(args, popis, dopad):
    """`ogr2ogr` s danými argumentmi. `True` = prešiel.

    `dopad` je veta o tom, čo sa nestane, keď to nevyjde – volajúci ju vie
    povedať presnejšie než tento súbor.
    """
    try:
        subprocess.run(["ogr2ogr", *args], check=True,
                       capture_output=True, text=True, timeout=TIMEOUT_S)
        return True
    except FileNotFoundError:
        log(f"::warning::{popis} sa nepodarilo – `ogr2ogr` tu nie je. {dopad} "
            f"Doplň `gdal-bin` (a `libsqlite3-mod-spatialite`) do jobu.")
        return False
    except subprocess.TimeoutExpired:
        log(f"::warning::{popis} sa nedokončilo do {TIMEOUT_S} s. {dopad}")
        return False
    except subprocess.CalledProcessError as exc:
        log(f"::warning::{popis} zlyhalo: {(exc.stderr or '').strip()[-500:]}. "
            f"{dopad}")
        return False


def _osmium(args, popis):
    """`osmium` s danými argumentmi. `True` = prešiel."""
    try:
        subprocess.run(["osmium", *args], check=True,
                       capture_output=True, text=True, timeout=TIMEOUT_S)
        return True
    except FileNotFoundError:
        log(f"::warning::{popis} sa nepodarilo – `osmium` tu nie je.")
        return False
    except subprocess.TimeoutExpired:
        log(f"::warning::{popis} sa nedokončilo do {TIMEOUT_S} s.")
        return False
    except subprocess.CalledProcessError as exc:
        log(f"::warning::{popis} zlyhalo: {(exc.stderr or '').strip()[-500:]}")
        return False


def hranice_z_pbf(pbf, levels=ADMIN_LEVELS):
    """PBF → `[{"name", "names", "admin_level", "rings"}]` hraníc.

    Dva kroky `osmium`: `tags-filter r/admin_level=…` nechá len hraničné
    relácie (bez neho by sa skladali aj hranice obcí) a `export
    --geometry-types=polygon` z nich poskladá plochy.

    Prázdny zoznam znamená „nedá sa", nie „hranica neexistuje" – volajúci má
    náhradné riešenie a musí ho ohlásiť.
    """
    if not pbf or not os.path.exists(pbf):
        log(f"::warning::Hranice sa nedajú prečítať – {pbf} nie je.")
        return []
    vyrazy = [f"r/admin_level={lvl}" for lvl in levels]
    with tempfile.TemporaryDirectory() as tmp:
        admin = os.path.join(tmp, "admin.osm.pbf")
        geo = os.path.join(tmp, "admin.geojsonseq")
        if not _osmium(["tags-filter", "--overwrite", "-o", admin, pbf,
                        *vyrazy], "Výber hraničných relácií z PBF"):
            return []
        # `--geometry-types=polygon`: relácie sa majú poskladať na plochy,
        # nie vypadnúť ako zväzok čiar
        if not _osmium(["export", "--overwrite", "-f", "geojsonseq",
                        "--geometry-types=polygon", "-o", geo, admin],
                       "Skladanie hraníc z relácií (`osmium export`)"):
            return []
        return _citaj_geojsonseq(geo)


def _citaj_geojsonseq(cesta):
    """GeoJSON Text Sequence → zoznam hraníc.

    Oddeľovač záznamov (RS, 0x1E) sa odstreľuje, nie predpokladá: `osmium
    export` ho pred každý riadok píše a riadok s ním by sa nedal prečítať.
    """
    hranice = []
    try:
        with open(cesta, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip().lstrip("\x1e").strip()
                if not line:
                    continue
                try:
                    feat = json.loads(line)
                except ValueError:
                    continue
                props = feat.get("properties") or {}
                geom = feat.get("geometry") or {}
                if geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                rings = rings_from_geojson(
                    {"features": [{"geometry": geom}]})
                if not rings:
                    continue
                try:
                    lvl = int(str(props.get("admin_level") or "").strip())
                except ValueError:
                    continue
                # meno sa hľadá vo viacerých kľúčoch: v OSM je slovenské meno
                # raz v `name`, raz v `name:sk` (pri štátoch aj `int_name`)
                names = {str(props.get(k)) for k in
                         ("name", "name:sk", "int_name", "official_name")
                         if props.get(k)}
                hranice.append({"name": str(props.get("name") or ""),
                                "names": names,
                                "admin_level": lvl,
                                "rings": rings})
    except OSError as exc:
        log(f"::warning::Poskladané hranice sa nedajú prečítať ({exc}).")
        return []
    return hranice


def vyber(hranice, name, admin_level):
    """Hranica daného mena a úrovne → prstence, alebo `None`.

    Pri viacerých zhodách sa berie tá najväčšia: relácia, po ktorej sa volá
    kraj, je z nich vždy tá s celou plochou.
    """
    hladane = (name or "").strip()
    if not hladane:
        return None
    zhody = [h for h in hranice
             if h["admin_level"] == admin_level
             and (hladane == h["name"] or hladane in h["names"])]
    if not zhody:
        return None
    return max(zhody, key=lambda h: _plocha(h["rings"]))["rings"]


def _plocha(rings):
    """Plocha prstencov v stupňoch² – len na porovnanie dvoch zhôd."""
    total = 0.0
    for ring, hole in rings:
        s = 0.0
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            s += x1 * y2 - x2 * y1
        total += (-1 if hole else 1) * abs(s) / 2.0
    return total


def uprav(rings, orez=None, tolerancia_m=OREZ_TOLERANCIA_M, popis="štátom"):
    """Hranica na orez: prienik so `orez` a zjednodušenie. `(rings, stav)`.

    Oboje v jednom `ogr2ogr`, lebo je to jedna otázka („čím sa reže").

    Prienik so štátom: hranica kraja a štátu je v OSM tá istá čiara všade, kde
    kraj leží na okraji republiky – ale relácia sa dá pokaziť a chýbajúca cesta
    v prstenci hranicu roztiahne na susedný štát. Prienik z toho robí nemožnosť.

    Zjednodušenie: `osmium extract --polygon` testuje každý uzol proti každej
    úsečke, takže by sa rez predĺžil rádovo osemnásobne (22 284 bodov proti
    7 189 po Douglas–Peuckerovi na 10 m). Pri 10 m je hranica stále o dva rády
    presnejšia než mriežka osm.fr a hlboko pod tým, čo v mape vidno.

    `ST_SimplifyPreserveTopology`, a nie vlastný Douglas–Peucker: prstenec sa
    zjednodušením dá pretnúť sám so sebou a taký polygón `osmium` neprijme.

    Dvaja susedia zjednodušujú spoločnú čiaru každý vo svojom prstenci, takže
    sa výsledky môžu líšiť najviac o dve tolerancie – meria to `seam.py`.

    Zlyhanie nie je chyba behu: vráti sa pôvodná hranica a `stav` povie, čo sa
    nestalo – rez bude len pomalší.
    """
    stav = {"orezane": False, "zjednodusene": False}
    if not rings:
        return rings, stav
    a = geojson_from_rings(rings)
    if not a:
        return rings, stav
    b = geojson_from_rings(orez) if orez else None
    # tolerancia je v stupňoch, lebo geometria je v stupňoch; pre toleranciu
    # stačí jedno číslo – rozdiel je pár metrov na desiatich
    tol = (tolerancia_m or 0) / 111320.0
    geom_sql = "a.geom"
    zdroje = "a"
    if b:
        geom_sql = "ST_Intersection(a.geom, b.geom)"
        zdroje = "a, b"
    if tol > 0:
        geom_sql = f"ST_SimplifyPreserveTopology({geom_sql}, {tol:.8f})"
    with tempfile.TemporaryDirectory() as tmp:
        fa = os.path.join(tmp, "a.geojson")
        fb = os.path.join(tmp, "b.geojson")
        gpkg = os.path.join(tmp, "obe.gpkg")
        out = os.path.join(tmp, "orez.geojson")
        with open(fa, "w") as f:
            json.dump(a, f)
        popis_op = "Hranica na orez"
        dopad = ("Reže sa presnou hranicou z relácie – je to správne územie, "
                 "len rez z rodiča potrvá dlhšie"
                 + (" a kraj sa nepretne so štátom." if b else "."))
        if not ogr2ogr(["-f", "GPKG", "-nln", "a", "-lco", "GEOMETRY_NAME=geom",
                        gpkg, fa], popis_op + " (zápis hranice)", dopad):
            return rings, stav
        if b:
            with open(fb, "w") as f:
                json.dump(b, f)
            if not ogr2ogr(["-f", "GPKG", "-update", "-nln", "b",
                            "-lco", "GEOMETRY_NAME=geom", gpkg, fb],
                           popis_op + f" (zápis hranice {popis})", dopad):
                return rings, stav
        if not ogr2ogr(["-f", "GeoJSON", "-dialect", "SQLITE", "-sql",
                        f"SELECT {geom_sql} AS geom FROM {zdroje}",
                        out, gpkg], popis_op + " (SQL)", dopad):
            return rings, stav
        try:
            with open(out) as f:
                upravene = rings_from_geojson(json.load(f))
        except (OSError, ValueError) as exc:
            log(f"::warning::{popis_op}: výstup sa nedal prečítať ({exc}). "
                f"{dopad}")
            return rings, stav
    if not upravene:
        log(f"::warning::{popis_op} vyšiel prázdny – reže sa presnou hranicou "
            f"z relácie.")
        return rings, stav
    stav["orezane"] = bool(b)
    stav["zjednodusene"] = tol > 0
    return upravene, stav


def _cli():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbf", required=True, help="OSM PBF, z ktorého sa číta")
    ap.add_argument("--name", default="", help="meno hranice (`osm_name`)")
    ap.add_argument("--level", type=int, default=0, help="admin_level")
    ap.add_argument("--out", default="", help="kam zapísať GeoJSON")
    args = ap.parse_args()

    hranice = hranice_z_pbf(args.pbf)
    if not hranice:
        print("V PBF sa nenašla ani jedna administratívna hranica.",
              file=sys.stderr)
        return 1
    if not args.name:
        for h in sorted(hranice, key=lambda h: (h["admin_level"], h["name"])):
            print(f"  admin_level={h['admin_level']:<3} {h['name']} "
                  f"({sum(len(r) for r, _ in h['rings'])} bodov)")
        return 0
    rings = vyber(hranice, args.name, args.level)
    if not rings:
        print(f"Hranica „{args.name}“ (admin_level={args.level}) v PBF nie je.",
              file=sys.stderr)
        return 1
    print(f"{args.name}: {len(rings)} prstencov, "
          f"{sum(len(r) for r, _ in rings)} bodov")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(geojson_from_rings(rings), f)
        print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
