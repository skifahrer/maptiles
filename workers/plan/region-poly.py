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

═══ HRANICA JE TERAZ PRESNÁ: Z OSM RELÁCIE, NIE Z `.poly` OSM.FR ═══

Dlho sa brala z `.poly`, ktorý osm.fr zverejňuje vedľa svojich extraktov. Bola
to tá istá čiara, ktorou je orezaný ich PBF, ale NEBOLA to hranica kraja: body
sú zaokrúhlené na mriežku 0,005° (≈ 550 m) a osm.fr si polygón okolo hranice
ešte sám ROZŠIRUJE – namerané na ôsmich krajoch SR sa susedné kraje v tých
`.poly` prekrývajú o 2 až 4 km. Nad tým sa prekryv ešte zväčšoval o
`BORDER_BUFFER_M` (2 500 m na stranu), aby medzi dvoma stiahnutými mapami
neostala medzera. Výsledok: mapa kraja siahala kilometre do susedného kraja,
do Poľska aj na Ukrajinu, a to isté robili vrstevnice, skaly aj tieňovanie.

Teraz sa hranica číta PRIAMO Z OSM (`workers/plan/boundary.py`): relácia
`boundary=administrative` s `admin_level` a `osm_name` z
`workers/data/regions.json`, poskladaná `osmium export`-om z toho istého PBF,
z akého je mapa. Kraj (`admin_level=4`) sa ešte PRETNE so štátom
(`admin_level=2`), takže čo v relácii vytŕča za štátnu hranicu, do mapy kraja
nejde. Prekryv so susedom sa tým nestráca, len prestáva byť potrebný: dva
susedné kraje zdieľajú v OSM tie isté cesty hranice, takže na seba nadväzujú
PRESNE – bez medzery a bez prekryvu. Že to tak naozaj je, meria `seam.py`
v každom behu (a hovorí aj to, koľko z toho ukroja dve zjednodušenia hranice –
rozpis pri `boundary.uprav`).

`.poly` Z OSM.FR OSTÁVA AKO NÁHRADA – nič viac. Keď sa hranica v PBF nenájde
(iné dáta, iné meno relácie), radšej sa reže po starom a nahlas
(`::warning::`), než aby beh spadol; ale mapa vtedy o sebe vie, že je orezaná
rozšíreným polygónom.

`.poly` PRE PLANETILER A PRE `osmium extract` SA PÍŠE Z TÝCH ISTÝCH PRSTENCOV
ako `.geojson` (`rings_to_poly_text`) – dva zápisy tej istej hranice by boli
dve pravdy o nej (pravidlo 1). Bez tejto vrstvy to číta Planetiler
(`--polygon=…`, „emit any tile that intersects the shape"), takže sa dlaždice
mapy prestanú vyrábať na celom obdĺžniku bboxu, a `osmium extract --polygon`,
ktorým sa kraj reže z rodičovského extraktu. Keď sa hranica nezíska vôbec,
`.poly` NEVZNIKNE – náhradný obdĺžnik z bboxu je presne to, čo Planetiler robí
aj bez neho, takže by len predstieral orez (a rez z rodiča vtedy zámerne
padne, viď `workers/plan/pbf.sh`).

Použitie:
    python3 workers/plan/region-poly.py --region=presovsky \
        --from-pbf=data/region.osm.pbf --out=data/region.geojson \
        --poly-out=data/region.poly --summary=$GITHUB_STEP_SUMMARY
    python3 workers/plan/region-poly.py --region=presovsky --out=…   (náhrada z osm.fr)
"""
import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

# KOĽKO TERÉNU SA POČÍTA EŠTE ZA HRANICOU KRAJA – dnes 0, lebo sa reže presne
# (rozpis v hlavičke tohto súboru aj pri `BORDER_BUFFER_M` v `area.py`). Číslo
# je definované v `area.py` (bez pomlčky v mene, dá sa normálne `import`-núť)
# a nafukuje okno, z ktorého sa čítajú vrstvy z výškového modelu
# (`area.py::pad_bbox`); nesie sa aj v menách uložených vrstiev, aby sa po jeho
# zmene nevrátila z Drive tá stará (`workers/lint/border-overlap.py`).
sys.path.insert(0, _HERE)
from area import BORDER_BUFFER_M  # noqa: E402
import boundary  # noqa: E402  (presná hranica z OSM – rozpis v tom súbore)
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
    """Prstence → GeoJSON. Preklad je v `boundary.py` – tam ho potrebuje aj
    čítanie hraníc z PBF a dve kópie by sa raz rozišli (pravidlo 1)."""
    return boundary.geojson_from_rings(rings)


def bbox_rect(bbox):
    """Náhrada, keď polygón nie je: obdĺžnik z bboxu (teda dnešné správanie)."""
    w, s, e, n = bbox
    ring = [(w, s), (e, s), (e, n), (w, n), (w, s)]
    return [(list(ring), False)]


def rings_to_poly_text(rings, name="region"):
    """`[(prstenec, je_diera)]` → text `.poly` (ten istý formát, aký sťahuje
    `poly_url`; parsuje ho späť `parse_poly` vyššie).

    Píše sa znova z prstencov, nie ukladá bajt po bajte to, čo prišlo zo
    servera: hranica je zvyčajne z OSM relácie (`boundary.py`), pretnutá so
    štátom a zjednodušená, takže „ako prišlo" by aj tak nesedelo – a boli by
    to dve pravdy o tej istej hranici (pravidlo 1).
    """
    lines = [name or "region"]
    for i, (ring, hole) in enumerate(rings, start=1):
        closed = ring if ring[0] == ring[-1] else list(ring) + [ring[0]]
        lines.append(f"!{i}" if hole else str(i))
        lines += [f"\t{lon:.6f}\t{lat:.6f}" for lon, lat in closed]
        lines.append("END")
    lines.append("END")
    return "\n".join(lines) + "\n"


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


def osm_meno(reg, kluc=""):
    """Meno, pod ktorým je región v OSM – `osm_name`, inak jeho `name`."""
    return (reg.get("osm_name") or reg.get("name") or kluc or "").strip()


def presne_rings(reg, hranice, kluc=""):
    """Prstence regiónu z už poskladaných hraníc PBF, alebo `None`.

    Jedno miesto, kde sa z `regions.json` (meno + `admin_level`) a zo zoznamu
    hraníc stane polygón – pýta sa naň aj samotný región v `main`, aj každý
    jeho súrodenec pri meraní švu, a dve kópie toho páru by sa raz rozišli.
    """
    if not hranice:
        return None
    return boundary.vyber(hranice, osm_meno(reg, kluc),
                          int(reg.get("admin_level") or 4))


def susedne_rings(regs, key, hranice=None):
    """Polygóny SÚRODENCOV a RODIČA daného regiónu (na meranie švu).

    Súrodenec = iný región s tým istým `osmfr.parent`, ktorého bbox sa toho
    nášho aspoň dotýka. Zoznam susedov sa NIKDE NEPÍŠE RUČNE (pravidlo 1):
    číselník by sa raz rozišiel s hranicami a chýbajúci sused by ticho
    znamenal „šev je v poriadku", teda presne ten omyl, ktorý má meranie
    odhaliť. Bboxy sú v `regions.json` a hranice v OSM – to stačí.

    ═══ VŠETKY HRANICE Z JEDNÉHO ZDROJA, ALEBO ŽIADNE ═══

    Keď je našou hranicou presná relácia z PBF (`hranice`), musia byť presné
    aj hranice susedov. Merať presnú hranicu proti ROZŠÍRENEJ z osm.fr by
    ukázalo prekryv 2 – 4 km, ktorý v skutočnosti nikde nie je – a to nie je
    meranie, to je porovnávanie dvoch rôznych otázok. Preto sa v tomto režime
    NEsťahuje nič: sused, ktorý v PBF nie je, sa vynechá a POVIE SA TO.

    Že tam susedia sú, zariaďuje `osmium extract -s smart -S
    types=multipolygon,boundary`: susedný kraj má s tým naším spoločné cesty
    hranice, takže sa jeho relácia doplní celá – aj v už rezanom PBF kraja.

    Vracia `({kľúč: prstence}, prstence_rodiča, [kľúče, čo chýbajú])`.
    """
    reg = regs.get(key) or {}
    parent = ((reg.get("osmfr") or {}).get("parent") or "")
    if not parent:
        return {}, None, []
    w, s, e, n = reg["bbox"]
    susedia, chyba = {}, []
    for k, r in regs.items():
        if k == key or not isinstance(r, dict):
            continue
        if ((r.get("osmfr") or {}).get("parent") or "") != parent:
            continue
        bw, bs, be, bn = r.get("bbox") or (0, 0, 0, 0)
        if bw > e or be < w or bs > n or bn < s:
            continue            # bboxy sa ani nedotýkajú – nie je to sused
        rings = (presne_rings(r, hranice, k) if hranice
                 else stiahni_rings(r))
        if rings:
            susedia[k] = rings
        else:
            chyba.append(k)
    reg_rodic = regs.get(parent) or {}
    rodic = (presne_rings(reg_rodic, hranice, parent) if hranice
             else stiahni_rings(reg_rodic))
    return susedia, rodic, chyba


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True, help="kľúč z data/regions.json")
    ap.add_argument("--regions", default="", help="cesta k regions.json")
    ap.add_argument("--from-pbf", default="",
                    help="OSM PBF, z ktorého sa prečíta PRESNÁ hranica "
                         "(relácia `boundary=administrative`); bez neho sa "
                         "berie náhradný `.poly` z osm.fr")
    ap.add_argument("--out", default="data/region.geojson")
    ap.add_argument("--poly-out", default="",
                    help="kam uložiť surový .poly (pre Planetiler --polygon "
                         "a pre `osmium extract --polygon`)")
    ap.add_argument("--summary", default="", help="kam dopísať súhrn")
    ap.add_argument("--no-seam", action="store_true",
                    help="nemerať šev so susednými krajmi")
    args = ap.parse_args()

    regs = regions(args.regions or None)
    reg = regs.get(args.region)
    if not reg:
        print(f"::error::Neznámy región '{args.region}'. Známe: "
              f"{', '.join(sorted(regs))}", file=sys.stderr)
        return 1
    bbox = tuple(reg["bbox"])

    # ═══ 1. PRESNÁ HRANICA Z OSM ═══ (rozpis v hlavičke súboru)
    rings, zdroj, presna = None, "", False
    hranice, stav, ma_stat = [], {}, False
    if args.from_pbf:
        hranice = boundary.hranice_z_pbf(args.from_pbf)
        surove = presne_rings(reg, hranice, args.region)
        if surove:
            # PRIENIK SO ŠTÁTOM: kraj nesmie vytŕčať za štátnu hranicu ani
            # vtedy, keď je jeho relácia v OSM pokazená (rozpis pri
            # `boundary.uprav`). Rodič je kľúč iného regiónu v tom istom
            # číselníku – jeho `admin_level` je 2, takže sa nájde tá istá
            # hranica, akou sa reže celé Slovensko.
            parent = ((reg.get("osmfr") or {}).get("parent") or "")
            stat = (presne_rings(regs[parent], hranice, parent)
                    if parent and parent in regs else None)
            # Región BEZ rodiča je sám tá krajina (`slovensko`,
            # `admin_level=2`) – nie je čím ho pretínať a nie je to chyba.
            ma_stat = bool(parent)
            pred = sum(ring_area_km2(r) for r, hole in surove if not hole)
            rings, stav = boundary.uprav(surove, stat)
            po = sum(ring_area_km2(r) for r, hole in rings if not hole)
            presna = True
            zdroj = (f"OSM relácia `{osm_meno(reg, args.region)}` "
                     f"(admin_level={reg.get('admin_level') or 4}) "
                     f"z {args.from_pbf}")
            if stav.get("orezane") and pred - po > 1.0:
                # Rule 4: čo sa orezalo, nie čo sa o to len skúsilo. Väčší
                # rozdiel než pár km² znamená, že relácia kraja naozaj
                # vytŕčala za štátnu hranicu – to sa má vedieť.
                print(f"::warning::Relácia kraja siahala {pred - po:,.0f} km² "
                      f"za štátnu hranicu; orezané prienikom so štátom.")
        else:
            print(f"::warning::V {args.from_pbf} nie je hranica "
                  f"`{osm_meno(reg, args.region)}` "
                  f"(admin_level={reg.get('admin_level') or 4}), takže sa "
                  f"reže NÁHRADNÝM `.poly` z osm.fr – ten je zaokrúhlený na "
                  f"~550 m a okolo hranice rozšírený, takže mapa presiahne do "
                  f"susedného kraja aj za štátnu hranicu. Skontroluj "
                  f"`osm_name` a `admin_level` v workers/data/regions.json.")

    # ═══ 2. NÁHRADA: `.poly` z osm.fr ═══
    raw = ""
    url = poly_url(reg)
    if rings is None and url:
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            rings = parse_poly(raw)
            zdroj = f"{url} (náhrada – nie je to hranica kraja, viď hlavičku)"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            # NIE JE TO CHYBA BEHU: bez polygónu sa dá počítať na bboxe ako
            # doteraz. Musí to ale byť nahlas – ticho by to znamenalo hodiny
            # počítania mimo kraj a rovnú hranu v tieňovaní.
            print(f"::warning::Polygón kraja sa nepodarilo stiahnuť "
                  f"({url}: {exc}) – vrstvy z DEM sa spočítajú na CELOM BBOXE "
                  f"regiónu, teda aj mimo kraj. Skús beh zopakovať.")
    # `.poly` sa píše len vtedy, keď hranica NAOZAJ je – obdĺžnik z bboxu by
    # orez len predstieral (rozpis v hlavičke).
    hranica_je = presna or bool(raw)
    if not rings:
        rings, zdroj = bbox_rect(bbox), "bbox regiónu (hranica nie je)"

    data = geojson(rings)
    if not data:
        print("::error::Polygón kraja nemá ani jeden vonkajší prstenec.",
              file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f)
    if args.poly_out and hranica_je:
        os.makedirs(os.path.dirname(args.poly_out) or ".", exist_ok=True)
        with open(args.poly_out, "w") as f:
            f.write(rings_to_poly_text(rings, args.region))

    # ═══ 3. ŠEV SO SUSEDMI ═══
    # Až TERAZ, keď je polygón na disku: je to MERANIE, nie výroba – keby
    # padlo alebo trvalo, mapa už má z čoho vzniknúť.
    #
    # Odkedy je hranica presná, sa nemeria „zavrú dve nafúknutia medzeru",
    # ale to hlavné, čo o susedovi treba vedieť: dotýkame sa ho, alebo je
    # medzi mapami diera – a nelezieme doňho (rozpis vo `seam.py`).
    # Zlyhanie merania nie je chyba behu – mapa je hotová, len sa o švíku
    # nedozvieme; ticho to ale nebude.
    sev = None
    if hranica_je and not args.no_seam:
        try:
            susedia, rodic, chyba = susedne_rings(regs, args.region, hranice)
            if chyba:
                # Rule 8: chýbajúci sused nesmie znamenať „šev je v poriadku".
                print(f"::warning::Hranicu susedov {', '.join(sorted(chyba))} "
                      f"sa nepodarilo získať z toho istého zdroja ako našu, "
                      f"takže sa s nimi šev NEMERAL – čísla nižšie hovoria len "
                      f"o zvyšných. Pri kraji to znamená, že v PBF nie je ich "
                      f"relácia; skontroluj `osm_name` a `admin_level` "
                      f"v workers/data/regions.json a že rez z rodiča má "
                      f"`-s smart -S types=multipolygon,boundary`.")
            if susedia:
                sev = seam.zmeraj_sev(rings, susedia, rodic, BORDER_BUFFER_M)
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
    if presna:
        print(f"  orez štátom          "
              + ("áno (relácia kraja pretnutá hranicou štátu)"
                 if stav.get("orezane") else
                 "netreba – tento región JE tá krajina"
                 if not ma_stat else
                 "NIE – hranicu štátu sa nepodarilo použiť (viď ::warning:: "
                 "vyššie)"))
        print(f"  zjednodušenie        "
              + (f"{boundary.OREZ_TOLERANCIA_M:g} m "
                 f"(kvôli času rezu, rozpis pri `boundary.uprav`)"
                 if stav.get("zjednodusene") else
                 "NIE – reže sa plnou geometriou, rez z rodiča potrvá dlhšie"))
    if args.poly_out:
        print(f"  .poly na orez        "
              f"{args.poly_out if hranica_je else 'NIE JE (dlaždice pôjdu na celom bboxe)'}")
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
                    f"{prstencov} prstenec/ov, hranica: "
                    + ("**presná z OSM**" if presna
                       else "náhradný `.poly` z osm.fr (rozšírený!)") + "\n")
            if sev and sev["bodov"]:
                f.write(f"- **Šev so susedmi**: {seam.zhrnutie(sev)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
