#!/usr/bin/env python3
"""Ktorý súbor z `_site` ide do ktorého balíka – a čo cestuje v základnej mape.

`publish-map.py` odpovedá na „ako sa balík volá, zabalí a nahrá", toto na „čo
je v ňom". Ktoré balíky vôbec sú, tu napísané nie je – zoznam drží
`workers/data/packages.json`; kým bol v každom mieste zvlášť, znamenal nový
balík päť úprav a ktorákoľvek zabudnutá bola tichá.

Tri druhy odpovedí:

  * vlastný balík (`baliky_vrstiev`) – ťažké veci, ktoré mapa na nakreslenie
    nepotrebuje a ktoré vážia porovnateľne s ňou samou;
  * časť základnej mapy (`casti_baliku`: hľadanie) – desiatky MB proti stovkám
    za dlaždice; vlastný balík by znamenal mapu, v ktorej sa nedá nič nájsť.
    Premeriava sa, aby bolo v katalógu vidieť, koľko z balíka je;
  * mimo balíka (`mimo_balika`: glyfy a viewer) – viewer si aplikácia
    nespúšťa a glyfy si nesie vo vlastnom binári, takže sa vynechajú vždy.

Značené trasy sú v základnej mape z toho istého dôvodu ako hľadanie. `linie`
sa tým rozpadlo: kreslená sieť je balík `cesty`, trasy sú v mape a obmedzenia
na ceste sú atribútmi tej siete.
"""
import hashlib
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
baliky = _load("deploy_baliky", "baliky.py")      # číselník balíkov


def log(msg):
    print(msg, flush=True)


# ---------- čo je v ktorom balíku ----------
# Základná mapa NEOBSAHUJE vrstevnice, skaly, tieňovanie, dopravnú sieť, body,
# hranice, vodstvo ani navigačný graf – sú to ťažké vrstvy, ktoré mapa na to,
# aby sa nakreslila, nepotrebuje, a majú vlastné balíky práve preto, aby si ich
# človek nemusel sťahovať, keď ich nechce. Vrstevnice a skaly sú SPOLU zámerne:
# sú z toho istého výpočtu nad tým istým DEM a jedna bez druhej sa nepoužíva.

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


def subory_baliku(site, man, b):
    """Súbory JEDNÉHO balíka podľa jeho položky v číselníku.

    Tri spôsoby, ako sa to dá povedať, a berú sa v tomto poradí:

      `priecinok`  CELÝ priečinok v `_site`, nie výber podľa mien. Navigačný
                   graf sú štyri súbory, ktoré si musia sedieť, plus
                   `graf.json` s tým, z čoho je – keby sa vyberali menami,
                   prvý ďalší súbor od Valhally by ticho vypadol a trasa by
                   „len nešla".
      `manifest`   kľúče v `regions.<kraj>` manifestu. Toto je tá správna
                   odpoveď: manifest je jediné miesto, ktoré vie, čo v mape
                   naozaj je.
      `pripony`    záloha, keď sa manifest nedá prečítať – koncovky mien
                   v `_site/tiles/`. Hľadá sa podľa PRÍPONY a nie podľa
                   priečinka: `tiles/` je spoločný pre všetky vrstvy, takže
                   „všetko v priečinku" by do balíka `tienovanie` pribalilo aj
                   mapu, vrstevnice a trasy.

    Balík bez všetkých troch (základná mapa, články z Wikipédie) tadiaľto
    nechodí – tie skladá `zaklad_subory`, resp. `vsetky_subory` nad
    priečinkom, ktorý podal workflow.
    """
    priecinok = b.get("priecinok")
    if priecinok:
        base = os.path.join(site, priecinok)
        if not os.path.isdir(base):
            return []
        return sorted(os.path.join(root, n)
                      for root, _dirs, names in os.walk(base) for n in names)

    reg = catalog.region_entry(man)
    rel = [reg[k] for k in b.get("manifest") or () if reg.get(k)]
    if not rel and b.get("pripony"):
        tiles = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(tiles))
               if n.endswith(tuple(b["pripony"]))] \
            if os.path.isdir(tiles) else []
    return [os.path.join(site, p) for p in rel
            if os.path.exists(os.path.join(site, p))]


def baliky_vrstiev(site, man):
    """`[(balík, súbory)]` pre všetko, čo má vlastný balík a je v `_site`.

    Teda všetko okrem základnej mapy (to je zvyšok) a článkov z Wikipédie (tie
    v `_site` nie sú – majú vlastnú pipeline a chodia cez `--wiki`).

    KAŽDÝ SA POČÍTA RAZ a to isté pole ide aj do `zaklad_subory` ako to, čo sa
    zo základnej mapy vynechá: druhé volanie tej istej funkcie by bola druhá
    odpoveď na tú istú otázku, a rozišli by sa presne vtedy, keď sa zmení
    jedno z tých dvoch miest.
    """
    return [(b, subory_baliku(site, man, b)) for b in baliky.zoznam()
            if b["kluc"] != "mapa" and b.get("zdroj", "site") == "site"]


# ---------- časti, ktoré cestujú V ZÁKLADNEJ MAPE ----------
# Hľadanie NIE JE balík (rozpis v hlavičke súboru). Je to časť základnej mapy
# a jediné, čo o nej publikovanie navyše robí, je, že ju PREMERIA – veľkosť
# ide do `maps.json` pod balík `mapa`, aby sa dalo povedať, koľko z tých
# stoviek MB je mapa a koľko to, čo v nej hľadá.
#
# Vlastnú funkciu má preto, že sa nedá vybrať podľa priečinka: `tiles/` je
# spoločný pre všetky vrstvy, takže „všetko v priečinku" by za index vyhlásilo
# aj dlaždice.

def hladanie_subory(site, man):
    """Časť `search` – SQLite FTS5 index na offline hľadanie.

    Jeden súbor, presunutý workers/search/build.sh do `_site/tiles/` ako
    `search-index.db`. Hľadá sa podľa PRÍPONY MENA a slova „search" v nej
    (rovnaké pravidlo, akým appka skenuje stiahnutý priečinok, nie pevné
    meno – `.db` súbor s „search" v mene).
    """
    base = os.path.join(site, "tiles")
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, n) for n in sorted(os.listdir(base))
            if n.endswith(".db") and "search" in n.lower()]


def trasy_subory(site, man):
    """Časť `trasy` – značené trasy z OSM relácií (`-trails.pmtiles`).

    ČASŤ, A NIE BALÍK, a je to zmena: trasy cestovali v `linie` vedľa
    dopravnej siete. Turistická mapa bez značiek je ale mapa, ktorá nesľubuje
    to, načo si ju človek stiahol – a je to jeden súbor v jednotkách MB proti
    stovkám za dlaždice, takže sa tu nemá čo šetriť. Ten istý dôvod, pre ktorý
    je v mape hľadanie.

    Premeriava sa z rovnakého dôvodu ako hľadanie: časť, ktorú nikto nemeria,
    sa v katalógu nedá odlíšiť od časti, ktorá tam nie je.
    """
    reg = catalog.region_entry(man)
    rel = [reg["trails"]] if reg.get("trails") else []
    if not rel:
        base = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(base))
               if n.endswith("-trails.pmtiles")] if os.path.isdir(base) else []
    return [os.path.join(site, p) for p in rel
            if os.path.exists(os.path.join(site, p))]


def casti_baliku(site, man):
    """Časti základnej mapy: `[(kľúč, popis, súbory)]` – aj tie, čo nie sú.

    Časť, ktorú tento build nevyrobil, sa v zozname NEVYNECHÁVA: prázdny
    zoznam sa zapíše ako `0` a to je odpoveď „hľadanie v tejto mape nie je".
    Mlčanie by sa dalo čítať aj ako „zabudlo sa to premerať" – ten istý dôvod,
    pre ktorý meno balíka nesie `bez_skal`.

    NAVIGÁCIA TU NIE JE a nie je to opomenutie: graf bol dvomi tretinami
    základnej mapy, takže sa z nej vybral do VLASTNÉHO balíka. Jeho veľkosť je
    preto v katalógu pod `maps.navigacia.size` ako pri každom inom balíku, nie
    pod `maps.mapa.casti`.
    """
    return [
        ("search", "index na offline hľadanie (SQLite FTS5)",
         hladanie_subory(site, man)),
        ("trasy", "značené trasy z OSM relácií (.pmtiles)",
         trasy_subory(site, man)),
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

    `vylucit` je dvoje. Jedno sú súbory VLASTNÝCH BALÍKOV (`baliky_vrstiev`):
    keby aj tie ostali v základnej mape, mali by ich cesty vnútri dvakrát –
    raz tu, raz v tom druhom archíve – a „iba mapa" by vážila rovnako ako mapa
    so všetkým, čo je presne to, kvôli čomu majú vlastné balíky. Druhé je to,
    čo v balíku nemá čo robiť – viewer (je na Pages) a glyfy (nesie si ich
    appka), teda `mimo_balika`. Oboje sa podáva zvonku, aby sa tá istá otázka
    nepočítala dvakrát; čo je čo, hovorí hlavička `publish-map.py`.

    KTORÝKOĽVEK BALÍK, ČO PRIBUDNE, PATRÍ AJ SEM – a odkedy sa zoznam berie
    z číselníka, netreba naň myslieť: `publish-map.py` sem podáva `vylucit`
    zložené z toho istého zoznamu, z akého sa balíky vyrábajú. Kým sa písali
    ručne, bolo vynechanie ticho: mapa je v poriadku, len o toľko väčšia,
    a na súbore to nikto nepozná. Presne to sa stalo `search-index.db`.

    HĽADANIE A ZNAČENÉ TRASY SEM NAOPAK NEPATRIA a nie je to opomenutie:
    druhý balík nemajú, sú to ČASTI tejto mapy (`casti_baliku`). Vynímať ich
    by znamenalo mapu, v ktorej sa nedá nič nájsť a na ktorej nie sú značky.
    """
    von = {os.path.abspath(p) for p in vylucit}
    return [p for p in vsetky_subory(site) if os.path.abspath(p) not in von]


def obsah_sha(base, subory):
    """sha256 obsahu balíka – tých istých súborov, nie archívu okolo nich."""
    h = hashlib.sha256()
    for rel, cesta in sorted((os.path.relpath(p, base), p) for p in subory):
        h.update(rel.replace(os.sep, "/").encode() + b"\0")
        h.update(_sha_suboru(cesta).encode() + b"\n")
    return h.hexdigest()


def _sha_suboru(cesta):
    h = hashlib.sha256()
    with open(cesta, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()
