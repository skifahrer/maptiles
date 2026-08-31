#!/usr/bin/env python3
"""
Kontrola: katalóg `maps.json` drží tvar a nikto ho neobchádza.

PREČO. `maps.json` je jediný zoznam toho, ktoré mapy sú hotové a kde na Drive
ležia. Je to súbor v repozitári, ktorý dopisuje BEH – a to je presne ten druh
veci, ktorá sa rozíde ticho:

  * mená v katalógu prestanú sedieť s menami balíkov, ktoré publikovanie
    naozaj vyrába (`<kraj>[-<výsek>][-testNkm2]{,-vrstevnice-skaly,-tienovanie}
    .zip`), a odkazy potom ukazujú na súbory, ktoré na Drive nie sú;
  * katalóg sa zapíše aj vtedy, keď publikovanie zlyhalo – zoznam by tvrdil,
    že mapa je hotová;
  * build stratí právo zapisovať (`contents: write`) a katalóg sa ticho
    prestane dopĺňať.

Spustiť sa dá aj lokálne:
    python3 workers/lint/catalog.py
"""
import json
import os
import re
import sys

import yaml

# Druhy balíkov, ktoré `baliky` v `publish-map.py` naozaj vyrába (`""` sa do
# katalógu zapisuje ako `mapa`) – táto množina musí sedieť s tým zoznamom,
# inak balík, ktorý pipeline práve pridala (naposledy `linie` a `body`, línie
# a body z OSM), zhodí lint napriek tomu, že v katalógu je zo skutočného behu.
DRUHY = {"mapa", "vrstevnice-skaly", "tienovanie", "wikipedia", "linie", "body"}
# ZRUŠENÉ DRUHY – v katalógu ešte môžu byť (kraj, ktorý sa odvtedy nestaval),
# ale publikovanie ich už NEVYRÁBA: `search` sa presťahoval DOVNÚTRA balíka
# `mapa` a jeho veľkosť je pod ním v `casti`. Hlásiť ich ako neznámy druh by
# znamenalo červený lint za starý zápis, ktorý najbližší build sám prepíše;
# preto sa berú, ale musia byť aj v `ZRUSENE` v `publish-map.py` – inak by
# starý `-search.zip` ostal ležať na Drive a katalóg by naň ukazoval.
ZRUSENE = {"search"}
# Meno balíka: `<kraj>[-<výsek>][-testNkm2]` + prípona druhu. Sedí to s
# `zaklad()` a `meno()` vo `workers/deploy/publish-map.py`.
MENO = re.compile(r"^[a-z0-9_]+(-[a-z0-9_]+)*(-test[0-9.]+km2)?"
                  r"(-vrstevnice-skaly|-tienovanie|-wikipedia|-search)?\.zip$")
CATALOG = "maps.json"
# RÝCHLY TEST MÁ VLASTNÝ SÚBOR. `maps.json` je jediná odpoveď na „ktoré mapy sú
# hotové" a mapa s terénom na 4 km² medzi ne nepatrí – uzol testu tam síce mal
# vlastný kľúč (`…_test4km2`), ale v zozname stál vedľa ostrých máp a vyzeral
# ako ďalší výsek. Zapisovať sa musí ďalej (balík `…-test4km2.zip` na Drive je
# inak jediný, o ktorom sa bez tokenu nedá dozvedieť), tak sú z toho dva súbory
# s tým istým tvarom.
CATALOG_TEST = "maps-test.json"
CATALOGS = (CATALOG, CATALOG_TEST)
WORKFLOW = ".github/workflows/build-map.yml"
# Samostatné pipeline, ktoré do TOHO ISTÉHO katalógu zapisujú tiež – tým istým
# skriptom (`publish-map.py`, pri článkoch s `--only=wikipedia`). Platia na ne
# tie isté dve pravidlá: musia mať právo commitnúť a nesmú zapísať po
# neúspešnom nahratí. Zoznam je preto zoznam a nie jedno meno: pribudla k nemu
# mapa sveta a bez toho by na ňu tieto kontroly ticho nedosiahli – čiže presne
# to, čomu sa tento súbor venuje.
WIKI_WORKFLOW = ".github/workflows/wiki.yml"
WORLD_WORKFLOW = ".github/workflows/world-map.yml"
PIPELINE = (WIKI_WORKFLOW, WORLD_WORKFLOW)
PUBLISH_MAP = "workers/deploy/publish-map.py"
# Čo sa do katalógu zapíše, skladá vedľajší modul – `publish-map.py` prerástol
# strop 800 riadkov a rezalo sa tam, kde sa mení otázka.
CATALOG_PY = "workers/deploy/catalog.py"
# A `catalog.sh` ten súbor commitne – na ČERSTVÚ vetvu, nie na SHA, s ktorou
# beh začal (inak druhý zapisujúci job v tom istom behu vždy skončí
# konfliktom; beh 31782846262).
CATALOG_SH = "workers/deploy/catalog.sh"
# Nahrávanie na Drive. Katalóg stojí na tom, že id balíka prežije ďalší build
# (rozpis pri `_skuska_stalych_id`), a rozhoduje o tom táto jedna funkcia.
FOLDER_PY = "workers/drive/folder.py"

bad = []

# Obsah `publish-map.py` treba UŽ pri kontrole katalógov (zrušené druhy), a
# ešte raz nižšie pri kontrole samotného skriptu. Číta sa preto raz, tu.
try:
    pmap_text = open(PUBLISH_MAP, encoding="utf-8").read()
except OSError:
    pmap_text = ""
pmap_zrusene = set()
for _m in re.findall(r"^ZRUSENE\s*=\s*\(([^)]*)\)", pmap_text, re.M):
    pmap_zrusene |= set(re.findall(r"[\"']([\w-]+)[\"']", _m))


def polozky(node, kde):
    """Rekurzívne prejde katalóg a vráti (cesta, položka s mapami)."""
    out = []
    if not isinstance(node, dict):
        return out
    if isinstance(node.get("maps"), dict):
        out.append((kde, node))
    for kluc in ("regions", "subregions"):
        for k, v in (node.get(kluc) or {}).items():
            out += polozky(v, f"{kde}/{k}" if kde else k)
    return out


def krajiny(data):
    """Krajiny sú kľúče v KORENI – metadáta katalógu začínajú podčiarkovníkom.

    Tá istá konvencia ako vo `workers/data/areas.json` (`_comment` medzi kľúčmi
    pohorí). Kto to číta, preskočí `_*`; kontrola musí robiť to isté, inak by
    `_comment` hlásila ako krajinu bez máp.
    """
    return {k: v for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict)}


def je_test(kluc):
    """Uzol rýchleho testu – `vysoke_tatry_test4km2`. Opak `rozdel_test`."""
    cut = kluc.rfind("_test")
    if cut < 0 or not kluc.endswith("km2"):
        return False
    return kluc[cut + 5:-3].replace(".", "").isdigit()


for cesta in CATALOGS:
    try:
        with open(cesta) as f:
            data = json.load(f)
    except FileNotFoundError:
        bad.append(f"{cesta} v repozitári nie je – build ho dopisuje, ale musí "
                   f"existovať aspoň prázdny (`{{}}`), inak sa prvý zápis "
                   f"nemá o čo oprieť.")
        continue
    except ValueError as exc:
        bad.append(f"{cesta} nie je platný JSON ({exc}) – build ho číta "
                   f"a dopisuje, takže na rozbitom súbore prestane katalóg "
                   f"vznikať.")
        continue

    if not isinstance(data, dict):
        bad.append(f"{cesta} nie je objekt – hlavný kľúč je KRAJINA "
                   f"(`slovensko`), pod ňou `regions` a `subregions`.")
        continue
    if [k for k in data if not k.startswith("_") and not isinstance(data[k], dict)]:
        bad.append(f"{cesta}: v koreni je kľúč, ktorý nie je ani krajina "
                   f"(objekt), ani metadáta (`_…`). Hlavný kľúč je krajina.")
    for kde, p in polozky({"regions": krajiny(data)}, ""):
        # DVA SÚBORY, DVA OBSAHY. Testovací uzol v `maps.json` je presne to,
        # čo sa touto zmenou riešilo: vyzerá ako ďalší výsek a to, že je v ňom
        # terén na pár km², je vidieť až na `test_km2` v položke.
        posledny = kde.rsplit("/", 1)[-1]
        if je_test(posledny) and cesta != CATALOG_TEST:
            bad.append(f"{cesta}: {kde} je uzol rýchleho testu a patrí do "
                       f"{CATALOG_TEST}. V zozname hotových máp vyzerá ako "
                       f"ďalší výsek, hoci terén je v ňom na pár km².")
        if not je_test(posledny) and cesta == CATALOG_TEST:
            bad.append(f"{cesta}: {kde} nie je rýchly test (kľúč nekončí na "
                       f"`_test<N>km2`), takže patrí do {CATALOG}.")
        # KEDY TÁ MAPA VZNIKLA – v oboch podobách. `updated_at` je ISO 8601
        # v UTC na čítanie okom, `updated_ts` sekundy od epochy na počítanie
        # veku bez parsovania dátumu; keď chýba jedno z nich, musí si ho
        # čitateľ dopočítať sám a to je práca, ktorú má katalóg ušetriť.
        for pole in ("updated_at", "updated_ts"):
            if p.get(pole) in (None, ""):
                bad.append(f"{cesta}: {kde} nemá `{pole}` – z katalógu sa "
                           f"nedá zistiť, kedy tá mapa vznikla.")
        for druh, m in p["maps"].items():
            if druh not in DRUHY | ZRUSENE:
                bad.append(f"{cesta}: {kde} má balík `{druh}`, ktorý "
                           f"publikovanie nevyrába (pozná {sorted(DRUHY)}).")
            if druh in ZRUSENE and pmap_text and druh not in pmap_zrusene:
                bad.append(f"{cesta}: {kde} má zrušený balík `{druh}`, ale "
                           f"`{PUBLISH_MAP}` ho nemá v `ZRUSENE`, takže ho "
                           f"nikto nezmaže z Drive ani z položky – katalóg by "
                           f"naň ukazoval navždy.")
            if not isinstance(m, dict) or not m.get("file") or not m.get("link"):
                bad.append(f"{cesta}: {kde}/{druh} nemá `file` a `link` – "
                           f"zoznam bez odkazu je na nič.")
                continue
            if not MENO.match(m["file"]):
                bad.append(f"{cesta}: {kde}/{druh} má meno `{m['file']}`, "
                           f"ktoré nesedí s tým, čo vyrába "
                           f"`workers/deploy/publish-map.py`.")

try:
    wf = yaml.safe_load(open(WORKFLOW))
    text = open(WORKFLOW).read()
except (OSError, ValueError) as exc:
    print(f"::error::{WORKFLOW} sa nedá prečítať: {exc}")
    sys.exit(1)

deploy = (wf.get("jobs") or {}).get("deploy") or {}
if (deploy.get("permissions") or {}).get("contents") != "write":
    bad.append(f"{WORKFLOW}: job `deploy` nemá `contents: write`, takže katalóg "
               f"{CATALOG} nemá ako commitnúť – a prestal by sa dopĺňať bez "
               f"jediného slova.")

kroky = deploy.get("steps") or []
katalog = [s for s in kroky if str(s.get("run", "")).find("deploy/catalog.sh") >= 0]
if not katalog:
    bad.append(f"{WORKFLOW}: v jobe `deploy` nie je krok, ktorý pustí "
               f"`workers/deploy/catalog.sh` – katalóg by sa zapísal na runner "
               f"a stratil sa s ním.")
else:
    for s in katalog:
        # Katalóg nesmie vzniknúť po neúspešnom publikovaní: ukazoval by na
        # súbory, ktoré na Drive nie sú.
        if "steps.publish.outcome == 'success'" not in str(s.get("if", "")):
            bad.append(f"{WORKFLOW}: krok „{s.get('name')}“ nemá podmienku "
                       f"`steps.publish.outcome == 'success'` – katalóg by "
                       f"ukazoval aj na balíky, ktoré sa nenahrali.")
if "--maps=" not in text:
    bad.append(f"{WORKFLOW}: `publish-map.py` sa volá bez `--maps=`, takže "
               f"katalóg nikto nedopíše.")

# ---- ktorý katalóg sa commitne, hovorí ten, kto doň zapísal ----
# `catalog.sh` dostáva meno súboru v `MAPS_JSON`. Keby tam stálo natvrdo
# `maps.json`, rýchly test by zapísal `maps-test.json` a commitol `maps.json`:
# na Drive by balík ležal, v repozitári by po ňom nezostalo nič a beh by bol
# zelený. Preto sa to podáva VÝSTUPOM kroku, ktorý publikoval.
for wf_path in (WORKFLOW,) + PIPELINE:
    try:
        wtext = open(wf_path, encoding="utf-8").read()
    except OSError:
        continue                      # chýbajúci súbor hlási kontrola nižšie
    if "MAPS_JSON: maps.json" in wtext:
        bad.append(f"{wf_path}: `MAPS_JSON` je natvrdo `maps.json`. Ktorý "
                   f"katalóg to je, vie iba krok, ktorý doň zapísal – podaj "
                   f"mu `steps.publish.outputs.maps_file`, inak rýchly test "
                   f"zapíše {CATALOG_TEST} a commitne {CATALOG}.")
    if "MAPS_JSON:" in wtext and "steps.publish.outputs.maps_file" not in wtext:
        bad.append(f"{wf_path}: krok s `catalog.sh` nedostáva "
                   f"`steps.publish.outputs.maps_file` – commitol by iný súbor, "
                   f"než ktorý `publish-map.py` práve zapísal.")

# ---- samostatné pipeline zapisujú do toho istého katalógu ----
for wf_path in PIPELINE:
    try:
        wwf = yaml.safe_load(open(wf_path))
        wtext = open(wf_path, encoding="utf-8").read()
    except (OSError, ValueError) as exc:
        bad.append(f"{wf_path} sa nedá prečítať: {exc}")
        continue
    for job, jd in ((wwf.get("jobs") or {})).items():
        if (jd.get("permissions") or {}).get("contents") != "write":
            bad.append(f"{wf_path}: job `{job}` nemá `contents: write`, "
                       f"takže {CATALOG} nemá ako commitnúť – balík by sa "
                       f"nahral na Drive a v katalógu by po ňom nezostalo nič.")
        kat = [s for s in (jd.get("steps") or [])
               if "deploy/catalog.sh" in str(s.get("run", ""))]
        if not kat:
            bad.append(f"{wf_path}: job `{job}` nepúšťa "
                       f"`workers/deploy/catalog.sh` – katalóg by sa zapísal "
                       f"na runner a stratil sa s ním.")
        for s in kat:
            if "steps.publish.outcome == 'success'" not in str(s.get("if", "")):
                bad.append(f"{wf_path}: krok „{s.get('name')}“ nemá "
                           f"podmienku `steps.publish.outcome == 'success'` – "
                           f"katalóg by ukazoval aj na balík, ktorý sa "
                           f"nenahral.")
    if wf_path == WIKI_WORKFLOW and "--only=wikipedia" not in wtext:
        bad.append(f"{WIKI_WORKFLOW}: `publish-map.py` sa volá bez "
                   f"`--only=wikipedia`. Bez toho by publikovanie chcelo celý "
                   f"web (`_site`), ktorý táto pipeline nerobí, a katalóg by "
                   f"prepísalo položkou bez máp.")
    # Mapa sveta naopak publikuje CELÚ mapu (`--site=_site`), takže položku
    # svojho uzla prepisuje – ale musí povedať, čo v nej je. Bez `MAP_LAYERS`
    # by si `publish-map.py` vypýtal vrstvy mapy kraja a do katalógu aj do
    # `obsah.json` by napísal „bez_vrstevnic, bez_skal, bez_tienovania“:
    # znie to ako mapa kraja s vypnutým terénom, a to táto mapa nie je.
    if wf_path == WORLD_WORKFLOW and "MAP_LAYERS" not in wtext:
        bad.append(f"{WORLD_WORKFLOW}: nikde nenastavuje `MAP_LAYERS`, takže "
                   f"katalóg by o mape sveta tvrdil, že je to mapa kraja bez "
                   f"vrstevníc, skál a tieňovania.")

# `--only` musí katalóg DOPĹŇAŤ, nie prepisovať: samostatná pipeline vie len
# o svojom balíku a prepis by zmazal odkazy na mapu, o ktorej nič nevie.
pmap = pmap_text
try:
    kmap = open(CATALOG_PY, encoding="utf-8").read()
except OSError as exc:
    bad.append(f"{CATALOG_PY} sa nedá prečítať: {exc}")
    kmap = ""
if not pmap:
    bad.append(f"{PUBLISH_MAP} sa nedá prečítať.")
# ČO SI ČITATEĽ NESMIE ODVODIŤ. Meno súboru s dlaždicami sa z kľúča uzla
# poskladať NEDÁ – uzol je `bratislavsky_test4km2`, balík `bratislavsky-test4km2
# .zip` a dlaždice v ňom `tiles/bratislavsky_test4-…`; pri výreze sa dokonca
# volajú podľa kraja, nie podľa výseku. Kto by si cestu odvodil, dostane súbor,
# ktorý v balíku nie je, a vrstva sa ticho nenačíta. A strop zoomu, ktorý
# v katalógu nie je, si čitateľ dosadí z `maxzoom` mapy – trasy (z14) a prvky
# (z15) by tak nad svojím stropom pýtali neexistujúce dlaždice a zmizli by
# práve tie dve vrstvy, ktoré sa vyberajú ťuknutím do mapy.
for kluc, preco in (
        ("tiles_paths", "cesty k `.pmtiles` sa do položky nezapisujú, takže "
                        "si ich čitateľ musí odvodiť z kľúča – a ten meno "
                        "súboru nie je"),
        ("trails_maxzoom", "strop zoomu značených trás (z14) v položke nie je"),
        ("features_maxzoom", "strop zoomu krajinných prvkov (z15) v položke "
                             "nie je"),
        ("rock_source", "z ktorého modelu sú SKALY, v položke nie je "
                        "(`dem_source` je zdroj vrstevníc)"),
        ("terrain_source", "z ktorého modelu je TIEŇOVANIE, v položke nie je "
                           "– pri prechode na náhradný model by atribúcia "
                           "tvrdila DMR 5.0 nad reliéfom zo Sonnyho"),
        ("casti", "koľko z balíka `mapa` je HĽADANIE a koľko NAVIGÁCIA, "
                  "v položke nie je. Vlastný balík tie dve veci nemajú "
                  "(cestujú v mape), takže katalóg je jediné miesto, kde sa "
                  "ich veľkosť dá prečítať bez stiahnutia stoviek MB – a "
                  "kým sa nedala, ležal `search-index.db` v balíku dvakrát "
                  "a nikto to na veľkosti nepoznal")):
    if kmap and kluc not in kmap:
        bad.append(f"{CATALOG_PY}: {preco}. Doplň to z `manifest.json` – "
                   f"pozná to, lebo podľa toho číta dlaždice aj viewer.")

if kmap and "def katalog_subor(" not in kmap:
    bad.append(f"{CATALOG_PY}: chýba `katalog_subor()` – nie je jedno miesto, "
               f"ktoré povie, či beh zapisuje do {CATALOG}, alebo do "
               f"{CATALOG_TEST}. Pýtajú sa naň traja (publish-map.py, "
               f"apple-archive.sh a cezeň catalog.sh) a tri výpočty toho "
               f"istého sa raz rozídu.")
if kmap and "def zapis_katalog(path, parts, regions, baliky, man, iba=" not in kmap:
    bad.append(f"{CATALOG_PY}: `zapis_katalog` nepozná režim „doplň jeden "
               f"balík“ (parameter `iba`). Samostatná pipeline by položku "
               f"regiónu prepísala a odkazy na mapu by zmizli.")

# RÝCHLY TEST SA ZAPISUJE, ALE DO VLASTNÉHO UZLA. Zapisovať sa musí – balík
# `…-test4km2.zip` na Drive je inak jediný, o ktorom sa bez tokenu nedá
# dozvedieť. Sadnúť na uzol ostrej mapy ale nesmie: terén je v ňom na pár km²
# a kto si ho stiahne podľa katalógu, dostane mapu s dierou. Preto sa
# kontroluje, že cesta v katalógu vzniká `cesta_katalog()` a podáva sa ako
# `kat=` – bez toho by test ostrú mapu prepísal.
if pmap:
    if "def cesta_katalog(" not in pmap:
        bad.append(f"{PUBLISH_MAP}: chýba `cesta_katalog()` – rýchly test by "
                   f"sa zapísal na miesto ostrej mapy toho istého kraja "
                   f"a katalóg by o mape zo 4 km² tvrdil, že je to kraj.")
    if "kat=kat" not in pmap:
        bad.append(f"{PUBLISH_MAP}: `zapis_katalog` sa volá bez `kat=`, takže "
                   f"uzol testu a uzol ostrej mapy sú ten istý.")
    # RÝCHLY TEST ZAPISUJE INAM, NIE NIKAM. Bez tohto volania by `--maps=`
    # z workflowu prešlo rovno do zápisu a testovacia mapa by sadla medzi
    # hotové – vlastný uzol ju od nich odlíši, ale v zozname stojí vedľa nich.
    if "catalog.katalog_subor(" not in pmap:
        bad.append(f"{PUBLISH_MAP}: `--maps` neprechádza cez "
                   f"`catalog.katalog_subor()`, takže rýchly test zapíše do "
                   f"{CATALOG} namiesto {CATALOG_TEST}.")
    if "maps_file=" not in pmap:
        bad.append(f"{PUBLISH_MAP}: nezapisuje výstup kroku `maps_file`, "
                   f"takže `catalog.sh` nemá ako vedieť, ktorý súbor "
                   f"commitnúť – a odvodiť si to sám nesmie (bola by to druhá "
                   f"pravda o tom istom).")
    if "nezapisujem" in pmap:
        bad.append(f"{PUBLISH_MAP}: katalóg sa pri niektorom behu preskakuje. "
                   f"Rýchly test má vlastný uzol (`cesta_katalog`), takže "
                   f"preskakovať ho netreba – a balík, ktorý v zozname nie je, "
                   f"nikto nenájde.")

# `.aar` doplní do katalógu druhý job – ten si musí vypýtať z vetvy a doplniť
# TEN ISTÝ súbor, do ktorého zapísal `deploy`. Bash si to nemá ako spočítať,
# tak sa pýta `catalog.py --subor`.
AAR_SH = "workers/deploy/apple-archive.sh"
try:
    aar = open(AAR_SH, encoding="utf-8").read()
except OSError as exc:
    bad.append(f"{AAR_SH} sa nedá prečítať: {exc}")
    aar = ""
if aar and "catalog.py --subor" not in aar:
    bad.append(f"{AAR_SH}: nepýta sa `catalog.py --subor`, ktorý katalóg je "
               f"ten správny. Pri rýchlom teste by si z vetvy vypýtal "
               f"{CATALOG}, doplnil doň `.aar` k mape, ktorá tam nie je, "
               f"a {CATALOG_TEST} by o `.aar` nevedel.")

try:
    csh = open(CATALOG_SH, encoding="utf-8").read()
except OSError as exc:
    bad.append(f"{CATALOG_SH} sa nedá prečítať: {exc}")
    csh = ""
if csh and "reset --mixed" not in csh:
    bad.append(f"{CATALOG_SH}: commit sa nerobí na čerstvú vetvu "
               f"(`git fetch` + `git reset --mixed FETCH_HEAD`). Druhý "
               f"zapisujúci job v tom istom behu – `.aar` po `deploy` – by "
               f"niesol aj cudzí zápis, rebase by ho pridával druhýkrát "
               f"a katalóg by sa zakaždým ticho zahodil.")

# ---- balík z INEJ pipeline prežije build mapy ----
# Toto sa staticky prečítať nedá, a bola to presne tá tichá chyba: `wikipedia`
# robí `wiki.yml`, ale položku regiónu prepisuje Build map – a ten ju pri
# každom builde (teda pri každej zmene štýlu) z katalógu zmazal, hoci
# `…-wikipedia.zip` na Drive ležal ďalej, lebo TAM sa balík, o ktorom beh
# nerozhoduje, nemaže. Katalóg sa preto skúša naostro: zapíše sa mapa, doplní
# sa cudzí balík a mapa sa zapíše znova.
def _skuska_katalogu():
    """Vráti zoznam chýb – prázdny, keď sa katalóg správa, ako má."""
    import contextlib
    import importlib.util
    import io
    import tempfile

    spec = importlib.util.spec_from_file_location("_lint_catalog", CATALOG_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lint_catalog"] = mod
    spec.loader.exec_module(mod)

    regions = {"bratislavsky": {"name": "Bratislavský kraj",
                                "country": "slovensko"}}
    man = {"default_region": "bratislavsky",
           "regions": {"bratislavsky": {"bbox": [16.8, 48.0, 17.5, 48.6],
                                        "maxzoom": 16}}}
    parts = ["slovensko", "bratislavsky"]
    mapove = ["mapa", "vrstevnice-skaly", "tienovanie"]
    mapa_baliky = [("", "bratislavsky.zip", 1, "id1", "zip"),
                   ("vrstevnice-skaly", "bratislavsky-vrstevnice-skaly.zip",
                    1, "id2", "zip"),
                   ("tienovanie", "bratislavsky-tienovanie.zip", 1, "id3", "zip")]

    def maps_v(path):
        with open(path) as f:
            return json.load(f)["slovensko"]["regions"]["bratislavsky"]["maps"]

    chyby = []
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.zapis_katalog(path, parts, regions, mapa_baliky, man,
                              spravuje=mapove)
            # `wiki.yml`: `--only=wikipedia`, teda doplnenie jedného balíka
            mod.zapis_katalog(path, parts, regions,
                              [("wikipedia", "bratislavsky-wikipedia.zip",
                                1, "id4", "zip")], {}, iba="wikipedia")
            po_wiki = maps_v(path)
            # a teraz ďalší build mapy – o `wikipedia` nerozhoduje
            mod.zapis_katalog(path, parts, regions, mapa_baliky, man,
                              spravuje=mapove)
            po_mape = maps_v(path)
            # beh, ktorý o `wikipedia` ROZHODUJE a nemá ju (články sa vypli):
            # ten ju zmazať MUSÍ – na Drive sa starý balík maže tiež
            mod.zapis_katalog(path, parts, regions, mapa_baliky, man,
                              spravuje=mapove + ["wikipedia"])
            po_vypnuti = maps_v(path)
    if "wikipedia" not in po_wiki:
        chyby.append(f"{CATALOG_PY}: `--only=wikipedia` balík do položky "
                     f"nedoplní – pipeline článkov by nahrala ZIP na Drive "
                     f"a v katalógu by po ňom nezostalo nič.")
    elif "wikipedia" not in po_mape:
        chyby.append(f"{CATALOG_PY}: build mapy zmazal z položky balík "
                     f"`wikipedia`, o ktorom nerozhoduje (nemá ho v "
                     f"`spravuje`). Na Drive ten ZIP ostáva ležať, takže "
                     f"katalóg by o ňom mlčal po každej zmene štýlu.")
    if "wikipedia" in po_vypnuti:
        chyby.append(f"{CATALOG_PY}: balík, o ktorom beh ROZHODUJE a "
                     f"nevyrobil ho, ostal v katalógu – odkazoval by na "
                     f"súbor, ktorý ten istý beh na Drive zmazal.")

    # ---- kedy tá mapa vznikla: dva zápisy jedného okamihu ----
    # Staticky sa to prečítať nedá – `updated_ts` môže v module byť a do
    # položky sa nedostať (napr. keď ho prepíše `merge`). Preto sa to skúša
    # naostro, tým istým volaním, aké robí `publish-map.py`.
    import calendar
    import time as _time
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.zapis_katalog(path, parts, regions, mapa_baliky, man,
                              spravuje=mapove)
        with open(path) as f:
            uzol = json.load(f)["slovensko"]["regions"]["bratislavsky"]
    for pole in ("updated_at", "updated_ts"):
        if uzol.get(pole) in (None, ""):
            chyby.append(f"{CATALOG_PY}: zapísaná položka nemá `{pole}` – "
                         f"z katalógu sa nedá zistiť, kedy tá mapa vznikla.")
    if uzol.get("updated_at") and uzol.get("updated_ts") is not None:
        try:
            zo_stringu = calendar.timegm(
                _time.strptime(uzol["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            zo_stringu = None
            chyby.append(f"{CATALOG_PY}: `updated_at` nie je ISO 8601 v UTC "
                         f"(`{uzol['updated_at']}`) – zoradiť sa to dá ako "
                         f"text len vtedy, keď má každý zápis ten istý tvar.")
        if zo_stringu is not None and zo_stringu != uzol["updated_ts"]:
            chyby.append(f"{CATALOG_PY}: `updated_at` a `updated_ts` hovoria "
                         f"o inom okamihu ({uzol['updated_at']} vs "
                         f"{uzol['updated_ts']}). Sú to dva zápisy JEDNÉHO "
                         f"času, nie dve merania.")
    if not any(m.get("updated_ts") is not None
               for m in (uzol.get("maps") or {}).values()):
        chyby.append(f"{CATALOG_PY}: ani jeden balík v položke nemá "
                     f"`updated_ts` – pri balíku z inej pipeline je to jediné, "
                     f"čo povie, ako je starý.")

    # ---- odkaz, za ktorým na Drive už súbor nie je ----
    # KAŽDÉ nahratie vyrobí NOVÉ id (`folder.upload_clobber` nahrá a starý
    # súbor zmaže), takže odkaz v katalógu platí do ďalšieho behu tej mapy.
    # Keď sa zápis nedostane do vetvy (rebase konflikt, spadnutý push – oboje
    # `catalog.sh` len ohlási), ostane v `maps.json` id z behu, ktorý ten
    # súbor práve zmazal. Preto sa položka pred zápisom porovnáva so
    # skutočným priečinkom (`zive`) – a preto sa to skúša naostro: staticky
    # sa nedá prečítať, či sa mŕtvy odkaz naozaj vyhodí a živý naozaj nechá.
    def _odkaz(fid):
        return {"file": f"{fid}.zip", "size": 1,
                "link": f"https://drive.google.com/file/d/{fid}/view",
                "download": f"https://drive.google.com/uc?export=download&id={fid}",
                "formats": {"zip": {
                    "file": f"{fid}.zip", "size": 1,
                    "link": f"https://drive.google.com/file/d/{fid}/view",
                    "download": f"https://drive.google.com/uc?export=download&id={fid}"}}}

    def _polozka_s(mapy, path):
        with open(path, "w") as f:
            json.dump({"slovensko": {"name": "Slovensko", "regions": {
                "bratislavsky": {"name": "Bratislavský kraj",
                                 "maps": mapy}}}}, f)

    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with contextlib.redirect_stdout(io.StringIO()):
            # Job s `.aar` položku NEPREPISUJE, ale dopĺňa (`merge`). Kým to
            # vedel vyhodiť len prepis, prebral si balíky z katalógu aj so
            # zrušeným `search` – a odkaz na súbor, ktorý ten istý beh z Drive
            # zmazal, v `maps.json` ožil.
            _polozka_s({"mapa": _odkaz("ziva"),
                        "search": _odkaz("zmazana")}, path)
            mod.zapis_katalog(path, parts, regions,
                              [("", "bratislavsky.aar", 1, "aar1", "aar")],
                              man, merge=True, spravuje=["mapa"],
                              zrusene=tuple(ZRUSENE), zive={"ziva": "x"})
            po_aar = maps_v(path)

            # Balík cudzej pipeline, ktorého súbor na Drive NIE JE, vypadne –
            # a ten, ktorý tam je, ostane. Bez tohto rozlíšenia by overovanie
            # buď nemazalo nič, alebo by zmazalo aj to, čo platí.
            _polozka_s({"mapa": _odkaz("ziva"),
                        "wikipedia": _odkaz("zmazana")}, path)
            mod.zapis_katalog(path, parts, regions, [], man,
                              merge=True, spravuje=["mapa"],
                              zrusene=tuple(ZRUSENE), zive={"ziva": "x"})
            po_overeni = maps_v(path)

            # A keď sa priečinok vypísať nedá, nesiaha sa na nič: „neviem" a
            # „nie je tam" sú dve rôzne odpovede a tá druhá by z katalógu
            # vymazala hotovú mapu.
            _polozka_s({"mapa": _odkaz("ziva"),
                        "wikipedia": _odkaz("ktovie")}, path)
            mod.zapis_katalog(path, parts, regions, [], man,
                              merge=True, spravuje=["mapa"],
                              zrusene=tuple(ZRUSENE), zive=None)
            bez_overenia = maps_v(path)

            # MŔTVY ODKAZ NA BALÍK, KTORÝ V PRIEČINKU JE POD INÝM ID, sa
            # OPRAVÍ, nevyhodí. Je to ten častejší prípad: balík nahral build,
            # ktorému sa zápis katalógu nedostal do vetvy (25. 8. 2026 tak bolo
            # mŕtvych 14 z 24 odkazov). Vyhodiť ho znamená tvrdiť, že mapa
            # neexistuje, hoci leží na Drive pripravená na stiahnutie.
            _polozka_s({"mapa": _odkaz("stare"),
                        "wikipedia": _odkaz("zmazana")}, path)
            mod.zapis_katalog(path, parts, regions, [], man,
                              merge=True, spravuje=["mapa"],
                              zrusene=tuple(ZRUSENE),
                              zive={"nove": "stare.zip"})
            po_ozivení = maps_v(path)
    if "search" in po_aar:
        chyby.append(f"{CATALOG_PY}: job s `.aar` vrátil do položky zrušený "
                     f"balík `search` – ukazoval by na súbor, ktorý ten istý "
                     f"beh na Drive zmazal.")
    if "zip" not in (po_aar.get("mapa", {}).get("formats") or {}):
        chyby.append(f"{CATALOG_PY}: doplnenie `.aar` zahodilo ZIP základnej "
                     f"mapy – katalóg by o balíku, ktorý na Drive leží, mlčal.")
    if "wikipedia" in po_overeni:
        chyby.append(f"{CATALOG_PY}: v položke ostal odkaz na súbor, ktorý "
                     f"v priečinku mapy na Drive nie je – aplikácia by ho "
                     f"stiahla a dostala chybovú stránku Drive.")
    if "mapa" not in po_overeni:
        chyby.append(f"{CATALOG_PY}: overenie odkazov vyhodilo aj balík, "
                     f"ktorého súbor na Drive JE.")
    if "wikipedia" not in bez_overenia:
        chyby.append(f"{CATALOG_PY}: beh, ktorý sa Drive nepýtal (`zive=None`), "
                     f"vyhodil balík z katalógu – „neviem“ nesmie znamenať "
                     f"„nie je tam“.")
    ozivena = po_ozivení.get("mapa") or {}
    if "nove" not in (ozivena.get("download") or ""):
        chyby.append(f"{CATALOG_PY}: odkaz ukazoval do prázdna, ale súbor "
                     f"`stare.zip` v priečinku JE (pod novým id) – katalóg ho "
                     f"mal prepísať naň, nie balík zahodiť. Zostalo: "
                     f"{ozivena.get('download') or '(balík vypadol)'}")
    if "nove" not in ((ozivena.get("formats") or {}).get("zip", {})
                      .get("download") or ""):
        chyby.append(f"{CATALOG_PY}: oživil sa len vrch položky a nie "
                     f"`formats.zip` (alebo naopak) – tie dva odkazy sú jedna "
                     f"vec a musia ukazovať na ten istý súbor.")
    if "wikipedia" in po_ozivení:
        chyby.append(f"{CATALOG_PY}: oživovanie nechalo v katalógu balík, "
                     f"ktorého súbor v priečinku nie je pod žiadnym id.")

    # ---- ktorý súbor: `maps.json` vs `maps-test.json` ----
    stary = os.environ.get("TEST_KM2")
    try:
        os.environ["TEST_KM2"] = "0"
        ostry = mod.katalog_subor(CATALOG)
        os.environ["TEST_KM2"] = "4"
        testovy = mod.katalog_subor(CATALOG)
    finally:
        if stary is None:
            os.environ.pop("TEST_KM2", None)
        else:
            os.environ["TEST_KM2"] = stary
    if ostry != CATALOG:
        chyby.append(f"{CATALOG_PY}: ostrý beh by zapisoval do `{ostry}`, "
                     f"nie do `{CATALOG}`.")
    if testovy != CATALOG_TEST:
        chyby.append(f"{CATALOG_PY}: rýchly test by zapisoval do `{testovy}`, "
                     f"nie do `{CATALOG_TEST}` – mapa s terénom na pár km² by "
                     f"skončila medzi hotovými mapami.")
    return chyby


def _skuska_stalych_id():  # noqa: C901
    """Prepíše `upload_clobber` súbor, alebo mu vyrobí nové id?

    PREČO TO STRÁŽI PRÁVE KONTROLA KATALÓGU. Celý `maps.json` stojí na tom, že
    id balíka prežije ďalší build – odkaz v ňom je jediné, čím sa mapa dá
    stiahnuť, a zapisuje sa RAZ, pri nahratí. Kým `upload_clobber` vyrábal nový
    súbor a starý mazal, platil ten odkaz do najbližšieho buildu tej mapy a
    stačilo, aby sa commit katalógu nedostal do vetvy (25. 8. 2026: pribudol
    ruleset na `master`, štyri behy nahrali balíky, žiadny katalóg nezapísal a
    14 z 24 odkazov ukazovalo na zmazané súbory).

    Naostro, nie z AST: „vracia to to isté id" sa nedá prečítať z tvaru kódu.
    Drive sa pritom nedotýkame – nahrávanie aj mazanie sú podstrčené.
    """
    import contextlib
    import importlib.util
    import io
    import tempfile
    chyby = []
    spec = importlib.util.spec_from_file_location("_lint_folder", FOLDER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as tmp:
        balik = f"{tmp}/mapa.zip"
        with open(balik, "wb") as f:
            f.write(b"x")

        def skuska(v_priecinku):
            stopa = {"upload": 0, "update": [], "delete": []}
            mod.files_named = lambda *_a, **_k: [dict(x) for x in v_priecinku]
            mod.update = lambda _c, _p, fid, *_a, **_k: (
                stopa["update"].append(fid) or fid)
            mod.upload = lambda *_a, **_k: (
                stopa.__setitem__("upload", stopa["upload"] + 1) or "nove_id")
            mod.auth.api_delete = lambda _c, fid: stopa["delete"].append(fid)
            with contextlib.redirect_stdout(io.StringIO()):
                fid, _ = mod.upload_clobber(None, balik, "mapa.zip",
                                            "priecinok")
            return fid, stopa

        # 1. Balík toho mena v priečinku UŽ JE – prepíše sa jeho obsah a id mu
        #    ostane. To je celý zmysel tejto funkcie.
        fid, stopa = skuska([{"id": "stale_id", "createdTime": "2026-01-01T00:00:00Z"}])
        if fid != "stale_id":
            chyby.append(f"{FOLDER_PY}: `upload_clobber` vrátil id "
                         f"`{fid}` namiesto `stale_id` – odkaz v `maps.json` "
                         f"by prestal platiť pri každom builde a katalóg, "
                         f"ktorý sa nestihne commitnúť, by ukazoval do prázdna.")
        if stopa["upload"]:
            chyby.append(f"{FOLDER_PY}: `upload_clobber` vyrobil NOVÝ súbor, "
                         f"hoci ten istý v priečinku už je.")
        if stopa["delete"]:
            chyby.append(f"{FOLDER_PY}: `upload_clobber` zmazal "
                         f"{stopa['delete']} – jediný súbor toho mena je ten, "
                         f"na ktorý ukazuje katalóg.")

        # 2. Dva súbory jedného mena (dva behy naraz): prepíše sa NAJSTARŠÍ –
        #    ten, na ktorý katalóg ukazuje – a duplikát ide preč.
        fid, stopa = skuska([
            {"id": "novsi", "createdTime": "2026-02-02T00:00:00Z"},
            {"id": "starsi", "createdTime": "2026-01-01T00:00:00Z"}])
        if fid != "starsi":
            chyby.append(f"{FOLDER_PY}: pri dvoch súboroch toho mena sa "
                         f"prepísal `{fid}`, nie najstarší `starsi` – ten "
                         f"druhý je ten, ktorý katalóg ponúka na stiahnutie.")
        if stopa["delete"] != ["novsi"]:
            chyby.append(f"{FOLDER_PY}: duplikát sa nezmazal "
                         f"({stopa['delete']}) – v priečinku by vedľa mapy "
                         f"ležala druhá s tým istým menom.")

        # 3. Prvý build tej mapy – v priečinku nie je nič, súbor sa vyrobí.
        fid, stopa = skuska([])
        if stopa["upload"] != 1 or fid != "nove_id":
            chyby.append(f"{FOLDER_PY}: prvý balík sa nenahral "
                         f"(upload={stopa['upload']}, id={fid}).")
    return chyby


try:
    bad += _skuska_stalych_id()
except Exception as exc:                      # noqa: BLE001 – čokoľvek je chyba
    bad.append(f"{FOLDER_PY} sa nedá skúšobne spustiť ({exc!r}).")

try:
    bad += _skuska_katalogu()
except SystemExit as exc:
    bad.append(f"{CATALOG_PY}: zápis katalógu spadol ({exc}) – skúška je "
               f"volanie, aké robí `publish-map.py`.")
except Exception as exc:                      # noqa: BLE001 – čokoľvek je chyba
    bad.append(f"{CATALOG_PY} sa nedá skúšobne spustiť ({exc!r}).")

for b in bad:
    print(f"::error::{b}")
print(f"katalóg máp: {len(bad)} chýb")
sys.exit(1 if bad else 0)
