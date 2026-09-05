#!/usr/bin/env python3
"""Skaly z tieňovania, 3/3: z rastra obrysy, švy a filter.

Od hotového rastra tmavosti po vrstvu `rock` v GeoPackage: prahy pásiem,
filter podľa plochy, zjednodušenie a vyhladenie. Samotné obrysy po blokoch,
značenie švov a ich zlepenie sú spoločné so skalami zo sklonu a robí ich
`workers/lib/contour-blocks.py`.

Rez je na tej istej hranici, na ktorej sa `shading-rocks.yml` delí na job
`vektor` a `skaly`. Spúšťa sa ako modul, nie z príkazovej riadky.
"""
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# cez toto sa siaha na skripty iného jobu; vlastné idú cez `_HERE`
_WORKERS = os.path.dirname(_HERE)


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# mriežka, `run()` a rýchlosť contouru sa berú z tej spodnej vrstvy;
# `CONTOUR_CELLS_PER_S` je tam preto, že podľa neho vyberá `probe_zoom` zoom
tiles = load("shading_tiles", "tiles.py")
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
run = tiles.run
CONTOUR_CELLS_PER_S = tiles.CONTOUR_CELLS_PER_S

# `watch.py` je spoločný pre obe cesty ku skalám, tak leží vo `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb  # noqa: E402

# obrysy po blokoch, značenie švov a ich zlepenie sú to isté, čo robia skaly
# zo sklonu, preto ležia vo `workers/lib/`. Boli tu druhýkrát vlastným kódom
# a tie dve kópie sa už stihli rozísť.
bloky_mod = load("contour_blocks", os.path.join(
    os.path.dirname(_HERE), "lib", "contour-blocks.py"))


def bbox_km2(bbox):
    """Plocha bboxu v km² – len na kontrolu, či výsledok nepokrýva všetko."""
    w, s_, e, n = bbox
    return ((e - w) * 111.32 * math.cos(math.radians((s_ + n) / 2))
            * (n - s_) * 110.54)


def ring_area(ring):
    """Plocha prstenca (shoelace) v jednotkách súradníc, so znamienkom."""
    s = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def filter_stream(src, dst, min_area, min_hole, cliff_level, merc_factor,
                  every=30, zapln_diery=False, min_level=0.5):
    """Prúdový filter nad GeoJSONSeq: odrobinky preč, dierky preč, triedy von.

    Vstup je už rozbitý na samostatné plochy, takže jeden riadok = jedna skala.
    Plocha sa počíta zo súradníc v EPSG:3857 a násobí `merc_factor`
    (= cos²(šírka)) – bez toho by pri 49° vyšla 2,3× väčšia.

    Diery ostávajú: sú to medzery medzi vláknami siete žliabkov a práve ony sú
    tá štruktúra. Zahadzujú sa podľa vlastnej plochy, nie podľa plochy celku.
    `zapln_diery` ich zaplní – voľba, nie predvolené správanie.
    """
    n_in = n_out = 0
    n_pozadie = 0
    holes_kept = holes_drop = 0
    total = 0.0
    n_cliff = 0
    biggest = 0.0
    # píše sa priebežne do `.part` a premenuje až hotové; riadok = jedna skala,
    # takže výstup rastie plynulo a je pri ňom počuť
    part = dst + ".part"
    t0 = time.time()
    last = t0
    with open(src) as fi, open(part, "w") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            feat = json.loads(line)
            g = feat.get("geometry") or {}
            t = g.get("type")
            if t == "Polygon":
                parts = [g["coordinates"]]
            elif t == "MultiPolygon":
                parts = g["coordinates"]
            else:
                continue
            dmin = feat.get("properties", {}).get("dmin")
            try:
                dmin = float(dmin)
            except (TypeError, ValueError):
                dmin = 0.0
            # pozadie preč: `gdal_contour -p` nevyrobí len pásmo skál, ale
            # všetky – vrátane toho pod prahom, čo je jeden obrovský polygón
            # na blok. Keď prejde ďalej, prekryje mapu súvislou plochou.
            # Skaly z DEM to majú vo `WHERE smin >= prah`; tu ten filter chýbal.
            if dmin < min_level:
                n_pozadie += 1
                continue
            cls = "cliff" if dmin >= cliff_level else "steep"

            for poly in parts:
                if not poly:
                    continue
                n_in += 1
                area = abs(ring_area(poly[0])) * merc_factor
                rings = [poly[0]]
                if zapln_diery:
                    holes_drop += len(poly) - 1
                else:
                    for hole in poly[1:]:
                        a = abs(ring_area(hole)) * merc_factor
                        if a >= min_hole:
                            rings.append(hole)
                            area -= a
                            holes_kept += 1
                        else:
                            holes_drop += 1
                if area < min_area:
                    continue
                fo.write(json.dumps({
                    "type": "Feature",
                    # `ceil`, nie `round`: dolná hranica pásma je 0,5
                    # a zaokrúhlenie by z nej spravilo nulu („vôbec nie tmavé")
                    "properties": {"class": cls, "dark": int(math.ceil(dmin)),
                                   "area": int(round(area))},
                    "geometry": {"type": "Polygon", "coordinates": rings},
                }, separators=(",", ":")) + "\n")
                n_out += 1
                now = time.time()
                if every and now - last >= every:
                    last = now
                    fo.flush()
                    print(f"  … filter plôch: {n_in} prečítaných, "
                          f"{n_out} ponechaných, beží {hms(now - t0)}",
                          flush=True)
                total += area
                biggest = max(biggest, area)
                n_cliff += (cls == "cliff")
    os.replace(part, dst)
    return {"n_in": n_in, "n": n_out, "cliff": n_cliff, "total_m2": total,
            "pozadie": n_pozadie,
            "max_m2": biggest, "holes": holes_kept, "holes_dropped": holes_drop}


# čísla o sťahovaní vedľa cache, nie v `_rozrobene`: sú o dlaždiciach, nie
# o prahoch, takže sa nesmú stratiť pri zmene prahu ani pri `fresh=1`
STIAHNUTE = "_stiahnute.txt"


def zapis_stiahnute(cache_dir, fetcher, n_tiles):
    """Odloží, čo stálo sieť – fáza `spojit` už nesťahuje a nemá to odkiaľ vedieť."""
    dl = {"tiles": n_tiles, "tiles_missing": fetcher.n_miss,
          "tiles_failed": fetcher.n_fail,
          "mb_downloaded": f"{fetcher.bytes / 1048576:.0f}",
          "ua_profiles": len(fetcher.ua_seen)}
    try:
        with open(os.path.join(cache_dir, STIAHNUTE), "w") as f:
            for k, v in dl.items():
                f.write(f"{k}={v}\n")
    except OSError as exc:
        print(f"  čísla o sťahovaní sa neuložili ({exc}) – v štatistike "
              f"ďalšej fázy budú nuly.", flush=True)
    return dl


def nacitaj_stiahnute(cache_dir, n_tiles):
    """Čísla z fázy sťahovania; keď chýbajú, radšej nuly než vymyslené hodnoty."""
    dl = {"tiles": n_tiles, "tiles_missing": 0, "tiles_failed": 0,
          "mb_downloaded": "0", "ua_profiles": 0}
    cesta = os.path.join(cache_dir, STIAHNUTE)
    try:
        with open(cesta) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k in dl:
                    dl[k] = int(v) if k not in ("mb_downloaded",) else v
        print(f"  čísla o sťahovaní z {cesta}: {dl['tiles']} dlaždíc, "
              f"{dl['mb_downloaded']} MB", flush=True)
    except OSError:
        print(f"  {cesta} nie je – čísla o dlaždiciach v štatistike budú nuly.",
              flush=True)
    return dl


def hotove(path, label):
    """True = túto fázu spravil predošlý beh a netreba ju robiť znova.

    Každá fáza sa píše do `.part` a premenuje až celá, takže existencia súboru
    znamená „dokončené". Zmysel to má vďaka tomu, že pracovný priečinok leží
    v cache dlaždíc.
    """
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"  {label}: hotové z predošlého behu "
              f"({dir_mb(path):.0f} MB) – preskakujem", flush=True)
        return True
    return False


def urovne_pasiem(args, cliff_level):
    """Prahy pre `-fl`. Plné plochy (predvolene) = jediné pásmo.

    Dve pásma mali zmysel, kým sa kreslili rôzne tmavo; odkedy sú všetky plochy
    jedna sivá, je z toho len dvojnásobok prstencov na obtiahnutie.
    """
    return (["0.5", "256"] if args.plne else
            ["0.5", repr(cliff_level), "256"])


def vrt_geo(vrt):
    """Ľavý horný roh a veľkosť pixela z hlavičky VRT."""
    with open(vrt) as f:
        head = f.read(8192)
    m = re.search(r"<GeoTransform>(.*?)</GeoTransform>", head, re.S)
    if not m:
        raise RuntimeError(f"{vrt} nemá GeoTransform")
    g = [float(x) for x in m.group(1).split(",")]
    return g[0], g[3], g[1]     # ox, oy, veľkosť pixela (x)


def obrysy(tifs, args, tmp, cliff_level):
    """Mozaika tmavosti → obrysy po blokoch v `tmp/bloky`. Vráti počet blokov.

    Prvá polovica vektorizácie a vo workflowe vlastný job: toto je tá drahá
    časť, zlepovanie a filter za ňou sú minúty.
    """
    vrt = os.path.join(tmp, "score.vrt")
    run(["gdalbuildvrt", "-q", vrt] + tifs)
    ox, oy, res = vrt_geo(vrt)
    # blok sa tu meria v dlaždiciach, nie v pixeloch: raster je z dlaždíc
    # poskladaný. Spodná vrstva pozná len pixely.
    blok_px = max(1, args.block_tiles) * TILE
    _, n_blokov = bloky_mod.po_blokoch(
        vrt, os.path.join(tmp, "bloky"),
        urovne_pasiem(args, cliff_level), ["-amin", "dmin", "-amax", "dmax"],
        blok_px, (ox, oy, res), budget_s=args.budget_min * 60)
    return n_blokov


def spoj(args, tmp, out, cliff_level, merc, uzemie_km2=0.0):
    """Obrysy blokov → hotový rock.gpkg v EPSG:4326.

    Druhá polovica vektorizácie: zlepenie blokov, švy, filter, zjednodušenie
    a vyhladenie. Číta `tmp/bloky`, teda to, čo nechal `obrysy()`.
    """
    d_bloky = os.path.join(tmp, "bloky")
    if not os.path.isdir(d_bloky):
        raise RuntimeError(
            f"Chýbajú obrysy blokov ({d_bloky}). Fáza `spojit` nadväzuje na "
            f"fázu `vektor` – buď nebežala, alebo sa medzitým stratila cache "
            f"s rozrobeným. Pusti beh s `--phase=vsetko`.")
    n_blokov = len([f for f in os.listdir(d_bloky) if f.endswith(".geojsonl")])

    # `-explodecollections` netreba – filter nižšie si MultiPolygon rozoberie
    # sám a jeden `ogr2ogr` nad celým územím je práve tá fáza, ktorej sa
    # chceme zbaviť
    seq = os.path.join(tmp, "bands.geojsonl")
    if not hotove(seq, "spojenie blokov"):
        part = seq + ".part"
        n = bloky_mod.zlej(d_bloky, part)
        os.replace(part, seq)
        print(f"  spojenie blokov: {n} útvarov z {n_blokov} blokov", flush=True)

    # zlepovanie plôch rozseknutých hranicou bloku je len kozmetika: odkedy
    # majú všetky plochy tú istú sivú, dva kusy vedľa seba vyzerajú ako jeden.
    # Stojí `ST_Union` a spatialite navyše, tak je predvolene vypnuté.
    if args.zlepit:
        # `dmin` je trieda pásma – zlučovať sa smie len v rámci nej, inak by
        # sa stena zlepila so svahom. `srs` sa nepodáva: súradnice sú metrické.
        seq = bloky_mod.zlep_svy(seq, tmp, klucovy_atribut="dmin",
                                 heartbeat=args.heartbeat,
                                 max_s=args.budget_min * 60,
                                 label="zlepenie švov")
    else:
        print("  švy: nezlepujem (`options: zlepit=1` to zapne) – rovnaká "
              "sivá bez priehľadnosti spoj aj tak nepotrebuje", flush=True)

    filt = os.path.join(tmp, "rock.geojsonl")
    st = filter_stream(seq, filt, args.min_area, args.min_hole,
                       cliff_level, merc, every=args.heartbeat,
                       zapln_diery=bool(args.zapln_diery), min_level=0.5)
    print(f"  filter: {st['n_in']} → {st['n']} plôch "
          f"({st.get('pozadie', 0)} pásiem pod prahom = pozadie preč, "
          f"pod {args.min_area:g} m² preč), "
          + (f"diery ZAPLNENÉ ({st['holes_dropped']} zahodených) – "
             f"tvar plôch je preč, `zapln_diery=0` ho vráti"
             if args.zapln_diery else
             f"diery {st['holes']} ostali, {st['holes_dropped']} pod "
             f"{args.min_hole:g} m² preč"), flush=True)
    # poistka proti návratu tej istej chyby: keď plochy pokryjú väčšinu územia,
    # nie je to skala, ale pozadie. Súčet, nie najväčšia plocha – pozadie je
    # jeden polygón na blok, takže ani jeden z nich nie je veľký voči celku.
    # 30 % nie je prísna hranica: správny výsledok na skalnatom výreze vyšiel 9,5 %.
    spolu_km2 = st.get("total_m2", 0) / 1e6
    if uzemie_km2 > 0 and spolu_km2 > 0.3 * uzemie_km2:
        print(f"::warning::Skaly pokrývajú {spolu_km2:.2f} km² z "
              f"{uzemie_km2:.2f} km² územia ({100 * spolu_km2 / uzemie_km2:.0f} %). "
              f"Toľko skál nikde nie je – aj kotol pod Gerlachom vyjde na "
              f"~10 %. V mape z toho bude pri nižších zoomoch súvislá sivá "
              f"plocha bez detailu. Zdvihni `options: open=…` (zahadzuje "
              f"najtenšie vlákna siete) alebo zníž `dark`.", flush=True)

    if not st["n"]:
        if st["n_in"] > 1000:
            # tisíce útvarov a ani jeden dosť veľký nie je „prísny prah" –
            # skôr je zle jednotka plochy
            print(f"::warning::Filter zahodil VŠETKÝCH {st['n_in']} útvarov "
                  f"ako menšie než {args.min_area:g} m². Pri takom počte to "
                  f"nevyzerá na prísny prah, ale na to, že plocha sa počíta "
                  f"v iných jednotkách než v metroch – skontroluj súradnice "
                  f"v {seq}.", flush=True)
        return st

    metric = os.path.join(tmp, "rock-metric.gpkg")
    cmd = ["ogr2ogr", "-f", "GPKG", metric, filt, "-nln", "rock",
           "-nlt", "MULTIPOLYGON", "-a_srs", WEBMERC,
           "-lco", "GEOMETRY_NAME=geom"]
    if args.simplify > 0:
        cmd += ["-simplify", repr(args.simplify)]
    run(cmd)

    smooth = os.path.join(tmp, "rock-smooth.gpkg")
    src = metric
    if args.smooth > 0:
        # `smooth-shapes.py` je v `contours-rocks/` (zaobľuje aj vrstevnice),
        # takže cesta sem nesmie ísť cez `dirname(__file__)`. Stráži to
        # `workers/lint/layout.py`.
        subprocess.run([sys.executable,
                        os.path.join(_WORKERS, "contours-rocks",
                                     "smooth-shapes.py"),
                        f"--in={metric}", f"--out={smooth}", "--layer=rock",
                        f"--maxzoom={args.maxzoom}",
                        f"--sag={args.smooth}"], check=True)
        src = smooth

    if os.path.exists(out):
        os.remove(out)
    run(["ogr2ogr", "-f", "GPKG", out, src, "rock", "-nln", "rock",
         "-t_srs", "EPSG:4326", "-nlt", "MULTIPOLYGON",
         "-lco", "GEOMETRY_NAME=geom"])
    return st


def empty_rock(out):
    """Prázdna vrstva – schéma na skaly odkazuje vždy, súbor musí existovať."""
    tmp = out + ".empty.geojson"
    with open(tmp, "w") as f:
        f.write('{"type":"FeatureCollection","features":[]}')
    if os.path.exists(out):
        os.remove(out)
    run(["ogr2ogr", "-f", "GPKG", out, tmp, "-nln", "rock", "-nlt", "POLYGON",
         "-a_srs", "EPSG:4326", "-lco", "GEOMETRY_NAME=geom"])
    os.remove(tmp)
