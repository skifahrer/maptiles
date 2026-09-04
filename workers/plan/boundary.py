#!/usr/bin/env python3
"""
PRESNÁ hranica kraja a štátu – z OSM dát, nie z rozšíreného `.poly` osm.fr.

PREČO TENTO SÚBOR VZNIKOL. Hranicu regiónu sme brali z `.poly`, ktorý osm.fr
zverejňuje vedľa svojich extraktov (`workers/plan/region-poly.py`). Je to
pohodlné – je to tá istá čiara, ktorou je orezaný ich PBF –, ale NIE JE TO
HRANICA KRAJA:

  * body sú zaokrúhlené na mriežku 0,005° (≈ 550 m), takže čiara po hranici
    len kľučkuje;
  * a osm.fr si polygón okolo hranice ešte SÁM ROZŠIRUJE – namerané na ôsmich
    krajoch SR: susedné kraje sa v `.poly` prekrývajú o 2 až 4 km.

Nad tým sme prekryv ešte zväčšovali (`BORDER_BUFFER_M` = 2 500 m na každú
stranu), aby medzi dvoma stiahnutými mapami neostala medzera. Výsledok: mapa
Prešovského kraja siahala kilometre do Košického kraja, do Poľska aj na
Ukrajinu, a to isté robili vrstevnice, skaly aj tieňovanie – počítali sa na
okne, ktoré bolo o ten prekryv nafúknuté.

TENTO SÚBOR TO OTÁČA: hranica sa berie PRIAMO Z OSM RELÁCIE
(`boundary=administrative` + `admin_level`), teda z tých istých dát, z akých
je mapa. Kraj sa reže na `admin_level=4`, štát na `admin_level=2`, a kraj sa
so štátom ešte PRETNE – čo v OSM vytŕča za štátnu hranicu, nemá byť ani
v mape kraja (rozpis pri `uprav`).

Prekryv so susedom sa tým nestráca, len prestáva byť potrebný: dva susedné
kraje zdieľajú v OSM TIE ISTÉ cesty hranice, takže na seba ich mapy nadväzujú
presne – bez medzery a bez prekryvu. Že to naozaj tak je, meria
`workers/plan/seam.py` v každom behu.

ODKIAĽ SA HRANICA ČÍTA: z PBF, ktoré si beh aj tak sťahuje. Nie z Overpassu
ani z Nominatimu – ďalší server je ďalšia vec, ktorá vie byť dole, a hlavne by
to bola DRUHÁ PRAVDA o hranici: mapa by bola rezaná podľa relácie z jedného
dňa a hranica nakreslená podľa relácie z iného. `osmium extract -s smart -S
types=multipolygon,boundary` (ktorým sa kraj reže z rodiča) DOPĹŇA členov
hraničných relácií, takže v rezanom PBF je hranica kraja, hranica štátu aj
hranice susedných krajov CELÉ – aj keď z nich väčšina leží von.

AKO SA Z RELÁCIE STANE POLYGÓN. Nie vlastným zlepovaním ciest do prstencov:
`osmium export` to vie sám (skladá plochy z relácií `type=multipolygon`
a `type=boundary`) a je to jeho práca, nie naša. Filtruje sa pred ním
(`osmium tags-filter r/admin_level=…`), aby sa neskladali tisíce hraníc obcí,
ktoré nikto nechce.

Použitie ako modul (volá ho `region-poly.py`):
    import boundary
    hranice = boundary.hranice_z_pbf("data/region.osm.pbf")
    kraj = boundary.vyber(hranice, "Prešovský kraj", 4)
    stat = boundary.vyber(hranice, "Slovensko", 2)
    rings, stav = boundary.uprav(kraj, stat)

Alebo z príkazového riadka (kontrola a debug):
    python3 workers/plan/boundary.py --pbf=data/region.osm.pbf
    python3 workers/plan/boundary.py --pbf=… --name='Prešovský kraj' --level=4
"""
import json
import os
import subprocess
import sys
import tempfile

# Ktoré úrovne sa z PBF vôbec skladajú. Štát (2) a kraj (4) – nič iné táto
# pipeline nereže a hranice obcí (8) sú tisíce plôch, ktorých zloženie by
# trvalo minúty a nikto by ich nepoužil.
ADMIN_LEVELS = (2, 4)

# O KOĽKO METROV SA HRANICA SMIE ODCHÝLIŤ pri zjednodušení pred rezom.
# Rozpis aj namerané čísla sú pri `uprav` – krátko: `osmium extract --polygon`
# testuje každý uzol proti každej úsečke hranice, takže presná hranica z OSM
# (22 284 bodov na Prešovskom kraji) by rez z rodiča predĺžila rádovo
# osemnásobne. Pri 10 m z nej ostane 7 189 bodov a je stále o dva rády
# presnejšia než mriežka 0,005° (≈ 550 m), na ktorú ju zaokrúhľuje osm.fr.
OREZ_TOLERANCIA_M = 10

# Koľko sekúnd sa čaká na `osmium`. Rez rodiča (373 MB) je desiatky sekúnd,
# skladanie hraníc je z toho zlomok – ale keď sa niečo zasekne, má to spadnúť
# a nie držať job až do stropu 360 minút.
TIMEOUT_S = 1800


def log(msg):
    print(msg, flush=True)


# ---------- geometria: GeoJSON ↔ prstence ----------
# JEDNA odpoveď pre celý priečinok `plan/`: `region-poly.py` aj `seam.py`
# pracujú s prstencami `[(body, je_diera)]` a obe podoby sa musia vedieť
# preložiť na jednom mieste. (`workers/lib/region-mask.py` má vlastnú kópiu –
# je v inom priečinku a má v mene pomlčku, takže sa `import`-núť nedá.)

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

    Je to zjednodušenie: `.poly` neurčuje, ku ktorému obrysu diera patrí, a pri
    kraji je vonkajší prstenec jeden veľký. Keby ich bolo viac (ostrov), diera
    v nesprávnom polygóne by pri `-cutline` nič nepokazila – gdalwarp berie
    úniu, takže by len nebola dierou.
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


# ---------- ogr2ogr ----------

def ogr2ogr(args, popis, dopad):
    """`ogr2ogr` s daným zoznamom argumentov. `True` = prešiel.

    `dopad` je veta o tom, ČO SA NESTANE, keď to nevyjde – volajúci ju vie
    povedať presnejšie než tento súbor a bez nej by bolo varovanie len
    „nepodarilo sa" (pravidlo 4).
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


# ---------- hranice z PBF ----------

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
    """PBF → `[{"name", "names", "admin_level", "rings"}]` administratívnych hraníc.

    Dva kroky, oba `osmium`:

      1. `tags-filter r/admin_level=…` nechá z PBF len hraničné relácie a to,
         na čo sa odkazujú. Bez neho by druhý krok skladal aj hranice obcí –
         tisíce plôch, ktoré tu nikto nechce.
      2. `export --geometry-types=polygon` z relácií POSKLADÁ plochy. Vie to
         aj pre `type=boundary`, nie len pre `type=multipolygon`, a je to jeho
         práca: vlastné zlepovanie ciest do prstencov by bola druhá pravda
         o tom, ako z relácie vzniká polygón.

    Prázdny zoznam znamená „nedá sa" (chýba `osmium`, alebo v PBF hranice nie
    sú) – NIE „hranica neexistuje". Volajúci na to má náhradné riešenie a musí
    ho ohlásiť; ticho by to bol presne ten omyl, po ktorom mapa vyzerá hotová
    a je orezaná inak, než hovorí.
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
        # nie vypadnúť ako zväzok čiar.
        if not _osmium(["export", "--overwrite", "-f", "geojsonseq",
                        "--geometry-types=polygon", "-o", geo, admin],
                       "Skladanie hraníc z relácií (`osmium export`)"):
            return []
        return _citaj_geojsonseq(geo)


def _citaj_geojsonseq(cesta):
    """GeoJSON Text Sequence → zoznam hraníc.

    Oddeľovač záznamov (RS, 0x1E) sa ODSTREĽUJE, nie predpokladá, že tam nie
    je: `osmium export` ho pred každý riadok píše a jeho prepínač sa medzi
    verziami volal rôzne. Riadok s ním by sa nedal prečítať ako JSON a hranica
    by ticho zmizla.
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
                # Meno sa hľadá vo VIACERÝCH kľúčoch: `regions.json` má
                # `osm_name` po slovensky a v OSM je slovenské meno raz v
                # `name`, raz v `name:sk` (pri štátoch aj `int_name`).
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

    Keď je zhôd viac (v rezanom PBF sa vie objaviť aj kus cudzej hranice
    s rovnakým menom), berie sa TÁ NAJVÄČŠIA: relácia, po ktorej sa volá kraj,
    je z nich vždy tá s celou plochou.
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

    DVE VECI V JEDNOM `ogr2ogr`, lebo je to jedna otázka („čím sa reže") a dve
    volania by znamenali dva medzivýsledky na disku a dve miesta, kde sa dá
    stratiť.

    ═══ 1. PRIENIK SO ŠTÁTOM ═══

    Hranica kraja a hranica štátu sú v OSM tá istá čiara všade, kde kraj leží
    na okraji republiky – prienik je teda väčšinou to isté, čo kraj sám.
    „Väčšinou" ale nie je „vždy": relácia sa dá pokaziť (chýbajúca cesta
    v prstenci hranicu roztiahne na susedný štát) a práve to je ten tichý
    omyl, po ktorom by mapa kraja siahala do Poľska a nikto by sa to z behu
    nedozvedel. Prienik je jeden `ogr2ogr` a robí z toho nemožnosť.

    ═══ 2. ZJEDNODUŠENIE, A PREČO SA MU NEDÁ VYHNÚŤ ═══

    `osmium extract --polygon` testuje KAŽDÝ uzol PBF proti KAŽDEJ úsečke
    polygónu (boost::geometry `covered_by` za bboxovým predfiltrom), takže čas
    rezu rastie s počtom bodov hranice priamo úmerne. Namerané na relácii
    Prešovského kraja (388271, plná geometria z api.openstreetmap.org):

        presná hranica z OSM        22 284 bodov
        Douglas–Peucker 10 m         7 189 bodov     ← toto sa reže
        `.poly` z osm.fr (0,005°)     2 753 bodov     (a je 2 – 4 km vedľa)

    Bez zjednodušenia by sa rez z rodiča predĺžil rádovo osemnásobne (dnes
    ~30 s). S 10 m je hranica stále o dva rády presnejšia než mriežka, ktorou
    ju zaokrúhľuje osm.fr, a hlboko pod tým, čo v mape vidno: dlaždica na z14
    má 1,5 km, pixel tieňovania na z14 asi 6 m.

    `ST_SimplifyPreserveTopology`, a nie vlastný Douglas–Peucker: prstenec sa
    zjednodušením dá pretnúť sám so sebou a taký polygón `osmium` ani
    `gdalwarp` neprijmú. Toto je presne tá funkcia, ktorá to nedovolí.

    ČO TO ROBÍ SO ŠVÍKOM. Dvaja susedia zjednodušujú tú istú spoločnú čiaru
    každý vo svojom prstenci, takže sa výsledky môžu líšiť – najviac o dve
    tolerancie, teda o 20 m. To nie je prekryv ani medzera „na papieri":
    meria to `workers/plan/seam.py` v každom behu a hovorí, koľko z toho
    naozaj vyšlo.

    Zlyhanie NIE JE chyba behu: vráti sa pôvodná (presná, nezjednodušená)
    hranica a `stav` povie, čo sa nestalo – rez potom bude len pomalší.
    """
    stav = {"orezane": False, "zjednodusene": False}
    if not rings:
        return rings, stav
    a = geojson_from_rings(rings)
    if not a:
        return rings, stav
    b = geojson_from_rings(orez) if orez else None
    # Tolerancia je v stupňoch, lebo geometria je v stupňoch (EPSG:4326).
    # Prepočet cez zemepisnú šírku stredu – na 49° je stupeň dĺžky o tretinu
    # kratší než stupeň šírky, ale pre TOLERANCIU stačí jedno číslo: rozdiel
    # je pár metrov na desiatich.
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
