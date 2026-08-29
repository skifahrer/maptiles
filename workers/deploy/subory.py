#!/usr/bin/env python3
"""
Ktorý súbor z `_site` ide do ktorého balíka – a čo cestuje v základnej mape.

PREČO ZVLÁŠŤ OD `publish-map.py`: ten odpovedá na „ako sa balík volá, ako sa
zabalí a ako sa nahrá na Drive"; toto na „čo je v ňom". Sú to dve otázky
a súbor prerástol strop 800 riadkov práve tam, kde sa stretli – rezalo sa
teda tam, kde sa mení otázka, rovnako ako pri `catalog.py`.

TRI DRUHY ODPOVEDÍ SÚ TU:

  * VLASTNÝ BALÍK (`vrstvy_subory`, `tienovanie_subory`). Ťažké vrstvy
    z výškového modelu, ktoré mapa na to, aby sa nakreslila, nepotrebuje –
    a ktoré vážia porovnateľne s ňou samou, takže sa oplatí nesťahovať ich.
  * ČASŤ ZÁKLADNEJ MAPY (`casti_baliku`: hľadanie a navigácia). Jednotky až
    desiatky MB proti stovkám za dlaždice; vlastný balík by znamenal mapu,
    v ktorej sa nedá nič nájsť ani nikam doviesť, a nikto by nemal ako
    zistiť, že mu druhý súbor chýba. Premeriavajú sa (`velkost_casti`),
    aby bolo v katalógu vidieť, koľko z balíka sú.
  * MIMO BALÍKA (`mimo_balika`: glyfy a viewer). Viewer je web, ktorý si
    aplikácia nespúšťa, a glyfy si appka nesie vo vlastnom binári – vynechajú
    sa preto VŽDY, nie podľa tvaru adresy v manifeste (rozpis v hlavičke
    `publish-map.py`). `kde_su_glyfy` k tomu povie, odkiaľ si ich kto vezme.

Zvyšok, teda `zaklad_subory`, je „všetko ostatné z `_site`".
"""
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


catalog = _load("deploy_catalog", "catalog.py")   # `region_entry` z manifestu


def log(msg):
    print(msg, flush=True)




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


def linie_subory(site, man):
    """Súbory balíka `linie` – značené trasy a obmedzenia na ceste (.pmtiles).

    ČISTO LÍNIOVÉ DÁTA Z OSM, a preto len tieto dve vrstvy. Krajinné prvky
    (`-features.pmtiles`) sú línie AJ plochy v jednom súbore (parkovisko,
    zjazdovka sú plochy) a vlastný balík nemajú – rozpis prečo je
    v `workers/README.md` pri balíkoch. `trails` a `roads` sú naopak
    z definície čisto línie (`geometry: line` v oboch schémach), takže sa
    dajú ponúknuť ako balík „línie z OSM" bez toho, aby sľuboval niečo, čo
    v ňom nie je.
    """
    reg = catalog.region_entry(man)
    rel = [reg[k] for k in ("trails", "roads") if reg.get(k)]
    if not rel:
        tiles = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(tiles))
               if n.endswith(("-trails.pmtiles", "-roads.pmtiles"))] \
            if os.path.isdir(tiles) else []
    return [os.path.join(site, p) for p in rel
            if os.path.exists(os.path.join(site, p))]


def body_subory(site, man):
    """Súbory balíka `body` – bodové krajinné prvky (.pmtiles).

    VLASTNÝ súbor (`workers/features/points.yml`), oddelený od
    `-features.pmtiles` (línie a plochy) práve kvôli tomuto balíku – appka
    nemala ako ponúknuť „body z OSM" zvlášť, kým boli všetky tri geometrie
    v jednom archíve.
    """
    reg = catalog.region_entry(man)
    rel = [reg[k] for k in ("points",) if reg.get(k)]
    if not rel:
        tiles = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(tiles))
               if n.endswith("-points.pmtiles")] \
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


# ---------- časti, ktoré cestujú V ZÁKLADNEJ MAPE ----------
# Hľadanie a navigácia NIE SÚ balíky (rozpis v hlavičke súboru). Sú to časti
# základnej mapy a jediné, čo o nich publikovanie navyše robí, je, že ich
# PREMERIA – veľkosť ide do `maps.json` pod balík `mapa`, aby sa dalo povedať,
# koľko z tých stoviek MB je mapa a koľko to, čo v nej jazdí a hľadá.
#
# Vlastnú funkciu majú preto, že sa nedajú vybrať podľa priečinka: `tiles/` je
# spoločný pre všetky vrstvy, takže „všetko v priečinku" by za index vyhlásilo
# aj dlaždice.

def hladanie_subory(site, man):
    """Časť `search` – SQLite FTS5 index na offline hľadanie.

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


def navigacia_subory(site, man):
    """Časť `navigacia` – navigačný graf Valhally z `_site/routing/`.

    CELÝ PRIEČINOK, a nie výber podľa mien: graf sú štyri súbory, ktoré si
    musia sedieť (`valhalla_tiles.tar`, `valhalla.json`, `admins.sqlite`,
    `timezones.sqlite`) plus `graf.json` s tým, z čoho a čím je postavený –
    a keby sa vyberali menami, prvý ďalší súbor od Valhally by z balíka ticho
    vypadol a trasa by „len nešla". `routing/` je zároveň jediný priečinok
    v `_site`, ktorý patrí grafu, takže tu na rozdiel od `tiles/` nič cudzie
    nehrozí.

    Že je graf za JEDEN REGIÓN a trasa v ňom končí na jeho hranici, hovorí
    `graf.json` v ňom (`rozsah: "region"`); rozpis je v hlavičke súboru
    a v `docs/navigation.md`.
    """
    base = os.path.join(site, "routing")
    if not os.path.isdir(base):
        return []
    return sorted(os.path.join(root, n)
                  for root, _dirs, names in os.walk(base) for n in names)


def casti_baliku(site, man):
    """Časti základnej mapy: `[(kľúč, popis, súbory)]` – aj tie, čo nie sú.

    Časť, ktorú tento build nevyrobil, sa v zozname NEVYNECHÁVA: prázdny
    zoznam sa zapíše ako `0` a to je odpoveď „hľadanie v tejto mape nie je".
    Mlčanie by sa dalo čítať aj ako „zabudlo sa to premerať" – ten istý dôvod,
    pre ktorý meno balíka nesie `bez_skal`.
    """
    return [
        ("search", "index na offline hľadanie (SQLite FTS5)",
         hladanie_subory(site, man)),
        ("navigacia", "navigačný graf Valhally pre tento región",
         navigacia_subory(site, man)),
    ]


def velkost_casti(casti):
    """`[(kľúč, popis, súbory)]` → `{kľúč: {"raw_size": B, "files": N, …}}`.

    `raw_size`, a nie `size`: pri balíku znamená `size` v katalógu ZABALENÝ
    súbor, kým toto sú bajty pred zabalením – jediné, čo sa tu dá zmerať, keď
    tá časť vlastný archív nemá. Rovnaký kľúč pre dve rôzne čísla je presne
    ten druh tichého omylu, ktorému sa mená v tomto repozitári vyhýbajú:
    sčítali by sa a nesedelo by to.
    """
    return {kluc: {"raw_size": sum(os.path.getsize(p) for p in subory),
                   "files": len(subory),
                   "popis": popis}
            for kluc, popis, subory in casti}


# ---------- balenie ----------

def vsetky_subory(site):
    subory = []
    for root, _dirs, names in os.walk(site):
        for n in names:
            subory.append(os.path.join(root, n))
    return subory


# ---------- čo do balíka NEPATRÍ ----------
#
# Rozpis je v hlavičke `publish-map.py`. Krátko: viewer je web, ktorý si
# aplikácia nespúšťa, a glyfy si appka nesie vo vlastnom binári – v balíku sú
# teda oboje mŕtva váha VŽDY, nie podľa tvaru adresy v manifeste.

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


def kde_su_glyfy(man):
    """Krátka veta do logu a do `obsah.json`: odkiaľ si ich kto vezme.

    Nie je to rozhodnutie – to je urobené (glyfy sa nebalia nikdy, rozpis
    v hlavičke `publish-map.py`) –, je to odpoveď na otázku, ktorú si nad
    menším balíkom položí každý: „a kde teda sú?“. Appka ich má v sebe vždy;
    web podľa toho, čo si štýl pýta, a to je v manifeste.
    """
    adresa = str(man.get("glyphs") or "")
    if adresa.startswith(("http://", "https://")):
        return f"appka ich má v sebe, web si ich berie z {adresa}"
    if adresa:
        return (f"appka ich má v sebe; štýl si ich pýta relatívne ({adresa}), "
                f"takže mimo appky ich treba doplniť")
    return "appka ich má v sebe (manifest sa nedá prečítať, adresu neviem)"


def mimo_balika(site, man):
    """Súbory z `_site`, ktoré do balíkov nepatria – zoznam a dôvody.

    Vracia `(subory, dovody)`; `dovody` je `[(popis, počet, bajty)]` do logu,
    lebo vynechať 90 MB potichu je presne to, čo pravidlo 4 zakazuje.
    """
    vsetky = vsetky_subory(site)
    skupiny = [
        ("viewer (je na Pages)", [p for p in vsetky if je_viewer(site, p)]),
        (f"glyfy ({kde_su_glyfy(man)})", [p for p in vsetky if je_glyf(site, p)]),
    ]

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
    balíky. Druhé je to, čo v balíku nemá čo robiť – viewer (je na Pages)
    a glyfy (nesie si ich appka), teda `mimo_balika`. Oboje sa podáva zvonku,
    aby sa tá istá otázka nepočítala dvakrát; čo je čo, hovorí hlavička
    `publish-map.py`.

    KTORÝKOĽVEK BALÍK, ČO PRIBUDNE, PATRÍ AJ SEM. Vynechať ho je ticho: mapa
    je v poriadku, len o toľko väčšia, a na súbore to nikto nepozná. Presne to
    sa stalo `search-index.db` – mal vlastný balík a zo základnej mapy ho nikto
    nevybral, takže si ho každý stiahol dvakrát.

    HĽADANIE A NAVIGÁCIA SEM NAOPAK NEPATRIA a nie je to opomenutie: druhý
    balík nemajú, sú to ČASTI tejto mapy (`casti_baliku`). Vynímať ich by
    znamenalo mapu, v ktorej sa nedá nič nájsť ani nikam doviesť.
    """
    von = {os.path.abspath(p) for p in vylucit}
    return [p for p in vsetky_subory(site) if os.path.abspath(p) not in von]
