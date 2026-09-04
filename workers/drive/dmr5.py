#!/usr/bin/env python3
"""DMR 5.0 (ETRS89) z Google Drive → výškový model do releasu.

Dva BigTIFFy v priečinku `FOLDER_ID`, čítané cez HTTP Range a prihlásené ako
vlastník. Drive vracia `content-length: 0`, hlavičku opravuje `serve.py`; drahá
je latencia, tak sa okno krája na bloky čítané súbežne; výšky sú elipsoidické,
tak sa odčíta geoid EGM2008.

Fázy (`--stage`): `plan`, `read` (jediná siaha na sieť), `finish`, `all`.
Pri `--tiles` sa okno rozširuje na celé stupne – meno je sľub o dlaždici.

Použitie:
    python3 workers/drive/dmr5.py --area=vysoke_tatry --grid-m=1 \\
        --out=out --asset=ugkk-vysoke_tatry.tif
    python3 workers/drive/dmr5.py --area=20,49,21,50 --grid-m=5 --tiles --out=out
    python3 workers/drive/dmr5.py --auth-check
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

# kde DMR 5.0 leží – priečinok, nie dve file id: priečinok je to, čo sa naozaj
# presúva a zdieľa. Tajomstvom je token vlastníka, nie toto id.
FOLDER_ID = "1H62op_LMUYDqKeFf-_sXS-46PLEmxDyd"
TIF_NAME = "dmr5_etrs89.tif"
OVR_NAME = TIF_NAME + ".ovr"


# stav medzi fázami; `--work` medzi krokmi jobu prežije
STATE = "dmr5-drive-stav.json"

# odhad ceny čítania, na pixel ZDROJA – hrubšiu mriežku číta GDAL z pyramíd,
# ktoré majú vlastné rozlíšenie. Rádový odhad: minúty alebo hodiny.
PX_PER_MIN = 24e6         # pri --jobs=12
BYTES_PER_PX = 3.8


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne.

    Cez `sys.modules`, nech ten istý modul nevznikne dvakrát (dva bazény spojení).
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


drive = load("drive_serve", "serve.py")
auth = load("drive_auth", "auth.py")
folder = load("drive_folder", "folder.py")
raster = load("dmr5_raster", "dmr5-raster.py")

# výrez je vedľa, v `dmr5-cut.py`; tento súbor sa pýta, ako sa k dátam dostať,
# čo to bude stáť a v akých fázach. `LOG` je jeden denník, preto sa berie odtiaľ.
cut = load("dmr5_cut", "dmr5-cut.py")
LOG, log, run = cut.LOG, cut.log, cut.run
src_window, blocks, read_blocks = cut.src_window, cut.blocks, cut.read_blocks
pyramid_level = cut.pyramid_level
to_wgs84, country_tiles = cut.to_wgs84, cut.country_tiles
SRC_EPSG = cut.SRC_EPSG


def state_path(work):
    return os.path.join(work, STATE)


# fázy sú samostatné procesy – bez tohto by v súhrne ostal log poslednej
_LOG_SAVED = 0


def save_state(work, state):
    global _LOG_SAVED
    state["log"] = state.get("log", []) + LOG[_LOG_SAVED:]
    _LOG_SAVED = len(LOG)
    os.makedirs(work, exist_ok=True)
    with open(state_path(work), "w") as f:
        json.dump(state, f, indent=1)


def load_state(work):
    """Stav z fázy `plan`; keď chýba, fázy bežali v zlom poradí."""
    p = state_path(work)
    if not os.path.exists(p):
        raise SystemExit(
            f"::error::Chýba {p} – fáza sa spúšťa až po `--stage=plan`.")
    with open(p) as f:
        return json.load(f)


def credentials():
    """Prihlásenie na Drive z prostredia, alebo None.

    Chyba je `::error::` a pád: ticho prejsť na verejný denný limit sa pozná
    až vtedy, keď Drive po pol dni prestane púšťať.
    """
    try:
        creds = auth.from_env()
        if creds is None:
            return None
        # token hneď: keď ho Drive nedá, povie sa to tu a nie po hodine
        creds.token()
    except auth.AuthError as exc:
        raise SystemExit(f"::error::{exc}")
    try:
        auth.whoami(creds)
    except auth.AuthError as exc:
        # len na výpis „ktorým účtom čítame“; čítanie tým nekončí
        log(f"::warning::Účet sa nepodarilo zistiť ({exc}). Čítanie beží "
            f"prihlásené, len sa v logu nebude vedieť ktorým účtom.")
    return creds


# raz vyriešené id sa v procese nehľadajú druhýkrát
_IDS = None


def resolve_ids(creds):
    """Priečinok na Drive → (id modelu, id pyramíd). Vypíše, čo našiel.

    Hľadá sa podľa mena; keby sa model premenoval, berie sa najväčší `.tif`.
    Bez prihlásenia to nejde – obsah priečinka povie len Drive API.
    """
    global _IDS
    if _IDS is not None:
        return _IDS
    if creds is None:
        raise SystemExit(
            "::error::DMR 5.0 leží v priečinku na Drive "
            f"({FOLDER_ID}) a jeho obsah vie vypísať len prihlásený beh – "
            "Drive API anonymné požiadavky neobsluhuje. Doplň secret "
            "GDRIVE_CREDENTIALS (alebo premennú DRIVE_CLIENT a secrety "
            "DRIVE_SECRET / DRIVE_REFRESH): vyrobí ich workflow „Prihlásenie "
            "na Drive (jednorazové)“, z počítača `python3 workers/"
            "drive-auth.py --login`.")
    files, _skipped = folder.listing(creds, FOLDER_ID)
    tifs = [f for f in files if f["name"].lower().endswith(".tif")]
    ovrs = [f for f in files if f["name"].lower().endswith(".ovr")]
    if not tifs:
        raise SystemExit(
            f"::error::V priečinku {FOLDER_ID} na Drive nie je ani jeden "
            f".tif (videl som: "
            + (", ".join(f["name"] for f in files[:8]) or "nič")
            + "). Vidí naň prihlásený účet a je v ňom DMR 5.0?")
    tif = next((f for f in tifs if f["name"] == TIF_NAME),
               max(tifs, key=lambda f: f["size"]))
    ovr = next((f for f in ovrs if f["name"] == tif["name"] + ".ovr"),
               max(ovrs, key=lambda f: f["size"]) if ovrs else None)
    log(f"  priečinok {FOLDER_ID}: {len(files)} súborov")
    for f in (tif, ovr):
        if f is not None:
            log(f"    {f['name']}  {f['size'] / 2**30:.2f} GiB"
                + ("" if f["owned"] else "  (tento účet ho NEVLASTNÍ – platí "
                                         "naň denný limit sťahovania)"))
    if ovr is None:
        # nie je to chyba, ale je to drahé: hrubšie mriežky z plného 1 m rastra
        log(f"::warning::V priečinku nie je `{OVR_NAME}` (pyramídy). Hrubšie "
            f"mriežky sa budú čítať z plného 1 m rastra a potrvá to násobne "
            f"dlhšie.")
    _IDS = (tif["id"], ovr["id"] if ovr else None)
    return _IDS


def serve_drive(port=0):
    """Shim nad oboma súbormi DMR 5.0. Vracia (base, sizes, stats, creds).

    Podáva ich pod kanonickými menami – GDAL si pyramídy hľadá ako sidecar
    podľa mena vedľa hlavného súboru.
    """
    creds = credentials()
    tif_id, ovr_id = resolve_ids(creds)
    ids = {TIF_NAME: tif_id}
    if ovr_id:
        ids[OVR_NAME] = ovr_id
    base, sizes, stats = drive.serve(ids, port, creds=creds)
    return base, sizes, stats, creds


def auth_check():
    """Povedz, ktorým účtom sa bude čítať, a či na oba súbory vidí."""
    print("Prístup k DMR 5.0 na Google Drive:")
    try:
        creds = auth.from_env()
        ids = [i for i in resolve_ids(creds) if i]
        return auth.do_check(argparse.Namespace(file=ids))
    except auth.AuthError as exc:
        print(f"::error::{exc}")
        return 2


def open_source(args):
    """Shim nad Drive + otvorený raster.

    Vracia (src, env, info, native_m, stats, creds). `finish` na sieť nesiaha.
    """
    log("Otváram DMR 5.0 (ETRS89) na Drive cez lokálny shim…")
    base, sizes, stats, creds = serve_drive(args.port)
    log(f"  prístup: {auth.describe(creds)}")
    for name, size in sizes.items():
        log(f"  {name}: {size / 2**30:.2f} GiB")
    src = f"/vsicurl/{base}/{TIF_NAME}"
    env = drive.gdal_env()
    if args.geoid == "egm2008":
        # mriežku geoidu si PROJ stiahne z CDN, keď ju nemá lokálne
        env["PROJ_NETWORK"] = "ON"

    t0 = time.time()
    info = json.loads(run(["gdalinfo", "-json", "-nomd", src], env).stdout)
    ov = [o["size"] for o in info["bands"][0].get("overviews", [])]
    log(f"  otvorené za {time.time() - t0:.1f} s: "
        f"{info['size'][0]:,} × {info['size'][1]:,} px, "
        f"mriežka {abs(info['geoTransform'][1]):g} m, {len(ov)} úrovní pyramíd")
    if not ov:
        log("::warning::Pyramídy sa nenašli – hrubšie mriežky sa budú počítať "
            "z plného 1 m rastra a potrvá to násobne dlhšie.")
    return src, env, info, abs(info["geoTransform"][1]), stats, creds


def drive_totals(state, stats):
    """Prirátaj, čo z Drive prišlo v tejto fáze, k tomu z predošlých."""
    if stats is None:
        return state.get("drive_bytes", 0), state.get("drive_requests", 0)
    with stats["lock"]:
        req, got = stats["requests"], stats["bytes"]
    state["drive_bytes"] = state.get("drive_bytes", 0) + got
    state["drive_requests"] = state.get("drive_requests", 0) + req
    return state["drive_bytes"], state["drive_requests"]


def stage_plan(args):
    """Otvor zdroj, spočítaj okno a bloky a povedz, čo to bude stáť.

    Vlastná fáza preto, že je lacná a odpovedá na jedinú otázku pred hodinovým
    čítaním: koľko toho bude.
    """
    src, env, info, native_m, stats, creds = open_source(args)
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)
    wkt_file = os.path.join(args.work, "src.wkt")
    with open(wkt_file, "w") as f:
        f.write((info.get("coordinateSystem") or {}).get("wkt", ""))

    area_name, bbox = raster.resolve_area(args.area, os.path.join(_DATA, "areas.json"))

    # okno sa pri `--tiles` rozširuje na celé stupne: meno `N49E020.tif` je
    # sľub a polovičná dlaždica by v ďalšom behu prešla kontrolou ako hotová
    tiles_out = bbox is None or args.tiles
    if bbox is not None and args.tiles:
        w, s, e, n = bbox
        bbox = (float(math.floor(w)), float(math.floor(s)),
                float(math.ceil(e)), float(math.ceil(n)))
        deg = int((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        area_name += (f" → celé stupne {bbox[0]:g},{bbox[1]:g}…{bbox[2]:g},"
                      f"{bbox[3]:g} ({deg} dlaždíc)")

    log(f"Územie: {area_name}, cieľová mriežka {args.grid_m:g} m")

    if bbox is None:
        box = (info["geoTransform"][0], info["geoTransform"][3]
               + info["geoTransform"][5] * info["size"][1],
               info["geoTransform"][0] + info["geoTransform"][1] * info["size"][0],
               info["geoTransform"][3])
    else:
        box = src_window(bbox, wkt_file, info, env)
    parts, (nx, ny) = blocks(box, args.grid_m, args.jobs)

    km_x, km_y = (box[2] - box[0]) / 1000, (box[3] - box[1]) / 1000
    area_m2 = (box[2] - box[0]) * (box[3] - box[1])
    cells = area_m2 / args.grid_m ** 2

    # cena je počet pixelov, ktoré prídu z Drive, nie buniek cieľa – číta sa
    # z najhrubšej pyramídy, ktorá je ešte jemnejšia. Hovorí to `cut.pyramid_level`,
    # lebo z tej istej úrovne vyplýva aj pomer pixel/bunka a teda resampling.
    ovr_level, read_m = pyramid_level(info, native_m, args.grid_m)
    src_px = area_m2 / read_m ** 2

    # merané pri `--jobs=12`; nad ~16 vláknami Drive začne odpovedať 403
    rate = PX_PER_MIN * min(args.jobs, 16) / 12.0
    est_min = src_px / max(rate, 1.0)
    est_gb = src_px * BYTES_PER_PX / 1e9
    asset = args.asset or f"ugkk-{args.area}.tif"

    print("── Plán čítania z Drive ─────────────────────────────")
    print(f"  územie          {area_name}")
    print(f"  okno            {km_x:.1f} × {km_y:.1f} km "
          f"({km_x * km_y:.0f} km²) v EPSG:{SRC_EPSG}")
    print(f"  cieľová mriežka {args.grid_m:g} m → {cells / 1e6:.1f} mil. buniek")
    print(f"  číta sa z       {read_m:g} m "
          + ("(plné rozlíšenie)" if read_m == native_m else
             f"(pyramída, úroveň {ovr_level})")
          + f" → {src_px / 1e6:.1f} mil. px")
    # čím sa to prevzorkuje: rozdiel medzi mriežkou v tieni a hladkým reliéfom
    print(f"  prevzorkovanie  {cut.read_args(args.grid_m, read_m, ovr_level)[1]}")
    print(f"  blokov          {len(parts)} ({nx}×{ny}), {args.jobs} naraz")
    print(f"  odhad           ~{est_min:.0f} min, ~{est_gb:.2f} GB z Drive")
    print("  výstup          " + (f"1° dlaždice do {args.out}/" if tiles_out
                                  else f"{args.out}/{asset}"))
    print("  výšky           " + ("EGM2008 (≈ Bpv)" if args.geoid == "egm2008"
                                  else "elipsoidické ETRS89"))
    print("─────────────────────────────────────────────────────", flush=True)
    if est_min > 120:
        print(f"::warning::Odhad čítania je ~{est_min / 60:.1f} h. Kratšie to "
              f"ide s menším územím alebo hrubšou mriežkou (--grid-m).")

    state = {
        "area": args.area,
        "area_name": area_name,
        # ako sa k dátam pristupovalo – nesie sa, čo sa naozaj použilo
        "drive_auth": auth.describe(creds),
        "bbox": list(bbox) if bbox is not None else None,
        "box": list(box),
        "blocks": [list(p) for p in parts],
        "grid_m": args.grid_m,
        "native_m": native_m,
        # z čoho sa číta: vyrátané v pláne, použité vo fáze `read`
        "read_m": read_m,
        "ovr_level": ovr_level,
        "tiles": tiles_out,
        "geoid": args.geoid,
        "asset": asset,
        "src_px": list(info["size"]),
        "cells": cells,
        "est_min": est_min,
    }

    # rozčítané bloky sedia len na ten istý plán: blok sa pozná podľa poradového
    # čísla v mene, takže po zmene územia by mozaika bola z dvoch zadaní
    old = None
    if os.path.exists(state_path(args.work)):
        with open(state_path(args.work)) as f:
            old = json.load(f)
    same = old is not None and all(old.get(k) == state[k]
                                   for k in ("box", "blocks", "grid_m", "geoid"))
    stale = [f for f in os.listdir(args.work)
             if f.startswith("blok-") and f.endswith((".tif", ".part"))]
    if stale and not same:
        for f in stale:
            os.remove(os.path.join(args.work, f))
        log(f"  plán sa zmenil – zahodených {len(stale)} blokov z predošlého")
    elif stale:
        log(f"  {len(stale)} blokov z predošlého pokusu sedí na tento plán "
            f"a znova sa čítať nebudú")

    if same and old.get("t_start"):
        state["t_start"] = old["t_start"]
        state["drive_bytes"] = old.get("drive_bytes", 0)
        state["drive_requests"] = old.get("drive_requests", 0)
        state["log"] = old.get("log", [])
    else:
        state["t_start"] = time.time()
    drive_totals(state, stats)
    save_state(args.work, state)
    return state


def stage_read(args, state):
    """Bloky z Drive na disk. Jediná fáza, ktorá siaha na sieť – a tá dlhá."""
    src, env, _info, _native, stats, creds = open_source(args)
    state["drive_auth"] = auth.describe(creds)
    parts = [tuple(p) for p in state["blocks"]]
    log(f"  {len(parts)} blokov, {args.jobs} naraz, cieľová mriežka "
        f"{state['grid_m']:g} m")
    read_blocks(src, parts, state["grid_m"], args.work, args.jobs, env,
                state["native_m"], state.get("read_m"), state.get("ovr_level"))
    got, req = drive_totals(state, stats)
    log(f"Z Drive doteraz {got / 1e9:.2f} GB v {req:,} požiadavkách")
    save_state(args.work, state)
    return state


def stage_finish(args, state):
    """Bloky na disku → COG alebo 1° dlaždice. Na sieť sa už nesiaha."""
    env = drive.gdal_env()
    if state["geoid"] == "egm2008":
        env["PROJ_NETWORK"] = "ON"
    parts = sorted(os.path.join(args.work, f)
                   for f in os.listdir(args.work)
                   if f.startswith("blok-") and f.endswith(".tif"))
    if not parts:
        raise SystemExit(f"::error::V {args.work} nie je ani jeden blok – "
                         f"fáza `read` nebežala alebo spadla.")
    if len(parts) != len(state["blocks"]):
        raise SystemExit(
            f"::error::Na disku je {len(parts)} blokov, plán ich má "
            f"{len(state['blocks'])}. Mozaika s dierou by sa doplnila nulami "
            f"a z nuly je v mape more – spusti fázu `read` znova.")
    log(f"Skladám {len(parts)} blokov, "
        f"{sum(os.path.getsize(p) for p in parts) / 1048576:.0f} MB na disku")

    if state["tiles"]:
        # okno rozšírené na celé stupne, nech sa pod menom dlaždice neuloží
        # presah prevodu do WGS84. `None` = celé Slovensko.
        country_tiles(parts, args.out, args.work, env, state["geoid"],
                      window=state["bbox"], grid_m=state["grid_m"])
        made = sorted(f for f in os.listdir(args.out) if f.endswith(".tif"))
        log(f"Hotovo: {len(made)} dlaždíc v {args.out}")
    else:
        dest = to_wgs84(parts, os.path.join(args.out, state["asset"]),
                        state["bbox"], state["grid_m"], args.work, env,
                        state["geoid"])
        made = [os.path.basename(dest)]

    # bloky až teraz: dovtedy sú to jediné prečítané dáta
    for p in parts:
        os.remove(p)
    state["made"] = made
    save_state(args.work, state)
    return state


def write_summary(path, state):
    got = state.get("drive_bytes", 0)
    req = state.get("drive_requests", 0)
    made = state.get("made", [])
    with open(path, "w") as f:
        f.write("## DMR 5.0 (ETRS89) z Drive\n\n")
        f.write("| vec | hodnota |\n|---|---|\n")
        f.write(f"| územie | {state['area_name']} |\n")
        f.write(f"| mriežka | {state['grid_m']:g} m |\n")
        f.write(f"| okno | {(state['box'][2] - state['box'][0]) / 1000:.1f} × "
                f"{(state['box'][3] - state['box'][1]) / 1000:.1f} km, "
                f"{len(state['blocks'])} blokov |\n")
        f.write(f"| zdroj | {state['src_px'][0]:,}×{state['src_px'][1]:,} px "
                f"@ {state['native_m']:g} m, EPSG:{SRC_EPSG} |\n")
        f.write(f"| výšky | {'EGM2008 (≈ Bpv)' if state['geoid'] == 'egm2008' else 'elipsoidické ETRS89'} |\n")
        f.write(f"| z Drive | {got / 1e9:.2f} GB / {req:,} požiadaviek |\n")
        f.write(f"| prístup | {state.get('drive_auth', '?')} |\n")
        f.write(f"| trvanie | {(time.time() - state['t_start']) / 60:.1f} min "
                f"(odhad bol {state['est_min']:.0f} min) |\n")
        f.write(f"| výstup | {', '.join(f'`{m}`' for m in made[:12]) or '–'} |\n")
        f.write("\n<details><summary>Log</summary>\n\n```\n"
                + "\n".join(state.get("log", []) + LOG[_LOG_SAVED:])
                + "\n```\n\n</details>\n")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", default="cele_slovensko",
                    help="kľúč z workers/data/areas.json, `cele_slovensko`, alebo bbox W,S,E,N")
    ap.add_argument("--grid-m", type=float, default=1.0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--work", default="drive-work")
    ap.add_argument("--asset", default=None,
                    help="meno výsledku pri výreze; predvolene ugkk-<area>.tif. "
                         "Pri bboxe v --area je povinné – `ugkk-20,49,21,50.tif` "
                         "si build vypýtať nevie.")
    ap.add_argument("--jobs", type=int, default=12,
                    help="koľko blokov sa číta naraz; nad ~16 začne Drive "
                         "odpovedať 403 a čakanie zožerie viac, než sa získa")
    ap.add_argument("--geoid", choices=("egm2008", "elipsoid"), default="egm2008")
    ap.add_argument("--tiles", action="store_true",
                    help="výstup sú 1° dlaždice (dem-dmr5) aj pri zadanom "
                         "výreze – okno sa rozšíri na celé stupne. Bez toho "
                         "je z výrezu jeden COG (dem-ugkk).")
    ap.add_argument("--stage", choices=("all", "plan", "read", "finish"),
                    default="all",
                    help="ktorú fázu spustiť; stav si podávajú cez --work")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--probe-only", action="store_true",
                    help="len otvor zdroj a vypíš, čo v ňom je")
    ap.add_argument("--auth-check", action="store_true",
                    help="povedz, ktorým účtom sa bude z Drive čítať a či "
                         "na oba súbory vidí; nič sa nečíta")
    ap.add_argument("--summary", default=None)
    args = ap.parse_args()

    if args.auth_check:
        return auth_check()

    if args.probe_only:
        _src, _env, info, native_m, _stats, _creds = open_source(args)
        log(f"  CRS: {(info.get('coordinateSystem') or {}).get('wkt', '')[:80]}…")
        log(f"  origin: {info['geoTransform'][0]}, {info['geoTransform'][3]}")
        for i, o in enumerate(info["bands"][0].get("overviews", [])):
            w, h = o["size"]
            log(f"    úroveň {i}: {w:,} × {h:,} px = "
                f"{native_m * info['size'][0] / w:.0f} m")
        return 0

    # fázy sa reťazia zhora nadol; `all` je všetky tri v jednom procese
    state = None
    if args.stage in ("all", "plan"):
        state = stage_plan(args)
    if args.stage in ("all", "read"):
        state = stage_read(args, state or load_state(args.work))
    if args.stage in ("all", "finish"):
        state = stage_finish(args, state or load_state(args.work))
        got, req = state.get("drive_bytes", 0), state.get("drive_requests", 0)
        log(f"Z Drive prišlo {got / 1e9:.2f} GB v {req:,} požiadavkách, "
            f"celý beh {(time.time() - state['t_start']) / 60:.1f} min")

    if args.summary:
        write_summary(args.summary, state or load_state(args.work))
    return 0


if __name__ == "__main__":
    sys.exit(main())
