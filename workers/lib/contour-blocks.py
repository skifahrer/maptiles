#!/usr/bin/env python3
"""`gdal_contour -p` po blokoch – aby to dobehlo aj nad veľkým územím.

Skladanie prstencov nie je lineárne v počte buniek: čím viac rozpracovaných
prstencov GDAL drží, tým drahšie je pridať segment. Namerané tempo po krokoch:
2 %/min do 17,5 %, potom 1,07, 0,36 a 0,26 – žiadny beh nad celým výrezom
nikdy nedobehol. V bloku sa prstence poskladajú rýchlo a čo je hotové, je na
disku, takže zrušený beh nezahodí prácu.

Platí sa za to švami: plocha cez hranicu bloku vypadne ako dva polygóny.
`zlep_svy()` ich spojí `ST_Union`-om nad tými, čo sa hranice naozaj dotýkajú.
Bez spatialite beh pokračuje s rozseknutými plochami a povie to – rozseknutá
skala je horšia mapa, nie žiadna mapa.

Používajú to obe cesty ku skalám (`rock-areas.py`, `rocks-shading/vector.py`);
boli to dve implementácie a rozišli sa. Čo je rozdielne, sa podáva parametrom.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from watch import dir_mb, hms, run_watched  # noqa: E402


# varovanie, ktoré GDAL vypíše nad každým blokom a je tu očakávané: z okna sa
# `<SRS>` vyhadzuje zámerne. Filtruje sa preto, že je to ten istý text, akým
# sa raz ohlásila skutočná chyba (skaly na zlých súradniciach, 0 dlaždíc) –
# varovanie, ktoré raz znamená „v poriadku" a raz „mapa je rozbitá", si človek
# odvykne čítať. Vypíše sa raz aj s dôvodom, ostatné sa spočítajú.
OCAKAVANE_VAROVANIE = "No SRS set on layer"


def _stderr_von(text, *, prve, kde):
    """Vypíše stderr z GDALu; očakávané varovanie zhrnie, zvyšok pustí celý.

    Vracia počet riadkov očakávaného varovania, nech ich vie volajúci spočítať.
    """
    ocakavane = 0
    for riadok in (text or "").splitlines():
        if not riadok.strip():
            continue
        if OCAKAVANE_VAROVANIE in riadok:
            ocakavane += 1
            if prve:
                print(f"    (GDAL: „{riadok.strip()}“ – tak to má byť, "
                      f"z okna bloku sa `<SRS>` vyhadzuje zámerne, aby "
                      f"súradnice ostali metrické. Ďalšie výskyty sa už "
                      f"nevypisujú, spočítajú sa.)", flush=True)
            continue
        print(f"    {kde}: {riadok.rstrip()}", flush=True)
    return ocakavane


def raster_size(vrt):
    """(šírka, výška) rastra v pixeloch."""
    try:
        info = json.loads(subprocess.run(["gdalinfo", "-json", vrt],
                                         check=True, capture_output=True,
                                         text=True).stdout)
        return info["size"][0], info["size"][1]
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return 0, 0


def plan(w_px, h_px, blok_px):
    """Ľavé horné rohy blokov. Blok je štvorec `blok_px`, posledný je menší."""
    return [(bx, by)
            for by in range(0, h_px, blok_px)
            for bx in range(0, w_px, blok_px)]


def oznac_svy(src, dst, na_hranici):
    """Prepíše GeoJSONSeq a útvarom na hranici bloku pridá `"sev":1`.

    Rozhoduje sa podľa toho, či sa súradnice útvaru dotýkajú okraja bloku –
    `na_hranici(geometry)` vráti True/False. Len tie idú potom do únie.
    """
    n = 0
    with open(src) as fi, open(dst, "w") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if na_hranici(obj.get("geometry") or {}):
                obj.setdefault("properties", {})["sev"] = 1
                n += 1
            fo.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return n


def _suradnice(geom):
    """Body geometrie – bez ohľadu na to, či je to Polygon alebo MultiPolygon."""
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        for ring in c or []:
            yield from ring
    elif t == "MultiPolygon":
        for poly in c or []:
            for ring in poly:
                yield from ring


def _plocha(geom):
    """Plocha geometrie v m² (shoelace nad metrickými súradnicami).

    Bez GDAL a bez závislostí – potrebuje sa len na porovnanie „koľko plochy
    išlo do únie a koľko z nej vyšlo". Diery sa odčítajú, takže to zhruba
    sedí aj na plochy s vnútornými prstencami.
    """
    def ring(body):
        s = 0.0
        for i in range(len(body) - 1):
            x0, y0 = body[i][0], body[i][1]
            x1, y1 = body[i + 1][0], body[i + 1][1]
            s += x0 * y1 - x1 * y0
        return abs(s) / 2.0

    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        prst = c or []
        return ring(prst[0]) - sum(ring(r) for r in prst[1:]) if prst else 0.0
    if t == "MultiPolygon":
        spolu = 0.0
        for poly in c or []:
            if poly:
                spolu += ring(poly[0]) - sum(ring(r) for r in poly[1:])
        return spolu
    return 0.0


def plocha_suboru(path):
    """Súčet plôch všetkých útvarov v GeoJSONSeq (m²)."""
    spolu = 0.0
    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    spolu += _plocha(json.loads(line).get("geometry") or {})
                except ValueError:
                    continue
    except FileNotFoundError:
        return 0.0
    return spolu


def _dotyka_sa(geom, x0, y0, x1, y1, tol):
    """Siaha geometria na okraj okna (v súradniciach rastra)?"""
    for x, y in _suradnice(geom):
        if (abs(x - x0) <= tol or abs(x - x1) <= tol
                or abs(y - y0) <= tol or abs(y - y1) <= tol):
            return True
    return False


def skontroluj_metricke(seq, minimum=1000.0, vzoriek=200):
    """Sú súradnice v metroch, alebo sa niekde stratili do stupňov?

    Nevidno to na ničom inom: beh dobehne a je zelený, len má každá plocha
    rádovo 1e-9 m² a filter najmenšej plochy ju vyhodí. Preto chyba, nie
    varovanie. Rozhoduje najväčšia súradnica zo vzorky, nie prvá.
    """
    najvacsia = 0.0
    videl = False
    try:
        with open(seq) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for x, y in _suradnice(obj.get("geometry") or {}):
                    videl = True
                    najvacsia = max(najvacsia, abs(x), abs(y))
                    vzoriek -= 1
                    if vzoriek <= 0:
                        break
                if vzoriek <= 0:
                    break
    except FileNotFoundError:
        return True
    if videl and najvacsia < minimum:
        # `RuntimeError`, nie `ValueError`: volajúci ju vypisuje ako
        # `::error::` s hláškou – tá je zrozumiteľná, traceback nie
        raise RuntimeError(
            f"súradnice vyzerajú ako stupne (najväčšia {najvacsia:.6f}), nie "
            f"ako metre – z okna bloku sa nevyhodil `<SRS>` a GDAL ich "
            f"prepočítal do WGS84. Plocha by potom vyšla rádovo 1e-9 m² "
            f"a filter najmenšej plochy by vyhodil VŠETKY skaly, pričom beh "
            f"by ostal zelený (behy 31245134321 a 31426542010).")
    return True


def po_blokoch(vrt, out_dir, urovne, atributy, blok_px, geo, *, budget_s=0):
    """Obrysy po blokoch do `out_dir/b*.geojsonl`. Vráti (priečinok, počet).

    `urovne`   – zoznam prahov pre `-fl`
    `atributy` – napr. `["-amin", "smin", "-amax", "smax"]`
    `geo`      – (ox, oy, res): ľavý horný roh a veľkosť bunky v metroch
    `budget_s` – strop času, vypnutý kým ho niekto nezapne. Hotové bloky
                 ostávajú na disku, takže `TimeoutError` nie je zahodená práca.
    """
    w_px, h_px = raster_size(vrt)
    if not w_px:
        raise RuntimeError(f"z {vrt} sa nedá prečítať rozmer rastra")
    ox, oy, res = geo
    bloky = plan(w_px, h_px, blok_px)
    os.makedirs(out_dir, exist_ok=True)
    hotovych = sum(1 for i in range(len(bloky))
                   if os.path.exists(os.path.join(out_dir, f"b{i:05d}.geojsonl")))
    print(f"  blok {blok_px}×{blok_px} px, {len(bloky)} blokov"
          + (f", {hotovych} už hotových z predošlého behu" if hotovych else ""),
          flush=True)

    t0 = time.time()
    spravene = 0
    bez_srs = 0
    for i, (bx, by) in enumerate(bloky):
        cesta = os.path.join(out_dir, f"b{i:05d}.geojsonl")
        if os.path.exists(cesta):
            continue
        bw, bh = min(blok_px, w_px - bx), min(blok_px, h_px - by)
        okno = os.path.join(out_dir, "okno.vrt")
        # `-of VRT` je len XML nad tým istým rastrom – výrez nestojí ani bajt
        subprocess.run(["gdal_translate", "-q", "-of", "VRT",
                        "-srcwin", str(bx), str(by), str(bw), str(bh),
                        vrt, okno], check=True)
        # z okna sa vyhodí <SRS>: ovládač GeoJSON prepočítava do WGS84 vždy,
        # keď zdroj vie, v čom je, takže by `gdal_contour` vypísal stupne
        # a každá skala by mala 1e-9 m². Stalo sa to dvakrát.
        with open(okno) as f:
            xml = f.read()
        with open(okno, "w") as f:
            f.write(re.sub(r"\s*<SRS[^>]*>.*?</SRS>", "", xml, flags=re.S))
        part = cesta + ".part"
        if os.path.exists(part):
            os.remove(part)
        # stderr sa chytá, nie potláča; pri páde sa vypíše všetko a až potom
        # sa chyba prehodí ďalej
        hotovo = subprocess.run(
            ["gdal_contour", "-p", "-q", "-fl", *urovne, *atributy,
             "-f", "GeoJSONSeq", "-nln", "band",
             # súradnice sú metrické, dve desatiny = centimeter
             "-lco", "COORDINATE_PRECISION=2", okno, part],
            capture_output=True, text=True)
        # `prve` sa viaže na prvý výskyt, nie na prvý blok
        bez_srs += _stderr_von(hotovo.stderr, prve=(bez_srs == 0),
                               kde="gdal_contour")
        if hotovo.stdout.strip():
            print(f"    gdal_contour: {hotovo.stdout.strip()}", flush=True)
        hotovo.check_returncode()
        # strážca: prvý blok sa pozrie, či sú súradnice naozaj metrické
        if spravene == 0:
            skontroluj_metricke(part)
        # súradnice sú v metroch výrezu; hranica bloku je jeho okraj
        x0, y0 = ox + bx * res, oy - by * res
        x1, y1 = x0 + bw * res, y0 - bh * res
        oznac_svy(part, cesta, lambda g: _dotyka_sa(g, x0, y1, x1, y0, res))
        os.remove(part)
        spravene += 1
        el = time.time() - t0
        # postup po blokoch je jediné, čo o tej dlhej fáze niečo povie
        if spravene and (i % max(1, len(bloky) // 50) == 0 or i == len(bloky) - 1):
            zvysok = el / spravene * (len(bloky) - i - 1)
            print(f"  … obrysy: blok {i + 1}/{len(bloky)}, beží {hms(el)}, "
                  f"zostáva ~{hms(zvysok)}, na disku {dir_mb(out_dir):.0f} MB",
                  flush=True)
        # rozpočet až po zapísanom bloku – ďalší beh nadviaže presne tu
        if budget_s and el > budget_s:
            raise TimeoutError(f"obrysy: {i + 1}/{len(bloky)} blokov")
    # koľko blokov varovanie vypísalo, sa povie: keď ho zrazu nemá jeden
    # z 364, je to rozdiel oproti zvyšku a stojí za to, aby bol vidieť
    if bez_srs:
        print(f"  (GDAL hlásil „{OCAKAVANE_VAROVANIE}“ pri {bez_srs} "
              f"z {spravene} počítaných blokov – očakávané)", flush=True)
    return out_dir, len(bloky)


def zlep_svy(seq, tmp, *, klucovy_atribut="smin", heartbeat=30,
             max_s=0, label="švy"):
    """Spojí plochy rozseknuté hranicou bloku. Vráti cestu k výsledku.

    Unionuje len útvary s `sev=1`, po triedach – inak by sa stena zlepila
    so svahom.

    Únia sa môže nepodariť a nepovie to návratovým kódom: `ST_Union` padá na
    neplatných geometriách, ogr2ogr pritom skončí úspechom a napíše prázdny
    súbor (raz tak z Vysokých Tatier ostalo 44 plôch so súhrnnou plochou
    0,00 km²). Preto `ST_MakeValid` pred úniou, prepočet plochy po nej
    a návrat pôvodných útvarov, keď vyjde prázdna.

    A výstupu sa nesmie dať SRS – tá istá pasca ako pri okne bloku, len o krok
    neskôr: `-a_srs` nad GeoJSONSeq metre neoznačí, ale zmení na stupne.
    """
    svy = os.path.join(tmp, "svy.geojsonl")
    zvysok = os.path.join(tmp, "bez-svov.geojsonl")
    n_sev = n_ok = 0
    with open(seq) as fi, open(svy, "w") as fs, open(zvysok, "w") as fz:
        for line in fi:
            if not line.strip():
                continue
            if '"sev":1' in line.replace(" ", ""):
                fs.write(line)
                n_sev += 1
            else:
                fz.write(line)
                n_ok += 1
    if not n_sev:
        print("  švy: žiadna plocha nesiaha na hranicu bloku", flush=True)
        return zvysok

    print(f"  švy: {n_sev} plôch na hranici bloku, {n_ok} mimo – "
          f"zlepujem tie prvé", flush=True)
    zlep = os.path.join(tmp, "zlepene.geojsonl")
    # žiadne `-a_srs` ani `-t_srs` (viď docstring). `ST_Union` je rovinná
    # operácia a SRID ju nezaujíma. `COORDINATE_PRECISION=2`: centimeter stačí.
    chyba = None
    try:
        run_watched(["ogr2ogr", "-f", "GeoJSONSeq", zlep, svy,
                     "-lco", "COORDINATE_PRECISION=2",
                     "-dialect", "SQLITE", "-explodecollections",
                     "-sql", f"SELECT {klucovy_atribut}, "
                             f"ST_Union(ST_MakeValid(geometry)) AS geometry "
                             f"FROM svy GROUP BY {klucovy_atribut}"],
                    label, tmp=zlep, every=heartbeat, max_s=max_s)
    except Exception as exc:
        chyba = f"{type(exc).__name__}"

    # úspech ogr2ogr nestačí a nerozhoduje ani počet útvarov (zlepiť 22 kúskov
    # do jedného je zmysel únie) – rozhoduje plocha
    n_zlep = 0
    if not chyba and os.path.exists(zlep):
        with open(zlep) as f:
            n_zlep = sum(1 for line in f if line.strip())
    # jednotky sa kontrolujú skôr než plocha: inak by sa prepočet do stupňov
    # ohlásil ako „stratená plocha" a poslal hľadať chybu do GEOSu
    if n_zlep:
        try:
            skontroluj_metricke(zlep)
        except RuntimeError as exc:
            chyba = ("únia vyšla v STUPŇOCH, nie v metroch – výstup dostal "
                     "SRS (`-a_srs`/`-t_srs`) a GeoJSON ovládač podľa neho "
                     f"súradnice prepočítal do WGS84; {exc}")
    plocha_pred = plocha_suboru(svy)
    plocha_po = plocha_suboru(zlep) if n_zlep and not chyba else 0.0
    stratene = (plocha_pred > 0 and plocha_po < plocha_pred * 0.5)
    if chyba or not n_zlep or stratene:
        preco = (f"({chyba})" if chyba else
                 "(únia skončila prázdna – hľadaj v logu `TopologyException`)"
                 if not n_zlep else
                 f"(z {plocha_pred/1e6:.2f} km² ostalo {plocha_po/1e6:.2f} km²)")
        # dôvod v tej hláške už dvakrát ukazoval vedľa („Chýba spatialite?",
        # potom natvrdo `TopologyException`), preto sa berie z toho, čo sa
        # naozaj zistilo, a nedopisuje sa k nemu domnienka
        print(f"::warning::Zlepenie švov sa nedá použiť {preco}"
              + f". Vraciam {n_sev} pôvodných plôch nezlepených: na hraniciach "
              f"blokov ({label}) budú rozseknuté a diery na nich otvorené, ale "
              f"BUDÚ – v mape je to vidieť ako priamu hranu v obryse. Keď je "
              f"dôvodom prázdna únia, hľadaj v logu vyššie `TopologyException` "
              f"z GEOS nad obrysom z gdal_contour; spatialite v tom nie je, "
              f"ten je nainštalovaný.", flush=True)
        return seq

    print(f"  švy: {n_sev} plôch zlepených na {n_zlep} "
          f"({plocha_pred/1e6:.2f} → {plocha_po/1e6:.2f} km²)", flush=True)
    spolu = os.path.join(tmp, "zlepene-spolu.geojsonl")
    with open(spolu, "w") as fo:
        for src in (zvysok, zlep):
            if os.path.exists(src):
                with open(src) as fi:
                    for line in fi:
                        if line.strip():
                            fo.write(line)
    return spolu


def zlej(out_dir, dst):
    """Zlepí bloky do jedného GeoJSONSeq (v poradí, nech je beh opakovateľný)."""
    n = 0
    with open(dst, "w") as fo:
        for meno in sorted(os.listdir(out_dir)):
            if not meno.endswith(".geojsonl"):
                continue
            with open(os.path.join(out_dir, meno)) as fi:
                for line in fi:
                    if line.strip():
                        fo.write(line)
                        n += 1
    return n
