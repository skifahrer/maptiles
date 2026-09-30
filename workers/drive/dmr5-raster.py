#!/usr/bin/env python3
"""
DMR 5.0 ako JEDEN GeoTIFF vo vzdialenom ZIPe – čítaný cez /vsizip//vsicurl/.

ČO JE V ARCHÍVE (zmerané behom 31184095104, `mode: len plán`):

    dmr5_0/dmr5_jtsk03.tif        151,43 GB   celé Slovensko, 1 m, jeden raster
    dmr5_0/dmr5_jtsk03.tif.ovr     46,28 GB   prehľadové úrovne (pyramídy)
    dmr5_0/dmr5_jtsk03.tfw                    world file
    dmr5_0/dmr5_jtsk03.tif.aux.xml / .xml     metadáta
    INFO_*.txt, 4× PDF, prehlad_lokalit_*.shp licencie a prehľad lokalít

Čakali sme textové výškové body po blokoch. Nie sú. Je to jeden súvislý
raster, takže sa nedá deliť po položkách archívu – a celé rozdeľovanie na
časti po položkách archívu tu nemá čo deliť.

ZATO SA DÁ ČÍTAŤ PRIAMO. GDAL vie `/vsizip//vsicurl/URL/cesta.tif`: ZIP číta
cez HTTP Range a GeoTIFF je dlaždicovaný, takže si vypýta len tie dlaždice,
ktoré potrebuje. Žiadne sťahovanie 151 GB na disk, žiadne medzivýsledky.

JEDNA VEC O TOM ALE PLATÍ A URČUJE CELÝ NÁVRH: položka v ZIPe je uložená
deflate-om (ÚGKK ju tak zabalil), a v deflate prúde sa nedá skočiť dopredu –
dá sa doň len rozbaliť od začiatku. Cena čítania je preto úmerná tomu, AKO
ĎALEKO V SÚBORE dáta ležia. Zmerané na napodobenine (44 MB ZIP, dlaždicovaný
DEFLATE GeoTIFF, HTTP server s Range):

    výrez na začiatku rastra      0,5 MB    1 % archívu
    výrez na konci rastra        44,1 MB  100 % archívu
    celý raster 1 m → 5 m        37,8 MB   (s .ovr, 1,1 s)
    to isté bez .ovr             46,1 MB   (2,7 s)

Z toho plynú pravidlá, podľa ktorých je tento script napísaný:

  1. JEDEN PRECHOD, NIE VIAC. Prevzorkovanie celej krajiny sa robí jedným
     `gdal_translate -tr`, nie po dlaždiciach – N výrezov by stálo N× cestu
     od začiatku súboru. Dlaždice 1°×1° sa krájajú až z hotového malého
     rastra.
  2. ČÍTAŤ SA MUSÍ DOPREDU. Výrez ide v dvoch krokoch: najprv
     `gdal_translate -projwin` (číta raster po riadkoch zhora nadol, teda
     sekvenčne) na disk, až potom `gdalwarp` z disku do WGS84. Warp priamo
     nad vzdialeným zdrojom si dlaždice pýta v poradí CIEĽOVEJ mriežky,
     a každý skok späť v deflate prúde znamená rozbaľovanie od začiatku –
     jeden krok späť môže stáť desiatky GB.
  3. PYRAMÍDY MIESTO RASTRA, KEĎ TO IDE. Pri cieli aspoň 2× hrubšom než
     zdroj sa číta z `.ovr` (46 GB) a nie z hlavného rastra (151 GB).
     Nespoliehame sa na to, že si `.ovr` nájde GDAL sám – vyberáme ho
     výslovne a je to vidieť v logu.
  4. SIDECARY SA NESMÚ SCHOVAŤ. `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`
     síce šetrí požiadavky, ale skryje `.ovr` aj `.tfw`.
  5. KAŽDÝCH 30 SEKÚND POVEDZ, ŽE ŽIJEŠ. Hodinový prechod cez 151 GB je
     inak v logu úplne ticho (GDAL kreslí percentá cez `\\r`, čo sa v logu
     GitHub Actions neobjaví). Heartbeat vypisuje prenesené bajty zo
     sieťovky, rýchlosť a odhad zvyšku.
  6. NAJPRV 16 BAJTOV, POTOM GDAL. Hlavička TIFFu nesie offset adresára
     dlaždíc (IFD) a ten rozhoduje o všetkom: keď je na začiatku, súbor sa
     otvorí za sekundu; keď je na konci, GDAL sa k nemu prehryzie len
     rozbalením celého člena – teda 151 GB ešte pred prvým pixelom. Beh
     31191478190 sa zasekol presne tu a v logu nebolo nič, z čoho by sa to
     dalo zistiť. Teraz sa tých 16 bajtov prečíta ako prvé a `gdalinfo` má
     strop (`--probe-timeout`), aby beh skončil s vysvetlením a nie po
     šiestich hodinách bez slova.

Použitie:
    python3 workers/drive/dmr5-raster.py --url=URL --area=cele --grid-m=5 --out=tiles
    python3 workers/drive/dmr5-raster.py --url=URL --area=vysoke_tatry --grid-m=1 \\
        --out=out --asset=ugkk-vysoke_tatry.tif
    python3 workers/drive/dmr5-raster.py --url=URL --probe-only
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Priečinok = job, súbor = krok; spoločné veci ležia o úroveň vyššie.
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # číselníky (areas, regions, zdroje)

# KTORÝM RESAMPLINGOM – jedna odpoveď pre celú pipeline, viď `lib/cell.py`.
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import resampling  # noqa: E402


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ČÍTANIE VZDIALENÉHO RASTRA JE VEDĽA. `dmr5-remote.py` vie otvoriť 151 GB
# TIFF v cudzom ZIPe cez /vsizip//vsicurl/, spraviť nad ním sondu a nájsť
# `.tfw` aj `.ovr` sidecary – vrátane oboch ciest cez pyramídy. Tento súbor
# sa pýta na niečo iné: ktorý kus zeme z toho vyrezať a s akou mriežkou.
# (Rozdelené preto, že spolu to malo 853 riadkov – pravidlo 5 v CLAUDE.md.)
remote = load("dmr5_remote", "dmr5-remote.py")
GDAL_ENV, Heartbeat = remote.GDAL_ENV, remote.Heartbeat
run, run_live, vsi_path = remote.run, remote.run_live, remote.vsi_path
pick_member, tiff_layout, probe = remote.pick_member, remote.tiff_layout, remote.probe
find_sidecar, ovr_source, ovr_fallback = (remote.find_sidecar, remote.ovr_source,
                                          remote.ovr_fallback)


def wgs_bbox_to_src(bbox_wgs, wkt_file, log):
    """(W, S, E, N) vo WGS84 → obálka v projekcii zdroja, cez `gdaltransform`.

    Nie cez pyproj: job má nainštalovaný len GDAL. A nie len rohy – Krovák je
    kužeľové zobrazenie, takže obdĺžnik vo WGS84 nie je obdĺžnik v S-JTSK
    a rohy by výrez odrezali.
    """
    w, s, e, n = bbox_wgs
    pts, steps = [], 16
    for i in range(steps + 1):
        f = i / steps
        pts += [(w + (e - w) * f, s), (w + (e - w) * f, n),
                (w, s + (n - s) * f), (e, s + (n - s) * f)]
    inp = "\n".join(f"{x} {y}" for x, y in pts) + "\n"
    r = subprocess.run(["gdaltransform", "-s_srs", "EPSG:4326",
                        "-t_srs", wkt_file],
                       input=inp, capture_output=True, text=True, env=GDAL_ENV)
    if r.returncode:
        raise SystemExit(f"::error::gdaltransform zlyhal: {r.stderr[:300]}")
    xs, ys = [], []
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 2:
            xs.append(float(f[0]))
            ys.append(float(f[1]))
    if not xs:
        raise SystemExit(f"::error::bbox {bbox_wgs} sa nedá prepočítať")
    log(f"  v projekcii zdroja: {min(xs):.0f},{min(ys):.0f} … "
        f"{max(xs):.0f},{max(ys):.0f}")
    return min(xs), min(ys), max(xs), max(ys)


def clamp_to_raster(box, info, pad_px, log):
    """Prienik okna s rozsahom rastra.

    Bez toho by `gdal_translate -projwin` presahujúcu časť DOPLNIL nulami –
    a nula je platná výška, takže by sa to potom prejavilo ako pás mora
    v mape, nie ako diera. (Presne to sa stalo pri prvom pokuse: minimum
    výšok spadlo zo 400 na 0.)
    """
    gt = info["geoTransform"]
    px, py = info["size"]
    rw, rn = gt[0], gt[3]
    re_, rs = rw + gt[1] * px, rn + gt[5] * py
    pad_x, pad_y = pad_px * abs(gt[1]), pad_px * abs(gt[5])
    w = max(box[0] - pad_x, min(rw, re_))
    s = max(box[1] - pad_y, min(rs, rn))
    e = min(box[2] + pad_x, max(rw, re_))
    n = min(box[3] + pad_y, max(rs, rn))
    if w >= e or s >= n:
        raise SystemExit("::error::Výrez nemá s rastrom spoločný ani jeden "
                         "pixel – skontroluj `area`.")
    if (w, s, e, n) != tuple(box):
        log(f"  orezané na rozsah rastra: {w:.0f},{s:.0f} … {e:.0f},{n:.0f}")
    return w, s, e, n



def degrees_per_metre(lat):
    """Krok mriežky v stupňoch pre daný krok v metroch na tejto šírke."""
    return (1.0 / (111320 * math.cos(math.radians(lat))), 1.0 / 110540)


def whole_country(vsi, grid_m, work, out_dir, log, expect=None):
    """Celá krajina: JEDEN prechod na hrubšiu mriežku, potom dlaždice.

    Krájať 1° dlaždice priamo zo zdroja by znamenalo prejsť ten deflate prúd
    toľkokrát, koľko je dlaždíc. Preto sa najprv prevzorkuje (sekvenčne, raz)
    a až malý výsledok sa krája.
    """
    os.makedirs(work, exist_ok=True)
    small = os.path.join(work, "dmr5-national.tif")
    t0 = time.time()
    log(f"Prevzorkovanie celej krajiny na {grid_m} m – jeden prechod, "
        f"toto je tá dlhá časť.")
    if expect:
        log(f"  čakám ~{expect / 1e9:.0f} GB zo siete")
    # Z 1 m na 5 m je pomer 5, teda hlboko nad `AVERAGE_RATIO` – priemer tu
    # má čo priemerovať a je poctivý. Aj tak sa naň pýtame `lib/cell.py`:
    # keby sa `--grid-m` raz priblížilo k mriežke zdroja, `average` by z nej
    # spravil mriežku v tieňovaní a nikto by nespozoroval, kedy sa to zlomilo.
    run_live(["gdal_translate", "-tr", str(grid_m), str(grid_m),
              "-r", resampling(grid_m, 1.0), "-of", "GTiff",
              "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
              "-co", "TILED=YES", "-co", "BIGTIFF=YES",
              "-co", "NUM_THREADS=ALL_CPUS", vsi, small],
             label="prevzorkovanie", expect_bytes=expect, watch=small)
    mb = os.path.getsize(small) / 1048576
    log(f"  hotovo za {(time.time() - t0) / 60:.1f} min, {mb:.0f} MB")

    log("Krájanie na dlaždice 1°×1° vo WGS84…")
    run_live(["python3", os.path.join(_WORKERS, "dem", "tiles.py"), "--out", out_dir, small])
    return small


def area_cut(vsi, bbox_wgs, grid_m, dest, work, log, info, expect=None):
    """Výrez v DVOCH krokoch – a to poradie je celá pointa.

    1. `gdal_translate -projwin` vyreže okno v pôvodnej projekcii a uloží ho
       na disk. Číta pritom raster po riadkoch zhora nadol, teda dopredu.
    2. `gdalwarp` prevedie ten malý miestny súbor do WGS84.

    Prečo nie rovno gdalwarp na vzdialený zdroj: warp si dlaždice pýta v takom
    poradí, v akom ich potrebuje pre CIEĽOVÚ mriežku, a to nie je poradie,
    v akom ležia v súbore. Každý skok späť v deflate prúde ale znamená
    rozbaľovanie od začiatku člena – jeden krok späť môže stáť desiatky GB.
    Sekvenčné čítanie tú pascu obchádza a warp potom pracuje nad diskom, kde
    je skákanie zadarmo.

    Cena prvého kroku je daná tým, ako ďaleko v súbore výrez leží: raster sa
    číta od severu, takže Tatry sú lacnejšie než Slovenský kras. S tým sa
    nedá spraviť nič, deflate sa preskakovať nedá.
    """
    os.makedirs(work, exist_ok=True)
    native = os.path.join(work, "vyrez-nativ.tif")
    wkt_file = os.path.join(work, "src.wkt")
    with open(wkt_file, "w") as f:
        f.write(info["wkt"])
    t0 = time.time()

    log(f"Výrez {bbox_wgs} pri {grid_m} m, krok 1/2: okno v pôvodnej "
        f"projekcii, čítané sekvenčne…")
    box = wgs_bbox_to_src(bbox_wgs, wkt_file, log)
    bw, bs, be, bn = clamp_to_raster(box, info, 4, log)
    run_live(["gdal_translate",
              "-projwin", repr(bw), repr(bn), repr(be), repr(bs),
              "-of", "GTiff", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
              "-co", "TILED=YES", "-co", "BIGTIFF=YES",
              "-co", "NUM_THREADS=ALL_CPUS", vsi, native],
             label="čítanie okna", expect_bytes=expect, watch=native)
    log(f"  okno: {os.path.getsize(native) / 1048576:.0f} MB, "
        f"{(time.time() - t0) / 60:.1f} min")

    dx, dy = degrees_per_metre((bbox_wgs[1] + bbox_wgs[3]) / 2)
    log(f"Krok 2/2: prevod do WGS84 ({grid_m * dx:.7f}° × {grid_m * dy:.7f}°) "
        f"– už len z disku, rýchle.")
    # Okno je už v cieľovej mriežke, mení sa len projekcia – pomer pixel/bunka
    # je 1 a kernel vyberá `lib/cell.py` (rozpis pri `dmr5-cut.to_wgs84`).
    run_live(["gdalwarp", "-overwrite",
              "-t_srs", "EPSG:4326",
              "-te", *[repr(v) for v in bbox_wgs],
              "-tr", repr(grid_m * dx), repr(grid_m * dy),
              "-r", resampling(grid_m, grid_m),
              "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
              "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
              "-co", "RESAMPLING=AVERAGE", "-co", "NUM_THREADS=ALL_CPUS",
              native, dest])
    os.remove(native)
    mb = os.path.getsize(dest) / 1048576
    log(f"  hotovo za {(time.time() - t0) / 60:.1f} min, {mb:.0f} MB")
    return dest


def resolve_area(area, areas_path):
    key = (area or "whole_country").strip()
    if key.lower() in ("", "whole", "whole_country", "cele", "cele_slovensko", "all"):
        return "whole country", None
    if "," in key:
        vals = [float(v) for v in key.split(",")]
        if len(vals) != 4:
            raise SystemExit(f"::error::bbox musí mať 4 čísla: {key}")
        return f"bbox {key}", tuple(vals)
    areas = json.load(open(areas_path))
    if key not in areas:
        known = ", ".join(k for k in areas if not k.startswith("_"))
        raise SystemExit(f"::error::neznámy výrez „{key}“. Známe: {known}")
    return areas[key]["name"], tuple(areas[key]["bbox"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--plan", default="plan.json",
                    help="z neho sa vyberie najväčší raster v archíve")
    ap.add_argument("--member", default="", help="cesta v archíve natvrdo")
    ap.add_argument("--area", default="cele")
    ap.add_argument("--areas", default=os.path.join(_DATA, "areas.json"))
    ap.add_argument("--grid-m", type=float, default=5.0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--work", default="raster-work")
    ap.add_argument("--asset", default="", help="meno súboru pri výreze")
    ap.add_argument("--probe-only", action="store_true",
                    help="len prečítať hlavičku a skončiť")
    ap.add_argument("--no-ovr", action="store_true",
                    help="nečítať z pyramíd, ani keď to ide")
    ap.add_argument("--debug", action="store_true",
                    help="CPL_DEBUG=ON – každá požiadavka do logu. Len na "
                         "krátke behy, pri 151 GB je toho milión riadkov.")
    ap.add_argument("--probe-timeout", type=float, default=900,
                    help="sekundy, koľko sa čaká na otvorenie rastra")
    ap.add_argument("--summary", default="")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = ap.parse_args()

    if args.debug:
        GDAL_ENV["CPL_DEBUG"] = "ON"
        GDAL_ENV["CPL_CURL_VERBOSE"] = "YES"

    lines = []

    def log(m):
        print(m, flush=True)
        lines.append(m)

    member = pick_member(args.plan, args.member)
    vsi = vsi_path(args.url, member)
    log(f"Položka v archíve: {member}")
    log(f"Cesta pre GDAL:    {vsi}")

    # ---- lacná diagnostika PRED tým, než sa pustí GDAL ----
    # 16 bajtov z každého súboru povie, či sa vôbec dá otvoriť rozumne rýchlo.
    # Beh 31191478190 sa zasekol presne tu a v logu nebolo nič, z čoho by sa
    # to dalo zistiť.
    log("Rozloženie rastrov v archíve (16 bajtov z každého):")
    main_entry = find_sidecar(args.plan, member, "")
    ovr_entry = find_sidecar(args.plan, member, ".ovr")
    lay = tiff_layout(args.url, main_entry, log) if main_entry else None
    lay_ovr = tiff_layout(args.url, ovr_entry, log) if ovr_entry else None
    for name, l in (("hlavný raster", lay), ("pyramídy", lay_ovr)):
        if l and l["share"] > 1.0:
            log(f"::warning::{name}: adresár dlaždíc je až na {l['share']:.0f} % "
                f"súboru. Člen ZIPu je deflate, takže sa k nemu GDAL dostane "
                f"len rozbalením všetkého pred ním – otvorenie samo o sebe "
                f"prečíta ~{l['ifd'] / 1e9:.1f} GB.")

    # Sondu púšťame BEZ hľadania sidecarov. Keby bol drahý niektorý z nich
    # (napr. `.ovr` so 46 GB), vyzeralo by to ako problém hlavného súboru –
    # a my ich aj tak otvárame sami, výslovne.
    t0 = time.time()
    forced = None
    info = probe(vsi, log, timeout=args.probe_timeout, no_sidecars=True,
                 expect_bytes=main_entry["csize"] if main_entry else None)
    if info is not None:
        log(f"  otvorené bez sidecarov za {time.time() - t0:.0f} s")
        gt = info["geoTransform"]
        if gt[:6] == [0.0, 1.0, 0.0, 0.0, 0.0, 1.0] or not info["wkt"]:
            # Georeferencia nie je v samotnom TIFFe – musí prísť z .tfw
            # alebo .aux.xml, a tie GDAL nájde len s povoleným readdir.
            log("Raster nemá georeferenciu v sebe – skúšam znova aj so "
                "sidecarmi (.tfw / .aux.xml).")
            info = probe(vsi, log, timeout=args.probe_timeout)
    if info is None:
        # Hlavný raster sa neotvoril. Namiesto toho, aby beh skončil naprázdno,
        # skúsime pyramídy – majú 46 GB namiesto 151 GB. Model s hrubšou
        # mriežkou je viac než žiadny model.
        forced, expect_fb, info = ovr_fallback(
            args.url, member, args.work, log, args.plan, args.probe_timeout)
        if info is None:
            log("::error::Raster sa nepodarilo otvoriť ani cez pyramídy. "
                "Ak je vyššie vidieť, že adresár dlaždíc leží hlboko v súbore, "
                "je to tá príčina: člen ZIPu je deflate, takže sa GDAL k nemu "
                "dostane len rozbalením všetkého pred ním.")
            return 3
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"member={member}\n")
            f.write(f"px={info['size'][0]}x{info['size'][1]}\n")
            f.write(f"cell_m={info['pixel'][0]}\n")
            f.write(f"overviews={len(info['overviews'])}\n")

    if args.probe_only:
        log("Len sonda – nič sa nesťahovalo okrem hlavičky.")
        area_name = None
    else:
        area_name, bbox = resolve_area(args.area, args.areas)
        os.makedirs(args.out, exist_ok=True)

        # Z čoho sa bude čítať – hlavný raster, alebo pyramídy. Pri 151 GB vs
        # 46 GB je to tá jediná vec, ktorá rozhoduje o dĺžke behu, tak nech
        # je v logu vidieť, čo sa vybralo a prečo.
        if forced:
            # Hlavný raster sa neotvoril, ideme z pyramíd – nie je z čoho
            # vyberať a jemnejšie než ich mriežka to nepôjde.
            src, expect = forced, expect_fb
            if args.grid_m < info["pixel"][0]:
                log(f"::warning::Vypýtaná mriežka {args.grid_m} m je jemnejšia "
                    f"než pyramída ({info['pixel'][0]:g} m) – výsledok bude "
                    f"interpolovaný, nová informácia v ňom nepribudne.")
        else:
            src, expect = (None, None) if args.no_ovr else ovr_source(
                args.url, member, info, args.grid_m, args.work, log, args.plan,
                args.probe_timeout)
        if src is None:
            src = vsi
            main_entry = find_sidecar(args.plan, member, "")
            expect = main_entry["csize"] if main_entry else None
            log(f"Čítam hlavný raster ({(expect or 0) / 1e9:.2f} GB v archíve).")

        if bbox is None:
            whole_country(src, args.grid_m, args.work, args.out, log, expect)
        else:
            asset = args.asset or "ugkk-vyrez.tif"
            area_cut(src, bbox, args.grid_m, os.path.join(args.out, asset),
                     args.work, log, info, expect)
        made = sorted(f for f in os.listdir(args.out) if f.endswith(".tif"))
        total = sum(os.path.getsize(os.path.join(args.out, f)) for f in made)
        log(f"Hotovo: {len(made)} súborov, {total / 1048576:.0f} MB")
        if args.github_output:
            with open(args.github_output, "a") as f:
                f.write(f"files={len(made)}\n")

    if args.summary:
        with open(args.summary, "w") as f:
            f.write("## Raster priamo z archívu\n\n")
            f.write("| vec | hodnota |\n|---|---|\n")
            f.write(f"| položka | `{member}` |\n")
            f.write(f"| veľkosť | {info['size'][0]}×{info['size'][1]} px |\n")
            f.write(f"| mriežka zdroja | {info['pixel'][0]} m |\n")
            f.write(f"| CRS | {info['crs']} |\n")
            f.write(f"| kompresia | {info['compression']} |\n")
            f.write(f"| dlaždica | {info['block']} |\n")
            f.write(f"| prehľadové úrovne | {len(info['overviews'])} |\n")
            if area_name:
                f.write(f"| územie | {area_name} |\n")
                f.write(f"| cieľová mriežka | {args.grid_m} m |\n")
            f.write("\n<details><summary>Log</summary>\n\n```\n"
                    + "\n".join(lines) + "\n```\n\n</details>\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
