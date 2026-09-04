#!/usr/bin/env python3
"""
Hotová mapa na Google Drive – balíky so stálym menom.

ČO TO ROBÍ. Z `_site` (celý web: dlaždice, štýly, vrstevnice, skaly,
tieňovanie, cestný graf, fonty a sprity) a z priečinka s článkami (`--wiki`)
sa zabalia balíky a nahrajú na Drive do priečinka podľa toho, čoho sa mapa
týka:

    <koreň>/slovensko/presovsky/vysoke_tatry/
        presovsky-vysoke_tatry.zip                    základná mapa, BEZ nižšie
                                                      (ale SO ZNAČENÝMI TRASAMI
                                                      a s hľadaním – to sú jej
                                                      časti, nie balíky; bez
                                                      glyfov a viewera)
        presovsky-vysoke_tatry-tienovanie.zip         len výškové dlaždice
        presovsky-vysoke_tatry-vrstevnice-skaly.zip   len tie dve vrstvy
        presovsky-vysoke_tatry-cesty.zip              CELÁ dopravná sieť aj
                                                      s obmedzeniami na ceste
        presovsky-vysoke_tatry-body.zip               body záujmu z OSM
        presovsky-vysoke_tatry-hranice.zip            hranice území a ich názvy
        presovsky-vysoke_tatry-vodstvo.zip            rieky, jazerá, more
        presovsky-vysoke_tatry-wikipedia.zip          články z Wikipédie
        presovsky-vysoke_tatry-navigacia.zip          navigačný graf (Valhalla)

KTORÉ BALÍKY SÚ, TU NAPÍSANÉ NIE JE – zoznam vyššie je ukážka, nie zdroj.
Drží ho `workers/data/packages.json` (číta ho `workers/deploy/baliky.py`) a je
to ten istý zoznam, z ktorého sa skladá formulár pregenerovania, dávka nad
krajinou aj mená a ikony v aplikácii. Balík preto pribúda na JEDNOM mieste;
kým sa písal na piatich, bola ktorákoľvek zabudnutá úprava tichá – vrstva sa
buď nezabalila nikam, alebo ostala aj v základnej mape a človek si ju stiahol
dvakrát.

GLYFY A WEBOVÝ VIEWER SA NEBALIA. Fonty boli po dlaždiciach druhá najväčšia vec
v balíku (tri fontstacky Noto Sans po ~34 MB, celý unicode) a mapa kraja z nich
použije zlomok; viewer (`index.html` a `*.js` z `poc/web`) je zase web, ktorý si
aplikácia nespúšťa – má vlastnú mapu. Oboje ostáva v `_site`, teda na Pages.

KDE SÚ TEDA GLYFY. Na dvoch miestach, a ani jedno z nich nie je balík mapy:

    web       na Pages. Manifest v balíku nesie ich ABSOLÚTNU adresu (`site.sh`
              ju skladá z `$BASE`), takže štýl vie, odkiaľ si ich vziať.
    aplikácia VO VLASTNOM BINÁRE. `skifahrer/rikimaps` si tri orezané stacky
              (3,5 MB) nesie sama a štýlu prepíše `glyphs` na ne pri načítaní –
              inak by offline mapa na hrebeni siahala na Pages a nemala ani
              jedno písmeno.

PRETO SA VYNECHÁVAJÚ VŽDY, nie podľa tvaru adresy v manifeste. Kým glyfy nosila
appka v balíku, bolo rozhodnutie odvodené z dát: „vynechaj ich práve vtedy, keď
na ne manifest odkazuje absolútne“, lebo pri relatívnom odkaze (mapa sveta) bol
balík jediné miesto, kde ich štýl našiel. Odkedy ich má appka v sebe, to
neplatí ani tam – a „keď sa manifest nedá prečítať, nechaj ich“ znamenalo
desiatky MB navyše zakaždým, keď sa `_site` zložilo v inom poradí (prvý ostrý
beh `.aar` presne tak dopadol).

ZÁKLADNÁ MAPA NEMÁ VRSTEVNICE, SKALY ANI TIEŇOVANIE. Sú to ťažké vrstvy
z výškového modelu, ktoré mapa na to, aby sa nakreslila, nepotrebuje, a majú
vlastné balíky presne preto, aby si ich človek nemusel sťahovať, keď ich
nechce – vážia porovnateľne s mapou samou (rozpis v `docs/velkost-balikov.md`).
Kto ich chce, rozbalí príslušný ZIP navrch (cesty vnútri sú tie isté ako
v `_site`, takže sa dá rozbaliť jeden cez druhý).

HĽADANIE A ZNAČENÉ TRASY SÚ NAOPAK V NEJ – SÚ TO ČASTI, NIE BALÍKY. Vlastný
`-search.zip` malo hľadanie a bola to chyba v tom, čo mapa sľubuje: kto si
stiahol mapu kraja, dostal mapu, v ktorej sa nedá nič nájsť, a že mu chýba
druhý súbor, nemal ako vedieť. Značené trasy sú ten istý prípad o krok ďalej –
turistická mapa bez značiek nesľubuje to, načo si ju človek stiahol. Cena za
oboje sú jednotky až desiatky MB proti stovkám, ktoré vážia dlaždice, takže sa
tu nemá čo šetriť. Merajú sa (`casti`), aby bolo v katalógu vidieť, koľko
z balíka sú.

`-cesty.zip` JE CELÁ DOPRAVNÁ SIEŤ, nie prívesok k mape: `-transport.pmtiles`,
teda cesty od diaľnice po schody, železnice, električky a metro, trajekty
a lanovky – a odteraz aj OBMEDZENIA NA CESTE (výška podjazdu, hmotnosť,
rýchlosť, pruhy) ako atribúty tých istých ciest. Cestná sieť V MAPE je vrstva
`transportation` schémy OpenMapTiles – stavaná na kreslenie a v jednom archíve
s vodstvom, krajinnou pokrývkou a popismi –, takže „chcem len siete, po ktorých
sa dá cestovať" znamenalo stiahnuť stovky MB a vytiahnuť si to z nich sám.
Rozpis je v hlavičke `workers/transport/transport.yml`.

BALÍK `linie` SA ROZPADOL A UŽ NIE JE. Boli v ňom tri vrstvy naraz (dopravná
sieť, značené trasy, obmedzenia na ceste) a každá z nich patrila inam: sieť je
odteraz `cesty`, trasy sú v mape (viď vyššie) a obmedzenia sú ATRIBÚTY tej
siete, nie vlastná vrstva – bola to tá istá cesta v druhom archíve, ktorú si
musel každý spájať späť cez `osm_id`. `linie` je preto v `ZRUSENE` a jeho starý
súbor sa na Drive maže.

HRANICE A VODSTVO SÚ NOVÉ BALÍKY z toho istého dôvodu, pre ktorý existuje
`cesty`: v mape sú obe veci nakreslené, ale nie použiteľné. Hranica vo vrstve
`boundary` OpenMapTiles je čiara BEZ MENA územia, ktoré ohraničuje (takže sa
z nej nedá povedať, v ktorej obci si), a voda je rozdelená do troch vrstiev
s menom mimo geometrie. Rozpis je v hlavičkách `workers/boundaries/
boundaries.yml` a `workers/water/water.yml`.

NAVIGÁCIA JE ZO ZÁKLADNEJ MAPY VON A MÁ VLASTNÝ BALÍK. Balila sa dovnútra mapy
s tým istým argumentom ako index, lenže NAMERANÉ TO TAK NIE JE: graf kraja váži
170 až 190 MB a mapa s ním 283 MB, čiže dve tretiny „základnej mapy" bola sieť,
po ktorej sa jazdí, nie mapa, ktorá sa kreslí. To je presne prípad vrstevníc
a tieňovania: ťažká vec, ktorú mapa na to, aby sa nakreslila, nepotrebuje.
Stojí vedľa `cesty` a sú to dve otázky: „chcem vidieť, kadiaľ sa dá ísť"
a „chcem, aby ma to tam doviezlo".

HĽADANIE AJ NAVIGÁCIA SÚ VŽDY ZA TEN JEDEN REGIÓN. Index je z toho istého PBF
ako mapa; graf sa z neho stavia tiež. Trasa v ňom KONČÍ NA HRANICI REGIÓNU –
hrana, ktorej v rezanom PBF chýba druhý koniec, je slepá ulica – a kto
potrebuje prejsť hranicu, má na to celoštátny graf z `navigation.yml`. Je to
zámer, nie opomenutie, a `graf.json` v balíku to o sebe hovorí
(`rozsah: "region"`).

KOĽKO Z BALÍKA TÁ ČASŤ JE, MUSÍ BYŤ VIDIEŤ. Časť, ktorá sa nedá odmerať, je
presne to, čím bol `search-index.db` predtým, než sa naň niekto pozrel: bol
v balíku dvakrát a na veľkosti to nikto nepoznal. Každá časť sa preto premeria
a jej veľkosť ide do `maps.json` pod balík `mapa` (kľúč `casti`).

Úrovne cesty, ktoré nedávajú zmysel, sa vynechajú: build celej krajiny nemá
kraj a build celého kraja nemá výsek. Chýbajúce priečinky sa vyrobia.

MENO AJ ODKAZ SÚ STÁLE – rovnaký kraj (a rovnaký výsek) má vždy to isté meno,
takže ďalší build starý balík PREPÍŠE a v priečinku je jeden aktuálny súbor
namiesto histórie behov. Prepíše sa pritom OBSAH toho istého súboru
(`folder.upload_clobber`), takže mu ostane id – a odkaz, ktorý o ňom hovorí
`maps.json`, platí aj po ďalšom builde. Kým sa nahrával nový súbor a starý sa
mazal, bol ten odkaz starý presne jeden build a katalóg, ktorý sa nestihol
commitnúť, ukazoval do prázdna (rozpis pri `upload_clobber`).

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
subory = load("deploy_subory", "subory.py")     # čo je v ktorom balíku
katalog_balikov = load("deploy_baliky", "baliky.py")   # ktoré balíky vôbec sú
# Mená nakrátko: čítajú sa v `main()` vedľa seba a `subory.subory` by bolo
# horšie čitateľné než to, čo tie funkcie robia.
baliky_vrstiev = subory.baliky_vrstiev
casti_baliku = subory.casti_baliku
kde_su_glyfy = subory.kde_su_glyfy
manifest_data = subory.manifest_data
mimo_balika = subory.mimo_balika
velkost_casti = subory.velkost_casti
vsetky_subory = subory.vsetky_subory
zaklad_subory = subory.zaklad_subory
BALICE = pack.BALICE
aa_je = pack.aa_je
auth = load("drive_auth", os.path.join(_DRIVE, "auth.py"))        # kto sme na Drive
folder = load("drive_folder", os.path.join(_DRIVE, "folder.py"))  # priečinky a nahrávanie

# Priečinok, do ktorého sa mapy publikujú. Ako pri DMR 5.0 a cache platí, že
# tajomstvo to nie je – id chodí v zdieľanom odkaze; tajomstvom je token.
FOLDER_ID = "1pvrw7CGUkQLwg8Ql8xbKA4HhQHvPl8_7"

# BALÍKY, KTORÉ UŽ NIE SÚ. Drží ich ten istý číselník ako tie živé
# (`workers/data/packages.json`, kľúč `zrusene`) – balík sa tam presunie
# z jedného zoznamu do druhého a obe strany zmeny sú tak na jednom mieste.
#
# Zoznam nie je pamätník: `-search.zip` aj `-linie.zip` z minulých behov na
# Drive LEŽIA ďalej (mená sú stále, takže ich nový beh neprepíše) a v katalógu
# by ostali ako odkaz, ktorý sľubuje niečo, čo si už netreba sťahovať – alebo
# horšie, čo už neexistuje: obsah `linie` sa rozpadol do `cesty` (dopravná
# sieť), do základnej mapy (značené trasy) a do atribútov tej siete
# (obmedzenia na ceste). Preto sa starý balík maže a z položky katalógu
# vypadne – rovnako, ako keď vrstva v builde nie je. Až prestane byť čo mazať,
# môže odtiaľto vypadnúť aj on.
ZRUSENE = katalog_balikov.zrusene()

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
    if env("TRANSPORT_ENABLED") == "true":
        out.append("doprava")
    if env("BOUNDARIES_ENABLED") == "true":
        out.append("hranice")
    if env("WATER_ENABLED") == "true":
        out.append("vodstvo")
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


# ---------- čo balík o sebe hovorí ----------

def obsah(kind, man, fmt="zip", casti=None):
    """`obsah.json` do balíka – to, čo kedysi nieslo meno súboru.

    `casti` sú kúsky, ktoré cestujú V ZÁKLADNEJ MAPE (dnes hľadanie) – píšu sa
    aj s veľkosťou a aj vtedy, keď v mape nie sú (`files: 0`). Kto balík
    rozbalí, sa tak nemusí pýtať priečinka, či v ňom index je.
    """
    reg = catalog.region_entry(man)
    return {
        "balik": kind or "mapa",
        # Časti sú vec ZÁKLADNEJ MAPY; vo vlastnom balíku vrstiev by kľúč
        # `casti` sľuboval, že tam hľadanie môže byť.
        **({"casti": velkost_casti(casti)} if not kind and casti else {}),
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
        # Vždy `True` – glyfy sa nebalia nikdy (rozpis v hlavičke). Pole ostáva,
        # lebo `obsah.json` má povedať, čo v balíku NIE JE: mlčanie sa dá čítať
        # ako „zabudlo sa to pribaliť“.
        "bez_glyfov": True,
        "glyphs": man.get("glyphs") or "",
        "glyfy_kde": kde_su_glyfy(man),
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
    # VŠETKO, ČO MÁ VLASTNÝ BALÍK, sa počíta PRED základnou mapou, lebo tá to
    # musí VYNECHAŤ – vlastné balíky majú práve preto, aby si ich človek
    # nemusel sťahovať, keď ich nechce (viď hlavička súboru). Zoznam drží
    # číselník (`workers/data/packages.json`), takže sem nový balík nepribúda
    # ručne: to je celý zmysel tej zmeny. Každý sa počíta RAZ a to isté pole
    # ide aj do vlastného balíka aj do `vylucit`; druhé volanie tej istej
    # funkcie by bola druhá odpoveď na tú istú otázku.
    vrstvy = baliky_vrstiev(args.site, man)
    # ČASTI ZÁKLADNEJ MAPY – hľadanie a značené trasy. Zo základnej mapy sa
    # NEVYNÍMAJÚ (sú v nej, o to ide); počítajú sa preto, aby sa dali premerať
    # a ich veľkosť išla do katalógu pod balík `mapa`.
    #
    # Pri `--only` sa nepočítajú vôbec: tá pipeline základnú mapu nerobí a jej
    # `_site` mapu ani neobsahuje, takže by premerala PRÁZDNO a katalóg by
    # o mape, ktorá hľadanie má, tvrdil, že ho nemá.
    casti = [] if args.only else casti_baliku(args.site, man)
    # Viewer je na Pages a glyfy si nesie appka (rozpis v hlavičke). Musí byť
    # VIDIEŤ, koľko toho balík takto nenesie – vynechaných 90 MB potichu je to
    # isté ako 90 MB navyše potichu.
    von_pack, von_dovody = mimo_balika(args.site, man)
    for popis, kolko, bajtov in von_dovody:
        log(f"Do balíka nejde {popis}: {kolko} súborov, "
            f"{folder.human(bajtov)}")
    for kluc, popis, subory in casti:
        log(f"V základnej mape je časť `{kluc}` – {popis}: "
            + (f"{len(subory)} súborov, "
               f"{folder.human(sum(os.path.getsize(p) for p in subory))}"
               if subory else "TENTO BUILD JU NEVYROBIL, v mape nebude"))
    # Vynechané zo základnej mapy: súbory VŠETKÝCH vlastných balíkov plus to,
    # čo v balíku nemá čo robiť. Skladá sa to z toho ISTÉHO poľa, z ktorého sa
    # tie balíky o riadok nižšie vyrábajú – balík, ktorý pribudne do číselníka,
    # tak nemá ako ostať aj v mape.
    vylucit = [p for _b, subory in vrstvy for p in subory] + von_pack
    baliky = [
        ("", "základná mapa – celá kresba z OSM aj so značenými trasami "
             "a hľadaním; bez vrstiev, ktoré majú vlastný balík, a bez glyfov "
             "a viewera",
         args.site, zaklad_subory(args.site, vylucit)),
    ] + [(b["kluc"], b["popis"], args.site, subory) for b, subory in vrstvy]
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
            ("wikipedia", katalog_balikov.balik("wikipedia")["popis"],
             args.wiki, vsetky_subory(args.wiki) if args.wiki else []))
    # `--only`: samostatná pipeline (napr. „Build wiki") vyrába JEDEN
    # balík a o zvyšok mapy sa nestará. Bez tohto by musela mať vlastný packer
    # a vlastný zápis do katalógu – dve kópie toho istého, ktoré sa raz rozídu.
    # Ostatné balíky sa vtedy ani nemažú: to, že ich tento beh nevyrobil,
    # neznamená, že v mape nie sú.
    if args.only:
        # Základná mapa je v zozname pod prázdnym kľúčom (jej meno nemá
        # príponu balíka), ale volá sa `mapa` – všade inde, v číselníku aj
        # v katalógu. `--only=mapa` teda musí ísť, inak by bola jediným
        # balíkom, ktorý sa nedá pregenerovať sám.
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
    # O ČOM TENTO BEH ROZHODUJE – jeden zoznam pre obe strany. Podľa neho sa
    # nižšie maže starý balík na Drive a podľa neho sa prepisujú balíky
    # v katalógu; keby si to katalóg počítal sám, prišiel by o `wikipedia`
    # presne v tom behu, ktorý ju na Drive nechal ležať (pravidlo 1).
    spravuje = [kind or "mapa" for kind, *_ in baliky]
    # ZRUŠENÝ BALÍK NIE JE VEC JEDNÉHO BEHU, a preto nejde cez `spravuje`, ale
    # vlastným parametrom (`zrusene=` v `zapis_katalog`). Kým sa naň hľadelo
    # ako na „balík, o ktorom tento beh rozhoduje", vedel ho z položky vyhodiť
    # len PREPIS – a job s `.aar` položku neprepisuje, ale dopĺňa: prebral si
    # teda balíky z katalógu aj s `-search` a odkaz na súbor, ktorý ten istý
    # beh o pár riadkov nižšie z Drive zmazal, sa v `maps.json` objavil znova.
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
        hotove.append((kind, name, popis, velkost, prepisane, file_id, fmt))
    log(f"Hotovo: {len(hotove)} balíkov v {folder.folder_link(fid)}")

    # ---------- balík, ktorý už neexistuje ----------
    # Meno je stále, takže ho nový beh NEPREPÍŠE – a `-search.zip` z minulého
    # behu by v priečinku ležal vedľa novej mapy a tváril sa, že si ho treba
    # stiahnuť, hoci index je odteraz vnútri mapy. Je to tá istá vec, akú robí
    # cyklus vyššie s balíkom vrstvy, ktorú build nevyrobil, len o dôvod
    # ďalej: nie „v tomto builde nie je", ale „taký balík už nie je".
    if not args.only:
        for kind in ZRUSENE:
            for fmt in formaty:
                name = meno(kind, fmt)
                kolko = folder.delete_named(creds, fid, name)
                if kolko:
                    log(f"::warning::Balík `{kind}` už neexistuje – jeho obsah "
                        f"je v základnej mape. Zmazal som {kolko}× {name}, aby "
                        f"si ho nikto nesťahoval druhýkrát.")

    # ---------- čo v priečinku NAOZAJ leží ----------
    # Zoznam id, ktoré v priečinku mapy sú TERAZ – teda po nahratí aj po
    # mazaní. Katalóg podľa neho zahodí odkazy na súbory, ktoré tam nie sú
    # (rozpis pri `precisti_mrtve` v `catalog.py`) – a keď taký súbor v
    # priečinku pod iným id JE, odkaz sa naň prepíše. Odkedy `upload_clobber`
    # prepisuje obsah a id nechá, je to už len záchranná sieť na balíky spred
    # tej zmeny a na ručné zásahy do priečinka.
    #
    # `None` a nie `{}` pri chybe: „nepodarilo sa mi to zistiť" a „v priečinku
    # nič nie je" sú dve rôzne odpovede a tá druhá by z katalógu vymazala celú
    # mapu. Beh na tom nepadá – balíky sú nahraté a to je to podstatné.
    zive = None
    try:
        zive = folder.ids_in(creds, fid)
        log(f"V priečinku mapy je {len(zive)} súborov – podľa nich sa "
            f"z katalógu vyhodia odkazy na tie, ktoré tam už nie sú.")
    except Exception as exc:                       # noqa: BLE001 – viď vyššie
        log(f"::warning::Priečinok mapy sa nedal vypísať ({exc}) – odkazy "
            f"v katalógu tento beh neoveril. Zapíšem ich tak, ako sú.")

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
            layers=vrstvy(), spravuje=spravuje,
            # KOĽKO Z MAPY JE HĽADANIE. Odkedy nemá vlastný balík, je toto
            # jediné miesto, kde sa to dá prečítať bez toho, aby si človek
            # stiahol stovky MB a rozbalil ich. (Navigácia už vlastný balík
            # má, takže jej veľkosť je v katalógu pod ním.)
            casti=None if args.only else velkost_casti(casti),
            # Balík, ktorý už neexistuje, a odkaz, za ktorým už súbor nie je –
            # dve veci, ktoré v katalógu vyzerajú ako ponuka na stiahnutie
            # a nie sú ňou. `zrusene` platí aj pri `--only`: „taký balík už
            # nie je" nezávisí od toho, ktorá pipeline katalóg práve píše.
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
            for _kind, name, popis, velkost, prepisane, _fid, _fmt in hotove:
                f.write(f"| `{name}` | {popis} | {folder.human(velkost)} | "
                        f"{'prepísaný' if prepisane else '–'} |\n")
            f.write("\n")
            # ČASTI ZÁKLADNEJ MAPY zvlášť – v tabuľke vyššie sú započítané
            # v jej veľkosti a bez tohto by sa nedalo povedať, koľko z nej sú.
            # Časť, ktorá v mape NIE JE, sa píše tiež: mlčanie by sa dalo
            # čítať aj ako „zabudlo sa to premerať".
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
        # Text tých hlášok už nesie, čo s nimi.
        print(f"::error::{exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        sys.exit(1)
