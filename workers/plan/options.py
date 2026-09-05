#!/usr/bin/env python3
"""Rozloží voľné `kľúč=hodnota` z inputu `options` na jednotlivé nastavenia.

`workflow_dispatch` dovolí najviac 10 inputov, tak sa zvyšok píše do jedného
poľa. Vrstva sa zapína tam, kde sa vyberá jej zdroj (`ziadne` = vypnuté).
Neznámy kľúč je chyba, nie ticho ignorovaná hodnota.

Použitie:
    python3 workers/plan/options.py --options=\"rock_res=1\" \\
        --rebuild=skaly --contour-source=sonny --rock-source=dmr5 \\
        --shading-source=sonny --test=true --publish-pages=true \\
        --out=$GITHUB_OUTPUT
"""
import argparse
import json
import os
import shlex
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import terrain_zoom_for, tile_m_per_px  # noqa: E402

# kľúč: (predvolená hodnota, popis)
DEFAULTS = {
    "crop_bbox": ("", "orezať región na west,south,east,north"),
    "area_bbox": ("", "vlastný výrez W,S,E,N namiesto pohoria z výberu"),
    # 4 km², nie 2: na dvoch sa skalná plocha často netrafila do ničoho
    "test_km2": ("4", "veľkosť štvorca pri zapnutom switchi `test` (km²)"),
    "test_at": ("", "stred testovacieho štvorca `lon,lat` (prázdne = stred výrezu)"),
    # predvolené: `rebuild: nic` znamená, že sa neprepočítava nič. Vzatú vrstvu
    # job hlási `::notice::`-om; prepočet si pýta `rebuild`.
    "reuse_layers": ("true", "nepočítať vrstvu z výškového modelu, ktorá "
                             "s týmito nastaveniami už raz vznikla"),
    "size_limit_mb": ("900", "rozpočet celej stránky v MB"),
    "auto_shrink": ("true", "znížiť zoom dlaždíc, keď sa nezmestia"),
    "ugkk_fallback": ("true", "keď DMR 5.0 pre výrez nie je, počítať zo Sonnyho"),
    "ugkk_urls": ("", "priame URL na ÚGKK dáta (posledná záchrana)"),
    "contour_maxzoom": ("14", "max zoom dlaždíc s vrstevnicami"),
    # 16 je tvrdý strop Planetilera; vyššie rieši overzoom
    "rock_maxzoom": ("16", "max zoom dlaždíc so skalami (strop Planetilera je 16)"),
    # skala je jedna súvislá plocha bez dier: kreslí sa sivou bez priehľadnosti
    "rock_plne": ("1", "1 = jedna trieda skál (žiadna plocha vnútri inej), "
                       "0 = triedy steep/cliff ako predtým"),
    # diery sú žliabky a police – práve ten tvar, pre ktorý sa skaly počítajú
    "rock_zapln_diery": ("0", "1 = zaplniť diery v skalách (súvislé plochy "
                              "namiesto tvaru) – neodporúča sa"),
    # `auto` vyberie mriežku z bunky DEM a rozpočtu času a napíše prečo
    "rock_res": ("auto", "mriežka na obrys skál v metroch, alebo `auto`"),
    "contour_smoothing": ("0", "zjemnenie DEM v oblúkových sekundách"),
    "trails_maxzoom": ("14", "max zoom dlaždíc so značenými trasami"),
    # `auto` = najnižší zoom, kde je pixel jemnejší než bunka modelu; pevná 13
    # znamenala, že DMR 5.0 vyzeralo ako Sonny
    "terrain_maxzoom": ("auto", "max zoom výškových dlaždíc (auto = podľa mriežky modelu)"),
    # na verejné AWS dlaždice sa 3D nezapína, sú globálne a hrubé
    "terrain_3d": ("auto", "3D terén v štýle (auto = keď máme vlastné výškové dlaždice)"),
    # trasy nemajú výber zdroja – idú z toho istého PBF ako mapa
    "trails": ("true", "generovať značené trasy z OSM relácií"),
    # násypy, múry, ploty, vedenia, prieseky, pramene, jaskyne, rozhľadne
    "features": ("true", "generovať krajinné prvky, ktoré OpenMapTiles nemá"),
    # offline FTS5 index, z toho istého PBF ako mapa
    "search": ("true", "generovať vyhľadávací index pre offline hľadávanie"),
    # graf pre tento región; trasa v ňom končí na hranici kraja, cez hranicu
    # vedie celoštátny balík z `navigation.yml`
    "navigacia": ("true", "stavať navigačný graf (Valhalla) pre tento región"),
    # graf a knižnica v telefóne si musia sedieť; použité ide do `graf.json`
    "valhalla_image": ("ghcr.io/valhalla/valhalla-scripted:latest",
                       "docker obraz, ktorým sa stavia navigačný graf"),
    # všetko, po čom sa dá cestovať, aj s obmedzeniami na ceste ako atribútmi
    # tých istých ciest – vrstva `transportation` OpenMapTiles ich nenesie
    "transport": ("true", "generovať dopravnú sieť (cesty, trate, trajekty, "
                          "lanovky) aj s obmedzeniami na ceste – balík `cesty`"),
    # 14, nie 15: najvyšší `min_zoom` v schéme je 14, vyššie pribúdajú len bajty
    "transport_maxzoom": ("14", "max zoom dlaždíc s dopravnou sieťou"),
    # vrstva `boundary` OpenMapTiles je čiara bez mena územia, ktoré ohraničuje
    "boundaries": ("true", "generovať hranice území a ich názvy – balík "
                           "`hranice`"),
    # 12: nad ním už hranica nepribúda, len body sídel (`min_zoom: 10`)
    "boundaries_maxzoom": ("12", "max zoom dlaždíc s hranicami"),
    # v OpenMapTiles je voda v troch vrstvách a meno leží mimo geometrie
    "water": ("true", "generovať vodstvo (rieky, jazerá, more) – balík "
                      "`vodstvo`"),
    # 14: najvyšší `min_zoom` v schéme je 13, o jeden vyššie je rezerva
    "water_maxzoom": ("14", "max zoom dlaždíc s vodstvom"),
    # z DMR 5.0 je 5 m dobrý default takmer všade
    "contour_interval": ("5", "interval vrstevníc v metroch (10 = redšie)"),
    # 15, nie 14: schéma má triedy s `min_zoom: 15` a Planetiler ich inak zahodí
    "features_maxzoom": ("15", "max zoom dlaždíc s krajinnými prvkami"),
    # orez dlaždíc na hranicu regiónu (`workers/lib/region-clip.sh`). Dočasne
    # vypnutý, vypnutý sa hlási `::warning::`-om v každom behu.
    "region_clip": ("false", "orezať dlaždice na hranicu regiónu (dočasne vypnuté)"),
    "publish": ("true", "nahrať hotovú mapu ako ZIPy na Google Drive"),
    # `.aar` robí vlastný job na macOS – nástroj `aa` inde neexistuje
    "apple_archive": ("true", "nahrať mapu aj ako .aar (Apple Archive, job na macOS)"),
    # prázdne = najnovší asset pre daný výrez
    "rock_img_asset": ("", "presné meno assetu so skalami z tieňovania (prázdne = spočítať v tomto behu)"),
    # ladenie pipeline, ktorú si build volá sám (shading-rocks.yml)
    "rock_img_zoom": ("auto", "zoom dlaždíc tieňovania (auto = najvyšší, čo sa zmestí do stropu)"),
    "rock_img_options": ("", "prepínače pre výpočet skál z tieňovania, napr. \"fill=40 min_hole=5\""),
    # `maxzoom` je od začiatku 16 a znižuje sa len pri ladení veľkosti
    "maxzoom": ("16", "max zoom mapových dlaždíc – Planetiler zvládne najviac 16"),
    "custom_pbf_url": ("", "vlastný región – URL na .osm.pbf"),
    "custom_name": ("", "vlastný región – zobrazované meno"),
    "custom_bbox": ("", "vlastný región – bbox W,S,E,N"),
}

# voľby, čo sa presťahovali medzi inputy – nech nespadnú na „neznáma voľba"
MOVED = {
    "rock_source": "je samostatný input vo formulári (výber zdroja skál), "
                   "nie voľba",
    "test": "je switch vo formulári (rýchly test na pár km²), nie voľba. "
            "Veľkosť štvorca je voľba `test_km2`",
    # bolo voľbou, kým bol formulár plný; starý zápis nesmie ticho prejsť
    "publish_pages": "je switch vo formulári (nasadiť na GitHub Pages), "
                     "nie voľba. Publikovanie na Drive je samostatná voľba "
                     "`publish`",
    # články z Wikipédie majú vlastný workflow
    "wikipedia": "už nie je: články z Wikipédie robí samostatný workflow "
                 "„Build wiki“ (wiki.yml), nie Build map",
    "wiki_langs": "je input workflowu „Build wiki“ (wiki.yml) – "
                  "angličtina a jazyk krajiny sa doplnia samy",
    "wiki_format": "je input workflowu „Build wiki“ (wiki.yml)",
    "wiki_max": "je input workflowu „Build wiki“ (wiki.yml)",
    "dem_source": "sa rozpadol na tri inputy vo formulári – `contour_source`, "
                  "`rock_source` a `shading_source`, každá vrstva má svoj "
                  "zdroj",
    "layers": "už nie je: vrstva sa zapína tým, že jej vo formulári vyberieš "
              "zdroj (`ziadne` = negenerovať). Trasy sa vypínajú voľbou "
              "`trails=false`",
    "rocks": "už nie je: skaly sa vypínajú výberom `rock_source: ziadne`",
}

# Hodnota vo výbere, ktorá vrstvu vypne. Slovom, nie prázdnym reťazcom –
# v rozbaľovacom zozname má byť vidieť, že „nič" je vedomá voľba.
NONE = "ziadne"

# Skaly majú okrem výškových modelov ešte jeden zdroj, ktorý DEM vôbec
# nečíta: hotové polygóny z workflowu „Dáta · tieňované skaly".
ROCK_FROM_SHADING = "tienovanie"

# `rebuild` je jeden výber namiesto troch zaškrtávatiek – tri booleany boli
# tri inputy a limit je desať.
#
# `tienovanie` SA VOLALO `teren`. Bolo to jediné miesto v celom repozitári,
# kde sa tá vrstva volala inak než všade inde: vyberá ju `shading_source`
# („Tieňovanie a 3D terén“), balík je `-tienovanie.zip` a v katalógu je
# `terrain_source`. Kto ju chcel prepočítať, hľadal vo výbere „tieňovanie“ –
# a keď ho nenašiel, usúdil, že sa tá vrstva pregenerovať nedá. Príznak ostal
# `terrain_rebuild`: identifikátory sú anglické, mená vo formulári slovenské.
REBUILD = {
    "nic": (),
    "vrstevnice": ("contours_rebuild",),
    "skaly": ("rocks_rebuild",),
    "tienovanie": ("terrain_rebuild",),
    # `clanky` tu už nie je: články sťahuje len workflow „Build wiki“
    "vsetko": ("contours_rebuild", "rocks_rebuild", "terrain_rebuild"),
}
# staré mená hodnoty → nové; prekladá sa nahlas, „Re-run“ nesie starý formulár
REBUILD_ALIAS = {"teren": "tienovanie"}
# príznaky, ktoré `rebuild` prepína – jeden zoznam, nech sa nedá zabudnúť
REBUILD_FLAGS = ("contours_rebuild", "rocks_rebuild", "terrain_rebuild")

# čo `rebuild` NEpregeneruje: „vsetko“ je páka na tri vrstvy, ostatné sa
# obnovuje inak. Vypisuje sa, inak „vsetko“ vyzerá ako lož.
REBUILD_MIMO = [
    ("výškový model (DEM)",
     "z Drive sa číta raz a ostáva v sklade; jeho podobu nesie MENO SKLADU "
     "(dnes `dem-dmr5-v2`), takže keď sa zmení pravidlo, ktorým vzniká, "
     "zmení sa meno a `check-dem` si ho doplní sám"),
    ("články z Wikipédie",
     "vlastná pipeline `Mapa · Build wiki`, tam je na to `rebuild: clanky`"),
    ("balíky na Drive (ZIP/AAR) a katalóg (`maps.json`, pri teste "
     "`maps-test.json`)",
     "prepisujú sa pri KAŽDOM behu, ktorý ich vyrobí (nahraj a až potom zmaž "
     "starý); balík vrstvy, ktorú beh nevyrobil, sa zmaže"),
]


def dem_sources(path=None):
    """Zdroje z workers/data/dem-sources.json → {kľúč: celý zápis zdroja}."""
    path = path or os.path.join(_DATA, "dem-sources.json")
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def pick_source(what, value, allowed):
    """Skontroluje hodnotu jedného výberu zdroja; vráti ju, alebo None pri chybe."""
    value = (value or NONE).strip()
    if value in allowed:
        return value
    print(f"::error::Neznámy zdroj „{value}“ pre {what}. Známe: "
          f"{', '.join(allowed)}", file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--options", default="")
    ap.add_argument("--rebuild", default="nic")
    ap.add_argument("--contour-source", default=NONE,
                    help="zdroj výšok pre vrstevnice, alebo `ziadne`")
    ap.add_argument("--rock-source", default=NONE,
                    help="zdroj skál: výškový model, `tienovanie`, alebo `ziadne`")
    ap.add_argument("--shading-source", default=NONE,
                    help="zdroj výšok pre tieňovanie a 3D terén, alebo `ziadne`")
    ap.add_argument("--test", default="false",
                    help="switch rýchleho testu: true = počítať len štvorec "
                         "s `test_km2` km²")
    ap.add_argument("--publish-pages", default="true",
                    help="switch nasadenia na GitHub Pages: false = mapa sa "
                         "postaví a skontroluje, ale nenasadí")
    ap.add_argument("--dem-sources", default="",
                    help="cesta k dem-sources.json (default vedľa skriptu)")
    ap.add_argument("--out", default="")
    ap.add_argument("--summary", default="",
                    help="kam pripísať blok do súhrnu behu (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()

    values = {k: v for k, (v, _) in DEFAULTS.items()}
    changed = {}

    # shlex, nie split(): hodnota môže byť v úvodzovkách
    for token in shlex.split(args.options or ""):
        if "=" not in token:
            print(f"::error::Voľba „{token}“ nemá tvar kľúč=hodnota.", file=sys.stderr)
            return 1
        k, v = token.split("=", 1)
        k = k.strip()
        if k in MOVED:
            print(f"::error::„{k}“ {MOVED[k]}. Vymaž to z `options` "
                  f"a nastav vo formulári.", file=sys.stderr)
            return 1
        if k not in DEFAULTS:
            print(f"::error::Neznáma voľba „{k}“. Známe voľby: "
                  f"{', '.join(sorted(DEFAULTS))}", file=sys.stderr)
            return 1
        values[k] = v
        changed[k] = v

    # zo switchu a veľkosti vyjde jedno číslo: 0 = ostrý beh, inak strana
    # štvorca v km². Normalizuje sa – `4.0` aj `4` dajú „4“.
    test_on = (args.test or "false").strip().lower()
    if test_on not in ("true", "false"):
        print(f"::error::Switch „test“ musí byť true alebo false, "
              f"nie „{args.test}“.", file=sys.stderr)
        return 1
    test_on = test_on == "true"

    size = (values["test_km2"] or "").strip()
    try:
        n = float(size)
    except ValueError:
        print(f"::error::Voľba „test_km2“ musí byť číslo v km², "
              f"nie „{size}“.", file=sys.stderr)
        return 1
    if n <= 0:
        # vypína sa switchom, nie nulou – inak sú na to isté dve páky
        print(f"::error::Voľba „test_km2“ musí byť väčšia než nula "
              f"(„{size}“). Rýchly test sa vypína odškrtnutím switchu "
              f"„test“.", file=sys.stderr)
        return 1
    if "test_km2" in changed and not test_on:
        print("::error::`test_km2` má zmysel len so zapnutým switchom „test“ "
              "– takto by sa nič nespočítalo inak. Zaškrtni `test`, alebo "
              "vymaž `test_km2` z options.", file=sys.stderr)
        return 1
    values["test_km2"] = f"{n:g}" if test_on else "0"

    # čo sa smie kde vybrať, hovorí `for` v dem-sources.json
    srcs = dem_sources(args.dem_sources or None)
    contour_src = pick_source(
        "vrstevnice (contour_source)", args.contour_source,
        [NONE] + [k for k, v in srcs.items() if "contours" in v.get("for", [])])
    rock_src = pick_source(
        "skaly (rock_source)", args.rock_source,
        [NONE, ROCK_FROM_SHADING]
        + [k for k, v in srcs.items() if "rocks" in v.get("for", [])])
    shading_src = pick_source(
        "tieňovanie (shading_source)", args.shading_source,
        [NONE] + [k for k, v in srcs.items() if "shading" in v.get("for", [])])
    if contour_src is None or rock_src is None or shading_src is None:
        return 1

    values["contour_source"] = contour_src
    values["rock_source"] = rock_src
    values["shading_source"] = shading_src

    # `terrain_maxzoom: auto` sa rozhodne tu a nikde inde: číslo potom
    # potrebuje kľúč cache, meno assetu aj atribúcia v štýle
    tz = values["terrain_maxzoom"].strip().lower()
    if tz == "auto":
        cell = float(srcs.get(shading_src, {}).get("cell_m") or 20)
        values["terrain_maxzoom"] = str(terrain_zoom_for(cell))
        if shading_src != NONE:
            print(f"Výškové dlaždice: model {shading_src} má mriežku "
                  f"{cell:g} m → maxzoom "
                  f"z{values['terrain_maxzoom']} (pixel "
                  f"{tile_m_per_px(int(values['terrain_maxzoom'])):.1f} m). "
                  f"Pevný zoom sa dá vynútiť voľbou `terrain_maxzoom=13`.")
    elif not tz.isdigit():
        print(f"::error::Voľba „terrain_maxzoom“ musí byť číslo alebo "
              f"`auto`, nie „{values['terrain_maxzoom']}“.", file=sys.stderr)
        return 1
    # pri `tienovanie` a `ziadne` je prázdny a nikto nesmie sťahovať DEM
    values["rock_dem"] = rock_src if rock_src in srcs else ""

    values["contour_lines"] = "true" if contour_src != NONE else "false"
    values["rocks"] = "true" if rock_src != NONE else "false"
    values["terrain"] = "true" if shading_src != NONE else "false"
    # `contours` je brána celého jobu, nie vrstva: obe vrstvy idú do jedného .pmtiles
    values["contours"] = ("true" if contour_src != NONE or rock_src != NONE
                          else "false")
    # `trails=1` by trasy ticho vyplo a zistilo by sa to až v mape
    if values["trails"] not in ("true", "false"):
        print(f"::error::Voľba „trails“ musí byť true alebo false, "
              f"nie „{values['trails']}“.", file=sys.stderr)
        return 1
    if values["features"] not in ("true", "false"):
        print(f"::error::Voľba „features“ musí byť true alebo false, "
              f"nie „{values['features']}“.", file=sys.stderr)
        return 1
    if values["transport"] not in ("true", "false"):
        print(f"::error::Voľba „transport“ musí byť true alebo false, "
              f"nie „{values['transport']}“.", file=sys.stderr)
        return 1
    for volba, co in (("boundaries", "hranice"), ("water", "vodstvo")):
        if values[volba] not in ("true", "false"):
            print(f"::error::Voľba „{volba}“ ({co}) musí byť true alebo "
                  f"false, nie „{values[volba]}“.", file=sys.stderr)
            return 1
    if values["search"] not in ("true", "false"):
        print(f"::error::Voľba search=... musí byť true alebo false, "
              f"nie {values['search']}.", file=sys.stderr)
        return 1
    if values["navigacia"] not in ("true", "false"):
        print(f"::error::Voľba navigacia=... musí byť true alebo false, "
              f"nie {values['navigacia']}.", file=sys.stderr)
        return 1

    if values["apple_archive"] not in ("true", "false"):
        print(f"::error::Voľba „apple_archive“ musí byť true alebo false, "
              f"nie „{values['apple_archive']}“.", file=sys.stderr)
        return 1
    if values["publish"] not in ("true", "false"):
        print(f"::error::Voľba „publish“ musí byť true alebo false, "
              f"nie „{values['publish']}“.", file=sys.stderr)
        return 1
    # switch vo formulári, ale skript sa dá spustiť aj ručne
    pages_on = (args.publish_pages or "true").strip().lower()
    if pages_on not in ("true", "false"):
        print(f"::error::Switch „publish_pages“ musí byť true alebo false, "
              f"nie „{args.publish_pages}“.", file=sys.stderr)
        return 1
    values["publish_pages"] = pages_on

    # inak by `contour_interval=päť` spadlo až v `gdal_contour`, po hodine
    try:
        interval = float(values["contour_interval"])
    except ValueError:
        print(f"::error::Voľba „contour_interval“ musí byť číslo v metroch, "
              f"nie „{values['contour_interval']}“.", file=sys.stderr)
        return 1
    if interval <= 0:
        print(f"::error::Voľba „contour_interval“ musí byť väčšia než nula "
              f"(„{values['contour_interval']}“). Vrstevnice sa vypínajú "
              f"výberom `contour_source: ziadne`.", file=sys.stderr)
        return 1
    values["contour_interval"] = f"{interval:g}"

    rebuild = (args.rebuild or "nic").strip()
    if rebuild in REBUILD_ALIAS:
        print(f"::notice::`rebuild: {rebuild}` sa dnes volá "
              f"`{REBUILD_ALIAS[rebuild]}` – tá istá vrstva, to isté meno ako "
              f"vo `shading_source` a v balíku `-tienovanie.zip`. Beriem to "
              f"ako `{REBUILD_ALIAS[rebuild]}`.")
        rebuild = REBUILD_ALIAS[rebuild]
    if rebuild not in REBUILD:
        print(f"::error::Neznáme rebuild „{args.rebuild}“. Známe: "
              f"{', '.join(REBUILD)}", file=sys.stderr)
        return 1
    for flag in REBUILD_FLAGS:
        values[flag] = "true" if flag in REBUILD[rebuild] else "false"

    # rýchly test pregenerúva vždy všetko: je to beh na ladenie a starý
    # výsledok by znamenal, že ladíš ducha. Cache ostrého behu je v bezpečí –
    # kľúče nesú `dem_bboxkey`, pri teste bbox testovacieho štvorca.
    if test_on:
        for flag in ("contours_rebuild", "rocks_rebuild", "terrain_rebuild"):
            values[flag] = "true"

    if values["reuse_layers"] not in ("true", "false"):
        print(f"::error::Voľba „reuse_layers“ musí byť true alebo false, "
              f"nie „{values['reuse_layers']}“.", file=sys.stderr)
        return 1
    # test neberie nič hotové, z toho istého dôvodu; tichý spor by sa hľadal dlho
    if test_on and values["reuse_layers"] == "true":
        if "reuse_layers" in changed:
            print("::notice::`reuse_layers=true` sa pri zapnutom switchi „test“ "
                  "neuplatní – rýchly test počíta vrstvy vždy nanovo, nech "
                  "neladíš na starom výsledku.")
        values["reuse_layers"] = "false"

    lines = [f"opt_{k}={v}" for k, v in values.items()]
    if args.out:
        with open(args.out, "a") as f:
            f.write("\n".join(lines) + "\n")

    # s čím beh štartuje: súhrn prípravného jobu je na stránke behu prvý,
    # takže sa to dá pozrieť hneď a ostáva na očiach aj po páde
    if args.summary:
        with open(args.summary, "a") as f:
            f.write("## Čo z toho vyšlo – s tým beh štartuje\n\n")
            f.write("| nastavenie | hodnota | |\n|---|---|---|\n")
            for k in sorted(values):
                mark = "**iné než default**" if k in changed else ""
                f.write(f"| `{k}` | `{values[k] or '—'}` | {mark} |\n")
            f.write("\nHodnoty bez značky sú predvolené. Tie označené si "
                    "zadal – buď vo formulári, alebo v poli `options`.\n\n")

    print("Nastavenia:")
    for k in sorted(values):
        mark = "  ←" if k in changed else ""
        d = DEFAULTS.get(
            k, ("", "z inputov formulára (zdroje / rebuild / test)"))[1]
        print(f"  {k:<20} {values[k] or '(prázdne)':<24} {d}{mark}")
    if changed:
        print(f"\nZmenené oproti predvolenému: {', '.join(sorted(changed))}")
    if test_on:
        print("Pregenerovať: VŠETKO (rýchly test počíta vždy nanovo, nech "
              f"neladíš na starom výsledku z cache; `rebuild: {rebuild}` "
              "sa tým prebíja)")
    elif rebuild != "nic":
        print(f"Pregenerovať: {rebuild}")
    if values["reuse_layers"] == "true":
        print("Hotové vrstvy: BERÚ SA – vrstevnice, skaly aj tieňovanie, "
              "ktoré s týmito nastaveniami už raz vznikli, sa neprepočítajú "
              "(prepočíta ich `rebuild`)")
    else:
        print("Hotové vrstvy: NEBERÚ SA (`reuse_layers=false`) – vrstevnice, "
              "skaly aj tieňovanie sa prepočítajú, len čo sa zmenil sklad "
              "modelu alebo skript, ktorý ich kreslí")
    if test_on or rebuild != "nic":
        # aj to, čo sa NEprepočíta – bez toho „vsetko“ sľubuje viac, než robí
        print("  prepočíta sa: "
              + ", ".join(f.replace("_rebuild", "")
                          for f in REBUILD_FLAGS if values[f] == "true"))
        for co, ako in REBUILD_MIMO:
            print(f"  NEprepočíta sa {co} – {ako}")
    print(f"\nVrstevnice: {contour_src}   Skaly: {rock_src}   "
          f"Tieňovanie: {shading_src}   Trasy: {values['trails']}   "
          f"Krajinné prvky: {values['features']}   "
          f"Dopravná sieť: {values['transport']}   "
          f"Hranice: {values['boundaries']}   "
          f"Vodstvo: {values['water']}")
    print("Rýchly test: " + (f"ZAPNUTÝ, terén (vrstevnice, skaly, tieňovanie) "
                             f"len na {values['test_km2']} km² zo stredu "
                             f"výrezu; mapa ostáva celý región a otvorí sa tam"
                             if test_on else "vypnutý – ostrý beh"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
