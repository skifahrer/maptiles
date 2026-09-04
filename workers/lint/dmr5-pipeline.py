#!/usr/bin/env python3
"""
Kontrola: DMR 5.0 sa dopĺňa vlastnou pipeline, a cesta k nemu ostáva celá.

PREČO. `update-dem.yml` DMR 5.0 stiahnuť nevie – model má 145 GB a runner má
voľných ~60 GB. Kým tam preň bol rozcestník, ktorý vypísal „choď inam" a skončil
ÚSPECHOM, doplnenie bolo tiché nič: `check-dem` poslal „dmr5 treba doplniť",
nedoplnilo sa, job zazelenal a build spadol o desať jobov neskôr na tom, že
v sklade nie je ani jedna dlaždica (beh 31307163093). Doplnenie, ktoré nedopĺňa,
musí byť červené hneď.

Preto sa staticky overuje, že tá cesta ostane celá: `dem-layers.yml` (vrstvy
z výškového modelu – volá ho build mapy aj pregenerovanie jednej vrstvy) má oba
joby (`mirror-dmr5-area`, `mirror-dmr5-tiles`), volajú `dmr5-drive.yml`,
dostávajú bbox aj meno assetu z `check-dem`, a `update-dem.yml` na `dmr5` padá.

Použitie:
    python3 workers/lint/dmr5-pipeline.py
"""
import re, sys, yaml
bad = 0

# 1. update-dem.yml musí na `dmr5` skončiť chybou, nie úspechom.
txt = open(".github/workflows/update-dem.yml").read()
m = re.search(r"^\s*dmr5\)(.*?);;", txt, re.S | re.M)
if not m or "::error::" not in m.group(1) or "exit 1" not in m.group(1):
    print("::error file=.github/workflows/update-dem.yml::vetva `dmr5` "
          "musí skončiť chybou – doplnenie, ktoré nedopĺňa, nesmie "
          "zazelenať (beh 31307163093).")
    bad += 1

# 2. dmr5-drive.yml musí byť volateľný a brať to, čo mu Build map dáva.
d = yaml.safe_load(open(".github/workflows/dmr5-drive.yml"))
on = d[[k for k in d if k is True or k == "on"][0]]
call = (on.get("workflow_call") or {}).get("inputs") or {}
# Doplnenie DMR 5.0 volajú JOBY VRSTIEV Z VÝŠKOVÉHO MODELU, a tie sa
# z `build-map-region.yml` presťahovali do vlastného workflowu – potrebuje ich
# aj pregenerovanie jednej vrstvy, a druhá kópia by bola druhá pravda o tom,
# ktorý model sa doplní, keď v sklade nie je.
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

# 3. VÝREZ SA DOPĹŇA BBOXOM, NIE KĽÚČOM POHORIA. Kľúč je meno
# obdĺžnika z `areas.json`; čo sa má naozaj prečítať, vie len Build
# map (výrez pretnutý s regiónom, pri rýchlom teste štvorec na pár
# km²). Kým sem chodil kľúč, `dmr5-drive.yml` si ho vyriešil
# druhýkrát a čítal z Drive celý obdĺžnik – test na pár km² tak čítal
# 541 km² Vysokých Tatier. Je to tá istá chyba ako beh 31307163093,
# len nezhodila beh, iba ho predražila – a preto sa vráti ticho.
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

# A druhá strana toho istého: kontrola to meno musí vedieť povedať.
chk = open("workers/dem/check.sh").read()
for out in ("mirror_dmr5_area", "mirror_dmr5_asset"):
    if f"{out}=" not in chk:
        print(f"::error file=workers/dem/check.sh::chýba výstup "
              f"`{out}`, ktorý {VRSTVY} podáva do dmr5-drive.yml")
        bad += 1

# 4. DLAŽDICA JE SĽUB O CELOM STUPNI. Krájanie preto musí dostať OKNO, ktoré
# sa naozaj prečítalo – prevod do WGS84 ho vydúva (`21,49…22,50` vyšlo ako
# `21.000,48.996 … 22.013,49.628`), takže sa doň zmestili aj tri cudzie stupne
# po pár set metroch. Uložili sa pod menami celých stupňov, kontrola ich
# spočítala ako platné, doplnenie sa nespustilo – a vrstevnice Prešovského kraja
# skončili v jednom štvorci, so zeleným behom (31476448895 → 31484544154).
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

# 5. A CHÝBAJÚCA DLAŽDICA DMR 5.0 SA MUSÍ DOPLNIŤ, nie prehliadnuť. Kým
# kontrola dopĺňala len vtedy, „keď nie je ani jedna", stačilo, aby v sklade
# ležali tri nepoctivé – a mozaika so 48 % kraja prešla ako hotová.
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
