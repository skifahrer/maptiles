#!/usr/bin/env python3
"""
Katalóg máp `maps.json` – čo sa doň píše a kam.

PREČO ZVLÁŠŤ OD `publish-map.py`: ten odpovedá na „čo sa publikuje, ako sa to
volá a ako sa to nahrá na Drive"; toto na „čo o tom vie zoznam v repozitári".
Sú to dve otázky a súbor prerástol strop 800 riadkov práve tam, kde sa
stretli – rezalo sa teda tam, kde sa mení otázka. Vedľa leží `catalog.sh`:
ten ten istý súbor commitne, keď ho tento modul zapísal.

Volá to `publish-map.py` (a cezeň aj pipeline článkov z Wikipédie
s `--only=wikipedia`). Samostatne sa dá spýtať jedinú vec – KTORÝ katalóg
je ten správny, keď beh je rýchly test:

    python3 workers/deploy/catalog.py --subor        # maps.json / maps-test.json

Robí to `deploy/apple-archive.sh` (bash si to nemá ako vypočítať) – nech na tú
otázku odpovedá to isté miesto ako pri zápise.
"""
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")     # číselníky (areas, regions)
_DRIVE = os.path.join(_WORKERS, "drive")


def _load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


folder = _load("drive_folder", os.path.join(_DRIVE, "folder.py"))


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def log(msg):
    print(msg, flush=True)


def rozdel_test(key):
    """`vysoke_tatry_test4km2` → (`vysoke_tatry`, `4`), inak `(key, "")`.

    Opak `cesta_katalog` v `publish-map.py`. Prípona je tá istá, akú nesú
    mená balíkov – aby sa uzol katalógu a súbor na Drive dali prečítať ako
    jedna vec.
    """
    cut = key.rfind("_test")
    if cut < 0 or not key.endswith("km2"):
        return key, ""
    stred = key[cut + 5:-3]
    return (key[:cut], stred) if stred.replace(".", "").isdigit() else (key, "")


# ---------- ktorý katalóg: ostrý, alebo testovací ----------
# JEDNO MIESTO, KTORÉ NA TO ODPOVEDÁ. Pýtajú sa naň traja: `publish-map.py`
# (kam zapísať), `deploy/apple-archive.sh` (ktorý súbor si vypýtať z vetvy
# a doplniť o `.aar`) a cez neho aj `deploy/catalog.sh` (ktorý commitnúť).
# Keby si to každý odvodil sám z `TEST_KM2`, raz sa rozídu – a rozísť sa tu
# znamená, že sa test zapíše do jedného súboru a commitne druhý.
KATALOG = "maps.json"
KATALOG_TEST = "maps-test.json"


def katalog_subor(base=KATALOG):
    """`maps.json`, alebo `maps-test.json` pri rýchlom teste. Prázdne = nezapisuj.

    PREČO VLASTNÝ SÚBOR A NIE LEN VLASTNÝ UZOL. Testovacia mapa má vlastný uzol
    už dávno (`cesta_katalog` v `publish-map.py`), takže na položku ostrej mapy
    sadnúť nemôže. Ležala ale v tom istom zozname – a `maps.json` je JEDINÁ
    odpoveď na otázku „ktoré mapy sú hotové". Kto ho číta, prechádza `regions`
    a `subregions`; uzol `vysoke_tatry_test4km2` v ňom vyzerá ako ďalší výsek
    a to, že je v ňom terén na 4 km², je vidieť až na `test_km2` v položke –
    teda na poli, o ktorom čitateľ nemusí vedieť. To je pravidlo 2 z druhej
    strany: keď rozsah nie je celý, musí sa zmeniť MENO. Tu je tým menom meno
    súboru.

    Zapisovať sa testy musia ďalej – balík `…-test4km2.zip` leží na Drive
    v priečinku ostrej mapy a bez katalógu sa o ňom bez tokenu nedá dozvedieť.
    Preto sú to dva súbory s tým istým tvarom, nie jeden a zahodenie.
    """
    if not base:
        return ""
    test_km2 = env("TEST_KM2", "0")
    if test_km2 in ("", "0"):
        return base
    koren, _, pripona = base.rpartition(".")
    return f"{koren or base}-test" + (f".{pripona}" if koren else "")


def region_entry(man):
    """Položka regiónu z `manifest.json` – zoomy, bbox, zdroje výšok."""
    key = man.get("default_region")
    return ((man.get("regions") or {}).get(key) or {}) if key else {}


# Ktoré vrstvy sú v balíku ako `.pmtiles` a pod akou cestou. Mená kľúčov sú tie
# isté ako v `manifest.json`, lebo odtiaľ to ide – dva slovníky pre tú istú vec
# by sa raz rozišli.
VRSTVY_TILES = ("pmtiles", "contours", "rocks", "trails", "features", "roads")


def tiles_paths(man, reg):
    """Cesty k `.pmtiles` v balíku – tak, ako ich beh naozaj pomenoval.

    MENO SÚBORU SA NEDÁ ODVODIŤ Z KĽÚČA V KATALÓGU a nikto sa o to nesmie
    pokúšať. Kľúč uzla je `bratislavsky_test4km2` (nesie, že mapa je zo 4 km²),
    balík sa volá `bratislavsky-test4km2.zip` a dlaždice v ňom
    `tiles/bratislavsky_test4-contours.pmtiles` – tri rôzne zápisy tej istej
    veci, lebo každý odpovedá na inú otázku. Kto by si z kľúča poskladal
    `tiles/<kľúč>.pmtiles`, dostane cestu, ktorá v balíku NIE JE, a vrstva sa
    ticho nenačíta. To isté platí pri výreze: uzol je `vysoke_tatry`, ale
    dlaždice sa volajú podľa KRAJA (`presovsky-…`), lebo mapa je celý kraj.

    Preto sa sem prepisujú cesty z `manifest.json` – ten ich pozná, lebo podľa
    neho ich číta aj viewer. Vrstva, ktorá v mape nie je, tu nie je tiež.

    Terén je v manifeste zvlášť (`dem`) a ako ADRESA NA PAGES
    (`pmtiles://<base>/tiles/…`), lebo tam ho číta prehliadač. Do katalógu
    patrí to, čo platí v balíku, teda relatívna cesta. Berie sa z nej MENO
    SÚBORU a predradí sa `tiles/`: hľadať v tej adrese `tiles/` sa nedá, lebo
    ju obsahuje aj meno repozitára (`…/maptiles/tiles/…` → `tiles/tiles/…`).
    V balíku ležia dlaždice vždy v `tiles/`, tak ako v `_site`.
    """
    out = {k: reg[k] for k in VRSTVY_TILES if reg.get(k)}
    dem = (man.get("dem") or "").rstrip("/")
    if dem.endswith(".pmtiles"):
        out["terrain"] = "tiles/" + dem.rsplit("/", 1)[-1]
    return out


# ---------- katalóg máp v repozitári ----------
# `maps.json` je JEDINÝ zoznam toho, ktoré mapy sú hotové a kde ležia. Na Drive
# sa to inak nedá zistiť bez tokenu a bez klikania: priečinky sú tri úrovne
# hlboko a mená balíkov si človek nepamätá. Preto ho zapisuje ten, kto tie
# súbory práve nahral – vie ich id, veľkosť aj to, čo v nich je.
#
# ŠTRUKTÚRA SEDÍ S CESTOU NA DRIVE, a to zámerne: `krajina → kraj → výsek` je tá
# istá odpoveď na otázku „čoho sa tá mapa týka", akú dáva `cesta()`. Dve rôzne
# hierarchie tých istých máp by sa raz rozišli (pravidlo 1).
#
# KRAJINA JE HLAVNÝ KĽÚČ – rovno v koreni, bez obálky:
#
#   slovensko.regions.presovsky.maps                          celý kraj
#   slovensko.regions.presovsky.subregions.vysoke_tatry.maps  výsek
#
# Metadáta katalógu ležia vedľa nich a poznať ich je po čom: začínajú
# podčiarkovníkom (`_comment`, `_updated_at`). Je to tá istá konvencia ako
# vo `workers/data/areas.json`, kde sú kľúče pohorí tiež v koreni a `_comment`
# medzi nimi – kto katalóg číta, preskočí kľúče na `_`.
#
# ZÁPIS JE „NAHRAĎ CELÚ POLOŽKU". Keď mapa v zozname nie je, pridá sa; keď je,
# prepíše sa celá – vrátane balíkov, ktoré tento build nevyrobil, aby v nej
# nezostal odkaz na súbor, ktorý sa medzitým zmazal.

def katalog_meno(regions, key, kind):
    """Ľudské meno kraja/výseku/krajiny – z číselníkov, nie vymyslené.

    Uzol rýchleho testu má v kľúči príponu, ktorá v číselníkoch nie je –
    meno sa hľadá bez nej a to, že je to test, sa dopíše. Bez toho by
    v katalógu stálo holé `vysoke_tatry_test4km2` a vyzeralo by to ako
    ďalšie pohorie.
    """
    key, test = rozdel_test(key)
    chvost = f" – rýchly test {test} km²" if test else ""
    if kind == "area":
        try:
            with open(os.path.join(_DATA, "areas.json")) as f:
                meno = (json.load(f).get(key) or {}).get("name") or key
        except (OSError, ValueError):
            meno = key
        return meno + chvost
    r = regions.get(key) or {}
    return (r.get("name") or key) + chvost


# ---------- kedy to vzniklo ----------
# DVA ZÁPISY TOHO ISTÉHO OKAMIHU, a je to zámer. `…_at` je ISO 8601 v UTC –
# to sa dá prečítať očami priamo v `maps.json` a zoradiť ako text. `…_ts` sú
# sekundy od epochy – to sa dá odčítať bez parsovania dátumu, teda „ako stará
# je táto mapa" je jedno mínus. Kým tu bol len reťazec, musel si ho každý
# čitateľ (viewer, aplikácia, skript) parsovať sám, a to je presne ten druh
# práce, ktorú katalóg má čitateľovi ušetriť – pozná ten okamih presne, tak ho
# napíše v oboch podobách naraz a nemôžu sa rozísť.
def teraz():
    """(ISO 8601 UTC, sekundy od epochy) – jeden okamih v oboch podobách."""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), int(t)


def zapis_balik(mapy, kind, name, velkost, fid, fmt, kedy="", kedy_ts=None):
    """Jeden balík v jednom formáte do `maps` položky katalógu.

    JEDNO MIESTO PRE OBE CESTY. Zapisujú sa tu dve vetvy – celý build
    (nahradenie položky) aj samostatná pipeline (`--only`, doplnenie jedného
    balíka) – a keby si každá skladala ten zápis sama, raz sa rozídu: jedna by
    vedela o formátoch a druhá nie.

    `formats` je to podstatné; `file`/`size`/`link`/`download` na úrovni
    balíka ukazujú na ZIP, aby starší čitateľ katalógu nemusel o formátoch
    vedieť. `.aar` ich preto NEPREPISUJE – prepísal by odkaz, ktorý sa
    doteraz čítal ako „stiahni mapu".
    """
    zaznam = {
        "file": name,
        "size": velkost,
        "link": folder.file_link(fid),
        "download": folder.download_link(fid),
        # Z KTORÉHO BEHU je práve TENTO balík. Články z Wikipédie robí iná
        # pipeline než mapu, takže `run` pri kraji (= beh, čo vyrobil mapu)
        # o nich nič nepovie – a naopak: keby si ho tá pipeline prepísala na
        # svoj, katalóg by tvrdil, že mapu vyrobil beh, ktorý stiahol len
        # články. Beh 1 workflowu „Build wiki" tak v katalógu prepísal
        # beh 110 Build map. Preto je pôvod pri balíku, nie len pri kraji.
        "run": env("GITHUB_RUN_NUMBER"),
    }
    if kedy:
        zaznam["updated_at"] = kedy
    if kedy_ts is not None:
        zaznam["updated_ts"] = kedy_ts
    polozka = mapy.setdefault(kind or "mapa", {})
    polozka.setdefault("formats", {})[fmt] = zaznam
    if fmt == "zip":
        polozka.update(zaznam)


def zapis(path, data, popis):
    """Zapíše katalóg, keď sa naozaj zmenil. True = súbor je iný."""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with open(path) as f:
            if f.read() == text:
                log(f"{path}: to isté ako doteraz – bez zmeny.")
                return False
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(text)
    log(f"{path}: {popis}")
    return True


def zapis_casti(mapy, casti):
    """Koľko z balíka `mapa` je hľadanie a koľko navigácia.

    HĽADANIE A NAVIGÁCIA NEMAJÚ VLASTNÝ BALÍK – cestujú v základnej mape
    (rozpis v hlavičke `publish-map.py`), takže toto je jediné miesto, kde sa
    ich veľkosť dá prečítať bez toho, aby si človek stiahol stovky MB
    a rozbalil ich. Píše sa aj `0`: „hľadanie v tejto mape nie je" je odpoveď,
    kým chýbajúci kľúč sa dá čítať aj ako „zabudlo sa to premerať".

    Číslo sa volá `raw_size` a stojí vedľa `size` toho istého balíka zámerne:
    `size` je zabalený ZIP, `raw_size` bajty pred zabalením (vlastný archív tá
    časť nemá, takže sa iné číslo zmerať nedá). Ten istý kľúč pre dve rôzne
    čísla by sa sčítal a nesedelo by to.
    """
    polozka = mapy.get("mapa")
    if polozka is None:
        return                        # tento beh základnú mapu nenahral
    if not casti:
        polozka.pop("casti", None)
        return
    polozka["casti"] = {k: dict(v) for k, v in casti.items()}


def zapis_katalog(path, parts, regions, baliky, man, iba="", merge=False,
                  kat=None, layers=None, spravuje=None, casti=None):
    """Doplň (alebo prepíš) položku v `maps.json`. Vracia True, keď sa zmenil.

    `baliky` je zoznam `(druh, meno, veľkosť, id, formát)` – to, čo sa naozaj
    nahralo.

    `kat` je cesta v KATALÓGU, keď sa líši od cesty na Drive (`parts`) –
    presne to je prípad rýchleho testu (viď `cesta_katalog`). `drive` v
    položke sa preto píše z `parts`: uzol je iný, priečinok ten istý.

    `layers` sú tie isté kúsky, aké nesie meno balíka (`vrstvy()` v
    `publish-map.py`) – podávajú sa, aby o tom, čo v mape je, nerozhodovali
    dve miesta.

    `merge=True` znamená „tento beh nahral LEN ĎALŠÍ FORMÁT toho istého, čo
    tam už je" – vtedy sa balíky doplnia k existujúcim namiesto nahradenia.
    Tak to má job na macOS, ktorý dobalí `.aar` po tom, čo `deploy` nahral
    ZIPy: keby prepisoval, katalóg by o ZIPoch prestal vedieť. Pri bežnom
    behu (`merge=False`) sa naopak MUSÍ nahradiť – inak by v katalógu ostali
    odkazy na balíky, ktoré tento build nevyrobil.

    `casti` sú kúsky, ktoré cestujú V BALÍKU `mapa` a vlastný balík nemajú
    (hľadanie, navigačný graf) – `{kľúč: {"raw_size": B, "files": N}}`. Zapisujú
    sa pod ten balík (`zapis_casti`), lebo inak sa ich veľkosť nedá zistiť
    inak než stiahnutím mapy. `None` znamená „tento beh ich nepočítal"
    (samostatná pipeline s `--only`), a vtedy sa nesmú ani zmazať.

    `spravuje` sú DRUHY BALÍKOV, O KTORÝCH TENTO BEH ROZHODUJE – ten istý
    zoznam, podľa ktorého `publish-map.py` maže starý balík na Drive. Balík,
    ktorý v ňom nie je, sa v položke NECHÁ TAK: `wikipedia` robí vlastná
    pipeline (`wiki.yml`) a Build map o nej nič nevie, takže „nevyrobil som
    ho" tam neznamená „v mape nie je". Na Drive to rozlíšenie platí od
    začiatku vlastnej pipeline, v katalógu chýbalo – a tak ho každý build
    mapy, teda každá zmena štýlu, z `maps.json` ticho zmazal, hoci
    `…-wikipedia.zip` na Drive ležal ďalej (behy 31892120453 a staršie:
    najprv prišiel o balík `bratislavsky`, potom aj `presovsky`).
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    je_test = os.path.basename(path) == KATALOG_TEST
    data.setdefault("_comment",
                    ("Rýchle TESTOVACIE behy" if je_test else
                     "Katalóg hotových máp na Google Drive")
                    + " – ktoré sú a kde. "
                    + ("Terén (vrstevnice, skaly, tieňovanie) je v nich len na "
                       "pár km² zo stredu výrezu, takže to NIE SÚ mapy na "
                       "stiahnutie; hotové mapy sú v maps.json. " if je_test
                       else "")
                    + "Hlavný kľúč je krajina, pod ňou `regions` (kraj) a "
                    "`subregions` (výsek); kľúče na `_` sú metadáta katalógu, "
                    "nie krajiny. Dopisuje ho na konci buildu "
                    "workers/deploy/publish-map.py (krok „Zapíš mapu do "
                    "maps.json“); ručne sa needituje. Odkazy otvorí ten, kto "
                    "má prístup k priečinku s mapami.")
    data["_updated_at"], data["_updated_ts"] = teraz()

    kat = kat or parts
    krajina = data.setdefault(kat[0], {})
    krajina.setdefault("name", katalog_meno(regions, kat[0], "region"))
    uzol = krajina                      # build celej krajiny končí tu
    if len(kat) > 1:
        regs = krajina.setdefault("regions", {})
        uzol = regs.setdefault(kat[1], {})
        uzol.setdefault("name", katalog_meno(regions, kat[1], "region"))
    if len(kat) > 2:
        subs = uzol.setdefault("subregions", {})
        uzol = subs.setdefault(kat[2], {})
        uzol.setdefault("name", katalog_meno(regions, kat[2], "area"))

    reg = region_entry(man)
    if iba:
        # DOPLNENIE, NIE PREPIS. Samostatná pipeline vie len o svojom balíku;
        # keby prepísala celú položku, zmazala by odkazy na mapu, zoomy aj
        # zdroje výšok, o ktorých nič nevie – a v katalógu by po nich nezostalo
        # nič. Preto sa mení len ten jeden balík a čas.
        uzol.setdefault("name", katalog_meno(regions, kat[-1], "region"))
        uzol.setdefault("drive", "/".join(parts))
        # `updated_at` a `run` pri kraji hovoria, KTORÝ BEH VYROBIL MAPU – to
        # táto pipeline nespravila a nesmie si to prisvojiť (`setdefault` je
        # tu na prvý zápis, keď mapa v katalógu ešte nie je). Kedy pribudol
        # tento balík, nesie balík sám (viď `zapis_balik`).
        uzol.setdefault("updated_at", data["_updated_at"])
        uzol.setdefault("updated_ts", data["_updated_ts"])
        uzol.setdefault("run", env("GITHUB_RUN_NUMBER"))
        mapy = uzol.setdefault("maps", {})
        for kind, name, velkost, fid, fmt in baliky:
            zapis_balik(mapy, kind, name, velkost, fid, fmt,
                        kedy=data["_updated_at"], kedy_ts=data["_updated_ts"])
        # `casti` sa tu NEPREPISUJÚ, aj keby prišli: samostatná pipeline
        # (`--only=wikipedia`) nemá `_site` mapy, takže by za „hľadanie v tejto
        # mape nie je" vyhlásila mapu, ktorá ho má.
        return zapis(path, data,
                     f"doplnený balík {iba} k {'/'.join(kat)}")
    polozka = {
        "name": uzol.get("name"),
        "drive": "/".join(parts),
        # KEDY TÁ MAPA VZNIKLA – dvakrát ten istý okamih (rozpis pri `teraz()`):
        # `updated_at` na čítanie okom, `updated_ts` na počítanie veku bez
        # parsovania dátumu. Je to čas TOHTO behu, teda čas, kedy sa balíky
        # nahrali na Drive: položka sa pri každom builde zapisuje celá, takže
        # „vytvorená" a „naposledy prepísaná" je pri mape to isté.
        "updated_at": data["_updated_at"],
        "updated_ts": data["_updated_ts"],
        "run": env("GITHUB_RUN_NUMBER"),
        "layers": list(layers or []),
        # Balík × formát. `formats` je to podstatné (ZIP otvorí čokoľvek,
        # `.aar` rozbalí iOS a macOS systémovo); `file`/`size`/`link` na
        # úrovni balíka ostávajú a ukazujú na ZIP, aby starší čitateľ
        # katalógu nemusel vedieť o formátoch.
        "maps": {},
    }
    # Čo o mape treba vedieť pri výbere, nie až po rozbalení. Zoomy a zdroje
    # nesie manifest, tak sa berú z neho. `bbox` je bbox MAPY, teda celého
    # regiónu – aj pri builde na výrez, lebo mapa je celý región a orezané sú
    # len vrstvy z výškového modelu. Práve preto je pri výreze vedľa neho aj
    # `area_bbox`: to je to, kde v tej mape vrstevnice a skaly naozaj sú.
    #
    # STROP ZOOMU MUSÍ BYŤ PRI KAŽDEJ VRSTVE, KTORÁ HO MÁ VLASTNÝ. Kto ho
    # nenájde, dosadí `maxzoom` mapy (16) – a nad skutočným stropom vrstvy
    # potom pýta dlaždice, ktoré neexistujú: trasy končia na z14 a krajinné
    # prvky na z15, takže od z15 resp. z16 by ticho zmizli. Nevyzerá to ako
    # chýbajúce dáta, ale ako pokazené ťuknutie do mapy – práve tie dve vrstvy
    # sa vyberajú dotykom. `terrain_maxzoom` je to isté pre raster tieňovania
    # (v manifeste `dem_maxzoom`, lebo tam je terén mimo položky regiónu).
    #
    # A KAŽDÁ VRSTVA Z VÝŠKOVÉHO MODELU MUSÍ POVEDAŤ, Z ČOHO JE. `dem_source`
    # je zdroj VRSTEVNÍC; skaly môžu byť z iného modelu (`rock_source`)
    # a tieňovanie tiež (`terrain_source`, v manifeste je hore ako
    # `dem_source`, lebo terén nie je časť položky regiónu). Keď sa niektorá
    # vrstva prepne na náhradný model, musí to niesť to, čo sa NAOZAJ použilo –
    # inak by atribúcia mapy tvrdila DMR 5.0 nad reliéfom zo Sonnyho.
    for k in ("bbox", "maxzoom", "contours_maxzoom", "contour_interval",
              "rocks_maxzoom", "rock_slope", "dem_source", "rock_source",
              "trails_maxzoom", "features_maxzoom", "roads_maxzoom"):
        if reg.get(k) is not None:
            polozka[k] = reg[k]
    # Cesty k dlaždiciam v balíku – NEODVODZUJÚ sa z kľúča uzla (rozpis pri
    # `tiles_paths`), a `terrain_maxzoom` k nim patrí z toho istého dôvodu ako
    # zoomy vyššie.
    tiles = tiles_paths(man, reg)
    if tiles:
        polozka["tiles"] = tiles
    if tiles.get("terrain"):
        if man.get("dem_maxzoom") is not None:
            polozka["terrain_maxzoom"] = man["dem_maxzoom"]
        if man.get("dem_source"):
            polozka["terrain_source"] = man["dem_source"]
    area_bbox = env("AREA_BBOX")
    test_km2 = env("TEST_KM2", "0")
    if test_km2 not in ("", "0"):
        # Pri teste to je to najdôležitejšie číslo v celej položke: mapa je
        # celý kraj, ale vrstevnice, skaly a tieňovanie sú len v tom štvorci.
        # Preto sa píše aj vtedy, keď sa nebeží na výrez – vtedy `area_bbox`
        # nižšie nesie práve ten testovací štvorec.
        polozka["test_km2"] = test_km2
    if area_bbox and (len(parts) > 2 or test_km2 not in ("", "0")):
        try:
            polozka["area_bbox"] = [float(v) for v in area_bbox.split(",")]
        except ValueError:
            pass
    stare_maps = uzol.get("maps") or {}
    if merge:
        polozka["maps"] = {k: dict(v) for k, v in stare_maps.items()}
    else:
        # PREPIS SA TÝKA LEN TOHO, O ČOM TENTO BEH ROZHODUJE. Balík, ktorý
        # robí iná pipeline, tu ostáva aj vtedy, keď ho tento beh nenahral –
        # inak by ho z katalógu zmazal, hoci jeho súbor na Drive leží ďalej
        # (a mazať ho tam beh nesmie, viď `publish-map.py`). Balík, o ktorom
        # beh rozhoduje a nevyrobil ho, naopak zmizne – to je tá istá vec ako
        # zmazanie starého ZIPu na Drive, len z druhej strany.
        if spravuje is None:
            raise SystemExit(
                "::error::`zapis_katalog` bez `spravuje=`: nedá sa povedať, "
                "ktoré balíky tento beh rieši a ktoré patria inej pipeline. "
                "Podaj druhy z `baliky` (robí to `publish-map.py`).")
        riesi = set(spravuje)
        polozka["maps"] = {k: dict(v) for k, v in stare_maps.items()
                           if k not in riesi}
    if merge:
        # ČO TENTO BEH NEVIE, TO NESMIE ZMAZAŤ. Položka sa zapisuje celá
        # (`uzol.clear()`), takže beh, ktorý pridáva len ďalší formát, by
        # z katalógu vyhodil všetko, čo sám nedopočítal – bbox, zoomy, zdroj
        # výšok. Tie sa berú z manifestu a ten sem chodí z iného jobu, takže
        # stačí, aby raz nedorazil. Pri `merge` je preto východiskom to, čo
        # v katalógu už je, a nové hodnoty idú navrch.
        zaklad = {k: v for k, v in uzol.items()
                  if k not in ("maps", "regions", "subregions")}
        zaklad.update(polozka)
        polozka = zaklad
    for kind, name, velkost, fid, fmt in baliky:
        zapis_balik(polozka["maps"], kind, name, velkost, fid, fmt,
                    kedy=data["_updated_at"], kedy_ts=data["_updated_ts"])
    if casti is not None:
        zapis_casti(polozka["maps"], casti)

    # `subregions` patria uzlu, nie tejto mape – nahradenie položky ich nesmie
    # zmazať (build Vysokých Tatier neruší mapu celého kraja a naopak).
    zachovaj = {k: uzol[k] for k in ("regions", "subregions") if k in uzol}
    uzol.clear()
    uzol.update(polozka)
    uzol.update(zachovaj)

    # Koľko balíkov v položke ostalo po INEJ pipeline – nech je na logu vidieť,
    # že sa nezmazali, a nie až na tom, že v katalógu chýbajú.
    cudzie = [k for k in polozka["maps"]
              if k not in {(kind or "mapa") for kind, *_ in baliky}]
    return zapis(path, data, f"zapísaná mapa {'/'.join(kat)} "
                             f"({len(polozka['maps'])} balíkov, "
                             + (f"z toho {len(cudzie)} z inej pipeline "
                                f"({', '.join(sorted(cudzie))}), " if cudzie else "")
                             + f"priečinok {'/'.join(parts)})")


if __name__ == "__main__":
    # Jediná otázka, na ktorú sa tento modul dá spýtať z príkazového riadka.
    # Zápis katalógu sem nepatrí: ten potrebuje manifest, zoznam nahratých
    # balíkov aj ich id na Drive, a to všetko vie iba `publish-map.py`.
    if sys.argv[1:] == ["--subor"]:
        print(katalog_subor())
    else:
        raise SystemExit(
            "::error::workers/deploy/catalog.py sa samostatne pýta len na "
            "`--subor` (ktorý katalóg zapisovať – maps.json, alebo pri "
            "rýchlom teste maps-test.json). Katalóg zapisuje "
            "workers/deploy/publish-map.py.")
