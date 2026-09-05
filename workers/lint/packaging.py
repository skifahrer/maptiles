#!/usr/bin/env python3
"""Glyfy ani viewer v balíku nie sú – ale musia byť kde inde.

Fonty boli po dlaždiciach druhá najväčšia vec v balíku (tri stacky po ~34 MB)
a viewer si aplikácia nespúšťa, tak oboje ostáva len v `_site`. Vynechať súbor
z balíka je jednoriadková zmena a mapa bez glyfov nespadne, len nemá jediné
písmeno.

Kontroluje sa:
  1.–3. `mimo_balika()` vynechá viewer aj glyfy – pri odkaze na Pages, pri
     relatívnom odkaze aj vtedy, keď sa manifest nedá prečítať;
  4. `deploy/site.sh` skladá adresu glyfov z `$BASE` a viewer do `_site` kopíruje;
  5. `world/style.mjs` odkazuje na adresu, nie do balíka;
  6. hľadanie ani značené trasy zo základnej mapy nevypadli a sú premerané;
  7. navigačný graf je naopak von – má vlastný balík a je v ňom celý;
  8. balík nie je v číselníku medzi živými a zrušenými naraz.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import zipfile

PUBLISH = "workers/deploy/publish-map.py"
CISELNIK = "workers/data/packages.json"
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

    Aj hľadanie (do mapy patrí), aj vrstvy s vlastným balíkom a graf Valhally.
    """
    for rel in ("index.html", "app.js", "themes.js", "style-overrides.json",
                "region.geojson", "fonts/Noto Sans Regular/0-255.pbf",
                "styles/svetla.json", "sprites/temaki.png",
                "tiles/manifest.json", "tiles/kraj.pmtiles",
                "tiles/kraj-contours.pmtiles", "tiles/kraj-rocks.pmtiles",
                "tiles/kraj-terrain.pmtiles",
                "tiles/kraj-transport.pmtiles", "tiles/kraj-trails.pmtiles",
                "tiles/kraj-points.pmtiles", "tiles/kraj-boundaries.pmtiles",
                "tiles/kraj-water.pmtiles",
                "tiles/search-index.db", "routing/valhalla_tiles.tar",
                "routing/valhalla.json", "routing/admins.sqlite",
                "routing/timezones.sqlite", "routing/graf.json"):
        cesta = os.path.join(site, rel)
        os.makedirs(os.path.dirname(cesta) or site, exist_ok=True)
        with open(cesta, "w") as f:
            f.write("x")


def v_baliku(pm, man):
    """Čo v základnej mape ostane, keď sa vynechá len `mimo_balika`.

    Na glyfy a viewer to stačí. Na to, čo patrí do ktorého balíka, nie:
    skladba `main()` zopakovaná tu by bola druhá pravda, tak to číta
    `zabalene()` z naozaj zabalených ZIPov.
    """
    with tempfile.TemporaryDirectory() as site:
        napln(site)
        von, _dovody = pm.mimo_balika(site, man)
        return {os.path.relpath(p, site).replace(os.sep, "/")
                for p in pm.zaklad_subory(site, von)}


def zabalene():
    """`{balík: {cesty vnútri}}` – z `publish-map.py --zip-only` nad `_site`.

    Beh, nie napodobenina: vrstva, ktorá ostane aj v základnej mape, sa
    stiahne dvakrát, a balík, čo zo zoznamu vypadne, sa nenahrá vôbec.
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
                # vnútri je navyše priečinok s menom balíka
                von[druh] = {n.split("/", 1)[1] for n in z.namelist()
                             if "/" in n}
        return von


# 1. až 3. čo v balíku ostane
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

# 6. hľadanie a značené trasy z balíka vypadnúť nesmú
# `search-index.db` vlastný balík mal a bola to mapa, v ktorej sa nedalo nič
# nájsť, kým si človek nestiahol druhý ZIP – o ktorom sa nedozvedel.
baliky = zabalene()
mapa_zip = baliky.get("mapa", set())
cesty_zip = baliky.get("cesty", set())
navigacia_zip = baliky.get("navigacia", set())

if baliky and "tiles/search-index.db" not in mapa_zip:
    bad.append(
        f"{PUBLISH}: `tiles/search-index.db` z balíka mapy VYPADOL. Hľadanie "
        f"vlastný balík nemá – cestuje v základnej mape a bez neho je to "
        f"mapa, v ktorej sa nedá nič nájsť. Nespadne pri tom nič; pozná sa to "
        f"až v telefóne.")

# značené trasy sú v mape z toho istého dôvodu: turistická mapa bez značiek
# nesľubuje to, načo si ju človek stiahol. Sú to jednotky MB proti stovkám.
if baliky and "tiles/kraj-trails.pmtiles" not in mapa_zip:
    bad.append(
        f"{PUBLISH}: `tiles/kraj-trails.pmtiles` z balíka mapy VYPADOL. "
        f"Značené trasy vlastný balík nemajú – cestujú v základnej mape a bez "
        f"nich je to turistická mapa bez značiek. Nespadne pri tom nič.")

# a musí byť aj premerané – veľkosť ide do maps.json pod balík `mapa`
import tempfile as _tf                                       # noqa: E402
sub = nacitaj_modul("deploy_subory", SUBORY)
with _tf.TemporaryDirectory() as site:
    napln(site)
    merane = sub.velkost_casti(sub.casti_baliku(site, PAGES))
for _cast, _preco in (("search", "index na offline hľadanie"),
                      ("trasy", "značené trasy")):
    if _cast in merane and merane[_cast].get("files"):
        continue
    if _cast not in merane:
        bad.append(
            f"{SUBORY}: časť `{_cast}` ({_preco}) sa nepremeriava, takže sa "
            f"jej veľkosť nemá ako dostať do `maps.json` – a keďže vlastný "
            f"balík nemá, nedá sa zistiť inak než stiahnutím celej mapy.")
    else:
        bad.append(
            f"{SUBORY}: časť `{_cast}` ({_preco}) nenašla ani jeden súbor "
            f"v `_site`, hoci tam sú. Zmenil sa výber podľa mena alebo "
            f"priečinka? V mape by tá časť ostala, len by o nej katalóg "
            f"tvrdil, že tam nie je.")

# 7. navigačný graf: vlastný balík, a preto zo základnej mapy von
# Namerané 170–190 MB grafu v 283 MB mape. Obe strany sa dajú pokaziť ticho:
# nechať ho v mape znamená stiahnuť ho dvakrát, nezabaliť ho nikam znamená
# mapu, ktorá vie, kde čo je, ale nevie ťa tam doviezť.
for meno in ("routing/valhalla_tiles.tar", "routing/valhalla.json",
             "routing/admins.sqlite", "routing/timezones.sqlite",
             "routing/graf.json"):
    if not baliky:
        break
    if meno in mapa_zip:
        bad.append(
            f"{PUBLISH}: `{meno}` ostal v ZÁKLADNEJ MAPE, hoci graf má vlastný "
            f"balík `-navigacia.zip`. Cesty vnútri sú tie isté, takže by ho mal "
            f"každý dvakrát: raz v mape, raz v balíku – a na veľkosti to nikto "
            f"nepozná. Patrí do `vylucit` v `zaklad_subory`.")
    if meno in cesty_zip:
        bad.append(
            f"{PUBLISH}: `{meno}` je v balíku `-cesty.zip`, kde graf nie je. "
            f"`cesty` je kreslená dopravná sieť (desiatky MB), graf je 170 až "
            f"190 MB – v jednom balíku by z neho bolo deväť desatín a kto chce "
            f"sieť len vidieť, sťahoval by ho tak či tak.")
    if meno not in navigacia_zip:
        bad.append(
            f"{PUBLISH}: `{meno}` sa do balíka `navigacia` nedostal. Graf sú "
            f"štyri súbory, ktoré si musia sedieť, plus `graf.json` s tým, "
            f"z čoho je – keď jeden chýba, trasa sa „len nenájde“ a vyzerá to "
            f"ako chyba aplikácie, nie ako chýbajúci súbor v balíku.")

# a to isté pre vrstvy s vlastným balíkom: „čo pribudne, patrí aj do `vylucit`"
# platí na všetky, nie na posledný pridaný
for druh, meno in (("vrstevnice-skaly", "tiles/kraj-contours.pmtiles"),
                   ("vrstevnice-skaly", "tiles/kraj-rocks.pmtiles"),
                   ("tienovanie", "tiles/kraj-terrain.pmtiles"),
                   ("cesty", "tiles/kraj-transport.pmtiles"),
                   ("body", "tiles/kraj-points.pmtiles"),
                   ("hranice", "tiles/kraj-boundaries.pmtiles"),
                   ("vodstvo", "tiles/kraj-water.pmtiles")):
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
        f"hoci graf má vlastný balík. Katalóg by tú istú vec niesol dvakrát – "
        f"pod `maps.mapa.casti` aj pod `maps.navigacia` – a veľkosti by sa "
        f"sčítali do čísla, ktoré si nikto nestiahne.")

# balík, ktorý sa vyrába, nesmie byť v `ZRUSENE`: „vyrába sa" a „starý sa
# maže" sú opačné tvrdenia a beh by ho podľa poradia nahral a hneď zmazal
import json as _json                                          # noqa: E402
with open(CISELNIK, encoding="utf-8") as _f:
    _cis = _json.load(_f)
_zive = {b["kluc"] for b in _cis.get("baliky") or []}
_mrtve = set(_cis.get("zrusene") or ())
for _k in sorted(_zive & _mrtve):
    bad.append(
        f"{CISELNIK}: balík `{_k}` je medzi živými AJ v `zrusene`. `zrusene` "
        f"znamená „starý sa maže“ – balík by tak zmizol z Drive aj z katalógu "
        f"hneď po tom, čo ho beh nahral.")
for _k in ("navigacia", "cesty", "hranice", "vodstvo"):
    if _k not in _zive:
        bad.append(
            f"{CISELNIK}: balík `{_k}` v číselníku nie je, takže sa nevyrobí "
            f"a katalóg o ňom nepovie nič – vrstva sa postaví a skončí nikde.")

# 4. Pages tie súbory naozaj má
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

# 5. mapa sveta neodkazuje do balíka
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
