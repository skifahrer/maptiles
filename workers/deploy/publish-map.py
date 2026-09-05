#!/usr/bin/env python3
"""Zabalí `_site` do balíkov so stálym menom a nahrá ich na Drive.

Zoznam balíkov drží `workers/data/packages.json`. Meno je stále, aby ďalší
build prepísal obsah toho istého súboru a odkaz v `maps.json` platil ďalej.
Čo je v balíku, hovorí `obsah.json` vnútri. Glyfy a viewer sa nebalia,
vrstvy z výškového modelu majú vlastné balíky.
"""
import argparse
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
_DRIVE = os.path.join(_WORKERS, "drive")


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pack = load("deploy_pack", "pack.py")
catalog = load("deploy_catalog", "catalog.py")
subory = load("deploy_subory", "subory.py")
katalog_balikov = load("deploy_baliky", "baliky.py")
baliky_vrstiev = subory.baliky_vrstiev
casti_baliku = subory.casti_baliku
kde_su_glyfy = subory.kde_su_glyfy
manifest_data = subory.manifest_data
mimo_balika = subory.mimo_balika
velkost_casti = subory.velkost_casti
vsetky_subory = subory.vsetky_subory
obsah_sha = subory.obsah_sha
zaklad_subory = subory.zaklad_subory
mena = load("deploy_mena", "mena.py")
bez_testu = mena.bez_testu
cesta = mena.cesta
cesta_katalog = mena.cesta_katalog
env = mena.env
meno = mena.meno
safe = mena.safe
vrstvy = mena.vrstvy
BALICE = pack.BALICE
aa_je = pack.aa_je
auth = load("drive_auth", os.path.join(_DRIVE, "auth.py"))
folder = load("drive_folder", os.path.join(_DRIVE, "folder.py"))

# id priečinka nie je tajomstvo, tajomstvom je token
FOLDER_ID = "1pvrw7CGUkQLwg8Ql8xbKA4HhQHvPl8_7"

# zrušené balíky sa na Drive mažú, inak by v katalógu ostal mŕtvy odkaz
ZRUSENE = katalog_balikov.zrusene()


def log(msg):
    print(msg, flush=True)


def obsah(kind, man, fmt="zip", casti=None):
    """`obsah.json` do balíka – to, čo kedysi nieslo meno súboru."""
    reg = catalog.region_entry(man)
    return {
        "balik": kind or "mapa",
        # časti sú vec základnej mapy
        **({"casti": velkost_casti(casti)} if not kind and casti else {}),
        # aj s príponou formátu: .aar nesmie o sebe tvrdiť, že je zip
        "subor": meno(kind, fmt),
        "format": fmt,
        "region": bez_testu(env("REGION_KEY")),
        "vyrez": bez_testu(env("AREA_KEY")) or "cely",
        "test_km2": env("TEST_KM2", "0"),
        "tiles_maxzoom": env("TILES_MAXZOOM"),
        "vrstvy": vrstvy(),
        # glyfy sa nebalia nikdy; pole ostáva, aby bolo vidieť, že chýbajú
        "bez_glyfov": True,
        "glyphs": man.get("glyphs") or "",
        "glyfy_kde": kde_su_glyfy(man),
        "bez_viewera": True,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run": env("GITHUB_RUN_NUMBER"),
        "run_id": env("GITHUB_RUN_ID"),
        "manifest": {"dem": man.get("dem"),
                     "dem_maxzoom": man.get("dem_maxzoom"),
                     "dem_source": man.get("dem_source"),
                     # appka podľa toho ponúka vrstvu „3D terén"; `dem` na to
                     # nestačí – dlaždice môžu byť a 3D vypnuté
                     "terrain_3d": man.get("terrain_3d"),
                     "terrain_exaggeration": man.get("terrain_exaggeration"),
                     "region": reg},
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default="_site", help="čo sa balí")
    # zip vždy, .aar navyše pre Apple; formáty sa pridávajú, neprepínajú
    ap.add_argument("--format", default="zip",
                    help="ktoré formáty vyrobiť: `zip`, `aar`, `zip,aar`")
    ap.add_argument("--folder", default=FOLDER_ID,
                    help="priečinok na Drive (URL alebo id)")
    ap.add_argument("--out", default="", help="kam odložiť ZIP (default RUNNER_TEMP)")
    ap.add_argument("--keep-zip", action="store_true",
                    help="nechať ZIP na disku aj po nahratí")
    ap.add_argument("--dry-run", action="store_true",
                    help="povedz mená a cestu, ale nič nebaľ ani nenahrávaj")
    ap.add_argument("--zip-only", action="store_true",
                    help="zabaľ do --out a na Drive nesiahaj (lokálna skúška)")
    ap.add_argument("--summary", default="", help="kam dopísať súhrn")
    ap.add_argument("--wiki", default="",
                    help="priečinok s článkami z Wikipédie (balík `wikipedia`); "
                         "prázdne = ten balík sa nepublikuje a starý sa zmaže")
    ap.add_argument("--only", default="",
                    help="publikuj LEN tento balík (napr. `wikipedia`) a "
                         "katalóg dopĺň, nie prepisuj – na samostatné "
                         "pipeline, ktoré nerobia celú mapu")
    ap.add_argument("--maps", default=catalog.KATALOG,
                    help="katalóg hotových máp v repozitári (prázdne = "
                         "nezapisuj). Pri rýchlom teste sa z neho stane "
                         "`maps-test.json` – rozhoduje o tom `catalog.py`.")
    args = ap.parse_args()

    # test zapisuje do vlastného súboru (`catalog.katalog_subor`)
    args.maps = catalog.katalog_subor(args.maps)
    # ten istý súbor commituje catalog.sh – podáva sa výstupom kroku
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out and args.maps:
        with open(gh_out, "a") as f:
            f.write(f"maps_file={args.maps}\n")
    if args.maps != catalog.KATALOG:
        log(f"Katalóg tohto behu: {args.maps} (rýchly test – hotové mapy sú "
            f"v {catalog.KATALOG})")

    with open(os.path.join(_DATA, "regions.json")) as f:
        regions = json.load(f)

    formaty = [f.strip() for f in args.format.split(",") if f.strip()]
    for f in formaty:
        if f not in BALICE:
            raise SystemExit(f"::error::Neznámy formát „{f}“. Známe: "
                             f"{', '.join(BALICE)}.")
    if "aar" in formaty and not aa_je():
        # ticho preskočiť sa nesmie; `aa` je len na macOS
        raise SystemExit("::error::Apple Archive sa nedá vyrobiť – nástroj "
                         "`aa` tu nie je. Je súčasťou macOS (11+), takže "
                         "`--format` s `aar` patrí do jobu na `macos-latest`; "
                         "na Linuxe nechaj `--format=zip`.")

    parts = cesta(regions)
    man = manifest_data(args.site)
    # balíky v jednom zozname: druh, obsah, popis, báza ciest v archíve.
    # Vlastné balíky sa počítajú pred základnou mapou – tá ich vynecháva.
    vrstvove_baliky = baliky_vrstiev(args.site, man)
    # časti základnej mapy: nevynímajú sa z nej, merajú sa do katalógu
    casti = [] if args.only else casti_baliku(args.site, man)
    # viewer a glyfy sa nebalia; musí byť vidieť, koľko toho balík nenesie
    von_pack, von_dovody = mimo_balika(args.site, man)
    for popis, kolko, bajtov in von_dovody:
        log(f"Do balíka nejde {popis}: {kolko} súborov, "
            f"{folder.human(bajtov)}")
    for kluc, popis, subory in casti:
        log(f"V základnej mape je časť `{kluc}` – {popis}: "
            + (f"{len(subory)} súborov, "
               f"{folder.human(sum(os.path.getsize(p) for p in subory))}"
               if subory else "TENTO BUILD JU NEVYROBIL, v mape nebude"))
    # zo základnej mapy von: súbory vlastných balíkov + čo tam nemá čo robiť
    vylucit = [p for _b, subory in vrstvove_baliky for p in subory] + von_pack
    baliky = [
        ("", "základná mapa – celá kresba z OSM aj so značenými trasami "
             "a hľadaním; bez vrstiev, ktoré majú vlastný balík, a bez glyfov "
             "a viewera",
         args.site, zaklad_subory(args.site, vylucit)),
    ] + [(b["kluc"], b["popis"], args.site, subory)
         for b, subory in vrstvove_baliky]
    # wikipédia má vlastnú pipeline; bez `--wiki` by jej balík beh mapy zmazal
    if args.wiki or args.only == "wikipedia":
        baliky.append(
            ("wikipedia", katalog_balikov.balik("wikipedia")["popis"],
             args.wiki, vsetky_subory(args.wiki) if args.wiki else []))
    # `--only`: samostatná pipeline robí jeden balík, ostatné sa nemažú
    if args.only:
        # základná mapa je v zozname pod prázdnym kľúčom, ale volá sa `mapa`
        if args.only == "mapa":
            args.only = ""
        znam = [k for k, *_ in baliky]
        if args.only not in znam:
            raise SystemExit(f"::error::`--only={args.only}` nepoznám. Balíky "
                             f"sú: {', '.join(k or 'mapa' for k in znam)}.")
        baliky = [b for b in baliky if b[0] == args.only]
        if not baliky[0][3]:
            raise SystemExit(
                f"::error::Balík `{args.only}` nemá ani jeden súbor – nie je "
                f"čo publikovať. (Zbehol krok, ktorý ho vyrába?)")
    elif not baliky[0][3]:
        raise SystemExit(f"::error::V {args.site} nie je ani jeden súbor – nie je "
                         f"čo publikovať. (Zbehol job `deploy` až po zloženie "
                         f"webu?)")
    # o čom tento beh rozhoduje – jeden zoznam pre mazanie aj pre katalóg
    spravuje = [kind or "mapa" for kind, *_ in baliky]
    # zrušený balík nie je vec jedného behu, ide vlastným parametrom
    for kind, popis, _base, subory in baliky:
        stav = (f"{len(subory)} súborov, "
                f"{folder.human(sum(os.path.getsize(p) for p in subory))}"
                if subory else "NIE JE V TOMTO BUILDE – starý balík sa zmaže")
        for fmt in formaty:
            log(f"  {meno(kind, fmt):<48} {popis} – {stav}")
    log(f"Priečinok na Drive: {'/'.join(parts)}")
    if args.dry_run:
        return 0

    if args.zip_only:
        # lokálna skúška: to isté balenie, len bez Drive
        out = args.out or os.environ.get("RUNNER_TEMP", "/tmp")
        for kind, popis, base, subory in baliky:
            if not subory:
                log(f"{meno(kind)}: {popis} v tomto builde nie je – vynechávam.")
                continue
            for fmt in formaty:
                name = meno(kind, fmt)
                BALICE[fmt](base, os.path.join(out, name), name[:-4], subory,
                            info=obsah(kind, man, fmt, casti))
        return 0

    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            "::error::Publikovanie mapy na Drive potrebuje token vlastníka, "
            "ale v prostredí nie je. Doplň secret GDRIVE_CREDENTIALS (alebo "
            "premennú DRIVE_CLIENT a secrety DRIVE_SECRET / DRIVE_REFRESH) "
            "a podaj ho jobu cez `env:` – vyrobí ich workflow „Prihlásenie "
            "na Drive (jednorazové)“.")
    # rozsah pred balením: readonly token nič nenahrá
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::Mapa sa nepublikovala: {auth.scope_hint()}")

    root = folder.folder_id(args.folder)
    fid = folder.ensure_path(creds, root, parts)
    hotove = []
    # ten istý obsah v oboch formátoch, tak sa počíta raz na balík
    shy = {}
    # balík × formát; čo je v balíku, nezávisí od toho, do čoho sa zabalí
    for (kind, popis, base, subory), fmt in [(b_, f) for b_ in baliky
                                             for f in formaty]:
        name = meno(kind, fmt)
        if not subory:
            # vrstva v builde nie je: starý balík toho mena by klamal
            kolko = folder.delete_named(creds, fid, name)
            if kolko:
                log(f"::warning::{popis} v tomto builde nie je – zmazal som "
                    f"{kolko}× starý {name}, aby v priečinku nezostal balík "
                    f"z iného behu.")
            else:
                log(f"{name}: {popis} v tomto builde nie je – nepublikujem.")
            continue
        dest = os.path.join(args.out or os.environ.get("RUNNER_TEMP", "/tmp"),
                            name)
        velkost = BALICE[fmt](base, dest, name[:-4], subory,
                              info=obsah(kind, man, fmt, casti))
        try:
            log(f"Nahrávam {name} ({folder.human(velkost)}) …")
            t0 = time.time()
            file_id, prepisane = folder.upload_clobber(
                creds, dest, name, fid, f"{'/'.join(parts)}/{name}")
            el = max(time.time() - t0, 1e-6)
            log(f"  hotovo za {el / 60:.1f} min "
                f"({velkost / el / 1e6:.1f} MB/s)"
                + (" – starý súbor toho mena prepísaný" if prepisane else ""))
        finally:
            if not args.keep_zip and os.path.exists(dest):
                os.remove(dest)
        if kind not in shy:
            shy[kind] = obsah_sha(base, subory)
        hotove.append((kind, name, popis, velkost, prepisane, file_id, fmt,
                       shy[kind]))
    log(f"Hotovo: {len(hotove)} balíkov v {folder.folder_link(fid)}")

    # meno je stále, nový beh ho neprepíše – zrušený balík treba zmazať
    if not args.only:
        for kind in ZRUSENE:
            for fmt in formaty:
                name = meno(kind, fmt)
                kolko = folder.delete_named(creds, fid, name)
                if kolko:
                    log(f"::warning::Balík `{kind}` už neexistuje – jeho obsah "
                        f"je v základnej mape. Zmazal som {kolko}× {name}, aby "
                        f"si ho nikto nesťahoval druhýkrát.")

    # čo v priečinku naozaj leží; `None` = nezistilo sa, `{}` = je prázdny
    zive = None
    try:
        zive = folder.ids_in(creds, fid)
        log(f"V priečinku mapy je {len(zive)} súborov – podľa nich sa "
            f"z katalógu vyhodia odkazy na tie, ktoré tam už nie sú.")
    except Exception as exc:                       # noqa: BLE001
        log(f"::warning::Priečinok mapy sa nedal vypísať ({exc}) – odkazy "
            f"v katalógu tento beh neoveril. Zapíšem ich tak, ako sú.")

    if args.maps:
        # test sa zapisuje tiež, len do vlastného uzla
        kat = cesta_katalog(parts)
        zmenene = catalog.zapis_katalog(
            args.maps, parts, regions,
            # do katalógu idú všetky formáty; `merge` dopĺňa, neprepisuje
            [(k, n, v, i, f, sh) for k, n, _p, v, _pr, i, f, sh in hotove],
            man, iba=args.only, merge="zip" not in formaty, kat=kat,
            layers=vrstvy(), spravuje=spravuje,
            # koľko z mapy je hľadanie – inde sa to nedá prečítať
            casti=None if args.only else velkost_casti(casti),
            # zrušené balíky a mŕtve odkazy von, aj pri `--only`
            zrusene=ZRUSENE, zive=zive)
        if args.summary and zmenene:
            with open(args.summary, "a") as f:
                f.write(f"Katalóg `{args.maps}` v repozitári je "
                        f"doplnený (`{'/'.join(kat)}`).\n\n")

    if args.summary:
        with open(args.summary, "a") as f:
            f.write("## Mapa na Google Drive\n\n")
            f.write(f"Priečinok [{'/'.join(parts)}]({folder.folder_link(fid)}) – "
                    f"mená sú stále, takže ďalší build tie isté súbory prepíše. "
                    f"Čo je v balíku, hovorí `obsah.json` v ňom.\n\n")
            f.write("| balík | čo je v ňom | veľkosť | starý |\n|---|---|--:|---|\n")
            for _kind, name, popis, velkost, prepisane, _fid, _fmt, _sha in hotove:
                f.write(f"| `{name}` | {popis} | {folder.human(velkost)} | "
                        f"{'prepísaný' if prepisane else '–'} |\n")
            f.write("\n")
            # časti zvlášť: v tabuľke sú započítané vo veľkosti mapy
            if casti:
                f.write("Z toho v základnej mape cestuje (vlastný balík "
                        "nemá):\n\n")
                f.write("| časť | čo to je | veľkosť |\n|---|---|--:|\n")
                for kluc, popis, subory in casti:
                    bajtov = sum(os.path.getsize(x) for x in subory)
                    f.write(f"| `{kluc}` | {popis} | "
                            + (folder.human(bajtov) if subory
                               else "**nie je v tejto mape**") + " |\n")
                f.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except auth.AuthError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
