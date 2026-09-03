#!/usr/bin/env python3
"""
Drží mapa susedného kraja tam, kde tá naša končí? – ZMERANÉ, nie predpokladané.

PREČO TENTO SÚBOR VZNIKOL. Kraje sa stavajú po jednom a každý sa oreže vlastným
`.poly` z osm.fr (`workers/plan/region-poly.py`). Či na seba dve HOTOVÉ mapy
nadväzujú, sa doteraz nikde nemeralo – vedelo sa len to, že sa polygón pred
orezom nafúkne o `BORDER_BUFFER_M` a *predpokladalo* sa, že to stačí. Keď to
raz stačiť prestane (osm.fr prekreslí polygón, niekto zmenší nafúknutie,
pribudne kraj s hrubšie zjednodušenou hranicou), nespadne nič: obe mapy budú
zelené a medzi nimi bude pás bez mapy, ktorý uvidí až človek s telefónom
v teréne. Presne to je pravidlo 8 – tichý omyl. Toto je meranie, ktoré ten
predpoklad zmení na číslo v logu každého behu.

ČO SA MERIA. Kraj je vnútri krajiny obklopený SÚRODENCAMI (`osmfr.parent`
ukazuje na tú istú krajinu). Mapa každého z nich siaha `BORDER_BUFFER_M` ZA
jeho vlastnú hranicu, takže miesto medzi dvoma mapami ostane nepokryté práve
vtedy, keď sú od seba obe pôvodné hranice ďalej než dve nafúknutia dokopy:

    medzera(p) = vzdialenosť bodu p na NAŠEJ hranici k najbližšiemu súrodencovi
    šev je zavretý  ⟺  medzera(p) < 2 × BORDER_BUFFER_M   pre každé vnútorné p

„Vnútorné p" znamená bod, ktorý leží aspoň `INSIDE_PARENT_M` vnútri polygónu
RODIČA (celej krajiny). Bez tejto podmienky by kontrola kričala na každom
kilometri štátnej hranice – tam žiadny súrodenec nie je a byť nemá; mapa tam
končí právom.

Namerané (osem krajov SR, `.poly` z osm.fr, 3. 9. 2026 – čísla sa dajú
zopakovať `python3 workers/plan/seam.py --region=…`): susedné kraje sa
v skutočnosti PREKRÝVAJÚ už v samotných `.poly` (2 – 4 km, lebo osm.fr svoje
polygóny okolo hranice sám rozširuje), takže `medzera` vychádza na drvivej
väčšine hranice 0 m a najhoršie miesto je hlboko pod 5 km, ktoré zavrú dve
nafúknutia. Kontrola teda dnes prechádza s veľkou rezervou – a presne to má
strážiť: keď sa raz to číslo pohne, povie to beh a nie používateľ.

BEZ SHAPELY, zámerne – tá istá úvaha ako vo `workers/lib/region-mask.py`:
ide o vzdialenosť bodu k lomenej čiare a o test „je bod v polygóne", čo je
dvadsať riadkov, kým shapely je závislosť navyše v jobe, ktorý dnes vystačí
s čistým Pythonom. Počíta sa v ROVINE (lokálne metre okolo stredu regiónu):
kraj má nižšie než 200 km, takže skreslenie je hlboko pod hrúbkou hranice.

I/O NIE JE TU. Súbor pozná len geometriu; `.poly` sťahuje a parsuje
`region-poly.py` (ten jediný vie, odkiaľ sa hranica berie – pravidlo 1) a sem
ich podáva ako hotové prstence. Preto je meno bez pomlčky: `region-poly.py`
si ho normálne `import`-ne.

Použitie ako modul:
    from seam import zmeraj_sev
    sprava = zmeraj_sev(moje_prstence, {"zilinsky": prstence, …},
                        rodic_prstence, buffer_m=2500)

Alebo z príkazového riadka (kontrola a debug, sťahuje si `.poly` sám cez
`region-poly.py`):
    python3 workers/plan/seam.py --region=trnavsky
"""
import math

M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# Ako často sa naša hranica ochutnáva. 250 m je pod hrúbkou všetkého, čo tu
# meriame (nafúknutie je 2 500 m), a na kraji s 500 km obvodu je to 2 000
# bodov – teda sekundy, nie minúty.
STEP_M = 250.0

# Koľko musí byť bod vnútri rodiča, aby sa bral ako VNÚTORNÁ hranica (a teda
# aby sa preň čakal súrodenec).
#
# PREČO AŽ 5 km. Polygóny z osm.fr sú okolo hranice ROZŠÍRENÉ a každý inak –
# ten Slovenska siaha na Morave o kus ďalej než ten Bratislavského kraja.
# Namerané: bod 16,9510 48,2620 leží PRESNE na hranici Bratislavského kraja
# (teda na štátnej hranici s Rakúskom) a od obrysu Slovenska je 2,04 km – pri
# prahu 2 km ho kontrola vzala ako vnútornú hranicu a hlásila „medzeru 28 km"
# k Trnavskému kraju, ktorý tam nemá čo robiť. Prah musí byť nad tým, o koľko
# sa dva nezávisle rozšírené polygóny líšia; 5 km na to stačí a vnútornú
# hranicu to nezakryje (kraje sú široké desiatky km).
INSIDE_PARENT_M = 5000.0

# Ako ďaleko ešte môže byť súrodenec, aby sa bod bral ako SPOLOČNÁ hranica
# s ním – násobok nafúknutia. Bod, pri ktorom nie je súrodenec ani takto
# ďaleko, je hranica s cudzinou (alebo tam naozaj chýba celý kraj, čo sa
# hlási zvlášť); počítať to ako „medzeru so susedom" by znamenalo hlásiť
# štátnu hranicu ako chybu švu.
SHARED_MULT = 4.0


def to_metric(rings, lat0):
    """`[(prstenec, je_diera)]` v stupňoch → to isté v metroch okolo `lat0`."""
    kx = M_PER_DEG_LON * math.cos(math.radians(lat0))
    return [([(x * kx, y * M_PER_DEG_LAT) for x, y in ring], hole)
            for ring, hole in rings]


def _inside(rings_m, x, y):
    """Je bod v polygóne? Ray casting, diery odpočítané."""
    ok = False
    for ring, hole in rings_m:
        c = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    c = not c
        if c:
            if hole:
                return False
            ok = True
    return ok


def _dist_to_segment(x, y, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def dist_to_boundary(rings_m, x, y):
    """Vzdialenosť bodu k OBRYSU (aj zvnútra – na rozdiel od
    `dist_to_polygon`, ktoré vnútri vracia 0)."""
    best = math.inf
    for ring, _ in rings_m:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            d = _dist_to_segment(x, y, x1, y1, x2, y2)
            if d < best:
                best = d
    return best


def dist_to_polygon(rings_m, bbox_m, x, y, limit=None):
    """Vzdialenosť bodu k polygónu v metroch; 0, keď je bod vnútri.

    `bbox_m` je predpočítaný obdĺžnik polygónu – bod, ktorý je od neho ďalej
    než `limit`, sa nemusí porovnávať so stovkami úsečiek (na ôsmich krajoch
    to je rozdiel medzi sekundami a minútami).
    """
    w, s, e, n = bbox_m
    if limit is not None:
        dx = w - x if x < w else x - e if x > e else 0.0
        dy = s - y if y < s else y - n if y > n else 0.0
        if math.hypot(dx, dy) > limit:
            return math.inf
    if _inside(rings_m, x, y):
        return 0.0
    return dist_to_boundary(rings_m, x, y)


def bbox_of(rings_m):
    xs = [x for ring, _ in rings_m for x, _ in ring]
    ys = [y for ring, _ in rings_m for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def sample_boundary(rings_m, step_m=STEP_M):
    """Body na obryse polygónu, husto po `step_m` (diery sa nevzorkujú:
    hranica s enklávou vnútri kraja nie je hranica so susedným krajom)."""
    out = []
    for ring, hole in rings_m:
        if hole:
            continue
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            d = math.hypot(x2 - x1, y2 - y1)
            kroky = max(1, int(d // step_m))
            for k in range(kroky):
                t = k / kroky
                out.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
    return out


def zmeraj_sev(moje, susedia, rodic, buffer_m, lat0=None, step_m=STEP_M):
    """Zmeria, či na našu mapu nadväzujú mapy susedov.

    `moje`, `rodic` a hodnoty v `susedia` sú PÔVODNÉ (nenafúknuté) prstence
    v stupňoch – nafúknutie sa do výsledku zaráta číslom (`buffer_m`), lebo
    ho na svojej strane robí každý kraj sám tým istým skriptom.

    Vracia slovník:
        limit_m     – koľko medzery zavrú dve nafúknutia (2 × buffer_m)
        bodov       – koľko bodov vnútornej hranice sa meralo
        najhorsia_m – najväčšia nameraná medzera (0 = kraje sa prekrývajú)
        kde         – (lon, lat) toho miesta, alebo None
        sused       – ktorý súrodenec je tam najbližšie
        zavrety     – True, keď najhoršie miesto zavrú nafúknutia
        podla_suseda – {kľúč: (najhoršia medzera, koľko bodov mu patrí)}
        bez_suseda  – koľko bodov HLBOKO vnútri krajiny nemá súrodenca ani
                      na dosah (`SHARED_MULT × buffer_m`); to už nie je
                      hranica s cudzinou, ale chýbajúci kraj
    """
    if not moje:
        return None
    ys = [y for ring, _ in moje for _, y in ring]
    lat0 = lat0 if lat0 is not None else (min(ys) + max(ys)) / 2
    kx = M_PER_DEG_LON * math.cos(math.radians(lat0))

    moje_m = to_metric(moje, lat0)
    rodic_m = to_metric(rodic, lat0) if rodic else None
    sus_m = {k: to_metric(v, lat0) for k, v in susedia.items() if v}
    sus_bbox = {k: bbox_of(v) for k, v in sus_m.items()}

    limit = 2.0 * buffer_m
    # Hľadá sa najhoršie miesto, tak sa musí merať aj kus ZA limit – inak by
    # sa nedalo povedať „chýbalo 300 m" ani „chýbalo 12 km". Za `dosah` sa
    # už žiadny súrodenec nehľadá: taký bod je hranica s cudzinou.
    dosah = SHARED_MULT * buffer_m

    najhorsia, kde, kto, bodov, bez = -1.0, None, None, 0, 0
    podla = {k: [-1.0, 0] for k in sus_m}
    for x, y in sample_boundary(moje_m, step_m):
        # LEN VNÚTORNÁ HRANICA. Na štátnej hranici žiadny súrodenec nie je
        # a mapa tam právom končí (rozpis v hlavičke).
        # Bez polygónu rodiča sa vnútorná hranica od štátnej odlíšiť nedá,
        # tak sa chýbajúci sused nehlási vôbec – merať medzeru to nebráni.
        hlboko = False
        if rodic_m is not None:
            # `dist_to_polygon` by vnútri vrátilo 0, tak sa vzdialenosť
            # k štátnej hranici meria k OBRYSU rodiča.
            if not _inside(rodic_m, x, y):
                continue
            d_rodic = dist_to_boundary(rodic_m, x, y)
            if d_rodic < INSIDE_PARENT_M:
                continue
            hlboko = d_rodic >= 3 * INSIDE_PARENT_M
        bodov += 1
        naj_d, naj_k = math.inf, None
        for k, rings in sus_m.items():
            d = dist_to_polygon(rings, sus_bbox[k], x, y, limit=dosah)
            if d < naj_d:
                naj_d, naj_k = d, k
        # `limit` v `dist_to_polygon` je len predfilter cez bbox (bboxy krajov
        # sa prekrývajú, takže väčšine bodov naozaj vzdialenosť spočíta) –
        # strop sa musí uplatniť aj na hotové číslo.
        if naj_d > dosah:
            naj_k = None
        if naj_k is None:
            # Súrodenec nie je ani na `dosah`. Hlboko vnútri krajiny to
            # znamená, že tam kraj CHÝBA (alebo sa jeho `.poly` nestiahol);
            # bližšie k okraju je to hranica s cudzinou a mapa tam právom
            # končí – rozšírené polygóny z osm.fr sa na štátnej hranici líšia
            # o kilometre (rozpis pri `INSIDE_PARENT_M`).
            if hlboko:
                bez += 1
            continue
        if podla[naj_k][0] < naj_d:
            podla[naj_k][0] = naj_d
        podla[naj_k][1] += 1
        if naj_d > najhorsia:
            najhorsia, kde, kto = naj_d, (x / kx, y / M_PER_DEG_LAT), naj_k
    return {
        "limit_m": limit,
        "bodov": bodov,
        "najhorsia_m": max(najhorsia, 0.0) if bodov else 0.0,
        "kde": kde,
        "sused": kto,
        "zavrety": bodov == 0 or (bez == 0 and najhorsia < limit),
        "podla_suseda": {k: (max(v[0], 0.0), v[1]) for k, v in podla.items()
                         if v[1]},
        "bez_suseda": bez,
    }


def sprava(vysledok, buffer_m):
    """Výsledok merania → riadky pre log (prvý je zhrnutie)."""
    if not vysledok:
        return ["Šev so susedmi sa nedal zmerať – hranica chýba."]
    v = vysledok
    if not v["bodov"]:
        return ["Šev so susedmi: vnútorná hranica žiadna (celá je štátna) – "
                "niet na čo nadviazať."]
    km = v["najhorsia_m"] / 1000.0
    lim = v["limit_m"] / 1000.0
    riadky = []
    if v["zavrety"]:
        riadky.append(
            f"Šev so susedmi ZAVRETÝ ✓ – najhoršie miesto vnútornej hranice "
            f"má k najbližšiemu kraju {km:.2f} km a dve nafúknutia "
            f"(2 × {buffer_m:g} m) zavrú {lim:.2f} km.")
    else:
        kde = (f" pri {v['kde'][0]:.4f},{v['kde'][1]:.4f}" if v["kde"] else "")
        riadky.append(
            f"::warning::MEDZERA MEDZI MAPAMI: na vnútornej hranici je miesto"
            f"{kde}, kde je najbližší kraj ({v['sused']}) až {km:.2f} km "
            f"ďaleko, kým dve nafúknutia (2 × {buffer_m:g} m) zavrú len "
            f"{lim:.2f} km. Medzi stiahnutými mapami tam ostane pás bez mapy. "
            f"Zdvihni BORDER_BUFFER_M vo workers/plan/area.py aspoň na "
            f"{math.ceil(v['najhorsia_m'] / 2 / 100) * 100:.0f} m.")
    if v["bez_suseda"]:
        riadky.append(
            f"::warning::{v['bez_suseda']} bodov vnútornej hranice nemá "
            f"súrodenca ani na dohľad – v mape krajiny tam chýba celý kraj "
            f"(alebo sa jeho `.poly` nestiahol).")
    for k, (m, n) in sorted(v["podla_suseda"].items(),
                            key=lambda kv: -kv[1][0]):
        riadky.append(f"  {k:<18} najväčšia medzera {m / 1000:5.2f} km "
                      f"({n} bodov spoločnej hranice)")
    return riadky


def _cli():
    import argparse
    import importlib.util
    import os
    import sys

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--region", required=True, help="kľúč z data/regions.json")
    ap.add_argument("--regions", default="", help="cesta k regions.json")
    ap.add_argument("--step-m", type=float, default=STEP_M)
    args = ap.parse_args()

    # `region-poly.py` má v mene pomlčku, tak sa načíta cez `importlib` –
    # sťahovanie a parsovanie `.poly` je jeho práca a druhá kópia by sa
    # s ním raz rozišla (pravidlo 1). V behu to takto NECHODÍ: tam volá
    # `region-poly.py` tento súbor, nie naopak.
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "region_poly", os.path.join(here, "region-poly.py"))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)

    regs = rp.regions(args.regions or None)
    if args.region not in regs:
        print(f"Neznámy región '{args.region}'. Známe: {', '.join(sorted(regs))}",
              file=sys.stderr)
        return 1
    moje = rp.stiahni_rings(regs[args.region])
    if not moje:
        print("Polygón regiónu sa nepodarilo stiahnuť.", file=sys.stderr)
        return 1
    susedia, rodic = rp.susedne_rings(regs, args.region)
    for r in sprava(zmeraj_sev(moje, susedia, rodic, rp.BORDER_BUFFER_M,
                               step_m=args.step_m), rp.BORDER_BUFFER_M):
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
