#!/usr/bin/env python3
"""Skaly z tieňovaných dlaždíc (JPG) → vektorové plochy (GeoPackage).

Pokusná druhá cesta k skalám; tá prvá (`contours-rocks/rock-areas.py`) počíta
sklon z DEM. Táto hľadá v hotovom hillshade tmavé plochy:

    XYZ dlaždice (JPG) → mozaika šedej v EPSG:3857 → raster „tmavosti“ →
    otvorenie → gdal_contour -p → filter plôch → zaoblenie → rock.gpkg

Tmavý ale nie je len sklon, ale sklon na odvrátenej strane, takže táto cesta
systematicky nájde severozápadné steny a prehliadne juhovýchodné.

Prah sa skladá z troch čísel:

    ref   = clip(miestne_pozadie − --rel, --dark-always, --dark)
    score = max(0, ref − šedá)

Miestne pozadie je priemer tých svetlejších pixelov v okne, aby ho nestiahlo
to, čo práve hľadáme. Bez `--dark-always` sa veľká súvislá stena nenájde
(okno pozadia sa zmestí dovnútra nej).

Vektorizuje sa po blokoch (`--block-tiles`): nad celou mozaikou skladanie
prstencov rástlo rýchlejšie než lineárne a nedopočítalo sa. Plochu cez hranicu
bloku zlepí `zlep_svy()`.

Rozrobené leží v `<cache-dir>/_rozrobene/<podpis prahov>/` a ďalší beh naň
nadviaže; každá fáza sa píše do `.part`. Po úspechu sa maže, `--fresh=1` ho
zahodí dopredu.

Použitie:
    python3 workers/rocks-shading/build.py --bbox=19.9,49.09,20.32,49.25 \\
        --zoom=auto --dark=110 --local=512 --rel=18 --cliff=25 --open=3 \\
        --out=data/rock.gpkg --stats=out/rock-img-stats.txt \\
        --preview=out/preview.png
"""
import argparse
import importlib.util
import math
import os
import shlex
import shutil
import sys
import time

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# tri fázy, tri moduly – v tom poradí, v akom ich robia joby `shading-rocks.yml`:
#   tiles.py   stiahni JPG dlaždice, raster.py   raster tmavosti,
#   vector.py  obrysy po blokoch, švy, filter, vyhladenie
tiles = load("shading_tiles", "tiles.py")
raster = load("shading_raster", "raster.py")
vector = load("shading_vector", "vector.py")

# čo si tento súbor z ktorej fázy berie
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
TILES_PER_S, CONTOUR_CELLS_PER_S = tiles.TILES_PER_S, tiles.CONTOUR_CELLS_PER_S
BG_DOWN = raster.BG_DOWN
run = tiles.run
tile_range, tile_res, ground_res = tiles.tile_range, tiles.tile_res, tiles.ground_res
Fetcher, probe_zoom, BROWSERS = tiles.Fetcher, tiles.probe_zoom, tiles.BROWSERS
build_score_raster = raster.build_score_raster
bbox_km2, obrysy, spoj, empty_rock = (vector.bbox_km2, vector.obrysy, vector.spoj,
                                      vector.empty_rock)
zapis_stiahnute, nacitaj_stiahnute = vector.zapis_stiahnute, vector.nacitaj_stiahnute

# `watch.py` je spoločný pre obe cesty ku skalám, tak leží vo `workers/lib/`
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb  # noqa: E402


def save_preview(rows, path):
    """Zmenšená mozaika vedľa nájdených plôch – aby sa prahy dali doladiť
    pohľadom, nie hádaním. Vľavo šedá, vpravo to isté s červenou maskou."""
    if not rows:
        return
    gray = np.concatenate([g for g, _ in rows], axis=0)
    mask = np.concatenate([m for _, m in rows], axis=0)
    rgb = np.dstack([gray, gray, gray])
    hit = mask > 0
    rgb[..., 0] = np.where(hit, 255, rgb[..., 0])
    rgb[..., 1] = np.where(hit, (gray * 0.35).astype(np.uint8), rgb[..., 1])
    rgb[..., 2] = np.where(hit, (gray * 0.35).astype(np.uint8), rgb[..., 2])
    both = np.concatenate([np.dstack([gray, gray, gray]), rgb], axis=1)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(both).save(path)
    print(f"  náhľad: {path} ({both.shape[1]}×{both.shape[0]} px)", flush=True)


def histogram(rows):
    """Rozloženie odtieňov šedej – prvé, čo treba vidieť pri ladení prahu."""
    if not rows:
        return ""
    gray = np.concatenate([g for g, _ in rows], axis=0)
    hist, _ = np.histogram(gray, bins=16, range=(0, 256))
    tot = max(1, hist.sum())
    out = ["  šedá     podiel"]
    for i, v in enumerate(hist):
        pct = 100.0 * v / tot
        out.append(f"  {i * 16:>3}–{i * 16 + 15:<3} {pct:5.1f} % "
                   f"{'█' * int(round(pct / 2))}")
    return "\n".join(out)


def print_plan(z, x0, y0, x1, y1, args):
    n_tiles = (x1 - x0) * (y1 - y0)
    cells = n_tiles * TILE * TILE
    dl_s = n_tiles / TILES_PER_S
    ct_s = cells / CONTOUR_CELLS_PER_S
    print("── Plán: skaly z tieňovaných dlaždíc ────────────────")
    print(f"  zoom            z{z}  ({tile_res(z):.2f} m/px v Mercatore, "
          f"~{ground_res(z, (args.bbox[1] + args.bbox[3]) / 2):.2f} m na zemi)")
    print(f"  dlaždice        {x1 - x0} × {y1 - y0} = {n_tiles}")
    print(f"  mozaika         {(x1 - x0) * TILE} × {(y1 - y0) * TILE} px "
          f"= {cells / 1e9:.2f} mld.")
    print(f"  prah tmavosti   nikdy nad {args.dark}, vždy pod {args.dark_always}"
          + (f", medzi tým {args.rel} pod pozadím "
             f"(okno {args.local:g} m = {args.local_px} px)"
             if args.local_px else ", bez miestneho pozadia"))
    print(f"  triedy          steep, cliff od {args.cliff} stupňov navyše")
    print("  užšie než       " + (f"{2 * args.open:g} m preč "
                                  f"(otvorenie {args.open_px} px) – "
                                  f"vlásočnice nie sú stena"
                                  if args.open_px else
                                  "nič (otvorenie vypnuté)"))
    print("  štruktúra       " + (f"vyplnená, okno {args.fill:g} m "
                                  f"({args.fill_px} px)" if args.fill_px
                                  else "jemná sieť žliabkov (fill vypnuté)"))
    print("  hlavičky        " + ("každý request ako iný prehliadač "
                                  f"({len(BROWSERS)} profilov)"
                                  if args.ua == "rotate" else
                                  "meno projektu" if args.ua == "project"
                                  else f"vlastné: {args.ua}"))
    print(f"  odhad sťahovanie ~{hms(dl_s)}")
    print(f"  odhad obrysy     ~{hms(ct_s)}")
    print("─────────────────────────────────────────────────────", flush=True)
    return n_tiles, cells


def apply_options(ap, args):
    """`kľúč=hodnota` z jedného textového poľa → tie isté prepínače.

    Rozkladá sa to tu a nie v YAMLe: prepínače pozná argparse, nie shell,
    takže preklep vypadne ako hláška.
    """
    raw = (args.options or "").strip()
    if not raw:
        return args
    known = {a.dest for a in ap._actions if a.dest not in ("help", "options")}
    extra = []
    for tok in shlex.split(raw):
        if "=" not in tok:
            print(f"::error::Voľba „{tok}“ nemá tvar kľúč=hodnota.",
                  file=sys.stderr)
            sys.exit(1)
        k, v = tok.split("=", 1)
        k = k.strip().replace("-", "_")
        if k not in known:
            print(f"::error::Neznáma voľba „{k}“. Známe voľby: "
                  f"{', '.join(sorted(known))}", file=sys.stderr)
            sys.exit(1)
        extra.append(f"--{k.replace('_', '-')}={v}")
    print(f"Z options: {' '.join(extra)}", flush=True)
    return ap.parse_args(sys.argv[1:] + extra)


def main():
    ap = argparse.ArgumentParser(
        description="Skalné plochy z tmavých miest v tieňovaných dlaždiciach.")
    ap.add_argument("--bbox", required=True, help="W,S,E,N v stupňoch")
    ap.add_argument("--url", default="https://sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg",
                    help="XYZ šablóna s {z}/{x}/{y}")
    ap.add_argument("--zoom", default="auto", help="číslo alebo `auto`")
    # z17 je strop: na z18 sú to 4× dlaždice, obrysy rastú ešte rýchlejšie
    # a mapa z toho nemá nič (plocha sa naťahuje overzoomom)
    ap.add_argument("--zoom-max", type=int, default=17,
                    help="najvyšší zoom, na ktorý sa vôbec pýtame dlaždíc "
                         "(odtiaľ `auto` skúša nadol)")
    ap.add_argument("--zoom-min", type=int, default=12)
    ap.add_argument("--max-tiles", type=int, default=60000,
                    help="strop na počet dlaždíc – `auto` pod neho zíde sám")
    # číslo, nie `store_true`: voľby chodia vždy ako `kľúč=hodnota`
    ap.add_argument("--block-tiles", type=int, default=8,
                    help="strana bloku v dlaždiciach pri obrysoch; menší blok "
                         "= menej pamäte a jemnejšie pokračovanie, ale viac "
                         "volaní GDALu (8 = 2048 px, 3 = 768 px)")
    # tri joby, každý s vlastným stropom času; medzivýsledky si podávajú cez
    # cache. `vsetko` je to isté v jednom kuse.
    ap.add_argument("--phase", default="vsetko",
                    choices=("vsetko", "stiahnut", "vektor", "spojit"),
                    help="ktorú časť spraviť")
    ap.add_argument("--zoom-out", default="",
                    help="kam zapísať vybraný zoom (`zoom=17`) pre ďalší job")
    ap.add_argument("--fresh", type=int, default=0,
                    help="1 = zahodiť rozrobené z predošlého behu a počítať "
                         "všetko odznova (dlaždice ostávajú v cache)")
    ap.add_argument("--log-every", type=int, default=25,
                    help="po koľkých dlaždiciach vypísať riadok "
                         "(1 = každá, 0 = len každých 15 s)")
    # 0 = bez stropu. Zastavenie v polovici obrysov nikdy nič nezachránilo.
    ap.add_argument("--budget-min", type=float, default=0,
                    help="koľko minút smú trvať obrysy; `auto` pod to zíde "
                         "sám a beh sa nad tým zastaví (0 = bez stropu, "
                         "predvolené)")
    ap.add_argument("--dark", type=int, default=125,
                    help="absolútny strop: nad touto šedou nie je skala nikdy")
    ap.add_argument("--dark-always", type=int, default=70,
                    help="pod touto šedou je skala vždy, nech je okolo čokoľvek")
    ap.add_argument("--local", type=float, default=1500.0,
                    help="okno miestneho pozadia v METROCH na zemi (0 = vypnuté)")
    ap.add_argument("--rel", type=int, default=18,
                    help="o koľko musí byť pixel pod miestnym pozadím")
    ap.add_argument("--cliff", type=int, default=25,
                    help="o koľko stupňov tmavšie začína trieda `cliff`")
    ap.add_argument("--blur", type=int, default=1,
                    help="polomer vyhladenia šedej v px (0 = vypnuté, max 2)")
    ap.add_argument("--fill", type=float, default=0.0,
                    help="spriemerovať tmavosť v okne toľkých METROV – zo "
                         "siete žliabkov spraví súvislú plochu (0 = vypnuté)")
    # vlásočnicové ryhy sú tmavé, ale nie sú steny – v mape z nich je sivá
    # deka. Mažú sa podľa šírky: celá sieť je jeden útvar, `min_area` nesiaha.
    ap.add_argument("--open", type=float, default=3.0,
                    help="zmazať útvary užšie než 2× toľko METROV "
                         "(0 = vypnuté, necháva aj vlásočnice)")
    # ~11 pixelov na z17; jemná sieť žliabkov je to, čo z hillshade chceme
    ap.add_argument("--min-area", type=float, default=7.0,
                    help="najmenšia skalná plocha v m²")
    # plné plochy: bez dier a bez druhého pásma
    ap.add_argument("--plne", type=int, default=1,
                    help="1 = jedno pásmo a jedna trieda (žiadna plocha "
                         "vnútri inej), 0 = pásma steep/cliff ako predtým")
    # diery sú medzery medzi vláknami siete – zapĺňanie z nich spravilo klaksy
    ap.add_argument("--zapln-diery", type=int, default=0,
                    help="1 = zaplniť diery (súvislé plochy namiesto siete)")
    ap.add_argument("--zlepit", type=int, default=0,
                    help="1 = zlepiť plochy rozseknuté hranicou bloku "
                         "(ST_Union, potrebuje spatialite)")
    ap.add_argument("--min-hole", type=float, default=10.0,
                    help="najmenšia diera, ktorá sa zachová, v m²")
    ap.add_argument("--simplify", type=float, default=-1,
                    help="zjednodušenie obrysu v metroch (-1 = jeden pixel)")
    ap.add_argument("--smooth", type=int, default=2,
                    help="dovolený priehyb zaobleného obrysu v ŠTVRTINÁCH "
                         "kroku mriežky dlaždice (0 = zaoblenie vypnuté)")
    # z maxzoomu vyjde krok mriežky, podľa ktorého sa obrys vzorkuje
    ap.add_argument("--maxzoom", type=int, default=16,
                    help="maxzoom dlaždíc so skalami (mriežka `extent`)")
    ap.add_argument("--jobs", type=int, default=12, help="paralelné sťahovanie")
    ap.add_argument("--ua", default="rotate",
                    help="`rotate` = každý request ako iný prehliadač, "
                         "`project` = priznať sa menom projektu, alebo "
                         "vlastný User-Agent doslova")
    ap.add_argument("--cache-dir", default="tiles-cache")
    ap.add_argument("--band-cells", type=float, default=150e6,
                    help="koľko pixelov naraz drží jeden pás v pamäti")
    ap.add_argument("--heartbeat", type=int, default=30)
    ap.add_argument("--preview", default="", help="kam uložiť náhľad PNG")
    ap.add_argument("--preview-down", type=int, default=16,
                    help="koľkokrát zmenšiť náhľad")
    ap.add_argument("--stats", default="", help="kam zapísať kľúč=hodnota")
    ap.add_argument("--options", default="",
                    help="zriedka menené prepínače ako `kľúč=hodnota`, "
                         "napr. `local=800 min_area=300`")
    ap.add_argument("--out", required=True)
    args = apply_options(ap, ap.parse_args())

    args.bbox = [float(v) for v in args.bbox.split(",")]
    if len(args.bbox) != 4:
        print("::error::--bbox musí byť W,S,E,N.", file=sys.stderr)
        return 1
    args.blur = max(0, min(2, args.blur))
    lat_mid = (args.bbox[1] + args.bbox[3]) / 2.0

    os.makedirs(args.cache_dir, exist_ok=True)
    fetcher = Fetcher(args.url, args.cache_dir, jobs=args.jobs, ua=args.ua,
                      log_every=args.log_every)

    if str(args.zoom).strip().lower() == "auto":
        z = probe_zoom(fetcher, args.bbox, args.zoom_max, args.zoom_min,
                       args.max_tiles, args.budget_min * 60)
        if not z:
            return 1
    else:
        z = int(args.zoom)

    # okno pozadia je zadané v metroch; v pixeloch je až tu, keď je známy zoom
    args.local_px = (int(round(args.local / ground_res(z, lat_mid)))
                     if args.local > 0 else 0)
    args.fill_px = (int(round(args.fill / ground_res(z, lat_mid)))
                    if args.fill > 0 else 0)
    args.open_px = (max(1, int(round(args.open / ground_res(z, lat_mid))))
                    if args.open > 0 else 0)
    x0, y0, x1, y1 = tile_range(args.bbox, z)
    n_tiles, cells = print_plan(z, x0, y0, x1, y1, args)
    if n_tiles > args.max_tiles:
        print(f"::error::z{z} má {n_tiles} dlaždíc, strop je {args.max_tiles}. "
              f"Zvoľ menší výrez alebo nižší zoom (alebo zdvihni --max-tiles).",
              file=sys.stderr)
        return 2

    if args.simplify < 0:
        # jeden pixel, nie štvrtina: zdroj je 8-bitový JPEG, pod pixel je zrno
        args.simplify = tile_res(z)

    # pracovný priečinok leží v cache dlaždíc – tá sa ukladá aj po páde.
    # Podpis v mene: iné prahy = iný medzivýsledok, dva behy sa nepomiešajú.
    podpis = (f"z{z}-d{args.dark}-a{args.dark_always}-r{args.rel}"
              f"-c{args.cliff}-l{args.local:g}-f{args.fill:g}-b{int(args.blur)}"
              # otvorenie mení raster tmavosti, teda aj obrysy v blokoch
              f"-o{args.open:g}"
              f"-m{args.min_area:g}-h{args.min_hole:g}"
              # plné plochy menia pásma, teda aj obsah blokov
              f"{'-plne' if args.plne else ''}"
              f"-zd{int(bool(args.zapln_diery))}")
    tmp = os.path.join(args.cache_dir, "_rozrobene", podpis)
    # `fresh` je vec fáz, ktoré rozrobené vyrábajú; `spojit` ho len číta
    # a zmazala by prácu, ktorú pred chvíľou vyrobil job vedľa
    if args.fresh and args.phase != "spojit":
        shutil.rmtree(tmp, ignore_errors=True)
    elif args.fresh:
        print("  `fresh` sa vo fáze `spojit` ignoruje: zlepuje sa to, čo "
              "vyrobila fáza `vektor` v tomto behu.", flush=True)
    os.makedirs(tmp, exist_ok=True)
    if os.listdir(tmp):
        print(f"── Rozrobené z predošlého behu ──────────────────────")
        print(f"  {tmp}")
        for f in sorted(os.listdir(tmp)):
            print(f"    {f}  {dir_mb(os.path.join(tmp, f)):.0f} MB")
        print("  hotové fázy sa preskočia; `options: fresh=true` to zahodí")
        print("─────────────────────────────────────────────────────", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    t_all = time.time()
    # prah 0,5, nie 1: izolínia v polovici kroku dá sub-pixelový obrys
    cliff_level = 0.5 + args.cliff
    merc = math.cos(math.radians(lat_mid)) ** 2
    dl_s = sc_s = vec_s = 0.0

    if args.phase == "spojit":
        # zlepovanie číta obrysy blokov, nie obrázky
        print("── Dlaždice: preskočené (fáza spojenia) ─────────────", flush=True)
        dl = nacitaj_stiahnute(args.cache_dir, n_tiles)
    else:
        print("── Sťahovanie dlaždíc ───────────────────────────────", flush=True)
        dl_s = fetcher.fetch_all(z, x0, y0, x1, y1)
        if fetcher.n_ok + fetcher.n_cached == 0:
            print("::error::Nestiahla sa ani jedna dlaždica – bez dát sa nedá "
                  "nič vektorizovať.", file=sys.stderr)
            return 1
        dl = zapis_stiahnute(args.cache_dir, fetcher, n_tiles)

        # vybraný zoom von, nech ho ďalší job nemusí hádať znova
        if args.zoom_out:
            with open(args.zoom_out, "a") as f:
                f.write(f"zoom={z}\n")

        if args.phase == "stiahnut":
            print("── Hotovo (len sťahovanie) ──────────────────────────")
            print(f"  zoom            z{z}")
            print(f"  dlaždice        {n_tiles} ({fetcher.bytes / 1048576:.0f} MB "
                  f"stiahnutých, {fetcher.n_cached} z cache)")
            print(f"  čas             {hms(dl_s)}")
            print("  Vektorizácia je vlastný job – dlaždice si vezme z cache.")
            print("─────────────────────────────────────────────────────", flush=True)
            return 0

    if args.phase != "spojit":
        print("── Raster tmavosti ──────────────────────────────────", flush=True)
        preview_rows = [] if args.preview else None
        tifs, sc_s = build_score_raster(fetcher, z, x0, y0, x1, y1, args, tmp,
                                        preview_rows)

        print("── Obrysy po blokoch ────────────────────────────────", flush=True)
        t_vec = time.time()
        try:
            n_blokov = obrysy(tifs, args, tmp, cliff_level)
        except RuntimeError as exc:
            # hláška je zrozumiteľná, traceback nie
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        except TimeoutError:
            # odhad bol vedľa; stiahnuté dlaždice ostávajú v cache
            print(f"::error::Obrysy sa nestihli do {args.budget_min:g} min. "
                  f"Skús nižší zoom (`zoom: {z - 1}`), menší výrez, alebo "
                  f"zdvihni rozpočet (`options: budget_min=…`). Dlaždice sú "
                  f"v cache, takže ďalší beh ich neťahá znova.",
                  file=sys.stderr)
            return 2
        vec_s = time.time() - t_vec

        # náhľad a histogram vznikajú pri rastri, nie z hotových polygónov
        if args.preview:
            save_preview(preview_rows, args.preview)
        hist = histogram(preview_rows) if preview_rows else ""
        if hist:
            print("── Rozloženie odtieňov šedej ────────────────────────")
            print(hist)
            print("─────────────────────────────────────────────────────",
                  flush=True)

        if args.phase == "vektor":
            print("── Hotovo (len obrysy) ──────────────────────────────")
            print(f"  bloky           {n_blokov}")
            print(f"  čas             tmavosť {hms(sc_s)}, obrysy {hms(vec_s)}")
            print("  Zlepenie, filter a vyhladenie sú vlastný job – "
                  "rozrobené si vezme z cache.")
            print("─────────────────────────────────────────────────────",
                  flush=True)
            return 0

    print("── Spojenie blokov a filter ─────────────────────────", flush=True)
    t_sp = time.time()
    try:
        st = spoj(args, tmp, args.out, cliff_level, merc,
                  uzemie_km2=bbox_km2(args.bbox))
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    sp_s = time.time() - t_sp
    if not st.get("n"):
        print("::warning::Nenašla sa ani jedna skalná plocha – prahy sú "
              "pravdepodobne prísne. Pozri náhľad a histogram z fázy obrysov.")
        empty_rock(args.out)

    total_km2 = st.get("total_m2", 0.0) / 1e6
    print("── Hotovo ───────────────────────────────────────────")
    print(f"  plôch           {st.get('n', 0)} "
          f"(z toho {st.get('cliff', 0)} `cliff`), "
          f"{st.get('n_in', 0) - st.get('n', 0)} pod {args.min_area:g} m² preč")
    print(f"  spolu           {total_km2:.2f} km², "
          f"najväčšia {st.get('max_m2', 0) / 1e4:.1f} ha")
    print(f"  diery           {st.get('holes', 0)}")
    # koľko dát na km² skál – to rozhoduje o rozpočte, nie počet plôch
    out_mb = dir_mb(args.out)
    per_km2 = out_mb / total_km2 if total_km2 > 0.001 else 0.0
    print(f"  výstup          {args.out} ({out_mb:.1f} MB"
          + (f", {per_km2:.1f} MB na km² skál)" if per_km2 else ")"))
    print(f"  čas             sťahovanie {hms(dl_s)}, tmavosť {hms(sc_s)}, "
          f"obrysy {hms(vec_s)}, spojenie {hms(sp_s)}, "
          f"spolu {hms(time.time() - t_all)}")
    if args.phase == "spojit":
        print("  (čas sťahovania a obrysov je z ich vlastných jobov)")
    print("─────────────────────────────────────────────────────", flush=True)

    if args.stats:
        os.makedirs(os.path.dirname(os.path.abspath(args.stats)) or ".",
                    exist_ok=True)
        with open(args.stats, "w") as f:
            for k, v in [
                ("count", st.get("n", 0)), ("cliff", st.get("cliff", 0)),
                ("total_km2", f"{total_km2:.3f}"),
                ("max_m2", int(st.get("max_m2", 0))),
                ("holes", st.get("holes", 0)),
                ("holes_dropped", st.get("holes_dropped", 0)),
                ("dropped", st.get("n_in", 0) - st.get("n", 0)),
                ("zoom", z), ("tiles", dl["tiles"]),
                ("tiles_missing", dl["tiles_missing"]),
                ("tiles_failed", dl["tiles_failed"]),
                ("mb_downloaded", dl["mb_downloaded"]),
                ("ua", args.ua), ("ua_profiles", dl["ua_profiles"]),
                ("cells", cells), ("px_m", f"{ground_res(z, lat_mid):.2f}"),
                ("dark", args.dark), ("dark_always", args.dark_always),
                ("local_m", f"{args.local:g}"), ("local_px", args.local_px),
                ("rel", args.rel),
                ("cliff_delta", args.cliff), ("blur", args.blur),
                ("fill_m", f"{args.fill:g}"),
                ("open_m", f"{args.open:g}"), ("open_px", args.open_px),
                ("out_mb", f"{out_mb:.1f}"), ("mb_per_km2", f"{per_km2:.1f}"),
                ("min_area_m2", f"{args.min_area:g}"),
                ("plne", int(bool(args.plne))),
                ("zapln_diery", int(bool(args.zapln_diery))),
                ("zlepene", int(bool(args.zlepit))),
                ("min_hole_m2", f"{args.min_hole:g}"),
                ("simplify_m", f"{args.simplify:.2f}"), ("smooth", args.smooth),
                ("seconds", int(time.time() - t_all)),
            ]:
                f.write(f"{k}={v}\n")

    # až teraz: inak by cache rástla o medzivýsledky každého behu
    shutil.rmtree(tmp, ignore_errors=True)
    print("Rozrobené zmazané – beh dobehol celý.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
