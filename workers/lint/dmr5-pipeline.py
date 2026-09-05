#!/usr/bin/env python3
"""Kontrola: DMR 5.0 sa dopĺňa vlastnou pipeline a cesta k nemu ostáva celá.

`update-dem.yml` model stiahnuť nevie (145 GB proti ~60 GB na runneri). Kým
tam preň bol rozcestník končiaci úspechom, doplnenie bolo tiché nič a build
spadol o desať jobov neskôr. Staticky sa overuje, že `dem-layers.yml` má oba
joby, volajú `dmr5-drive.yml`, dostávajú bbox aj meno assetu z `check-dem`,
a že `update-dem.yml` na `dmr5` padá.
"""
import re, sys, yaml
bad = 0

# 1. update-dem.yml musí na `dmr5` skončiť chybou
txt = open(".github/workflows/update-dem.yml").read()
m = re.search(r"^\s*dmr5\)(.*?);;", txt, re.S | re.M)
if not m or "::error::" not in m.group(1) or "exit 1" not in m.group(1):
    print("::error file=.github/workflows/update-dem.yml::vetva `dmr5` "
          "musí skončiť chybou – doplnenie, ktoré nedopĺňa, nesmie "
          "zazelenať (beh 31307163093).")
    bad += 1

# 2. dmr5-drive.yml musí byť volateľný a brať to, čo mu Build map dáva
d = yaml.safe_load(open(".github/workflows/dmr5-drive.yml"))
on = d[[k for k in d if k is True or k == "on"][0]]
call = (on.get("workflow_call") or {}).get("inputs") or {}
# doplnenie volajú joby vrstiev z výškového modelu – vo vlastnom workflowe,
# lebo ich potrebuje aj pregenerovanie jednej vrstvy
VRSTVY = ".github/workflows/dem-layers.yml"
bm = yaml.safe_load(open(VRSTVY))
for name, job in (bm.get("jobs") or {}).items():
    if job.get("uses") != "./.github/workflows/dmr5-drive.yml":
        continue
    for key in (job.get("with") or {}):
        if key not in call:
            print(f"::error file={VRSTVY}::job "
                  f"'{name}' podáva `{key}`, ktoré dmr5-drive.yml "
                  f"v `workflow_call` nemá")
            bad += 1
if not any(j.get("uses") == "./.github/workflows/dmr5-drive.yml"
           for j in (bm.get("jobs") or {}).values()):
    print(f"::error file={VRSTVY}::DMR 5.0 nemá "
          f"kto doplniť – žiadny job nevolá dmr5-drive.yml")
    bad += 1

# 3. výrez sa dopĺňa bboxom, nie kľúčom pohoria: kľúč je meno obdĺžnika
# z areas.json, čo sa má naozaj prečítať vie len Build map. Kým sem chodil
# kľúč, čítal sa z Drive celý obdĺžnik – test na pár km² tak čítal 541 km².
for name, job in (bm.get("jobs") or {}).items():
    with_ = job.get("with") or {}
    if job.get("uses") != "./.github/workflows/dmr5-drive.yml":
        continue
    if str(with_.get("tiles", "")).lower() == "true":
        continue   # dlaždice sa zadávajú stupňami, meno je z nich
    area, asset = str(with_.get("area", "")), str(with_.get("asset", ""))
    if "mirror_dmr5_area" not in area:
        print(f"::error file={VRSTVY}::job "
              f"'{name}' podáva do dmr5-drive.yml `area: {area}` – "
              f"výrez sa musí brať z `check-dem.outputs."
              f"mirror_dmr5_area` (bbox toho, čo si beh vypýtal), "
              f"inak sa z Drive číta celý obdĺžnik z areas.json.")
        bad += 1
    if "mirror_dmr5_asset" not in asset:
        print(f"::error file={VRSTVY}::job "
              f"'{name}' nepodáva `asset` z `check-dem.outputs."
              f"mirror_dmr5_asset`. Pri bboxe v `area` je povinný – "
              f"meno sa z bboxu odvodiť nedá a build si súbor hľadá "
              f"podľa kľúča výrezu.")
        bad += 1

# a druhá strana: kontrola to meno musí vedieť povedať
chk = open("workers/dem/check.sh").read()
for out in ("mirror_dmr5_area", "mirror_dmr5_asset"):
    if f"{out}=" not in chk:
        print(f"::error file=workers/dem/check.sh::chýba výstup "
              f"`{out}`, ktorý {VRSTVY} podáva do dmr5-drive.yml")
        bad += 1

# 4. dlaždica je sľub o celom stupni: prevod do WGS84 okno vydúva, takže sa
# doň zmestili aj tri cudzie stupne po pár set metroch – uložili sa pod menami
# celých stupňov a mozaika prešla ako hotová
cut = open("workers/drive/dmr5-cut.py").read()
m = re.search(r"def country_tiles\((.*?)\):(.*?)(?=\ndef |\Z)", cut, re.S)
if not m or "window" not in m.group(1):
    print("::error file=workers/drive/dmr5-cut.py::`country_tiles` musí brať "
          "okno (`window`) – bez neho sa pod meno celého stupňa uloží presah "
          "prevodu do WGS84 (behy 31476448895 → 31484544154).")
    bad += 1
elif "--window" not in m.group(2):
    print("::error file=workers/drive/dmr5-cut.py::`country_tiles` okno "
          "nepodáva do `workers/dem/tiles.py` (`--window=`), takže sa rez "
          "znova riadi rozsahom rastra a dlaždica bude klamať o rozsahu.")
    bad += 1
dm = open("workers/drive/dmr5.py").read()
if not re.search(r"country_tiles\([^)]*window\s*=", dm, re.S):
    print("::error file=workers/drive/dmr5.py::fáza `finish` musí podať do "
          "`country_tiles` okno z plánu (`window=state[\"bbox\"]`) – to je to "
          "územie, ktoré sa naozaj prečítalo.")
    bad += 1
tl = open("workers/dem/tiles.py").read()
if "--window" not in tl:
    print("::error file=workers/dem/tiles.py::chýba voľba `--window`, ktorou "
          "volajúci hovorí, ktoré stupne prečítal celé. Bez nej sa do skladu "
          "dostanú dlaždice s pár set metrami dát pod menom celého stupňa.")
    bad += 1

# 5. chýbajúca dlaždica sa musí doplniť: „keď nie je ani jedna" prepustilo
# mozaiku so 48 % kraja
if "coverage.py" not in open("workers/dem/fetch.sh").read():
    print("::error file=workers/dem/fetch.sh::sťahovanie dlaždíc nemeria, či "
          "mozaika územie naozaj pokrýva (`workers/dem/coverage.py`) – počet "
          "súborov na to neodpovedá.")
    bad += 1
if not re.search(r"\$src\" = 'dmr5'.{0,200}?chybaju.{0,80}?need=true", chk, re.S):
    print("::error file=workers/dem/check.sh::pri `dmr5` sa musí doplniť KAŽDÁ "
          "chýbajúca dlaždica (`[ -n \"$chybaju\" ] && need=true`). Doplnenie "
          "číta presne tie stupne, ktoré mu podáme, a prázdny stupeň sa uloží "
          "prázdny – chýbajúce meno teda znamená „nikdy sme to nečítali\".")
    bad += 1
print(f"cesta k DMR 5.0: {bad} chýb")
sys.exit(1 if bad else 0)
