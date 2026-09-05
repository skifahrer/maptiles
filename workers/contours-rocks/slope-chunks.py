#!/usr/bin/env python3
"""Raster sklonu po častiach – s trvalým skladom, aby sa nič nepočítalo dvakrát.

Jednotkou práce aj uloženia je ČASŤ: každá sa z Drive prečíta, prevedie na
sklon a uloží zvlášť, takže zrušený beh o hotové časti nepríde. Predtým bolo
jednotkou celé územie, čiže všetko alebo nič.

Jednotkou je sklon, nie hotové skaly: vektorizovať po častiach nejde (diera
prerezaná hranicou časti sa zmení na zárez). Sklon je pritom tá drahá časť.
Vedľajší zisk: zmena prahu `rock_slope` už neznamená nové čítanie z Drive.

Hranice častí sú prichytené na mriežku ukotvenú v počiatku EPSG:3035, nie na
bbox – tá istá zem tak padne vždy do tej istej časti a sklad trafí aj beh na
iné, prekrývajúce sa územie.

Geoid sa tu zámerne neprevádza: mení sa plynulo, takže na ploche jednej časti
je to konštantný posun a sklon sa ním nemení.

Použitie:
    python3 workers/contours-rocks/slope-chunks.py --bbox=19.9,49.09,20.32,49.25 \\
        --res=2 --drive --out=slope-chunks --jobs=6
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# plánovanie, metrická sústava aj mierka sklonu sú v `rock-areas.py`
rock = load("rock_areas", "rock-areas.py")
METRIC, SCALE = rock.METRIC, rock.SCALE

# trvalý sklad častí je priečinok na Drive; berie sa ako modul – volať ho
# procesom na každú z rádovo stovky častí by znamenalo stovku vypísaní priečinka
store = load("drive_store", os.path.join(os.pardir, "drive", "store.py"))

# strana časti v pixeloch: menšie časti = jemnejšie obnovenie po páde a menšie
# súbory, väčšie = menej réžie okolo každej
CHUNK_PX = 4096
MARGIN_PX = 8    # presah, aby sklon na okraji časti nebol zrezaný
MAX_CHUNKS = 600  # nad tým prestáva byť sklad výhodou (viď poistku v main)


def chunk_grid(bbox, res, chunk_px=CHUNK_PX):
    """Časti absolútnej mriežky, ktoré zasahujú do bboxu.

    Vracia `(ix, iy, x0, y0, x1, y1)` v metroch EPSG:3035; indexy sú v mriežke
    ukotvenej v počiatku sústavy, teda nezávislé od územia.

    Prevod do stupňov ide jedným volaním `gdaltransform` nad všetkými rohmi:
    jeden proces na časť by pri jemnej mriežke trval dlhšie než výpočet.
    """
    side = chunk_px * res
    mx0, my0, mx1, my1 = rock.to_metric(bbox)
    cand = []
    for iy in range(math.floor(my0 / side), math.ceil(my1 / side)):
        for ix in range(math.floor(mx0 / side), math.ceil(mx1 / side)):
            x0, y0 = ix * side, iy * side
            cand.append((ix, iy, x0, y0, x0 + side, y0 + side))
    if not cand:
        return []

    # osem bodov na časť: hranica je po prevode krivka a pri veľkej časti by sa
    # mohla do bboxu vydúvať stredom strany, kým rohy ostanú vonku
    pts = []
    for _, _, x0, y0, x1, y1 in cand:
        pts += [(x0, y0), (x1, y0), (x0, y1), (x1, y1),
                ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1),
                (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
    try:
        out = subprocess.run(
            ["gdaltransform", "-s_srs", METRIC, "-t_srs", "EPSG:4326"],
            input="\n".join(f"{x} {y}" for x, y in pts),
            capture_output=True, text=True, check=True).stdout.split()
    except subprocess.CalledProcessError:
        return cand   # keď sa to nedá zistiť, radšej počítať než vynechať

    xs = [float(v) for v in out[0::3]]
    ys = [float(v) for v in out[1::3]]
    keep = []
    for i, c in enumerate(cand):
        cx, cy = xs[i * 8:(i + 1) * 8], ys[i * 8:(i + 1) * 8]
        if not (max(cx) < bbox[0] or min(cx) > bbox[2]
                or max(cy) < bbox[1] or min(cy) > bbox[3]):
            keep.append(c)
    return keep


def chunk_name(ix, iy, res):
    """Meno časti v sklade: nesie mriežku aj polohu. Prah sklonu v ňom nie je –
    ten sa uplatňuje až pri vektorizácii, takže jeho zmena smie sklad použiť.

    Znamienko ide do písmena (E/W, N/S): `slope-r2--615--358` sa číta zle.
    """
    sx = f"E{ix:04d}" if ix >= 0 else f"W{-ix:04d}"
    sy = f"N{iy:04d}" if iy >= 0 else f"S{-iy:04d}"
    return f"slope-r{res:g}-{sx}{sy}.tif"


# ---------- sklad ----------

NOTE = ("Medzivýsledok skál: sklon terénu v stotinách stupňa (Int16, "
        "EPSG:3035) po častiach absolútnej mriežky (workers/contours-rocks/slope-chunks.py)")


class Store:
    """Časti v adresári (cache behu) a v sklade na Drive (trvalé).

    Dve vrstvy zámerne: cache je rýchla, ale prerieďuje sa; sklad na Drive
    nevyprší sám, takže hodina čítania sa nemá ako stratiť.

    Sklad si tento skript volá ako modul – pri stovkách častí je jedno
    vypísanie priečinka a potom priame prenosy oveľa lacnejšie než proces
    na každú časť.
    """

    def __init__(self, path, store_name, use_store=True):
        self.path = path
        self.store_name = store_name
        self.lock = threading.Lock()
        self.hits_local = 0
        self.hits_store = 0
        self.made = 0
        os.makedirs(path, exist_ok=True)
        self.creds = None
        self.items = {}      # meno → {id, size, created}; vypíše sa RAZ
        self.assets = set()
        self.use_store = False
        if not use_store:
            return
        # bez tokenu sa pokračuje, ale nahlas: časti sa dajú spočítať aj bez
        # skladu (stojí to čas, nie správnosť)
        try:
            self.creds = store.creds_or_die("sklad častí sklonu")
            # jeden výpis priečinka na celý beh; častí je rádovo stovka
            self.items = store.index(self.creds, store_name)
            self.assets = set(self.items)
            self.use_store = True
        except SystemExit as exc:
            print(f"::warning::Sklad častí sklonu na Drive je vypnutý "
                  f"({str(exc).splitlines()[0][:200]}) – časti sa spočítajú "
                  f"a po behu sa stratia.", flush=True)

    def local(self, name):
        p = os.path.join(self.path, name)
        return p if os.path.exists(p) and os.path.getsize(p) > 0 else None

    def take(self, name):
        """Časť z cache alebo zo skladu; None = treba ju spočítať."""
        p = self.local(name)
        if p:
            with self.lock:
                self.hits_local += 1
            return p
        if not self.use_store or name not in self.items:
            return None
        try:
            store.download(self.creds, dict(self.items[name], name=name),
                           os.path.join(self.path, name))
        except (RuntimeError, OSError, SystemExit):
            return None
        if self.local(name):
            with self.lock:
                self.hits_store += 1
            return os.path.join(self.path, name)
        return None

    def put(self, name):
        """Hotovú časť do skladu. Zlyhanie uploadu nesmie zhodiť beh – časť je
        spočítaná a v adresári."""
        with self.lock:
            self.made += 1
        if not self.use_store:
            return
        try:
            # `clobber=False`: časť sa nahráva len vtedy, keď v sklade nebola,
            # takže niet čo prepisovať
            store.upload(self.creds, self.store_name,
                         os.path.join(self.path, name), name, NOTE,
                         clobber=False)
        except (RuntimeError, OSError, SystemExit) as exc:
            print(f"::warning::Časť {name} sa nepodarilo uložiť do skladu "
                  f"{self.store_name} – nabudúce sa bude počítať znova. "
                  f"{str(exc)[:200]}", flush=True)
        else:
            with self.lock:
                self.assets.add(name)


def slope_chunk(dem, chunk, res, out_path, work, env=None):
    """DEM → sklon pre jednu časť, orezaný presne na jej hranicu.

    Presah `MARGIN_PX` je preto, že `gdaldem slope` počíta z okolia bunky –
    bez neho by mal každý okraj pás nezmyselného sklonu a v mozaike šachovnicu.
    """
    ix, iy, x0, y0, x1, y1 = chunk
    m = MARGIN_PX * res
    dem_tif = os.path.join(work, f"dem-{ix}-{iy}.tif")
    slope_tif = os.path.join(work, f"slope-{ix}-{iy}.tif")

    def run(cmd):
        # stderr musí byť v chybe: `capture_output` ho inak prehltne a z padnutého
        # behu ostane len „returned non-zero exit status 1"
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if r.returncode:
            raise RuntimeError(
                f"{cmd[0]} skončil s kódom {r.returncode} pre časť {ix},{iy}:\n"
                f"  {' '.join(cmd)}\n  {r.stderr.strip()[:500]}")
        return r
    try:
        run(["gdalwarp", "-q", "-overwrite", "-t_srs", METRIC,
             "-te", repr(x0 - m), repr(y0 - m), repr(x1 + m), repr(y1 + m),
             "-tr", repr(res), repr(res), "-r", "cubicspline",
             "-ot", "Float32", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
             "-multi", "-ovr", "AUTO", dem, dem_tif])
        run(["gdaldem", "slope", "-q", "-compute_edges",
             "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", dem_tif, slope_tif])
        # Float32 → Int16 v stotinách stupňa: mozaika celého pohoria sa vo
        # Float32 na disk runnera nezmestí a 0,01° je nerozoznateľné
        tmp_out = out_path + ".part"
        # `-of GTiff` výslovne: ovládač sa háda z prípony a `.part` GDAL nepozná.
        # Prípona musí ostať iná než `.tif`, inak by rozrobený súbor vyzeral hotový.
        run(["gdal_translate", "-q", "-of", "GTiff", "-ot", "Int16",
             "-scale", "0", repr(90.0), "0", repr(90.0 * SCALE),
             "-projwin", repr(x0), repr(y1), repr(x1), repr(y0),
             "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=2", "-co", "TILED=YES",
             slope_tif, tmp_out])
        # až premenovanie spraví časť hotovou – inak by prerušený beh nechal
        # v cache useknutý súbor
        os.replace(tmp_out, out_path)
    finally:
        for f in (dem_tif, slope_tif):
            if os.path.exists(f):
                os.remove(f)
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbox", required=True, help="west,south,east,north v stupňoch")
    ap.add_argument("--res", default="auto",
                    help="mriežka sklonu v metroch, alebo `auto`")
    ap.add_argument("--out", default="slope-chunks",
                    help="adresár so skladom častí (ukladá sa do cache)")
    ap.add_argument("--work", default="", help="pracovný adresár (default: --out/tmp)")
    ap.add_argument("--dem", default="", help="lokálny DEM (.vrt/.tif)")
    ap.add_argument("--drive", action="store_true",
                    help="čítať priamo z DMR 5.0 na Drive cez HTTP Range")
    ap.add_argument("--jobs", type=int, default=4,
                    help="koľko častí naraz; pri --drive rozhoduje latencia, "
                         "nie pásmo, takže sa oplatí ísť vyššie")
    ap.add_argument("--store", default=os.environ.get("SLOPE_STORE", "dem-slope"),
                    help="sklad na Drive (viď workers/drive/store.py)")
    ap.add_argument("--no-store", action="store_true",
                    help="nepoužiť ani neodkladať do skladu (testovací beh)")
    ap.add_argument("--rebuild", action="store_true",
                    help="prepočítať časti aj keď v sklade sú")
    ap.add_argument("--chunk-px", type=int, default=CHUNK_PX)
    ap.add_argument("--dem-cell-m", type=float, default=0.0,
                    help="bunka zdroja v metroch (na `--res=auto`); "
                         "pri --drive je to 1")
    # 0 = bez stropu času (viď ROCK_BUDGET_MIN v build-map-region.yml)
    ap.add_argument("--budget-min", type=float, default=0.0)
    ap.add_argument("--chunk-cells", type=float, default=150e6)
    ap.add_argument("--tries", type=int, default=3,
                    help="koľko pokusov na jednu časť, kým sa beh vzdá")
    ap.add_argument("--heartbeat", type=float,
                    default=float(os.environ.get("ROCK_HEARTBEAT_S") or 30),
                    help="ako často povedať, čo práve beží (0 = ticho)")
    ap.add_argument("--print-res", action="store_true",
                    help="len vypíš zvolenú mriežku a skonči")
    ap.add_argument("--stats", default="", help="kam zapísať štatistiku (key=value)")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    x0, y0, x1, y1 = rock.to_metric(bbox)

    dem_cell = args.dem_cell_m or (1.0 if args.drive else 0.0)
    if not dem_cell and args.dem:
        dem_cell = rock.dem_cell_metres(args.dem, (bbox[1] + bbox[3]) / 2)[0]
    if str(args.res).strip().lower() in ("auto", "", "0"):
        # tabuľka výberu ide na stderr: volajúci si berie mriežku cez
        # `RES=$(… --print-res)`, takže na stdout smie byť len to číslo
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            res = rock.pick_res(x0, y0, x1, y1, args.chunk_cells, bbox,
                                args.budget_min, dem_cell)
    else:
        res = float(args.res)

    if args.print_res:
        print(f"{res:g}")
        return 0

    chunks = chunk_grid(bbox, res, args.chunk_px)
    if not chunks:
        print(f"::error::Ani jedna časť nezasahuje do územia {args.bbox}.")
        return 2
    # poistka na počet častí: strana časti je `chunk_px × res`, takže jemná
    # mriežka ju zmenší a počet rastie s druhou mocninou. Nad tisíckami prestáva
    # byť sklad výhodou.
    if len(chunks) > MAX_CHUNKS:
        side_km = args.chunk_px * res / 1000
        print(f"::error::Vyšlo {len(chunks)} častí po {side_km:g} km "
              f"(mriežka {res:g} m, {args.chunk_px}² px) a strop je "
              f"{MAX_CHUNKS}. Zdvihni --chunk-px (napr. "
              f"{args.chunk_px * 4}), zvoľ hrubšiu mriežku (rock_res) "
              f"alebo menší výrez (rock_area).")
        return 2

    work = args.work or os.path.join(args.out, "tmp")
    os.makedirs(work, exist_ok=True)
    sklad = Store(args.out, args.store, use_store=not args.no_store)

    # čo to bude stáť – pred prvým gdalwarpom. Do odhadu patrí aj to, čo
    # v sklade už je: druhý beh na tom istom pohorí nestojí nič.
    side_km = args.chunk_px * res / 1000
    names = [chunk_name(ix, iy, res) for ix, iy, *_ in chunks]
    have = 0 if args.rebuild else sum(
        1 for n in names if sklad.local(n) or n in sklad.assets)
    todo = len(chunks) - have
    cells = len(chunks) * args.chunk_px ** 2
    est_s = todo * args.chunk_px ** 2 / rock.SLOPE_CELLS_PER_S

    print("── Plán sklonu ──────────────────────────────────────")
    print(f"  mriežka         {res:g} m")
    print(f"  častí           {len(chunks)} po {side_km:g}×{side_km:g} km "
          f"({args.chunk_px}² px)")
    print(f"  buniek          {cells / 1e9:.2f} mld.")
    print(f"  sklad           {args.out}"
          + (f" + Drive {args.store}" if sklad.use_store
             else " (sklad na Drive vypnutý)"))
    print(f"  z toho hotových {have} → počítať treba {todo}")
    print(f"  odhad           {rock.hms(est_s)}"
          + ("  (všetko je v sklade)" if not todo else ""))
    print(f"  mozaika na disk ~{cells / 1e9 * rock.MOSAIC_MB_PER_GCELL:.0f} MB")
    print("─────────────────────────────────────────────────────", flush=True)

    t0 = time.time()
    env = None
    stats_drive = None
    if args.drive:
        # shim nad Drive, id súborov aj prihlásenie sú v `drive/dmr5.py`
        dd = load("dmr5_drive", os.path.join(os.pardir, "drive", "dmr5.py"))
        base, sizes, stats_drive, creds = dd.serve_drive(0)
        dem = f"/vsicurl/{base}/{dd.TIF_NAME}"
        env = dd.drive.gdal_env()
        print(f"  zdroj: DMR 5.0 na Drive, "
              + ", ".join(f"{n} {s / 2**30:.1f} GiB" for n, s in sizes.items()))
        print(f"  prístup: {dd.auth.describe(creds)}")
    elif args.dem:
        dem = args.dem
        print(f"  zdroj: {dem}")
    else:
        print("::error::Chýba zdroj – zadaj --dem alebo --drive.")
        return 2

    done = [0]
    lock = threading.Lock()
    running = {}          # meno časti → odkedy sa počíta
    failed = []           # čo sa nepodarilo ani na posledný pokus
    tries = max(1, args.tries)

    def compute(name, chunk, path):
        """Jedna časť – a keď spojenie vypadne, ešte raz.

        Sieť medzi GDALom a shimom vypadne raz za desaťtisíce požiadaviek
        a doteraz to znamenalo koniec celého behu. Časť sa počíta minútu, takže
        druhý pokus stojí minútu; pád stojí celý job.

        Trvalé chyby sa opakovaním nespravia, tak sú pokusy tri a čaká sa krátko.
        Po `slope_chunk` neostáva nič rozrobené, takže ďalší pokus začína načisto.
        """
        for attempt in range(1, tries + 1):
            with lock:
                running[name] = time.time()
            try:
                slope_chunk(dem, chunk, res, path, work, env)
                return
            except Exception as exc:                    # noqa: BLE001
                if attempt >= tries:
                    with lock:
                        failed.append(name)
                    raise
                wait = 5 * attempt
                why = str(exc).strip().splitlines()[-1][:200]
                print(f"::warning::Časť {name} zlyhala na {attempt}. pokus "
                      f"z {tries}, skúšam znova o {wait} s: {why}", flush=True)
                time.sleep(wait)
            finally:
                with lock:
                    running.pop(name, None)

    def one(chunk):
        ix, iy = chunk[0], chunk[1]
        name = chunk_name(ix, iy, res)
        path = os.path.join(args.out, name)
        got = None if args.rebuild else sklad.take(name)
        if got is None:
            compute(name, chunk, path)
            sklad.put(name)
        with lock:
            done[0] += 1
            el = time.time() - t0
            eta = el / done[0] * (len(chunks) - done[0])
            print(f"  [{done[0]}/{len(chunks)}] {name} "
                  f"{'zo skladu' if got else 'spočítaná'} – "
                  f"{rock.hms(el)} za sebou, zostáva ~{rock.hms(eta)}", flush=True)
        return path

    # tep: riadok na hotovú časť stačí, kým časti trvajú desiatky sekúnd – len
    # čo sa jedna zasekne, vyzerá zaseknutý beh presne ako pomalý.
    # Počet požiadaviek na Drive je tu hlavné číslo: keď rastie, číta sa.
    stop = threading.Event()

    def beat():
        while not stop.wait(args.heartbeat):
            now = time.time()
            with lock:
                live = sorted(running.items(), key=lambda kv: kv[1])
                d = done[0]
            parts = [f"[{d}/{len(chunks)}] beží {len(live)}"]
            if live:
                parts.append(", ".join(
                    f"{n.rsplit('-', 1)[-1][:-4]} {rock.hms(now - t)}"
                    for n, t in live[:4]))
            if stats_drive:
                with stats_drive["lock"]:
                    got, req = stats_drive["bytes"], stats_drive["requests"]
                    bad = stats_drive.get("failed", 0)
                parts.append(f"z Drive {got / 1e9:.2f} GB v {req:,} požiadavkách"
                             + (f", {bad:,} zlyhalo" if bad else ""))
            print("  … " + "  ".join(parts), flush=True)

    if args.heartbeat > 0:
        threading.Thread(target=beat, daemon=True).start()

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            tiles = list(ex.map(one, chunks))
    except Exception:
        # čo z toho ostalo: sklad je celý zmysel tohto skriptu, takže pri páde
        # musí byť vidieť, že hotová práca sa nezahodila
        stop.set()
        with lock:
            bad = list(failed)
        have_now = sum(1 for n in names if sklad.local(n))
        print(f"::error::Sklon spadol na {len(bad)} častiach"
              + (f" ({', '.join(bad[:6])})" if bad else "")
              + f"; v sklade ich je {have_now} z {len(chunks)} – ďalší beh "
              f"dopočíta len zvyšok, nič sa nezahodilo.", flush=True)
        raise
    stop.set()

    vrt = os.path.join(args.out, f"slope-r{res:g}.vrt")
    subprocess.run(["gdalbuildvrt", "-q", vrt] + tiles, check=True)
    mb = sum(os.path.getsize(t) for t in tiles) / 1048576
    print(f"Mozaika sklonu: {len(tiles)} častí, {mb:.0f} MB → {vrt}")
    print(f"  zo skladu {sklad.hits_local} lokálne + {sklad.hits_store} "
          f"z Drive, novo spočítaných {sklad.made}, "
          f"celkom {rock.hms(time.time() - t0)}")
    if stats_drive:
        with stats_drive["lock"]:
            print(f"  z Drive {stats_drive['bytes'] / 1e9:.2f} GB "
                  f"v {stats_drive['requests']:,} požiadavkách")

    if args.stats:
        with open(args.stats, "w") as f:
            f.write(f"res={res:g}\nvrt={vrt}\nchunks={len(tiles)}\n"
                    f"from_cache={sklad.hits_local}\n"
                    f"from_store={sklad.hits_store}\n"
                    f"computed={sklad.made}\nmosaic_mb={mb:.0f}\n")
    print(f"slope_vrt={vrt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
