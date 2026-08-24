#!/usr/bin/env python3
"""
Glyfy a viewer sú na Pages – v balíku byť nemajú, ale musia byť KDE INDE.

PREČO TO EXISTUJE. Fonty boli po dlaždiciach druhá najväčšia vec v balíku mapy
(tri fontstacky Noto Sans po ~34 MB, celý unicode; mapa kraja z nich použije
zlomok) a webový viewer (`index.html` + `*.js` z `poc/web`) je stránka, ktorú
si aplikácia nespúšťa – má vlastnú mapu. Oboje sa preto do ZIPu ani `.aar`
nebalí a ostáva len v `_site`, teda na Pages.

A PRÁVE PRETO SÚ TU TIETO KONTROLY: vynechať súbor z balíka je jednoriadková
zmena, ktorá sa dá spraviť aj tam, kde ten súbor NIE JE ODKIAĽ VZIAŤ – a mapa
bez glyfov nespadne, len nemá jediné písmeno a vyzerá ako pokazený štýl.
Rozhodnutie preto nie je prepínač, ale odpoveď z dát: glyfy sa vynechajú práve
vtedy, keď na ne manifest odkazuje ABSOLÚTNOU adresou (Pages). Mapa sveta má
v manifeste `fonts/{fontstack}/{range}.pbf`, teda odkaz DO BALÍKA – na Pages
nejde a jej glyfy sú orezané na stovky kB –, takže tej sa nechajú.

ČO SA KONTROLUJE:

  1. `mimo_balika()` naozaj vynechá viewer aj glyfy, keď je odkaz absolútny,
  2. pri RELATÍVNOM odkaze glyfy v balíku OSTANÚ (mapa sveta),
  3. a keď sa manifest nedá prečítať, ostanú tiež – „neviem" nesmie znamenať
     „zahoď" (väčší balík je chyba, ktorú vidno na veľkosti),
  4. `workers/deploy/site.sh` skladá adresu glyfov z `$BASE`, čiže absolútnu,
     a viewer do `_site` ďalej KOPÍRUJE (na Pages ostať musí),
  5. `workers/world/style.mjs` drží glyfy relatívne, teda v balíku.

Spustiť sa dá aj lokálne:
    python3 workers/lint/packaging.py
"""
import importlib.util
import os
import re
import sys
import tempfile

PUBLISH = "workers/deploy/publish-map.py"
SITE = "workers/deploy/site.sh"
WORLD_STYLE = "workers/world/style.mjs"

bad = []


def nacitaj(cesta):
    spec = importlib.util.spec_from_file_location("publish_map", cesta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["publish_map"] = mod
    spec.loader.exec_module(mod)
    return mod


def napln(site):
    """Napodobenina `_site`: viewer, glyfy, štýly, sprite, dlaždice."""
    for rel in ("index.html", "app.js", "themes.js", "style-overrides.json",
                "region.geojson", "fonts/Noto Sans Regular/0-255.pbf",
                "styles/svetla.json", "sprites/temaki.png",
                "tiles/manifest.json", "tiles/kraj.pmtiles"):
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
if "fonts/Noto Sans Regular/0-255.pbf" not in svet:
    bad.append(
        f"{PUBLISH}: glyfy sa vynechali aj pri RELATÍVNOM odkaze. Tak ich má "
        f"mapa sveta – tá na Pages nejde, takže balík je jediné miesto, kde ich "
        f"štýl nájde, a bez nich by v nej nebolo ani jedno meno.")

neznamy = v_baliku(pm, {})
if "fonts/Noto Sans Regular/0-255.pbf" not in neznamy:
    bad.append(
        f"{PUBLISH}: keď sa manifest nedá prečítať, glyfy sa zahodili. "
        f"„Neviem“ musí znamenať NECHAŤ: väčší balík je chyba, ktorú vidno na "
        f"veľkosti, kým mapa bez písmen vyzerá ako pokazený štýl.")

# ---- 4. Pages tie súbory naozaj má ----
with open(SITE, encoding="utf-8") as f:
    site_sh = f.read()

if not re.search(r'glyphs\s*=\s*"\$BASE/fonts/\{fontstack\}/\{range\}\.pbf"',
                 site_sh.replace("GLYPHS=", "glyphs=")):
    bad.append(
        f"{SITE}: adresa glyfov v manifeste sa neskladá z `$BASE`. Balík sa "
        f"podľa nej rozhoduje, či glyfy pribaliť – relatívna adresa by "
        f"znamenala „sú v balíku“, lenže tam ich Build map nedáva.")

if not re.search(r"cp\s+poc/web/\*\.js\s+poc/web/\*\.json\s+poc/web/index\.html\s+_site/",
                 site_sh):
    bad.append(
        f"{SITE}: viewer sa už do `_site` nekopíruje. Z balíka je vynechaný "
        f"práve preto, že je na Pages – keď zmizne aj odtiaľ, nie je nikde.")

# ---- 5. mapa sveta si glyfy nesie ----
with open(WORLD_STYLE, encoding="utf-8") as f:
    world = f.read()
if 'url("fonts/{fontstack}/{range}.pbf")' not in world:
    bad.append(
        f"{WORLD_STYLE}: mapa sveta už neodkazuje na glyfy relatívne. Odkedy "
        f"balenie rozhoduje podľa tvaru tej adresy, by ich absolútna adresa "
        f"z balíka vyhodila – a `svet.zip` na Pages nemá kam siahnuť.")

for b in bad:
    print(f"::error::{b}")
print(f"Glyfy a viewer sú mimo balíka, ale na Pages: {len(bad)} chýb")
sys.exit(1 if bad else 0)
