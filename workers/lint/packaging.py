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
     ale na adresu, z ktorej si ich vezme ten, kto nie je appka.

Spustiť sa dá aj lokálne:
    python3 workers/lint/packaging.py
"""
import importlib.util
import os
import re
import sys
import tempfile

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

    Aj hľadanie a navigácia – tie do balíka PATRIA (kontrola 6 nižšie).
    """
    for rel in ("index.html", "app.js", "themes.js", "style-overrides.json",
                "region.geojson", "fonts/Noto Sans Regular/0-255.pbf",
                "styles/svetla.json", "sprites/temaki.png",
                "tiles/manifest.json", "tiles/kraj.pmtiles",
                "tiles/search-index.db", "routing/valhalla_tiles.tar",
                "routing/valhalla.json", "routing/admins.sqlite",
                "routing/timezones.sqlite", "routing/graf.json"):
        cesta = os.path.join(site, rel)
        os.makedirs(os.path.dirname(cesta) or site, exist_ok=True)
        with open(cesta, "w") as f:
            f.write("x")


def v_baliku(pm, man):
    with tempfile.TemporaryDirectory() as site:
        napln(site)
        von, _dovody = pm.mimo_balika(site, man)
        return {os.path.relpath(p, site).replace(os.sep, "/")
                for p in pm.zaklad_subory(site, von)}


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

# ---- 6. hľadanie a navigácia z balíka VYPADNÚŤ NESMÚ ----
# Vlastný balík nemajú: `search-index.db` ho mal a bola to mapa, v ktorej sa
# nedalo nič nájsť, kým si človek nestiahol druhý ZIP – o ktorom sa v aplikácii
# nedozvedel. Graf Valhally je to isté o jeden krok ďalej: mapa, ktorá vie, kde
# čo je, ale nevie ťa tam doviezť. Vypadnúť pritom môžu jedným riadkom (stačí
# ich pridať medzi to, čo `zaklad_subory` vynecháva) a NIČ NESPADNE – preto
# kontrola.
for meno in ("tiles/search-index.db", "routing/valhalla_tiles.tar",
             "routing/admins.sqlite", "routing/graf.json"):
    if meno not in kraj:
        bad.append(
            f"{PUBLISH}: `{meno}` z balíka mapy VYPADOL. Hľadanie ani "
            f"navigačný graf vlastný balík nemajú – cestujú v základnej mape "
            f"a bez nich je to mapa, v ktorej sa nedá nič nájsť ani nikam "
            f"doviesť. Nespadne pri tom nič; pozná sa to až v telefóne.")

# A musia byť aj PREMERANÉ – veľkosť ide do `maps.json` pod balík `mapa`
# (`casti`). Časť, ktorú nikto nemeria, je presne to, čím bol `search-index.db`
# predtým, než sa naň niekto pozrel: v balíku dvakrát, a na veľkosti to nikto
# nepoznal.
import tempfile as _tf                                       # noqa: E402
sub = nacitaj_modul("deploy_subory", SUBORY)
with _tf.TemporaryDirectory() as site:
    napln(site)
    merane = sub.velkost_casti(sub.casti_baliku(site, PAGES))
for kluc in ("search", "navigacia"):
    if kluc not in merane:
        bad.append(
            f"{SUBORY}: časť `{kluc}` sa nepremeriava, takže sa jej veľkosť "
            f"nemá ako dostať do `maps.json` – a keďže vlastný balík nemá, "
            f"nedá sa zistiť inak než stiahnutím celej mapy.")
    elif not merane[kluc].get("files"):
        bad.append(
            f"{SUBORY}: časť `{kluc}` nenašla ani jeden súbor v `_site`, hoci "
            f"tam sú. Zmenil sa výber podľa mena alebo priečinka? V mape by "
            f"tá časť ostala, len by o nej katalóg tvrdil, že tam nie je.")

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
