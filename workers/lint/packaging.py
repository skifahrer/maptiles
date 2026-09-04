#!/usr/bin/env python3
"""
Glyfy ani viewer v balíku nie sú – ale musia byť KDE INDE.

PREČO TO EXISTUJE. Fonty boli po dlaždiciach druhá najväčšia vec v balíku mapy
(tri fontstacky Noto Sans po ~34 MB, celý unicode; mapa kraja z nich použije
zlomok) a webový viewer (`index.html` + `*.js` z `poc/web`) je stránka, ktorú
si aplikácia nespúšťa – má vlastnú mapu. Oboje sa preto do ZIPu ani `.aar`
nebalí a ostáva len v `_site`, teda na Pages.

A PRÁVE PRETO SÚ TU TIETO KONTROLY: vynechať súbor z balíka je jednoriadková
zmena, ktorá sa dá spraviť aj tam, kde ten súbor NIE JE ODKIAĽ VZIAŤ – a mapa
bez glyfov nespadne, len nemá jediné písmeno a vyzerá ako pokazený štýl.
Glyfy majú preto DVE miesta, kde sú, a obe sa strážia: appka si tri orezané
stacky nesie v sebe (`skifahrer/rikimaps`, `GlyphStore` – to odtiaľto vidieť
nie je), a pre všetkých ostatných musí adresa v štýle na niečo ukazovať.

ČO SA KONTROLUJE:

  1. `mimo_balika()` naozaj vynechá viewer aj glyfy, keď manifest odkazuje na
     Pages,
  2. vynechá ich AJ pri relatívnom odkaze (mapa sveta) – appka ich má v sebe,
  3. a vynechá ich aj vtedy, keď sa manifest nedá prečítať; „neviem" tu už
     neznamená „nechaj", lebo nechať znamená desiatky MB navyše v každom balíku,
  4. `workers/deploy/site.sh` skladá adresu glyfov z `$BASE`, čiže absolútnu,
     a viewer do `_site` ďalej KOPÍRUJE (na Pages ostať musí),
  5. `workers/world/style.mjs` neodkazuje na glyfy DO BALÍKA – tam už nie sú –,
     ale na adresu, z ktorej si ich vezme ten, kto nie je appka,
  6. hľadanie zo základnej mapy nevypadlo a je premerané (vlastný balík nemá),
  7. navigačný graf je NAOPAK von – cestuje v balíku `-linie.zip` – a v tom
     balíku je celý; v základnej mape by ho každý stiahol druhýkrát.

Spustiť sa dá aj lokálne:
    python3 workers/lint/packaging.py
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import zipfile

PUBLISH = "workers/deploy/publish-map.py"
SUBORY = "workers/deploy/subory.py"
SITE = "workers/deploy/site.sh"
WORLD_STYLE = "workers/world/style.mjs"

bad = []


def nacitaj_modul(meno, cesta):
    spec = importlib.util.spec_from_file_location(meno, cesta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[meno] = mod
    spec.loader.exec_module(mod)
    return mod


def nacitaj(cesta):
    return nacitaj_modul("publish_map", cesta)


def napln(site):
    """Napodobenina `_site`: viewer, glyfy, štýly, sprite, dlaždice.

    Aj hľadanie – to do základnej mapy PATRÍ (kontrola 6) –, aj vrstvy
    s vlastným balíkom a graf Valhally, ktoré z nej naopak vypadnúť MUSIA
    (kontrola 7).
    """
    for rel in ("index.html", "app.js", "themes.js", "style-overrides.json",
                "region.geojson", "fonts/Noto Sans Regular/0-255.pbf",
                "styles/svetla.json", "sprites/temaki.png",
                "tiles/manifest.json", "tiles/kraj.pmtiles",
                "tiles/kraj-contours.pmtiles", "tiles/kraj-rocks.pmtiles",
                "tiles/kraj-terrain.pmtiles", "tiles/kraj-trails.pmtiles",
                "tiles/kraj-roads.pmtiles", "tiles/kraj-points.pmtiles",
                "tiles/search-index.db", "routing/valhalla_tiles.tar",
                "routing/valhalla.json", "routing/admins.sqlite",
                "routing/timezones.sqlite", "routing/graf.json"):
        cesta = os.path.join(site, rel)
        os.makedirs(os.path.dirname(cesta) or site, exist_ok=True)
        with open(cesta, "w") as f:
            f.write("x")


def v_baliku(pm, man):
    """Čo v ZÁKLADNEJ MAPE ostane, keď sa vynechá len `mimo_balika`.

    Na glyfy a viewer (kontroly 1 až 3) to stačí a je to lacné. NA TO, ČO
    PATRÍ DO KTORÉHO BALÍKA, TO NESTAČÍ: `vylucit` skladá `main()` a tá istá
    skladba tu by bola druhá pravda o tom istom – kontrola by potom hlásila
    zelenú aj vtedy, keby balík z `main()` vypadol. Preto to, čo sa balí,
    číta `zabalene()` z NAOZAJ ZABALENÝCH ZIPov.
    """
    with tempfile.TemporaryDirectory() as site:
        napln(site)
        von, _dovody = pm.mimo_balika(site, man)
        return {os.path.relpath(p, site).replace(os.sep, "/")
                for p in pm.zaklad_subory(site, von)}


def zabalene():
    """`{balík: {cesty vnútri}}` – z `publish-map.py --zip-only` nad `_site`.

    Beh, nie napodobenina. Rozdelenie `_site` na balíky je celé v `main()`
    (`vylucit`, zoznam `baliky`) a dá sa pokaziť oboma smermi potichu: vrstva,
    ktorá ostane aj v základnej mape, sa stiahne dvakrát, a balík, ktorý zo
    zoznamu vypadne, sa nenahrá vôbec. Ani jedno nespadne a na veľkosti to
    nikto nepozná – tak to musí povedať kontrola, a povedať to o tom, čo
    naozaj vyšlo z packera.
    """
    with tempfile.TemporaryDirectory() as tmp:
        site = os.path.join(tmp, "_site")
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        napln(site)
        prostredie = dict(os.environ, REGION_KEY="kraj", AREA_KEY="cely",
                          TEST_KM2="0", TILES_MAXZOOM="16")
        beh = subprocess.run(
            [sys.executable, PUBLISH, f"--site={site}", f"--out={out}",
             "--zip-only", "--maps="],
            env=prostredie, capture_output=True, text=True)
        if beh.returncode:
            bad.append(f"{PUBLISH}: `--zip-only` nad napodobeninou `_site` "
                       f"spadol ({beh.returncode}); nedá sa povedať, čo je "
                       f"v ktorom balíku.\n{beh.stdout}\n{beh.stderr}")
            return {}
        von = {}
        for name in sorted(os.listdir(out)):
            druh = name[len("kraj"):-len(".zip")].lstrip("-") or "mapa"
            with zipfile.ZipFile(os.path.join(out, name)) as z:
                # Vnútri je navyše priečinok s menom balíka (`pack.zabal`).
                von[druh] = {n.split("/", 1)[1] for n in z.namelist()
                             if "/" in n}
        return von


# ---- 1. až 3. čo v balíku ostane ----
pm = nacitaj(PUBLISH)

PAGES = {"glyphs": "https://x.github.io/mapa/fonts/{fontstack}/{range}.pbf"}
kraj = v_baliku(pm, PAGES)
for meno in ("index.html", "app.js", "style-overrides.json",
             "fonts/Noto Sans Regular/0-255.pbf"):
    if meno in kraj:
        bad.append(
            f"{PUBLISH}: `{meno}` sa zabalil do mapy kraja, hoci manifest "
            f"odkazuje na glyfy na Pages. Glyfy sú desiatky MB, ktoré v balíku "
            f"nikto neotvorí, a viewer je web, ktorý si aplikácia nespúšťa.")
for meno in ("tiles/kraj.pmtiles", "styles/svetla.json", "sprites/temaki.png",
             "tiles/manifest.json", "region.geojson"):
    if meno not in kraj:
        bad.append(
            f"{PUBLISH}: `{meno}` z balíka VYPADOL. To nie je viewer ani glyf – "
            f"je to mapa; bez neho sa balík nedá otvoriť a nespadne pri tom nič.")

svet = v_baliku(pm, {"glyphs": "fonts/{fontstack}/{range}.pbf"})
if "fonts/Noto Sans Regular/0-255.pbf" in svet:
    bad.append(
        f"{PUBLISH}: glyfy ostali v balíku pri RELATÍVNOM odkaze. Odkedy si ich "
        f"appka nesie v sebe, nie je to jediný zdroj ani pri mape sveta – a pri "
        f"strope 15 MB na podobu `basic` je to váha, ktorú nikto nerozbalí.")

neznamy = v_baliku(pm, {})
if "fonts/Noto Sans Regular/0-255.pbf" in neznamy:
    bad.append(
        f"{PUBLISH}: keď sa manifest nedá prečítať, glyfy ostali v balíku. "
        f"Presne tak dopadol prvý ostrý beh `.aar` – desiatky MB navyše v každom "
        f"balíku, a na súbore to nikto nepozná.")

# ---- 6. hľadanie z balíka VYPADNÚŤ NESMIE ----
# Vlastný balík nemá: `search-index.db` ho mal a bola to mapa, v ktorej sa
# nedalo nič nájsť, kým si človek nestiahol druhý ZIP – o ktorom sa v aplikácii
# nedozvedel. Vypadnúť pritom môže jedným riadkom (stačí ho pridať medzi to, čo
# `zaklad_subory` vynecháva) a NIČ NESPADNE – preto kontrola.
baliky = zabalene()
mapa_zip = baliky.get("mapa", set())
linie_zip = baliky.get("linie", set())

if baliky and "tiles/search-index.db" not in mapa_zip:
    bad.append(
        f"{PUBLISH}: `tiles/search-index.db` z balíka mapy VYPADOL. Hľadanie "
        f"vlastný balík nemá – cestuje v základnej mape a bez neho je to "
        f"mapa, v ktorej sa nedá nič nájsť. Nespadne pri tom nič; pozná sa to "
        f"až v telefóne.")

# A musí byť aj PREMERANÉ – veľkosť ide do `maps.json` pod balík `mapa`
# (`casti`). Časť, ktorú nikto nemeria, je presne to, čím bol `search-index.db`
# predtým, než sa naň niekto pozrel: v balíku dvakrát, a na veľkosti to nikto
# nepoznal.
import tempfile as _tf                                       # noqa: E402
sub = nacitaj_modul("deploy_subory", SUBORY)
with _tf.TemporaryDirectory() as site:
    napln(site)
    merane = sub.velkost_casti(sub.casti_baliku(site, PAGES))
if "search" not in merane:
    bad.append(
        f"{SUBORY}: časť `search` sa nepremeriava, takže sa jej veľkosť nemá "
        f"ako dostať do `maps.json` – a keďže vlastný balík nemá, nedá sa "
        f"zistiť inak než stiahnutím celej mapy.")
elif not merane["search"].get("files"):
    bad.append(
        f"{SUBORY}: časť `search` nenašla ani jeden súbor v `_site`, hoci tam "
        f"sú. Zmenil sa výber podľa mena alebo priečinka? V mape by tá časť "
        f"ostala, len by o nej katalóg tvrdil, že tam nie je.")

# ---- 7. navigačný graf: v balíku `linie`, a preto ZO ZÁKLADNEJ MAPY VON ----
# Graf sa kedysi balil dovnútra mapy s argumentom „jednotky až desiatky MB
# proti stovkám za dlaždice". Namerané to tak nie je: 170 až 190 MB grafu
# v 283 MB mape, čiže dve tretiny. Odvtedy je zo základnej mapy von a cestuje
# v balíku `linie` (tá istá cestná a chodníková sieť z toho istého PBF ako
# trasy a obmedzenia, len zjazdná) – a obe strany tej zmeny sa dajú pokaziť
# potichu. Nechať ho v mape ZNOVA (vypadne riadok z `vylucit`) znamená, že si
# ho každý stiahne dvakrát a na súbore to nikto nepozná; to je presne to, čo
# sa stalo `search-index.db`. Nezabaliť ho nikam (`graf_subory` prestane byť
# v `linie_subory`) znamená mapu, ktorá vie, kde čo je, ale nevie ťa tam
# doviezť – a spoznať sa to dá až v telefóne.
for meno in ("routing/valhalla_tiles.tar", "routing/valhalla.json",
             "routing/admins.sqlite", "routing/timezones.sqlite",
             "routing/graf.json"):
    if not baliky:
        break
    if meno in mapa_zip:
        bad.append(
            f"{PUBLISH}: `{meno}` ostal v ZÁKLADNEJ MAPE, hoci graf cestuje "
            f"v balíku `-linie.zip`. Cesty vnútri sú tie isté, takže by ho mal "
            f"každý dvakrát: raz v mape, raz v balíku – a na veľkosti to nikto "
            f"nepozná. Patrí do `vylucit` v `zaklad_subory`.")
    if meno not in linie_zip:
        bad.append(
            f"{PUBLISH}: `{meno}` sa do balíka `linie` nedostal. Graf sú "
            f"štyri súbory, ktoré si musia sedieť, plus `graf.json` s tým, "
            f"z čoho je – keď jeden chýba, trasa sa „len nenájde“ a vyzerá to "
            f"ako chyba aplikácie, nie ako chýbajúci súbor v balíku.")

# A to isté pre vrstvy, ktoré vlastný balík majú dávno: pravidlo „ktorýkoľvek
# balík, čo pribudne, patrí aj do `vylucit`" platí na všetky, nie na ten
# posledný pridaný.
for druh, meno in (("vrstevnice-skaly", "tiles/kraj-contours.pmtiles"),
                   ("vrstevnice-skaly", "tiles/kraj-rocks.pmtiles"),
                   ("tienovanie", "tiles/kraj-terrain.pmtiles"),
                   ("linie", "tiles/kraj-trails.pmtiles"),
                   ("linie", "tiles/kraj-roads.pmtiles"),
                   ("body", "tiles/kraj-points.pmtiles")):
    if not baliky:
        break
    if meno in mapa_zip:
        bad.append(
            f"{PUBLISH}: `{meno}` je v ZÁKLADNEJ MAPE aj v balíku `{druh}`. "
            f"„Iba mapa“ tým váži rovnako ako mapa so všetkým, čo je presne "
            f"to, kvôli čomu má tá vrstva vlastný balík.")
    if meno not in baliky.get(druh, set()):
        bad.append(
            f"{PUBLISH}: `{meno}` sa do balíka `{druh}` nedostal – ten balík "
            f"sľubuje vrstvu, ktorú nenesie.")

if "navigacia" in merane:
    bad.append(
        f"{SUBORY}: `casti_baliku` hlási `navigacia` ako ČASŤ základnej mapy, "
        f"hoci graf cestuje v balíku `linie`. Katalóg by tú istú vec niesol "
        f"dvakrát – pod `maps.mapa.casti` aj pod `maps.linie` – a veľkosti by "
        f"sa sčítali do čísla, ktoré si nikto nestiahne.")

# ZRUŠENÝ BALÍK SA MUSÍ AJ MAZAŤ. `-navigacia.zip` zanikol spojením s `linie`,
# ale na Drive z minulých behov LEŽÍ – mená sú stále, takže ho nový beh
# neprepíše. Bez `ZRUSENE` by v priečinku ostal vedľa nového `-linie.zip`
# a katalóg by ponúkal oba: kto by si stiahol ten druhý, dostal by graf, ktorý
# už nikto neaktualizuje. To isté sa kedysi stalo `-search.zip`.
pmap_text = open(PUBLISH, encoding="utf-8").read()
if not re.search(r"^ZRUSENE\s*=.*\bnavigacia\b", pmap_text, re.M):
    bad.append(
        f"{PUBLISH}: `navigacia` nie je v `ZRUSENE`. Ten balík zanikol "
        f"(graf je odteraz v `linie`), takže sa starý `-navigacia.zip` musí "
        f"z Drive mazať a z katalógu vypadnúť – inak ponúka graf, ktorý už "
        f"nikto neprepisuje.")
if '("navigacia", ' in pmap_text:
    bad.append(
        f"{PUBLISH}: balík `navigacia` je späť v zozname `baliky`. Graf patrí "
        f"do `linie` – dva balíky pre tú istú sieť sú dve položky v katalógu "
        f"a dve miesta, kde sa dá zabudnúť.")

# ---- 4. Pages tie súbory naozaj má ----
with open(SITE, encoding="utf-8") as f:
    site_sh = f.read()

if not re.search(r'glyphs\s*=\s*"\$BASE/fonts/\{fontstack\}/\{range\}\.pbf"',
                 site_sh.replace("GLYPHS=", "glyphs=")):
    bad.append(
        f"{SITE}: adresa glyfov v manifeste sa neskladá z `$BASE`. V balíku "
        f"glyfy nie sú, takže táto adresa je pre web jediné, čo mu povie, kam "
        f"siahnuť – relatívna by ukazovala do balíka, kde nie je nič.")

if not re.search(r"cp\s+poc/web/\*\.js\s+poc/web/\*\.json\s+poc/web/index\.html\s+_site/",
                 site_sh):
    bad.append(
        f"{SITE}: viewer sa už do `_site` nekopíruje. Z balíka je vynechaný "
        f"práve preto, že je na Pages – keď zmizne aj odtiaľ, nie je nikde.")

# ---- 5. mapa sveta neodkazuje do balíka ----
with open(WORLD_STYLE, encoding="utf-8") as f:
    world = f.read()
if 'url("fonts/{fontstack}/{range}.pbf")' in world:
    bad.append(
        f"{WORLD_STYLE}: mapa sveta odkazuje na glyfy DO BALÍKA, kde už nie sú. "
        f"Appke to nevadí (nesie si ich), ale rozbalený balík vo vieweri by bol "
        f"bez jediného mena – a to vyzerá ako pokazený štýl, nie ako chýbajúci "
        f"súbor.")
if "fonts.openmaptiles.org" not in world:
    bad.append(
        f"{WORLD_STYLE}: štýl sveta nemá odkiaľ vziať glyfy. Appka si ich nesie "
        f"v sebe, ale ten, kto appka nie je, potrebuje adresu – bez nej je mapa "
        f"bez nápisov.")

for b in bad:
    print(f"::error::{b}")
print(f"Glyfy a viewer sú mimo balíka, ale majú kde byť: {len(bad)} chýb")
sys.exit(1 if bad else 0)
