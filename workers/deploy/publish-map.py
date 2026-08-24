#!/usr/bin/env python3
"""
Hotová mapa na Google Drive – ŠTYRI ZIPy so stálym menom.

ČO TO ROBÍ. Z `_site` (celý web: dlaždice, štýly, vrstevnice, skaly,
tieňovanie, fonty a sprity) a z priečinka s článkami (`--wiki`) sa zabalia
balíky a nahrajú na Drive do priečinka podľa toho, čoho sa mapa týka:

    <koreň>/slovensko/presovsky/vysoke_tatry/
        presovsky-vysoke_tatry.zip                    základná mapa, BEZ nižšie
                                                      (a bez glyfov a viewera – tie sú na Pages)
        presovsky-vysoke_tatry-vrstevnice-skaly.zip   len tie dve vrstvy
        presovsky-vysoke_tatry-tienovanie.zip         len výškové dlaždice
        presovsky-vysoke_tatry-wikipedia.zip          články z Wikipédie

GLYFY A WEBOVÝ VIEWER SA NEBALIA – SÚ NA PAGES. Fonty boli po dlaždiciach
druhá najväčšia vec v balíku (tri fontstacky Noto Sans po ~34 MB, celý unicode)
a mapa kraja z nich použije zlomok; viewer (`index.html` a `*.js` z `poc/web`)
je zase web, ktorý si aplikácia nespúšťa – má vlastnú mapu. Oboje ostáva v
`_site`, teda na Pages, takže sa nič nestráca: manifest v balíku nesie
ABSOLÚTNU adresu glyfov (`site.sh` ju skladá z `$BASE`), takže štýl vie, odkiaľ
si ich vziať.

A NIE JE TO NATVRDO: glyfy sa vynechajú PRÁVE VTEDY, keď na ne manifest
odkazuje absolútnou adresou. Mapa sveta má v manifeste `fonts/{fontstack}/…`,
teda odkaz DO BALÍKA (na Pages nejde a jej glyfy sú orezané na stovky kB) –
tej sa preto nechajú. Jedna otázka, jedna odpoveď: kde si štýl glyfy pýta,
tam musia byť.

ZÁKLADNÁ MAPA NEMÁ VRSTEVNICE, SKALY ANI TIEŇOVANIE. Sú to ťažké vrstvy
z výškového modelu a majú vlastné balíky presne preto, aby si ich človek
nemusel sťahovať, keď ich nechce – kým boli aj v základnej mape, ten dôvod
neplatil a „iba mapa" vážila rovnako ako mapa so všetkým. Kto ich chce, rozbalí
príslušný ZIP navrch (cesty vnútri sú tie isté ako v `_site`, takže sa dá
rozbaliť jeden cez druhý).

Úrovne cesty, ktoré nedávajú zmysel, sa vynechajú: build celej krajiny nemá
kraj a build celého kraja nemá výsek. Chýbajúce priečinky sa vyrobia.

MENO JE STÁLE – rovnaký kraj (a rovnaký výsek) má vždy to isté meno, takže
ďalší build starý balík PREPÍŠE a v priečinku je jeden aktuálny súbor namiesto
histórie behov. Poradie je „najprv nahraj, potom zmaž starý" (`folder.
upload_clobber`): Drive dovolí dva súbory s tým istým menom vedľa seba, takže
„najprv zmaž" by po spadnutom nahrávaní nenechalo ani nové, ani staré.

ČO V TOM BALÍKU JE, HOVORÍ `obsah.json` V ŇOM. Kým bolo meno jedinečné, nieslo
zoom, vrstvy a ich zdroje (`…-z16-vrstevnice_dmr5_5m-skaly_dmr5-…-r73.zip`);
stále meno to nesie ako súbor vnútri – dátum, číslo behu, výrez, zoomy, zdroje
výšok, prah sklonu. Vrstva, ktorá v mape NIE JE, je tam napísaná tiež
(`bez_skal`): mlčanie sa dá čítať aj ako „zabudlo sa to dopísať".

BALÍK VRSTVY, KTORÚ TENTO BUILD NEVYROBIL, SA ZMAŽE. Inak by vedľa novej mapy
ostal starý `-tienovanie.zip` z iného behu a na súbore by to nikto nepoznal –
tá istá trieda tichého omylu ako dlaždica, ktorá sľubuje celý stupeň.

TESTOVACÍ BEH TO MUSÍ POVEDAŤ. Rýchly test počíta terén len na pár km² zo
stredu výrezu; mapa z neho vyzerá ako každá iná, len jej väčšina chýba. V mene
je preto `test4km2` – a je to nutné dvakrát: aby sa nedalo pomýliť, a aby test
NEPREPÍSAL ostrú mapu (meno je sľub o rozsahu, ako pri assetoch DEM).

Použitie (hodnoty berie z prostredia, tak ako ostatné workery):
    REGION_KEY=presovsky AREA_KEY=vysoke_tatry TILES_MAXZOOM=16 \\
        python3 workers/deploy/publish-map.py --site=_site
    python3 workers/deploy/publish-map.py --site=_site --dry-run   # len mená a cesta
"""
import argparse
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Priečinok = job, súbor = krok; spoločné veci ležia o úroveň vyššie.
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # číselníky (areas, regions, zdroje)
_DRIVE = os.path.join(_WORKERS, "drive")   # prihlásenie a nahrávanie na Drive


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pack = load("deploy_pack", "pack.py")   # ako sa balík zabalí (zip / aar)
catalog = load("deploy_catalog", "catalog.py")  # čo sa píše do maps.json
BALICE = pack.BALICE
aa_je = pack.aa_je
auth = load("drive_auth", os.path.join(_DRIVE, "auth.py"))        # kto sme na Drive
folder = load("drive_folder", os.path.join(_DRIVE, "folder.py"))  # priečinky a nahrávanie

# Priečinok, do ktorého sa mapy publikujú. Ako pri DMR 5.0 a cache platí, že
# tajomstvo to nie je – id chodí v zdieľanom odkaze; tajomstvom je token.
FOLDER_ID = "1pvrw7CGUkQLwg8Ql8xbKA4HhQHvPl8_7"

# Balí sa `deflate` na najnižší stupeň. Obsah `_site` je z veľkej časti už
# komprimovaný (PMTiles nesú gzip-nuté dlaždice, tieňovanie sú PNG), takže
# vyšší stupeň stojí minúty a ušetrí percentá.


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def log(msg):
    print(msg, flush=True)


def safe(text):
    """Kus mena súboru: bez diakritiky, medzier a lomítok."""
    prevod = {"á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i",
              "ĺ": "l", "ľ": "l", "ň": "n", "ó": "o", "ô": "o", "ŕ": "r",
              "š": "s", "ť": "t", "ú": "u", "ý": "y", "ž": "z"}
    out = []
    for ch in text.strip().lower():
        ch = prevod.get(ch, ch)
        out.append(ch if (ch.isalnum() and ch.isascii()) or ch in "._-" else "_")
    return "".join(out).strip("_") or "bez_mena"


def bez_testu(key):
    """`presovsky_test4` → `presovsky`.

    Kľúč výrezu aj regiónu nesie pri rýchlom teste príponu `_test<N>`, aby si
    testovací výsledok nesadol na miesto ostrého. Do CESTY ale patrí to
    pohorie, o ktoré ide – že je to test, povie meno súboru.
    """
    base = key
    while True:
        cut = base.rfind("_test")
        if cut < 0 or not base[cut + 5:].replace(".", "").isdigit():
            return base
        base = base[:cut]



# ---------- kam to patrí ----------

def krajina_z_url(url):
    """Krajina z odkazu na osm.fr export.

    `…/extracts/europe/austria/tirol-latest.osm.pbf` → `austria`. Vlastný PBF
    je jediný prípad, keď región nie je v `workers/data/regions.json`, takže sa
    krajina nemá odkiaľ inak dozvedieť. Keď sa z odkazu vyčítať nedá, ide to
    do `ostatne` – nie do `slovensko`, kde nepatrí.
    """
    cesta = url.split("/extracts/", 1)[-1] if "/extracts/" in url else url
    kusy = [k for k in cesta.split("/") if k]
    if len(kusy) >= 2:
        return safe(kusy[-2])
    return "ostatne"


def cesta(regions):
    """Priečinky pod koreňom: [krajina, kraj?, výsek?]."""
    region_key = bez_testu(env("REGION_KEY"))
    custom_url = env("CUSTOM_PBF_URL")
    area_key = bez_testu(env("AREA_KEY"))

    if custom_url:
        # Vlastný PBF: v `regions.json` nie je, kraj je to, čo si človek
        # pomenoval sám (alebo slug z odkazu).
        kraj = safe(env("CUSTOM_NAME") or region_key
                    or custom_url.rsplit("/", 1)[-1].split(".")[0])
        parts = [krajina_z_url(custom_url), kraj]
    else:
        r = regions.get(region_key) or {}
        krajina = safe(r.get("country") or region_key or "ostatne")
        parts = [krajina]
        # Celá krajina nemá nadradený kraj – `admin_level` 2 je štát.
        if r.get("admin_level") != 2 and region_key:
            parts.append(safe(region_key))
    # `cely` znamená „celý región", teda žiadny výrez – vlastnú úroveň
    # nedostane, inak by v každom kraji ležal priečinok `cely`.
    if area_key and area_key != "cely":
        parts.append(safe(area_key))
    return parts


def cesta_katalog(parts):
    """Kam to patrí v KATALÓGU – to isté, len rýchly test má vlastný uzol.

    Na Drive ležia balíky testu v tom istom priečinku ako ostrá mapa (odlíši
    ich meno – `…-test4km2.zip`), ale v katalógu na jej miesto sadnúť NESMÚ:
    terén je v nich na pár km² a čitateľ by si podľa nich stiahol „mapu
    kraja". Zapisovať sa ale majú – bez toho o nich nevie nikto, kto nemá
    otvorený Drive, a to je presne to, načo `maps.json` je. Uzol preto dostane
    tú istú príponu, akú nesú súbory: `vysoke_tatry_test4km2`.
    """
    test_km2 = env("TEST_KM2", "0")
    if test_km2 in ("", "0"):
        return parts
    return parts[:-1] + [f"{parts[-1]}_test{safe(test_km2)}km2"]


# ---------- ako sa to volá ----------

def vrstvy():
    """Kúsky mena, ktoré hovoria, čo je v mape a z čoho.

    Vrstva sa do mena zapíše aj vtedy, keď v mape NIE JE (`bez_vrstevnic`).
    Mlčanie by sa dalo čítať dvoma spôsobmi – „nie sú" aj „zabudlo sa to
    dopísať" – a to je presne ten rozdiel, kvôli ktorému sa mená píšu.

    `MAP_LAYERS` je pre pipeline, ktorá NEROBÍ mapu kraja a tento zoznam
    vrstiev na ňu nesadá – zatiaľ mapa sveta (`world-map.yml`). Bez toho by
    o sebe napísala „bez_vrstevnic, bez_skal, bez_tienovania", čo je pri mape,
    ktorá nemá ani cesty, mätúce: znie to ako mapa kraja s vypnutým terénom.
    Podáva sa prostredím a nie prepínačom zámerne – ten istý zoznam potrebuje
    aj job, čo dobalí `.aar` (položku katalógu prepisuje navrch), a env stojí
    v oboch jobov na tom istom mieste vo workflowe.
    """
    vlastne = env("MAP_LAYERS")
    if vlastne:
        return [safe(k) for k in vlastne.split(",") if k.strip()]

    out = []
    if env("CONTOURS_ENABLED") == "true":
        interval = env("CONTOUR_INTERVAL", "10")
        out.append(f"vrstevnice_{safe(env('CONTOURS_SOURCE', '?'))}_{safe(interval)}m")
    else:
        out.append("bez_vrstevnic")

    if env("ROCKS_ENABLED") == "true":
        out.append(f"skaly_{safe(env('ROCKS_SOURCE', '?'))}")
    else:
        out.append("bez_skal")

    if env("TERRAIN_ENABLED") == "true":
        out.append(f"tienovanie_{safe(env('TERRAIN_SOURCE', '?'))}")
    else:
        out.append("bez_tienovania")

    # Trasy a prvky sa píšu, len keď sú – nie sú to vrstvy z výškového modelu
    # a meno by bez toho narástlo o dve „bez_" na každom behu.
    if env("TRAILS_ENABLED") == "true":
        out.append("trasy")
    if env("FEATURES_ENABLED") == "true":
        out.append("prvky")
    if env("ROADS_ENABLED") == "true":
        out.append("obmedzenia")
    return out


def zaklad():
    """Stále meno bez prípony: `<kraj>[-<výsek>][-testNkm2]`.

    Zoom, vrstvy, ich zdroje, dátum ani číslo behu v ňom NIE SÚ – práve preto
    je stále a ďalší build ten istý súbor prepíše. Všetko to nesie `obsah.json`
    vnútri balíka.
    """
    region = bez_testu(env("REGION_KEY")) or "mapa"
    area = bez_testu(env("AREA_KEY"))
    kusy = [safe(region)]
    if area and area != "cely":
        kusy.append(safe(area))
    test_km2 = env("TEST_KM2", "0")
    if test_km2 not in ("", "0"):
        # Rýchly test má terén len na pár km². Bez tohto by mapa vyzerala ako
        # ostrá, chýbala by jej väčšina – a PREPÍSALA by tú ostrú.
        kusy.append(f"test{safe(test_km2)}km2")
    return "-".join(kusy)


# Prípony podľa formátu. `.aar` je Apple Archive – to, čo iOS a macOS vedia
# rozbaliť SYSTÉMOVO (framework AppleArchive), bez tretej knižnice v aplikácii
# a s dekompresiou LZFSE, ktorá je na Apple hardvéri rýchlejšia než deflate.
# ZIP ostáva, lebo ten otvorí čokoľvek; `.aar` je navyše, nie namiesto.
PRIPONY = {"zip": ".zip", "aar": ".aar"}


def meno(kind="", fmt="zip"):
    """Meno balíka: základ + druh (`` = celá mapa) + prípona formátu."""
    return zaklad() + (f"-{kind}" if kind else "") + PRIPONY[fmt]


# ---------- čo je v ktorom balíku ----------
# Základná mapa NEOBSAHUJE vrstevnice, skaly ani tieňovanie – to sú ťažké
# vrstvy z výškového modelu a majú vlastné balíky práve preto, aby si ich
# človek nemusel sťahovať, keď ich nechce. Vrstevnice so skalami sú aj to,
# čo sa nosí do inej mapy, a tieňovanie je jedna pyramída PNG. Vrstevnice
# a skaly sú SPOLU zámerne – sú z toho istého výpočtu nad tým istým DEM
# a jedna bez druhej sa nepoužíva.

def manifest_data(site):
    """`_site/tiles/manifest.json` – jediné miesto, ktoré vie, čo v mape je.

    Berie sa odtiaľ, a nie z ďalších premenných prostredia: manifest skladá
    `workers/deploy/site.sh` a vrstva, ktorá v ňom nie je, v mape nie je
    (pravidlo 1 – jedna otázka, jedna odpoveď, jedno miesto).
    """
    path = os.path.join(site, "tiles", "manifest.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        log(f"::warning::{path} sa nedá prečítať ({exc}) – balíky vrstiev sa "
            f"skladajú podľa mien súborov v `_site`.")
        return {}



def vrstvy_subory(site, man):
    """Súbory balíka `vrstevnice-skaly` – z manifestu, inak podľa mena."""
    reg = catalog.region_entry(man)
    rel = [reg[k] for k in ("contours", "rocks") if reg.get(k)]
    if not rel:
        tiles = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(tiles))
               if n.endswith(("-contours.pmtiles", "-rocks.pmtiles"))] \
            if os.path.isdir(tiles) else []
    return [os.path.join(site, p) for p in rel
            if os.path.exists(os.path.join(site, p))]


def tienovanie_subory(site, man):
    """Súbory balíka `tienovanie` – raster `.pmtiles` s výškovými dlaždicami.

    Balí sa len vlastný archív. Keď sa tieňovanie nevyrobilo, štýl padá na
    cudzie dlaždice (AWS Terrain Tiles) a tie do nášho balíka nepatria – nie
    sú naše a nie sú v `_site`.

    Bola to pyramída tisícov PNG súborov v `_site/terrain`; odkedy je z nej
    jeden `.pmtiles` (workers/terrain/pack.py), je to jeden súbor. Hľadá sa
    podľa PRÍPONY MENA, nie podľa priečinka: `tiles/` je spoločný pre všetky
    vrstvy, takže „všetko v priečinku" by do balíka `tienovanie` pribalilo
    aj mapu, vrstevnice a trasy.
    """
    base = os.path.join(site, "tiles")
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, n) for n in sorted(os.listdir(base))
            if n.endswith("-terrain.pmtiles")]


def hladanie_subory(site, man):
    """Súbory balíka `search` – SQLite FTS5 index na offline hľadanie.

    Jeden súbor, presunutý workers/search/build.sh do `_site/tiles/` ako
    `search-index.db`. Hľadá sa podľa PRÍPONY MENA a slova „search" v nej
    (rovnaké pravidlo, akým appka skenuje stiahnutý priečinok, nie pevné
    meno – `.db` súbor s „search" v mene), z rovnakého dôvodu ako
    `tienovanie_subory`: `tiles/` je spoločný pre všetky vrstvy.
    """
    base = os.path.join(site, "tiles")
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, n) for n in sorted(os.listdir(base))
            if n.endswith(".db") and "search" in n.lower()]


def obsah(kind, man, fmt="zip"):
    """`obsah.json` do balíka – to, čo kedysi nieslo meno súboru."""
    reg = catalog.region_entry(man)
    return {
        "balik": kind or "mapa",
        # Meno TOHO súboru, v ktorom `obsah.json` leží – čiže aj s príponou
        # formátu. Keby tu bolo natvrdo `.zip`, `.aar` by o sebe tvrdil, že
        # je ZIP, a to je presne ten druh tichého omylu, ktorému sa mená
        # súborov v tomto repozitári vyhýbajú.
        "subor": meno(kind, fmt),
        "format": fmt,
        "region": bez_testu(env("REGION_KEY")),
        "vyrez": bez_testu(env("AREA_KEY")) or "cely",
        "test_km2": env("TEST_KM2", "0"),
        "tiles_maxzoom": env("TILES_MAXZOOM"),
        "vrstvy": vrstvy(),
        # ČO V BALÍKU NIE JE A KDE TO JE. Mlčanie sa dá čítať ako „zabudlo sa
        # to pribaliť“ – to isté pravidlo, akým sa tu píše `bez_skal`.
        "bez_glyfov": glyfy_su_inde(man),
        "glyphs": man.get("glyphs") or "",
        "bez_viewera": True,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run": env("GITHUB_RUN_NUMBER"),
        "run_id": env("GITHUB_RUN_ID"),
        # Čo o mape hovorí manifest: bbox, zoomy vrstiev, zdroje výšok, prah
        # sklonu, testovací štvorec. Neopisuje sa – kopíruje sa.
        "manifest": {"dem": man.get("dem"),
                     "dem_maxzoom": man.get("dem_maxzoom"),
                     "dem_source": man.get("dem_source"),
                     "region": reg},
    }



# ---------- balenie ----------

def vsetky_subory(site):
    subory = []
    for root, _dirs, names in os.walk(site):
        for n in names:
            subory.append(os.path.join(root, n))
    return subory


# ---------- čo do balíka NEPATRÍ ----------
#
# Rozpis je v hlavičke súboru. Krátko: glyfy a viewer ležia na Pages, takže
# v balíku sú mŕtva váha – ale len vtedy, keď sa na ne dá odtiaľ dostať.

# Viewer je to, čo `workers/deploy/site.sh` kopíruje do KOREŇA `_site`
# z `poc/web` (`cp poc/web/*.js poc/web/*.json poc/web/index.html _site/`).
# Podpriečinky sa neriešia zámerne: `styles/`, `sprites/` a `tiles/` sú mapa.
VIEWER_PRIPONY = (".html", ".js", ".mjs", ".css")
VIEWER_SUBORY = ("style-overrides.json",)   # jediný `.json`, čo tam z viewera ide


def je_viewer(site, cesta):
    """Súbor webového viewera v koreni `_site`?"""
    rel = os.path.relpath(cesta, site)
    if os.path.dirname(rel):
        return False
    return rel.endswith(VIEWER_PRIPONY) or rel in VIEWER_SUBORY


def je_glyf(site, cesta):
    """Súbor v `_site/fonts/` – teda glyf."""
    rel = os.path.relpath(cesta, site)
    return rel.split(os.sep)[0] == "fonts"


def glyfy_su_inde(man):
    """Odkazuje manifest na glyfy MIMO balíka (absolútnou adresou)?

    Toto je celé rozhodnutie, a je odvodené z dát, nie z prepínača: keď štýl
    ukazuje na `https://…/fonts/{fontstack}/{range}.pbf` (Pages), sú súbory
    v balíku mŕtva váha. Keď ukazuje relatívne – mapa sveta – sú JEDINÝ zdroj
    a vynechať sa nesmú (na Pages tá mapa nejde).

    Keď sa manifest prečítať nedá, odpoveď je „neviem“, a to znamená NECHAŤ:
    väčší balík je chyba, ktorú vidno na veľkosti, kým mapa bez písmen vyzerá
    ako pokazený štýl.
    """
    return str(man.get("glyphs") or "").startswith(("http://", "https://"))


def mimo_balika(site, man):
    """Súbory z `_site`, ktoré do balíkov nepatria – zoznam a dôvody.

    Vracia `(subory, dovody)`; `dovody` je `[(popis, počet, bajty)]` do logu,
    lebo vynechať 90 MB potichu je presne to, čo pravidlo 4 zakazuje.
    """
    vsetky = vsetky_subory(site)
    skupiny = [("viewer (je na Pages)", [p for p in vsetky if je_viewer(site, p)])]
    if glyfy_su_inde(man):
        skupiny.append((f"glyfy (štýl si ich pýta z {man.get('glyphs')})",
                        [p for p in vsetky if je_glyf(site, p)]))
    elif any(je_glyf(site, p) for p in vsetky):
        log("Glyfy ostávajú v balíku – manifest na ne odkazuje relatívne "
            f"({man.get('glyphs') or 'manifest sa nedá prečítať'}), takže "
            f"balík je jediné miesto, kde ich štýl nájde.")

    subory, dovody = [], []
    for popis, kus in skupiny:
        if not kus:
            continue
        subory.extend(kus)
        dovody.append((popis, len(kus), sum(os.path.getsize(p) for p in kus)))
    return subory, dovody


def zaklad_subory(site, vylucit):
    """Súbory balíka `mapa` – všetko z `_site` OKREM toho, čo doň nepatrí.

    `vylucit` je dvoje. Jedno sú súbory balíkov `vrstevnice-skaly`
    a `tienovanie`: keby aj tie ostali v základnej mape, mali by ich cesty
    vnútri dvakrát – raz tu, raz v tom druhom ZIPe – a „iba mapa" by vážila
    rovnako ako mapa so všetkým, čo je presne to, kvôli čomu majú vlastné
    balíky. Druhé je to, čo nemá vlastný balík, lebo je na Pages – glyfy
    a viewer (`mimo_balika`). Oboje sa podáva zvonku, aby sa tá istá otázka
    nepočítala dvakrát; čo je čo, hovorí hlavička súboru.
    """
    von = {os.path.abspath(p) for p in vylucit}
    return [p for p in vsetky_subory(site) if os.path.abspath(p) not in von]


# ---------- beh ----------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default="_site", help="čo sa balí")
    # ZIP vždy (otvorí ho čokoľvek), `.aar` navyše pre iOS a macOS. Je to
    # zoznam a nie druhý prepínač „aj aar": formáty sa pridávajú, nie
    # prepínajú, a `--format=aar` samotné má zmysel v jobe na macOS, ktorý
    # dobalí to, čo Linux nevie.
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

    # RÝCHLY TEST ZAPISUJE DO VLASTNÉHO SÚBORU. `maps.json` je jediná odpoveď
    # na „ktoré mapy sú hotové" a mapa s terénom na 4 km² medzi ne nepatrí –
    # vlastný uzol (`cesta_katalog`) ju síce na položku ostrej mapy nepustí,
    # ale v zozname stála vedľa nej a vyzerala ako ďalší výsek. Ktorý súbor to
    # je, hovorí JEDNO miesto (`catalog.katalog_subor`), lebo tú istú otázku si
    # kladie aj `apple-archive.sh` a cezeň `catalog.sh` – dva výpočty by
    # znamenali zápis do jedného súboru a commit druhého.
    args.maps = catalog.katalog_subor(args.maps)
    # A ten istý súbor musí commitnúť `workers/deploy/catalog.sh` – to je ĎALŠÍ
    # KROK workflowu a kroky si prostredie nepodávajú. Ide to teda výstupom
    # kroku (`steps.publish.outputs.maps_file`); keby si ho ten krok odvodil
    # sám z `TEST_KM2`, bola by to druhá pravda o tom istom a rozišla by sa
    # presne vtedy, keď na tom záleží – zápis do jedného súboru, commit
    # druhého, a beh pri tom zelený.
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
        # Ticho preskočiť sa to NESMIE: v priečinku by potom chýbal `.aar`
        # a na ničom by nebolo vidieť prečo. `aa` je len na macOS.
        raise SystemExit("::error::Apple Archive sa nedá vyrobiť – nástroj "
                         "`aa` tu nie je. Je súčasťou macOS (11+), takže "
                         "`--format` s `aar` patrí do jobu na `macos-latest`; "
                         "na Linuxe nechaj `--format=zip`.")

    parts = cesta(regions)
    man = manifest_data(args.site)
    # Balíky v jednom zozname: druh, čo do neho patrí, a popis do logu.
    # Zoznam preto, že sa s nimi robí to isté – zabaliť, nahrať, prepísať
    # starý – a kópie toho istého by sa raz rozišli.
    # Piaty balík (wikipedia, nižšie) má VLASTNÝ KORENNÝ PRIEČINOK, a preto je
    # v každom riadku aj báza: články z Wikipédie nie sú súčasťou webu (na
    # Pages by len zjedli rozpočet stránky), takže ich job `wiki` odloží ako
    # samostatný artefakt a `deploy` ich podá sem cez `--wiki`. Cesty v ZIPe sa
    # počítajú od tej bázy, takže vnútri je `articles.ndjson`, nie
    # `_wiki/articles.ndjson`.
    #
    # Vrstevnice, skaly a tieňovanie sa počítajú PRED základnou mapou, lebo tá
    # ich musí VYNECHAŤ – majú vlastné balíky práve preto, aby si ich človek
    # nemusel sťahovať, keď ich nechce (viď hlavička súboru).
    vrstvy_pack = vrstvy_subory(args.site, man)
    tien_pack = tienovanie_subory(args.site, man)
    # Glyfy a viewer sú na Pages (rozpis v hlavičke). Musí byť VIDIEŤ, koľko
    # toho balík takto nenesie – vynechaných 90 MB potichu je to isté ako
    # 90 MB navyše potichu.
    von_pack, von_dovody = mimo_balika(args.site, man)
    for popis, kolko, bajtov in von_dovody:
        log(f"Do balíka nejde {popis}: {kolko} súborov, "
            f"{folder.human(bajtov)}")
    baliky = [
        ("", "základná mapa – bez vrstevníc, skál, tieňovania, glyfov a viewera",
         args.site, zaklad_subory(args.site, vrstvy_pack + tien_pack + von_pack)),
        ("vrstevnice-skaly", "vrstevnice a skalné plochy (.pmtiles)",
         args.site, vrstvy_pack),
        ("tienovanie", "výškové dlaždice pre tieňovanie a 3D terén (raster .pmtiles)",
         args.site, tien_pack),
        ("search", "vyhľadávací index pre offline hľadanie (SQLite FTS5)",
         args.site, hladanie_subory(args.site, man)),
    ]
    # WIKIPÉDIA SA PRIDÁ, LEN KEĎ O NEJ TENTO BEH VIE. Odkedy má vlastnú
    # pipeline (`.github/workflows/wiki.yml`), Build map články nesťahuje –
    # a keby ten balík ostal v zozname natrvalo, videl by ho ako „v tomto
    # builde nie je" a starý `-wikipedia.zip` aj `.aar` by na Drive ZMAZAL.
    # Pri každom builde mapy, teda pri každej zmene štýlu.
    #
    # To mazanie je pritom správne pri vrstve, ktorú beh vypol (skaly, terén):
    # tam „nie je v builde" naozaj znamená „nemá tam čo robiť". Rozdiel je
    # v tom, či o balíku tento workflow vôbec rozhoduje – a to hovorí `--wiki`
    # (dostal som články) alebo `--only=wikipedia` (idem robiť práve ten).
    if args.wiki or args.only == "wikipedia":
        baliky.append(
            ("wikipedia", "články z Wikipédie: articles.ndjson + index.json",
             args.wiki, vsetky_subory(args.wiki) if args.wiki else []))
    # `--only`: samostatná pipeline (napr. „Build wiki") vyrába JEDEN
    # balík a o zvyšok mapy sa nestará. Bez tohto by musela mať vlastný packer
    # a vlastný zápis do katalógu – dve kópie toho istého, ktoré sa raz rozídu.
    # Ostatné balíky sa vtedy ani nemažú: to, že ich tento beh nevyrobil,
    # neznamená, že v mape nie sú.
    if args.only:
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
    # O ČOM TENTO BEH ROZHODUJE – jeden zoznam pre obe strany. Podľa neho sa
    # nižšie maže starý balík na Drive a podľa neho sa prepisujú balíky
    # v katalógu; keby si to katalóg počítal sám, prišiel by o `wikipedia`
    # presne v tom behu, ktorý ju na Drive nechal ležať (pravidlo 1).
    spravuje = [kind or "mapa" for kind, *_ in baliky]
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
        # Lokálna skúška: to isté balenie, len bez Drive – nech sa dá pozrieť,
        # čo v balíkoch je, bez tokenu a bez nahrávania.
        out = args.out or os.environ.get("RUNNER_TEMP", "/tmp")
        for kind, popis, base, subory in baliky:
            if not subory:
                log(f"{meno(kind)}: {popis} v tomto builde nie je – vynechávam.")
                continue
            for fmt in formaty:
                name = meno(kind, fmt)
                BALICE[fmt](base, os.path.join(out, name), name[:-4], subory,
                            info=obsah(kind, man, fmt))
        return 0

    creds = auth.from_env()
    if creds is None:
        raise SystemExit(
            "::error::Publikovanie mapy na Drive potrebuje token vlastníka, "
            "ale v prostredí nie je. Doplň secret GDRIVE_CREDENTIALS (alebo "
            "premennú DRIVE_CLIENT a secrety DRIVE_SECRET / DRIVE_REFRESH) "
            "a podaj ho jobu cez `env:` – vyrobí ich workflow „Prihlásenie "
            "na Drive (jednorazové)“.")
    # Rozsah PRED balením: readonly token nič nenahrá, tak nech sa kvôli nemu
    # nebalí gigabajt. Tá istá lacná otázka ako pri cache.
    if auth.can_write(creds) is False:
        raise SystemExit(f"::error::Mapa sa nepublikovala: {auth.scope_hint()}")

    root = folder.folder_id(args.folder)
    fid = folder.ensure_path(creds, root, parts)
    hotove = []
    # Balík × formát: každý balík sa vyrobí v každom žiadanom formáte. Formát
    # je vonkajší cyklus zámerne až tu, nie v `baliky` – to, ČO je v balíku,
    # je vec obsahu a nie toho, do čoho sa zabalí.
    for (kind, popis, base, subory), fmt in [(b_, f) for b_ in baliky
                                             for f in formaty]:
        name = meno(kind, fmt)
        if not subory:
            # Vrstva v tomto builde nie je. Starý balík toho istého mena by
            # vedľa novej mapy tvrdil, že je – a na súbore by to nikto
            # nepoznal. Platí to pre KAŽDÝ formát: keby sa mazal len ZIP,
            # ostal by vedľa neho `.aar` z iného behu.
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
                              info=obsah(kind, man, fmt))
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
        hotove.append((kind, name, popis, velkost, prepisane, file_id, fmt))
    log(f"Hotovo: {len(hotove)} balíkov v {folder.folder_link(fid)}")

    # ---------- katalóg ----------
    if args.maps:
        # RÝCHLY TEST SA ZAPISUJE TIEŽ, LEN INAM. Balíky na Drive ležia
        # v priečinku ostrej mapy a odlišuje ich meno (`…-test4km2.zip`) –
        # a kým sa katalóg pri teste preskakoval, bol to jediný druh balíka,
        # o ktorom sa bez otvoreného Drive nedalo dozvedieť. Uzol testu je
        # vlastný (`cesta_katalog`), takže na položku ostrej mapy sadnúť
        # nemôže; že je to test, hovorí kľúč, meno aj `test_km2` v položke.
        kat = cesta_katalog(parts)
        zmenene = catalog.zapis_katalog(
            args.maps, parts, regions,
            # Do katalógu idú VŠETKY formáty. Beh, ktorý nahral len
            # `.aar`, sa k tomu, čo tam je, pridá (`merge`) – inak by
            # katalóg o ZIPoch prestal vedieť. To isté robí `iba`, len
            # o balík vyššie: samostatná pipeline pozná jediný balík.
            [(k, n, v, i, f) for k, n, _p, v, _pr, i, f in hotove],
            man, iba=args.only, merge="zip" not in formaty, kat=kat,
            layers=vrstvy(), spravuje=spravuje)
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
            for _kind, name, popis, velkost, prepisane, _fid, _fmt in hotove:
                f.write(f"| `{name}` | {popis} | {folder.human(velkost)} | "
                        f"{'prepísaný' if prepisane else '–'} |\n")
            f.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except auth.AuthError as exc:
        # Text tých hlášok už nesie, čo s nimi.
        print(f"::error::{exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
