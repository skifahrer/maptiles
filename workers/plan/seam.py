#!/usr/bin/env python3
"""Drží mapa susedného kraja tam, kde tá naša končí – a nelezie do neho?

Kraje sa stavajú po jednom a každý sa oreže vlastnou hranicou. Či na seba dve
hotové mapy nadväzujú, sa nikde nemeralo – a keby prestali, nespadne nič: obe
mapy budú zelené a medzi nimi pás bez mapy.

Pre každý bod vnútornej hranice sa meria oboje:

    medzera(p)  = ako ďaleko je najbližší súrodenec (0 = dotýkame sa)
    prekryv(p)  = ako hlboko je `p` vnútri súrodenca (0 = nelezieme doňho)

a porovnáva s `limit_m = 2 × BORDER_BUFFER_M + TOLERANCIA_M`. `BORDER_BUFFER_M`
je dnes 0, takže limitom je tolerancia dvoch zjednodušení hranice.

„Vnútorné p" je bod aspoň `INSIDE_PARENT_M` vnútri polygónu rodiča – na štátnej
hranici žiadny súrodenec nie je a mapa tam právom končí.

Hranice susedov musia byť z toho istého zdroja ako naša (`region-poly.py`);
merať presnú hranicu proti rozšírenému `.poly` z osm.fr by ukázalo prekryv
2–4 km, ktorý nikde nie je.

Bez shapely zámerne: je to vzdialenosť bodu k lomenej čiare a test „bod
v polygóne". Počíta sa v rovine (lokálne metre okolo stredu regiónu).

I/O nie je tu – hranice zháňa `region-poly.py` a sem ich podáva ako prstence.

Použitie:
    from seam import zmeraj_sev
    python3 workers/plan/seam.py --region=trnavsky
"""
import math

from boundary import OREZ_TOLERANCIA_M   # susedný súbor, bez pomlčky v mene

M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# ako často sa naša hranica ochutnáva; hustejšie nemá zmysel – vzdialenosť sa
# počíta k úsečkám susedovho obrysu, nie k jeho bodom
STEP_M = 250.0

# koľko musí byť bod vnútri rodiča, aby sa bral ako vnútorná hranica.
# 5 km preto, že aj presná hranica kraja splýva so štátnou na desiatkach
# kilometrov, a pri náhradných `.poly` sa dva nezávisle rozšírené polygóny
# líšia o kilometre. Vnútornú hranicu to nezakryje (kraje sú široké desiatky km).
INSIDE_PARENT_M = 5000.0

# ako ďaleko ešte môže byť súrodenec, aby to bol spoločný šev. Pevných 5 km,
# nie násobok nafúknutia: to je dnes 0 a vyšla by nula. Dosah je vlastnosť
# geografie, nie nafúknutia – a je to zároveň predfilter, ktorý drží meranie
# v sekundách.
DOSAH_M = 5000.0

# koľko sa ešte toleruje na medzere aj na prekryve: dve zjednodušenia hranice
# (`boundary.OREZ_TOLERANCIA_M` na každej strane švu). Berie sa odtiaľ, kde sa
# zjednodušuje – dve pravdy o jednej tolerancii by sa rozišli.
TOLERANCIA_M = 2 * OREZ_TOLERANCIA_M


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
    """Zmeria, či na našu mapu nadväzujú mapy susedov – a či do nich nelezie.

    `moje`, `rodic` a hodnoty v `susedia` sú prstence v stupňoch, všetky
    z rovnakého zdroja. `buffer_m` sa zaráta do limitu číslom, nie geometriou.

    Vracia `limit_m`, `bodov`, `medzera_m`, `prekryv_m`, `kde`, `sused`,
    `kde_prekryv`, `sused_prekryv`, `sedi`, `podla_suseda` a `bez_suseda`
    (body hlboko vnútri krajiny bez súrodenca – to už nie je hranica
    s cudzinou, ale chýbajúci kraj).
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

    limit = 2.0 * buffer_m + TOLERANCIA_M
    # hľadá sa najhoršie miesto, tak sa meria aj kus za limit – inak by sa
    # nedalo povedať „chýbalo 300 m" ani „chýbalo 12 km"
    dosah = DOSAH_M

    naj_medzera, kde, kto = -1.0, None, None
    naj_prekryv, kde_p, kto_p = -1.0, None, None
    bodov, bez = 0, 0
    podla = {k: [-1.0, -1.0, 0] for k in sus_m}
    for x, y in sample_boundary(moje_m, step_m):
        # len vnútorná hranica; bez polygónu rodiča sa od štátnej odlíšiť nedá,
        # tak sa chýbajúci sused vtedy nehlási vôbec
        hlboko = False
        if rodic_m is not None:
            # `dist_to_polygon` by vnútri vrátilo 0, tak sa meria k obrysu
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
        # `limit` v `dist_to_polygon` je len predfilter cez bbox – strop sa
        # musí uplatniť aj na hotové číslo
        if naj_d > dosah:
            naj_k = None
        if naj_k is None:
            # súrodenec nie je ani na `DOSAH_M`: hlboko vnútri krajiny to
            # znamená chýbajúci kraj, bližšie k okraju hranicu s cudzinou
            if hlboko:
                bez += 1
            continue
        # prekryv: `dist_to_polygon` vráti vnútri suseda 0, tak sa hĺbka domeria
        # k jeho obrysu – a len pre toho najbližšieho
        prekryv = (dist_to_boundary(sus_m[naj_k], x, y)
                   if naj_d == 0.0 and _inside(sus_m[naj_k], x, y) else 0.0)
        if podla[naj_k][0] < naj_d:
            podla[naj_k][0] = naj_d
        if podla[naj_k][1] < prekryv:
            podla[naj_k][1] = prekryv
        podla[naj_k][2] += 1
        if naj_d > naj_medzera:
            naj_medzera, kde, kto = naj_d, (x / kx, y / M_PER_DEG_LAT), naj_k
        if prekryv > naj_prekryv:
            naj_prekryv, kde_p, kto_p = (prekryv,
                                         (x / kx, y / M_PER_DEG_LAT), naj_k)
    medzera = max(naj_medzera, 0.0) if bodov else 0.0
    prekryv = max(naj_prekryv, 0.0) if bodov else 0.0
    return {
        "limit_m": limit,
        "bodov": bodov,
        "medzera_m": medzera,
        "prekryv_m": prekryv,
        "kde": kde,
        "sused": kto,
        "kde_prekryv": kde_p,
        "sused_prekryv": kto_p,
        "sedi": bodov == 0 or (bez == 0 and medzera <= limit
                               and prekryv <= limit),
        "podla_suseda": {k: (max(v[0], 0.0), max(v[1], 0.0), v[2])
                         for k, v in podla.items() if v[2]},
        "bez_suseda": bez,
    }


def zhrnutie(vysledok):
    """Jedna veta do súhrnu behu: sedí šev, a s akými číslami?"""
    if not vysledok or not vysledok["bodov"]:
        return "vnútorná hranica žiadna (celá je štátna) – niet na čo nadviazať"
    v = vysledok
    cisla = (f"medzera {v['medzera_m']:.0f} m, prekryv {v['prekryv_m']:.0f} m, "
             f"tolerancia {v['limit_m']:.0f} m")
    if v["sedi"]:
        return f"sedí ✓ ({cisla})"
    if v["bez_suseda"]:
        return f"**chýba celý sused** ({cisla})"
    if v["medzera_m"] > v["limit_m"]:
        return (f"**MEDZERA {v['medzera_m']:.0f} m** pri susedovi "
                f"`{v['sused']}` ({cisla})")
    return (f"**PREKRYV {v['prekryv_m']:.0f} m** do suseda "
            f"`{v['sused_prekryv']}` ({cisla})")


def sprava(vysledok, buffer_m):
    """Výsledok merania → riadky pre log (prvý je zhrnutie)."""
    if not vysledok:
        return ["Šev so susedmi sa nedal zmerať – hranica chýba."]
    v = vysledok
    if not v["bodov"]:
        return ["Šev so susedmi: vnútorná hranica žiadna (celá je štátna) – "
                "niet na čo nadviazať."]
    lim = v["limit_m"]
    riadky = []
    if v["sedi"]:
        riadky.append(
            f"Šev so susedmi SEDÍ ✓ – najväčšia medzera k susednému kraju je "
            f"{v['medzera_m']:.0f} m, najhlbšie zaliezanie doňho "
            f"{v['prekryv_m']:.0f} m; tolerancia je {lim:.0f} m "
            f"(2 × nafúknutie {buffer_m:g} m + 2 × zjednodušenie hranice "
            f"{OREZ_TOLERANCIA_M:g} m).")
    if v["medzera_m"] > lim:
        kde = (f" pri {v['kde'][0]:.4f},{v['kde'][1]:.4f}" if v["kde"] else "")
        riadky.append(
            f"::warning::MEDZERA MEDZI MAPAMI: na vnútornej hranici je miesto"
            f"{kde}, kde je najbližší kraj ({v['sused']}) až "
            f"{v['medzera_m']:.0f} m ďaleko, kým sa toleruje {lim:.0f} m. "
            f"Medzi stiahnutými mapami tam ostane pás bez mapy. Buď sa "
            f"hranice tých dvoch krajov v OSM naozaj rozchádzajú, alebo je "
            f"jedna z nich z náhradného `.poly` – pozri `zdroj` vyššie.")
    if v["prekryv_m"] > lim:
        kde = (f" pri {v['kde_prekryv'][0]:.4f},{v['kde_prekryv'][1]:.4f}"
               if v["kde_prekryv"] else "")
        riadky.append(
            f"::warning::MAPA PRESAHUJE DO SUSEDA: hranica ide{kde} až "
            f"{v['prekryv_m']:.0f} m vnútri kraja {v['sused_prekryv']}, kým "
            f"sa toleruje {lim:.0f} m. Kus susedného kraja sa tak vezie "
            f"v tejto mape aj vo vrstvách z výškového modelu – presne to, "
            f"čomu má presná hranica zabrániť.")
    if v["bez_suseda"]:
        riadky.append(
            f"::warning::{v['bez_suseda']} bodov vnútornej hranice nemá "
            f"súrodenca ani na dohľad – v mape krajiny tam chýba celý kraj "
            f"(alebo sa jeho hranica nezískala).")
    for k, (m, p, n) in sorted(v["podla_suseda"].items(),
                               key=lambda kv: -kv[1][0]):
        riadky.append(f"  {k:<18} medzera {m:6.0f} m, prekryv {p:6.0f} m "
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
    ap.add_argument("--from-pbf", default="",
                    help="PBF s presnými hranicami (bez neho sa berú "
                         "náhradné `.poly` z osm.fr a čísla o prekryve "
                         "hovoria o NICH, nie o hraniciach krajov)")
    args = ap.parse_args()

    # `region-poly.py` má v mene pomlčku, tak sa načíta cez `importlib`.
    # V behu to chodí opačne: `region-poly.py` volá tento súbor.
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
    import boundary as b
    hranice = b.hranice_z_pbf(args.from_pbf) if args.from_pbf else []
    moje = (rp.presne_rings(regs[args.region], hranice, args.region)
            or rp.stiahni_rings(regs[args.region]))
    if not moje:
        print("Hranicu regiónu sa nepodarilo získať.", file=sys.stderr)
        return 1
    susedia, rodic, chyba = rp.susedne_rings(regs, args.region, hranice)
    if chyba:
        print(f"Hranica susedov {', '.join(sorted(chyba))} nie je z toho "
              f"istého zdroja – s nimi sa nemeria.")
    for r in sprava(zmeraj_sev(moje, susedia, rodic, rp.BORDER_BUFFER_M,
                               step_m=args.step_m), rp.BORDER_BUFFER_M):
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
