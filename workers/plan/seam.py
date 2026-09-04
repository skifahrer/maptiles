#!/usr/bin/env python3
"""
Drží mapa susedného kraja tam, kde tá naša končí – a nelezie do neho?

PREČO TENTO SÚBOR VZNIKOL. Kraje sa stavajú po jednom a každý sa oreže vlastnou
hranicou (`workers/plan/region-poly.py`). Či na seba dve HOTOVÉ mapy nadväzujú,
sa doteraz nikde nemeralo – vedelo sa len to, že sa polygón pred orezom nafúkne
o `BORDER_BUFFER_M` a *predpokladalo* sa, že to stačí. Keď to raz stačiť
prestane, nespadne nič: obe mapy budú zelené a medzi nimi bude pás bez mapy,
ktorý uvidí až človek s telefónom v teréne. Presne to je pravidlo 8 – tichý
omyl. Toto je meranie, ktoré ten predpoklad mení na číslo v logu každého behu.

ČO SA MERIA – TERAZ OBE STRANY. Odkedy sa hranica berie PRESNE z OSM relácie
(`workers/plan/boundary.py`) a nenafukuje sa, nestačí sa pýtať „nie je medzi
mapami diera?". Rovnako dôležité je „nelezie naša mapa do suseda?" – kvôli
tomu sa hranica menila. Pre každý bod vnútornej hranice sa preto meria oboje:

    medzera(p)  = ako ďaleko je od `p` najbližší súrodenec (0 = dotýkame sa)
    prekryv(p)  = ako hlboko je `p` vnútri súrodenca (0 = nelezieme doňho)

a obe sa porovnávajú s `limit_m`:

    limit_m = 2 × BORDER_BUFFER_M + TOLERANCIA_M

`BORDER_BUFFER_M` je dnes 0 (režeme presne), takže limitom je samotná
TOLERANCIA – dve zjednodušenia hranice (`boundary.OREZ_TOLERANCIA_M` na každej
strane). Susedné kraje zdieľajú v OSM tie isté cesty hranice, ale každý si ich
zjednodušuje vo svojom prstenci, takže sa výsledky môžu o toľko rozísť. Čo je
nad tým, už nie je zaokrúhlenie, ale chyba – a povie to `::warning::`.

„Vnútorné p" znamená bod, ktorý leží aspoň `INSIDE_PARENT_M` vnútri polygónu
RODIČA (celej krajiny). Bez tejto podmienky by kontrola kričala na každom
kilometri štátnej hranice – tam žiadny súrodenec nie je a byť nemá; mapa tam
končí právom.

HRANICE SUSEDOV MUSIA BYŤ Z TOHO ISTÉHO ZDROJA ako tá naša – zariaďuje to
`region-poly.py::susedne_rings`. Merať presnú hranicu proti rozšírenému `.poly`
z osm.fr by ukázalo prekryv 2 – 4 km, ktorý nikde nie je.

Namerané pred prechodom na presnú hranicu (osem krajov SR, `.poly` z osm.fr,
3. 9. 2026): susedné kraje sa v tých polygónoch PREKRÝVALI o 2 – 4 km, lebo
osm.fr svoje polygóny okolo hranice sám rozširuje – čiže „medzera" vychádzala
0 m a šev sa tváril ako v poriadku, hoci mapa kraja siahala kilometre do
susedného. Práve to je dôvod, prečo sa odteraz meria aj prekryv.

BEZ SHAPELY, zámerne – tá istá úvaha ako vo `workers/lib/region-mask.py`:
ide o vzdialenosť bodu k lomenej čiare a o test „je bod v polygóne", čo je
dvadsať riadkov, kým shapely je závislosť navyše v jobe, ktorý dnes vystačí
s čistým Pythonom. Počíta sa v ROVINE (lokálne metre okolo stredu regiónu):
kraj má nižšie než 200 km, takže skreslenie je hlboko pod hrúbkou hranice.

I/O NIE JE TU. Súbor pozná len geometriu; hranice zháňa `region-poly.py` (ten
jediný vie, odkiaľ sa berú – pravidlo 1) a sem ich podáva ako hotové prstence.
Preto je meno bez pomlčky: `region-poly.py` si ho normálne `import`-ne.

Použitie ako modul:
    from seam import zmeraj_sev
    sprava = zmeraj_sev(moje_prstence, {"zilinsky": prstence, …},
                        rodic_prstence, buffer_m=0)

Alebo z príkazového riadka (kontrola a debug, hranice si zháňa cez
`region-poly.py` – bez PBF teda z náhradných `.poly` osm.fr):
    python3 workers/plan/seam.py --region=trnavsky
"""
import math

from boundary import OREZ_TOLERANCIA_M   # susedný súbor, bez pomlčky v mene

M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

# Ako často sa naša hranica ochutnáva. Na kraji s 500 km obvodu je 250 m
# 2 000 bodov – teda sekundy, nie minúty. Hustejšie to nemá zmysel: meraný
# jav (rozdiel dvoch zjednodušení hranice) je desiatky metrov a vzdialenosť
# sa počíta k ÚSEČKÁM susedovho obrysu, nie k jeho bodom, takže krok vzorky
# presnosť merania neurčuje – určuje len to, či sa najhoršie miesto trafí.
STEP_M = 250.0

# Koľko musí byť bod vnútri rodiča, aby sa bral ako VNÚTORNÁ hranica (a teda
# aby sa preň čakal súrodenec).
#
# PREČO AŽ 5 km. Je to prah z čias, keď sa hranice brali z osm.fr, a ostáva:
# aj presná hranica kraja splýva so štátnou na desiatkach kilometrov a bod na
# nej nemá čakať súrodenca. Pri náhradných `.poly` (osm.fr) je navyše nutný –
# tie sú okolo hranice ROZŠÍRENÉ a každý inak:
# ten Slovenska siaha na Morave o kus ďalej než ten Bratislavského kraja.
# Namerané: bod 16,9510 48,2620 leží PRESNE na hranici Bratislavského kraja
# (teda na štátnej hranici s Rakúskom) a od obrysu Slovenska je 2,04 km – pri
# prahu 2 km ho kontrola vzala ako vnútornú hranicu a hlásila „medzeru 28 km"
# k Trnavskému kraju, ktorý tam nemá čo robiť. Prah musí byť nad tým, o koľko
# sa dva nezávisle rozšírené polygóny líšia; 5 km na to stačí a vnútornú
# hranicu to nezakryje (kraje sú široké desiatky km).
INSIDE_PARENT_M = 5000.0

# Ako ďaleko ešte môže byť súrodenec, aby sa bod bral ako SPOLOČNÁ hranica
# s ním. Bod, pri ktorom nie je súrodenec ani takto ďaleko, je hranica
# s cudzinou (alebo tam naozaj chýba celý kraj, čo sa hlási zvlášť); počítať
# to ako „medzeru so susedom" by znamenalo hlásiť štátnu hranicu ako chybu
# švu.
#
# PEVNÝCH 5 km, A NIE NÁSOBOK NAFÚKNUTIA. Kým sa nafukovalo o 2 500 m, bol
# dosah `4 × buffer` = 10 km; odkedy je nafúknutie 0 (režeme presne), by
# z toho vyšla nula a nesusedil by so susedom ani bod, ktorý na jeho hranici
# priamo leží. Dosah je vlastnosť GEOGRAFIE (ako ďaleko od seba môžu byť dve
# hranice, aby to ešte bol ten istý šev), nie nafúknutia. Je to zároveň
# predfilter, ktorý meranie drží v sekundách: bod porovnáva len so susedmi,
# ktorých bbox je bližšie.
DOSAH_M = 5000.0

# Koľko sa ešte toleruje – na medzere aj na prekryve. Sú to DVE zjednodušenia
# hranice (`boundary.OREZ_TOLERANCIA_M` na každej strane švu): susedia
# zdieľajú v OSM tie isté cesty hranice, ale každý si ich zjednodušuje vo
# svojom prstenci, takže sa spoločná čiara môže o toľko rozísť. Berie sa
# odtiaľ, kde sa zjednodušuje, a nie druhým číslom tu – dve pravdy o jednej
# tolerancii by sa raz rozišli (pravidlo 1).
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

    `moje`, `rodic` a hodnoty v `susedia` sú prstence v stupňoch, VŠETKY
    Z ROVNAKÉHO ZDROJA (rozpis v hlavičke). `buffer_m` je nafúknutie, ktoré si
    na svojej strane pridáva každý kraj sám tým istým skriptom – dnes 0, lebo
    sa reže presne; zaráta sa do limitu číslom, nie geometriou.

    Vracia slovník:
        limit_m     – čo sa ešte toleruje (2 × buffer_m + TOLERANCIA_M)
        bodov       – koľko bodov vnútornej hranice sa meralo
        medzera_m   – najväčšia nameraná MEDZERA k najbližšiemu súrodencovi
        prekryv_m   – najhlbšie zaliezanie DO súrodenca
        kde         – (lon, lat) najhoršieho miesta (podľa medzery), či None
        sused       – ktorý súrodenec je tam najbližšie
        kde_prekryv, sused_prekryv – to isté pre prekryv
        sedi        – True, keď je medzera aj prekryv v limite
        podla_suseda – {kľúč: (najväčšia medzera, najväčší prekryv, bodov)}
        bez_suseda  – koľko bodov HLBOKO vnútri krajiny nemá súrodenca ani
                      na dosah (`DOSAH_M`); to už nie je hranica s cudzinou,
                      ale chýbajúci kraj
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
    # Hľadá sa najhoršie miesto, tak sa musí merať aj kus ZA limit – inak by
    # sa nedalo povedať „chýbalo 300 m" ani „chýbalo 12 km". Za `DOSAH_M`
    # sa už žiadny súrodenec nehľadá: taký bod je hranica s cudzinou.
    dosah = DOSAH_M

    naj_medzera, kde, kto = -1.0, None, None
    naj_prekryv, kde_p, kto_p = -1.0, None, None
    bodov, bez = 0, 0
    podla = {k: [-1.0, -1.0, 0] for k in sus_m}
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
            # Súrodenec nie je ani na `DOSAH_M`. Hlboko vnútri krajiny to
            # znamená, že tam kraj CHÝBA (alebo sa jeho hranica nezískala);
            # bližšie k okraju je to hranica s cudzinou a mapa tam právom
            # končí.
            if hlboko:
                bez += 1
            continue
        # PREKRYV. `dist_to_polygon` vráti vnútri suseda 0, takže sa hĺbka
        # musí domerať k jeho OBRYSU – a len pre toho najbližšieho: bod, ktorý
        # je vnútri dvoch susedov naraz, je taká chyba hraníc, že na ňu stačí
        # tá väčšia z dvoch hodnôt, a lacnejšie je to o rád.
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

    # `region-poly.py` má v mene pomlčku, tak sa načíta cez `importlib` –
    # zháňanie hraníc je jeho práca a druhá kópia by sa s ním raz rozišla
    # (pravidlo 1). V behu to takto NECHODÍ: tam volá
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
