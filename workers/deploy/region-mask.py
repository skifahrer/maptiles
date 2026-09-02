#!/usr/bin/env python3
"""
Hranica stiahnutého regiónu pre viewer: `data/region.geojson` → `_site/region.geojson`.

PREČO TO VZNIKLO. Mapa sa stavia z PBF kraja, ale dlaždice sa robia na
OBDĹŽNIKU jeho bboxu – a Planetiler do nich okrem OSM dát kreslí aj vodstvo,
pobrežia a Natural Earth, ktoré sú celosvetové. Prešovský kraj má bbox
199 × 82 km, čiže skoro dvojnásobok svojej plochy: po stiahnutí regiónu do
telefónu tak mapa pokračovala do Poľska aj na Ukrajinu, len tam z nej ostalo
podfarbené prázdno bez ciest a sídel. Používateľ z toho nemá ako prečítať, kde
jeho stiahnutá mapa naozaj končí – vyzerá to ako mapa, ktorá sa nedonačítala.

ČO S TÝM. Dve polovice, a obe sú potrebné:

  1. Dlaždice sa mimo kraja prestanú VYRÁBAŤ (`--polygon` Planetileru,
     `workers/lib/region-clip.sh`). To je hrubý orez – Planetiler vynechá celé
     dlaždice, ktoré sa tvaru nedotknú, takže na z14 môže presahovať ešte
     zhruba jednu dlaždicu (~1,5 km).
  2. Presnú hranicu dokreslí až ŠTÝL, a to z tohto súboru: `mimo` je plocha
     „všetko okrem regiónu" (vykreslí sa farbou podkladu, takže za hranicou
     nie je nič) a `hranica` je obrys, aby bolo vidieť, kde stiahnutá mapa
     končí. To isté dostane web aj iOS, lebo štýl je spoločný.

TVAR SA NEPOČÍTA DRUHÝKRÁT. Berie sa polygón z `workers/plan/region-poly.py`,
teda ten istý `.poly`, ktorým je orezaný PBF a ktorý dostáva `-cutline`
vrstevníc a maska tieňovania. Keby si hranicu kreslil viewer po svojom, bola
by to druhá pravda o jednej hranici (pravidlo 1) – a rozišla by sa ticho:
mapa by vyzerala celá, len by jej kúsok chýbal alebo prebýval.

OREZ NA BBOX BEHU. Keď je mapa menšia než kraj (`crop_bbox`, vlastný región),
prstence sa najprv orežú na bbox, ktorý beh naozaj postavil – Sutherland–
Hodgman proti obdĺžniku. Bez toho by maska sľubovala mapu tam, kde nie sú
dlaždice. Pri bežnom behu (kraj celý) sa neoreže nič a prstence idú tak, ako
prišli.

Použitie:
    python3 workers/deploy/region-mask.py --poly=data/region.geojson \\
        --bbox=19.865,48.745,22.585,49.48 --out=_site/region.geojson
"""
import argparse
import json
import math
import os
import sys

# Web Mercator končí na ±85,0511° – vyššie sa mapa nekreslí, takže plocha
# „mimo regiónu" nemá načo siahať ďalej.
LAT_MAX = 85.0511


def rings_from_geojson(path):
    """GeoJSON → `[(prstenec, je_diera)]`; prstenec je zoznam `(lon, lat)`."""
    with open(path) as f:
        data = json.load(f)
    feats = (data.get("features") if data.get("type") == "FeatureCollection"
             else [data])
    out = []
    for feat in feats or []:
        geom = feat.get("geometry") if "geometry" in feat else feat
        if not geom:
            continue
        polys = ([geom.get("coordinates")] if geom.get("type") == "Polygon"
                 else geom.get("coordinates") or [])
        for poly in polys:
            for i, ring in enumerate(poly or []):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) >= 3:
                    out.append((pts, i > 0))     # prvý prstenec = obrys
    return out


def clip_ring(ring, bbox):
    """Prstenec orezaný na obdĺžnik (Sutherland–Hodgman), alebo `[]`.

    Konvexný orezávač, takže na obdĺžnik to platí aj pre nekonvexný prstenec;
    z kraja rozdeleného bboxom na dva kusy vyjde jeden prstenec so spojnicou
    po hrane obdĺžnika. Pri obryse je tá spojnica presne to, čo tam patrí –
    mapa naozaj končí na hrane bboxu.
    """
    w, s, e, n = bbox
    hrany = (("x>", w), ("x<", e), ("y>", s), ("y<", n))
    body = list(ring)
    if body and body[0] == body[-1]:
        body = body[:-1]
    for smer, hodnota in hrany:
        if not body:
            return []

        def vnutri(p):
            return (p[0] >= hodnota if smer == "x>" else
                    p[0] <= hodnota if smer == "x<" else
                    p[1] >= hodnota if smer == "y>" else
                    p[1] <= hodnota)

        def prienik(a, b):
            if smer in ("x>", "x<"):
                t = (hodnota - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
                return (hodnota, a[1] + t * (b[1] - a[1]))
            t = (hodnota - a[1]) / (b[1] - a[1]) if b[1] != a[1] else 0.0
            return (a[0] + t * (b[0] - a[0]), hodnota)

        nove = []
        for i, b in enumerate(body):
            a = body[i - 1]
            if vnutri(b):
                if not vnutri(a):
                    nove.append(prienik(a, b))
                nove.append(b)
            elif vnutri(a):
                nove.append(prienik(a, b))
        body = nove
    return body if len(body) >= 3 else []


def uzavri(ring, presnost=6):
    """Prstenec na GeoJSON súradnice – zaokrúhlený a uzavretý."""
    coords = [[round(x, presnost), round(y, presnost)] for x, y in ring]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def ring_area_km2(ring):
    """Plocha prstenca v km² – rovinná aproximácia, stačí na výpis."""
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


def svet_ring():
    return [(-180.0, -LAT_MAX), (180.0, -LAT_MAX),
            (180.0, LAT_MAX), (-180.0, LAT_MAX)]


def mask_geojson(obrysy, diery):
    """Dve črty: `mimo` (plocha okolo regiónu) a `hranica` (jeho obrys).

    `mimo` je JEDEN polygón cez celý svet, v ktorom sú obrysy regiónu DIERAMI –
    presne tak, ako to earcut v MapLibre potrebuje (prvý prstenec je obrys,
    ďalšie diery; na smere navíjania mu nezáleží). Diery samotného regiónu
    (enkláva vnútri kraja) idú do masky ako samostatné plné polygóny: to, čo
    nie je kraj, sa má prekryť aj vtedy, keď to leží v jeho vnútri.
    """
    mask = [[uzavri(svet_ring())] + [uzavri(r) for r in obrysy]]
    mask += [[uzavri(r)] for r in diery]
    # Obrys ide ako jeden polygón s dierami – kreslí sa `line` vrstvou, ktorá
    # obtiahne každý prstenec, takže enklávy dostanú hranicu tiež.
    hranica = [[uzavri(r)] + [uzavri(d) for d in diery] for r in obrysy[:1]]
    hranica += [[uzavri(r)] for r in obrysy[1:]]
    return {
        "type": "FeatureCollection",
        "_comment": ("Hranica stiahnutého regiónu pre viewer (web aj iOS): "
                     "`mimo` je plocha okolo regiónu, `hranica` jeho obrys. "
                     "Vyrába workers/deploy/region-mask.py z toho istého "
                     "polygónu, ktorým je orezaný PBF."),
        "features": [
            {"type": "Feature", "properties": {"kind": "mimo"},
             "geometry": {"type": "MultiPolygon", "coordinates": mask}},
            {"type": "Feature", "properties": {"kind": "hranica"},
             "geometry": {"type": "MultiPolygon", "coordinates": hranica}},
        ],
    }


def pad_bbox(bbox, meters):
    """`bbox` zväčšený o `meters` na každú stranu (stupne podľa šírky).

    NA ČO TO JE. `region-poly.py` polygón NAFÚKNE o kus von – prekryv so
    susedným krajom namiesto medzery na hranici (rozpis tam). Bez tohto by
    `--bbox` nižšie bol ešte TESNÝ obdĺžnik z `workers/data/regions.json`
    (presne okolo pôvodného, nenafúknutého polygónu) a orez „mapa je menšia
    než kraj" (`orez` nižšie) by nafúknutý pás pri KAŽDOM bežnom behu odrezal
    späť na starú, presnú hranicu – presne to, čo mal `--pad-m` zabrániť.
    """
    if not meters:
        return bbox
    w, s, e, n = bbox
    lat0 = max(min((s + n) / 2, LAT_MAX), -LAT_MAX)
    dlat = meters / 110540.0
    dlon = meters / (111320.0 * math.cos(math.radians(lat0)))
    return (w - dlon, s - dlat, e + dlon, n + dlat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poly", default="data/region.geojson",
                    help="polygón regiónu z workers/plan/region-poly.py")
    ap.add_argument("--bbox", default="", help="bbox behu: west,south,east,north")
    ap.add_argument("--pad-m", type=float, default=0.0,
                    help="o koľko m zväčšiť --bbox pred orezom – rovnaké "
                         "číslo, o aké `region-poly.py` nafúkol --poly "
                         "(BORDER_BUFFER_M), inak orez z tejto vrstvy "
                         "nafúknutý pás zase odreže (viď `pad_bbox`)")
    ap.add_argument("--out", default="_site/region.geojson")
    args = ap.parse_args()

    if not os.path.isfile(args.poly):
        print(f"::warning::Polygón regiónu ({args.poly}) nie je – mapa sa "
              f"nasadí bez hranice a v aplikácii bude siahať aj za región. "
              f"Zvyčajne to znamená, že sa v jobe `plan` nestiahol `.poly`; "
              f"skús beh zopakovať.")
        return 0

    rings = rings_from_geojson(args.poly)
    if not rings:
        print(f"::error::V {args.poly} nie je ani jeden prstenec.",
              file=sys.stderr)
        return 1

    bbox = None
    if args.bbox:
        try:
            w, s, e, n = (float(v) for v in args.bbox.split(","))
            bbox = pad_bbox((w, max(s, -LAT_MAX), e, min(n, LAT_MAX)),
                            args.pad_m)
        except ValueError:
            print(f"::error::--bbox má byť west,south,east,north, prišlo "
                  f"'{args.bbox}'.", file=sys.stderr)
            return 1

    # Orezáva sa LEN keď región z bboxu behu naozaj vytŕča (crop_bbox, vlastný
    # región). Pri bežnom behu je kraj celý vnútri a orez by len pridal body.
    orez = False
    if bbox:
        xs = [x for ring, _ in rings for x, _ in ring]
        ys = [y for ring, _ in rings for _, y in ring]
        orez = (min(xs) < bbox[0] or max(xs) > bbox[2]
                or min(ys) < bbox[1] or max(ys) > bbox[3])

    obrysy, diery = [], []
    for ring, hole in rings:
        r = clip_ring(ring, bbox) if orez else list(ring)
        if not r:
            continue
        (diery if hole else obrysy).append(r)

    if not obrysy:
        print(f"::error::Po oreze na bbox {args.bbox} neostal z regiónu ani "
              f"kúsok – bbox behu a polygón regiónu sa neprekrývajú. Over "
              f"`crop_bbox` (a `custom_bbox`), či je naozaj v tom regióne.",
              file=sys.stderr)
        return 1

    data = mask_geojson(obrysy, diery)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f)

    plocha = (sum(ring_area_km2(r) for r in obrysy)
              - sum(ring_area_km2(r) for r in diery))
    bodov = sum(len(r) for r in obrysy) + sum(len(r) for r in diery)
    kb = os.path.getsize(args.out) / 1024
    print(f"Hranica regiónu: {args.out}")
    print(f"  prstencov            {len(obrysy)} (+{len(diery)} dier), "
          f"{bodov} bodov, {kb:.1f} kB")
    print(f"  plocha regiónu       {plocha:,.0f} km²")
    print(f"  orez na bbox behu    "
          f"{args.bbox if orez else 'netreba (región je celý v bboxe)'}")
    print("  Za touto hranicou štýl nekreslí nič – ani vodstvo a Natural "
          "Earth, ktoré Planetiler dáva do dlaždíc na celom obdĺžniku.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
