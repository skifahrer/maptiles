#!/usr/bin/env python3
"""
Polygón kraja (nie jeho obdĺžnik) do `data/region.geojson`.

PREČO. Vrstvy z výškového modelu – vrstevnice, skaly, tieňovanie – sa doteraz
počítali na BBOXE regiónu. Bbox Prešovského kraja je 19.865,48.745,22.585,49.48,
čo je obdĺžnik ~199×82 km = 16 300 km², kým samotný kraj má 8 973 km². Takmer
polovica práce teda padla mimo kraj – do susedných krajov, do Poľska, na Ukrajinu
a do Maďarska. A nie je to len práca navyše:

  * DMR 5.0 je LEN Slovensko, takže za hranicou je v modeli NODATA. Hranica
    dát a nodaty je pre `gdaldem slope` zvislá stena – sklon 90°. V behu
    31635772047 z toho vyšlo 13 403 km² „skalnej plochy" (bbox má 16 300 km²,
    čiže skalou bolo označené skoro celé územie), zlepovanie švov to nedalo
    dokopy a spadlo na náhradné riešenie s 375 nezlepenými plochami.
  * Tieňovanie tie prázdne miesta vykreslí ako biele, takže mapa má rovnú
    hranu tam, kde končia dáta.

Polygón sa neberie z OSM ani sa nekreslí ručne – **stiahne sa ten istý `.poly`,
ktorým je orezaný náš PBF** (openstreetmap.fr ich zverejňuje vedľa extraktov).
Vďaka tomu je mapa a jej výškové vrstvy orezané ROVNAKO; druhá definícia hranice
kraja by sa raz rozišla s tou prvou (pravidlo 1).

Formát `.poly` je textový: meno, potom bloky prstencov (`!` na začiatku mena
znamená dieru), každý blok končí `END` a celý súbor tiež.

`.poly` PRE PLANETILER SA PÍŠE ZNOVA (`--poly-out`), nie ukladá bajt po bajte
tak, ako prišiel zo servera: prstence sa medzitým môžu NAFÚKNUŤ (`buffer_rings`
nižšie), takže druhý zápis „to, čo prišlo" by bol druhá pravda o tej istej
hranici (pravidlo 1) – `.poly` aj `.geojson` preto vychádzajú z TÝCH ISTÝCH
(prípadne nafúknutých) prstencov, cez `rings_to_poly_text`. Bez tejto vrstvy to
číta Planetiler (`--polygon=…`, „emit any tile that intersects the shape"),
takže sa dlaždice mapy prestanú vyrábať na celom obdĺžniku bboxu. Keď sa
polygón stiahnuť nepodarí, `.poly` NEVZNIKNE (a `--polygon` sa Planetileru
nedá) – náhradný obdĺžnik z bboxu je presne to, čo Planetiler robí aj bez
neho, takže by len predstieral orez.

PREKRYV SO SUSEDNÝM KRAJOM (`buffer_rings`, rozpis pri nej): `.poly` z osm.fr
je zjednodušená čiara (body na mriežke 0,005° ≈ 550 m) a KAŽDÝ kraj má svoju
vlastnú – susedné kraje preto nemusia zdieľať tú istú hranicu. Polygón sa
pred zápisom nafúkne o kus VON, aby sa dve susedné mapy v tom páse
PREKRÝVALI namiesto toho, aby medzi nimi ostala diera; nie je to presnejšia
hranica (tú osm.fr nedáva), je to rezerva.

KOĽKO TEJ REZERVY TREBA, SA TERAZ MERIA, NIE HÁDA (`seam.py`, volá sa nižšie).
Pôvodný popis tu tvrdil „namerané: medzera 3 – 5 km medzi dvoma stiahnutými
susedmi". Prepočítané na `.poly` všetkých ôsmich krajov to tak NIE JE: osm.fr
si polygóny okolo hranice sám rozširuje, takže sa susedné kraje prekrývajú už
BEZ nafúknutia (2 – 4 km) a medzera na spoločnej hranici vychádza 0 m. Číslo
v tvrdení sa opraviť dalo len tak, že sa začne merať v každom behu – kým sa
nemeralo, nikto by sa o skutočnej medzere nedozvedel ani vtedy, keby raz
naozaj vznikla.

Použitie:
    python3 workers/plan/region-poly.py --region=presovsky --out=data/region.geojson
    python3 workers/plan/region-poly.py --region=presovsky --out=… --poly-out=data/region.poly
    python3 workers/plan/region-poly.py --region=presovsky --out=… --summary=$GITHUB_STEP_SUMMARY
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

# O KOĽKO METROV SA POLYGÓN NAFÚKNE VON (diery vnútri o to isté dnu) – prekryv
# so susedným krajom namiesto medzery, rozpis v hlavičke súboru a pri
# `buffer_rings`. DEFINOVANÁ V `area.py` (bez pomlčky v mene, dá sa normálne
# `import`-núť odtiaľto) – TO ISTÉ ČÍSLO nafukuje aj okno, z ktorého sa čítajú
# vrstvy z výškového modelu (`area.py::pad_bbox`), inak by nafúknutý polygón
# vytŕčal z okna, ktoré ho má orezať cez `-cutline`, a von z okna by nebolo
# čo vidieť.
sys.path.insert(0, _HERE)
from area import BORDER_BUFFER_M  # noqa: E402
import seam  # noqa: E402  (šev so susedmi – meranie, rozpis v tom súbore)

# Polygóny ležia vedľa extraktov, ale v inom priečinku a BEZ `-latest` v mene:
# `extracts/europe/slovakia/presovsky-latest.osm.pbf` → `polygons/europe/slovakia/presovsky.poly`.
POLY_BASE = os.environ.get("OSMFR_POLYGONS",
                           "https://download.openstreetmap.fr/polygons")


def regions(path=None):
    with open(path or os.path.join(_DATA, "regions.json")) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def poly_url(reg):
    """URL `.poly` k prvému slugu regiónu, alebo `None` (Slovensko ako celok)."""
    osmfr = reg.get("osmfr") or {}
    slugs = osmfr.get("slugs") or []
    if not slugs:
        return None
    slug = slugs[0].removesuffix("-latest")
    return f"{POLY_BASE}/{osmfr.get('dir', '')}/{slug}.poly"


def parse_poly(text):
    """`.poly` → `[(prstenec, je_diera)]`, prstenec je zoznam `(lon, lat)`."""
    rings, ring, hole = [], None, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "polygon":
            continue
        if line == "END":
            if ring is not None:
                if len(ring) >= 3:
                    rings.append((ring, hole))
                ring = None
            continue
        parts = line.split()
        if len(parts) == 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            if ring is None:
                ring, hole = [], False
            ring.append((lon, lat))
        else:
            # Meno prstenca – `!` znamená dieru.
            ring, hole = [], line.startswith("!")
    return rings


def ring_bbox(rings):
    xs = [x for ring, _ in rings for x, _ in ring]
    ys = [y for ring, _ in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def ring_area_km2(ring):
    """Plocha prstenca v km² – rovinná aproximácia, stačí na pomer a výpis."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(y for _, y in ring) / len(ring)
    kx = 111.32 * math.cos(math.radians(lat0))
    ky = 110.57
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(s) / 2.0


def geojson(rings):
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


def bbox_rect(bbox):
    """Náhrada, keď polygón nie je: obdĺžnik z bboxu (teda dnešné správanie)."""
    w, s, e, n = bbox
    ring = [(w, s), (e, s), (e, n), (w, n), (w, s)]
    return [(list(ring), False)]


def rings_to_poly_text(rings, name="region"):
    """`[(prstenec, je_diera)]` → text `.poly` (ten istý formát, aký sťahuje
    `poly_url`; parsuje ho späť `parse_poly` vyššie).

    Píše sa znova z prstencov a nie ukladá bajt po bajte to, čo prišlo zo
    servera – tie už môžu byť NAFÚKNUTÉ (`buffer_rings`), takže druhý zápis
    „ako prišlo" by bol druhá pravda o tej istej hranici (pravidlo 1).
    """
    lines = [name or "region"]
    for i, (ring, hole) in enumerate(rings, start=1):
        closed = ring if ring[0] == ring[-1] else list(ring) + [ring[0]]
        lines.append(f"!{i}" if hole else str(i))
        lines += [f"\t{lon:.6f}\t{lat:.6f}" for lon, lat in closed]
        lines.append("END")
    lines.append("END")
    return "\n".join(lines) + "\n"


def _rings_from_geojson_dict(data):
    """GeoJSON dict (Polygon/MultiPolygon) → `[(prstenec, je_diera)]`.

    To isté, čo `workers/lib/region-mask.py::rings_from_geojson` (a
    `deploy/region-mask.py`) číta z hotového súboru – vlastná kópia, lebo
    ten modul má v mene pomlčku (žiadny `import` naň) a je v inom priečinku;
    tri kópie pár riadkov sú lacnejšie než `importlib` cez dva priečinky pre
    jednu pomocnú funkciu.
    """
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


def _ogr2ogr(args, popis):
    """`ogr2ogr` s daným zoznamom argumentov. `True` = prešiel."""
    try:
        subprocess.run(["ogr2ogr", *args], check=True,
                       capture_output=True, text=True)
        return True
    except FileNotFoundError:
        print(f"::warning::Prekryv na hranici (viď hlavičku súboru) sa "
              f"nepodarilo dopočítať – `ogr2ogr` tu nie je. Polygón ostáva "
              f"PRESNE na hranici kraja, takže sa medzi susednými mapami môže "
              f"znova objaviť medzera. Doplň `gdal-bin` do jobu.")
        return False
    except subprocess.CalledProcessError as exc:
        print(f"::warning::Prekryv na hranici sa nepodarilo dopočítať "
              f"({popis} zlyhalo): {exc.stderr.strip()[-500:]}. Polygón "
              f"ostáva PRESNE na hranici kraja. Skontroluj, že job má aj "
              f"`libsqlite3-mod-spatialite` (ST_Buffer je zo SpatiaLite).")
        return False


def buffer_rings(rings, meters=BORDER_BUFFER_M):
    """Nafúkne obrysy o `meters` VON (diery vnútri o to isté DNU).

    PREČO. `.poly` z osm.fr je zjednodušená čiara a každý kraj má svoju
    vlastnú – susedné kraje preto nemusia zdieľať tú istú hranicu. Presnejšiu
    hranicu odtiaľ nedostaneme, ale PREKRYV áno: keď sa polygón oboch krajov
    nafúkne von, pás popri hranici je v oboch mapách, takže na seba nadväzujú
    aj vtedy, keď sa ich hranice o kus líšia (rovnaká úvaha ako pri bboxoch
    pohorí v `workers/data/areas.json`).

    KOĽKO TREBA: dnes `BORDER_BUFFER_M` = 2 500 m na každej strane, teda
    5 km spolu. Že to na skutočné hranice stačí, sa v každom behu ZMERIA
    (`seam.py` – nameraná medzera na spoločnej hranici je dnes 0 m, lebo
    osm.fr polygóny okolo hranice sám rozširuje). Keď to raz stačiť
    prestane, povie to beh; predtým to nebolo z čoho zistiť.

    AKO. Rovinný `ST_Buffer` (GEOS cez SpatiaLite) v metrickej sústave
    (EPSG:3035, tá istá, v akej tento repozitár už robí rovinné operácie –
    `workers/lib/contour-blocks.py`), nie posun bodov o stupeň: buffer
    v stupňoch by bol na rovníku aj pri póle iný, a nafúknutý polygón s dierou
    (enkláva) by bez GEOS-u vyžadoval ručne riešiť samopretínanie na
    konkávnych rohoch – presne to, na čo `ST_Buffer` existuje.

    GPKG, NIE GeoJSON, PRE MEDZIVÝSLEDOK V METROCH: ovládač GeoJSONu
    prepočíta súradnice SPÄŤ do WGS84, hneď ako uvidí, že vrstva má nastavené
    SRS iné než 4326 (tá istá pasca, rozpísaná pri
    `contour-blocks.py::zlep_svy`) – GPKG si SRS len uloží, nemení podľa
    neho súradnice.

    Zlyhanie NIE JE CHYBA BEHU: `.poly` z osm.fr bez prekryvu je presne to,
    čo bolo doteraz, tak sa vráti pôvodný `rings` (a `_ogr2ogr` povie prečo).
    Vracia `(rings, ok)` – `ok` hovorí, či sa prekryv naozaj podaril, nech to
    volajúci vie napísať do výpisu (rule 4: čo sa nafúklo, nie čo sa
    o to len skúsilo).
    """
    if not rings or meters <= 0:
        return rings, False
    data = geojson(rings)
    if not data:
        return rings, False
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "hranica.geojson")
        metric = os.path.join(tmp, "hranica_m.gpkg")
        out = os.path.join(tmp, "hranica_buf.geojson")
        with open(src, "w") as f:
            json.dump(data, f)
        if not _ogr2ogr(
                ["-f", "GPKG", "-nln", "hranica", "-lco", "GEOMETRY_NAME=geom",
                 metric, src, "-t_srs", "EPSG:3035"],
                "prevod do metrov (EPSG:3035)"):
            return rings, False
        if not _ogr2ogr(
                ["-f", "GeoJSON", "-t_srs", "EPSG:4326",
                 "-dialect", "SQLITE", "-sql",
                 f"SELECT ST_Buffer(geom, {meters:g}) AS geom FROM hranica",
                 out, metric],
                "ST_Buffer"):
            return rings, False
        try:
            with open(out) as f:
                buffered = _rings_from_geojson_dict(json.load(f))
        except (OSError, ValueError) as exc:
            print(f"::warning::Prekryv na hranici: výstup ST_Buffer sa nedal "
                  f"prečítať ({exc}). Polygón ostáva presne na hranici kraja.")
            return rings, False
    if not buffered:
        print("::warning::Prekryv na hranici vyšiel prázdny – polygón ostáva "
              "presne na hranici kraja.")
        return rings, False
    return buffered, True


def stiahni_rings(reg, timeout=20):
    """`.poly` regiónu zo servera → prstence, alebo `None`.

    Kratší `timeout` než pri vlastnom polygóne je zámer: toto je meranie
    navyše, a keď osm.fr práve nedvíha, nemá to k trom hodinám buildu
    pridať osem čakaní po minúte.

    Bez `::warning::` a bez náhrady za bboxom: je to pomocník pre SUSEDOV
    (`susedne_rings`), kde chýbajúci polygón nie je chyba behu – len sa
    o toho suseda šev nedá zmerať. Región, ktorý sa práve stavia, si to
    v `main` rieši sám a nahlas.
    """
    url = poly_url(reg)
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse_poly(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def susedne_rings(regs, key):
    """Polygóny SÚRODENCOV a RODIČA daného regiónu (na meranie švu).

    Súrodenec = iný región s tým istým `osmfr.parent`, ktorého bbox sa toho
    nášho aspoň dotýka. Zoznam susedov sa NIKDE NEPÍŠE RUČNE (pravidlo 1):
    číselník by sa raz rozišiel s hranicami a chýbajúci sused by ticho
    znamenal „šev je v poriadku", teda presne ten omyl, ktorý má meranie
    odhaliť. Bboxy sú v `regions.json` a hranice na osm.fr – to stačí.

    Vracia `({kľúč: prstence}, prstence_rodiča)`; čo sa nestiahlo, chýba.
    """
    reg = regs.get(key) or {}
    parent = ((reg.get("osmfr") or {}).get("parent") or "")
    if not parent:
        return {}, None
    w, s, e, n = reg["bbox"]
    susedia = {}
    for k, r in regs.items():
        if k == key or not isinstance(r, dict):
            continue
        if ((r.get("osmfr") or {}).get("parent") or "") != parent:
            continue
        bw, bs, be, bn = r.get("bbox") or (0, 0, 0, 0)
        if bw > e or be < w or bs > n or bn < s:
            continue            # bboxy sa ani nedotýkajú – nie je to sused
        rings = stiahni_rings(r)
        if rings:
            susedia[k] = rings
    rodic = stiahni_rings(regs.get(parent) or {})
    return susedia, rodic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True, help="kľúč z data/regions.json")
    ap.add_argument("--regions", default="", help="cesta k regions.json")
    ap.add_argument("--out", default="data/region.geojson")
    ap.add_argument("--poly-out", default="",
                    help="kam uložiť surový .poly (pre Planetiler --polygon)")
    ap.add_argument("--summary", default="", help="kam dopísať súhrn")
    ap.add_argument("--no-seam", action="store_true",
                    help="nemerať šev so susednými krajmi (sťahuje ich .poly)")
    args = ap.parse_args()

    regs = regions(args.regions or None)
    reg = regs.get(args.region)
    if not reg:
        print(f"::error::Neznámy región '{args.region}'. Známe: "
              f"{', '.join(sorted(regs))}", file=sys.stderr)
        return 1
    bbox = tuple(reg["bbox"])
    url = poly_url(reg)

    rings, zdroj, raw = None, "", ""
    if url:
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            rings = parse_poly(raw)
            zdroj = url
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            # NIE JE TO CHYBA BEHU: bez polygónu sa dá počítať na bboxe ako
            # doteraz. Musí to ale byť nahlas – ticho by to znamenalo hodiny
            # počítania mimo kraj a rovnú hranu v tieňovaní.
            print(f"::warning::Polygón kraja sa nepodarilo stiahnuť "
                  f"({url}: {exc}) – vrstvy z DEM sa spočítajú na CELOM BBOXE "
                  f"regiónu, teda aj mimo kraj. Skús beh zopakovať.")
    zo_servera = bool(raw)          # `.poly` sa píše len vtedy (viď nižšie)
    if not rings:
        rings, zdroj = bbox_rect(bbox), "bbox regiónu (polygón nie je)"

    # PREKRYV SO SUSEDOM – LEN KEĎ JE POLYGÓN NAOZAJ Z OSM.FR. Obdĺžnik z bboxu
    # (`bbox_rect`) je náhrada za chýbajúci polygón a je aj tak oveľa väčší než
    # kraj sám (rozpis v hlavičke), takže nafúknuť ho o pár km navyše by nič
    # neriešilo – susedný gap vzniká medzi dvoma NEZÁVISLE zjednodušenými
    # polygónmi, nie medzi dvoma obdĺžnikmi.
    buffer_ok = False
    povodne = rings                 # nenafúknuté – na meranie švu nižšie
    if zo_servera:
        rings, buffer_ok = buffer_rings(rings)

    data = geojson(rings)
    if not data:
        print("::error::Polygón kraja nemá ani jeden vonkajší prstenec.",
              file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f)
    # `.poly` pre Planetiler – len keď je polygón naozaj zo servera (viď
    # hlavičku): písaný ZNOVA z (prípadne nafúknutých) `rings`, nie uložený
    # bajt po bajte tak, ako prišiel (rozpis pri `rings_to_poly_text`).
    if args.poly_out and zo_servera:
        os.makedirs(os.path.dirname(args.poly_out) or ".", exist_ok=True)
        with open(args.poly_out, "w") as f:
            f.write(rings_to_poly_text(rings, args.region))

    # ŠEV SO SUSEDMI. Až TERAZ, keď je polygón na disku: je to MERANIE, nie
    # výroba – keby padlo alebo trvalo, mapa už má z čoho vzniknúť.
    #
    # Nafúknutie hore je len POLOVICA odpovede na otázku „nadväzuje na našu
    # mapu tá susedná?" – druhú polovicu robí sused na svojej strane a nikto
    # ich nikdy nedal dokopy. Toto ich dá: zmeria, či medzeru medzi dvoma
    # PÔVODNÝMI hranicami vôbec zavrú dve nafúknutia (rozpis vo `seam.py`).
    # Zlyhanie merania nie je chyba behu – mapa je hotová, len sa o švíku
    # nedozvieme; ticho to ale nebude.
    sev = None
    if zo_servera and not args.no_seam:
        try:
            susedia, rodic = susedne_rings(regs, args.region)
            if susedia:
                sev = seam.zmeraj_sev(povodne, susedia, rodic,
                                      BORDER_BUFFER_M)
        except Exception as exc:                        # noqa: BLE001
            print(f"::warning::Šev so susedmi sa nepodarilo zmerať ({exc}). "
                  f"Mapa je hotová, len sa nevie, či na ňu susedná nadväzuje.")

    pw, ps, pe, pn = ring_bbox(rings)
    plocha = sum(ring_area_km2(r) for r, hole in rings if not hole) \
        - sum(ring_area_km2(r) for r, hole in rings if hole)
    bw, bs, be, bn = bbox
    bbox_km2 = ring_area_km2([(bw, bs), (be, bs), (be, bn), (bw, bn)])
    podiel = 100 * plocha / bbox_km2 if bbox_km2 else 0
    prstencov = sum(1 for _, hole in rings if not hole)
    dier = sum(1 for _, hole in rings if hole)

    print(f"Polygón kraja: {args.out}")
    print(f"  zdroj                {zdroj}")
    if zo_servera:
        print(f"  prekryv so susedom   "
              + (f"+{BORDER_BUFFER_M:g} m (rozpis: prečo, v hlavičke súboru)"
                 if buffer_ok else
                 "NIE JE – nepodarilo sa (viď ::warning:: vyššie), polygón "
                 "ostáva presne na hranici kraja"))
    if args.poly_out:
        print(f"  .poly pre Planetiler  "
              f"{args.poly_out if zo_servera else 'NIE JE (dlaždice pôjdu na celom bboxe)'}")
    print(f"  prstencov            {prstencov} (+{dier} dier), "
          f"{sum(len(r) for r, _ in rings)} bodov")
    print(f"  bbox polygónu        {pw:.3f},{ps:.3f},{pe:.3f},{pn:.3f}")
    print(f"  bbox regiónu         {bw},{bs},{be},{bn}")
    # TOTO JE TO ČÍSLO, o ktoré ide: koľko práce padalo mimo kraj.
    print(f"  plocha kraja         {plocha:,.0f} km² z {bbox_km2:,.0f} km² "
          f"bboxu = {podiel:.0f} %")
    print(f"  mimo kraj            {bbox_km2 - plocha:,.0f} km² "
          f"({100 - podiel:.0f} % bboxu) sa už nepočíta")
    if sev:
        for riadok in seam.sprava(sev, BORDER_BUFFER_M):
            print(riadok)
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(f"- **Orez na kraj**: {plocha:,.0f} km² z "
                    f"{bbox_km2:,.0f} km² bboxu ({podiel:.0f} %), "
                    f"{prstencov} prstenec/ov\n")
            if zo_servera:
                f.write(
                    f"- **Prekryv so susedom**: "
                    + (f"+{BORDER_BUFFER_M:g} m (proti medzere medzi "
                       f"nezávisle zjednodušenými hranicami susedných "
                       f"krajov)\n" if buffer_ok else
                       "sa nepodarilo dopočítať – polygón ostáva presne na "
                       "hranici kraja (viď `::warning::` v logu)\n"))
            if sev and sev["bodov"]:
                f.write(
                    f"- **Šev so susedmi**: "
                    + (f"zavretý ✓ (najhoršie miesto "
                       f"{sev['najhorsia_m'] / 1000:.2f} km, zavrú sa "
                       f"{sev['limit_m'] / 1000:.2f} km)\n" if sev["zavrety"]
                       else f"**MEDZERA {sev['najhorsia_m'] / 1000:.2f} km** "
                            f"pri susedovi `{sev['sused']}` – dve nafúknutia "
                            f"zavrú len {sev['limit_m'] / 1000:.2f} km, medzi "
                            f"mapami tam ostane pás bez mapy\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
