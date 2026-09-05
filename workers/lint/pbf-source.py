#!/usr/bin/env python3
"""Kraj sa reže z rodičovského extraktu – hotový export kraja sa nesmie vrátiť.

Hotový `{kraj}-latest.osm.pbf` nie je referenčne úplný: plocha pokračujúca do
susedného kraja v ňom nemá všetkých členov a Planetiler ju zahodí celú.
Namerané na Bratislavskom kraji: 250 z 3075 plošných relácií, medzi nimi tri
CHKO. Po reze z rodiča ostane päť, všetky na hranici so zahraničím.

  1. každý región s `osmfr` má `dir` aj neprázdne `slugs`;
  2. každý kraj má `osmfr.parent` na región, ktorý má vlastný `osmfr`;
  3. `plan/pbf.sh` reže rodiča `osmium extract -s smart --polygon`;
  4. a má pri tom `-S types=multipolygon,boundary` – `smart` inak dopĺňa
     členov len `type=multipolygon`, kým CHKO je `type=boundary`;
  5. rez sa nesmie ticho preskočiť, keď chýba hranica.

Rozpis s číslami je v hlavičke `workers/plan/pbf.sh`.
"""
import json
import re
import sys

REGIONS = "workers/data/regions.json"
PBF = "workers/plan/pbf.sh"

bad = []

# ---- 1. a 2. číselník regiónov ----
with open(REGIONS, encoding="utf-8") as f:
    regions = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

for key, reg in regions.items():
    osmfr = reg.get("osmfr") or {}
    if not osmfr:
        continue
    if not osmfr.get("dir") or not osmfr.get("slugs"):
        bad.append(
            f"Región `{key}` má `osmfr`, ale nie `dir` a neprázdne `slugs`. "
            f"URL sa skladá ako `<base>/<dir>/<slug>.osm.pbf`, takže bez nich "
            f"sa PBF nemá odkiaľ stiahnuť.")

    parent = osmfr.get("parent")
    if (reg.get("admin_level") or 0) > 2 and not parent:
        bad.append(
            f"Región `{key}` je kraj, ale nemá `osmfr.parent`. Kraj sa reže "
            f"z rodičovského extraktu – hotový `{key}-latest.osm.pbf` z osm.fr "
            f"nie je referenčne úplný a plochy presahujúce do susedného kraja "
            f"(CHKO, veľké lesy) by z mapy ticho zmizli celé.")
    if parent and parent not in regions:
        bad.append(
            f"Región `{key}` má `osmfr.parent` = `{parent}`, ale taký región "
            f"v {REGIONS} nie je. Rodič je KĽÚČ regiónu, nie URL.")
    elif parent and not (regions[parent].get("osmfr") or {}).get("dir"):
        bad.append(
            f"Rodič `{parent}` regiónu `{key}` nemá `osmfr.dir` – nedá sa "
            f"z neho zložiť adresa, z ktorej sa má rezať.")
    if parent == key:
        bad.append(f"Región `{key}` je rodičom sám sebe.")

# ---- 3. až 5. čím to reže ----
with open(PBF, encoding="utf-8") as f:
    text = f.read()
kod = "\n".join(r for r in text.splitlines() if not r.lstrip().startswith("#"))

rezy = re.findall(r"osmium extract((?:[^\n]*\\\n)*[^\n]*)", kod)
rez_rodica = [v for v in rezy if "--polygon" in v]

if not rez_rodica:
    bad.append(
        f"{PBF} nereže kraj z rodičovského extraktu (`osmium extract "
        f"--polygon`). Hotový export kraja z osm.fr sa použiť nesmie: nemá "
        f"členov plôch, čo presahujú do susedného kraja, a Planetiler ich "
        f"zahodí CELÉ – z mapy zmizne CHKO aj s tou časťou, čo v kraji leží.")

# `-S types=` musí byť pri KAŽDOM reze, nie len pri tom z rodiča: orez na
# `crop_bbox` aj na štvorec rýchleho testu majú ten istý problém, len sa
# prejaví ešte skôr – zo 4 km² vytŕča skoro každá plocha.
for volanie in rezy:
    if "-s smart" not in volanie:
        bad.append(
            f"{PBF}: `osmium extract` bez `-s smart`. Bez neho sa členovia "
            f"relácií nedopĺňajú a rez nespraví nič navyše oproti hotovému "
            f"exportu.")
    if "types=multipolygon,boundary" not in volanie:
        bad.append(
            f"{PBF}: `osmium extract -s smart` bez `-S types=multipolygon,boundary`. "
            f"Predvolene `smart` dopĺňa členov len reláciám "
            f"`type=multipolygon`, kým CHKO je `type=boundary` – bez toho "
            f"prepínača ostanú CHKO Malé Karpaty, Záhorie aj Dunajské luhy "
            f"rozbité a v mape ich nebude. Nespadne po tom nič.")

if not re.search(r'\$OSMFR_BASE/\$PDIR/\$SLUG\.osm\.pbf', kod):
    bad.append(
        f"{PBF} neskladá URL rodiča ako `$OSMFR_BASE/$PDIR/$SLUG.osm.pbf` – "
        f"adresa sa má brať z `osmfr.dir` a `osmfr.slugs` toho regiónu, na "
        f"ktorý ukazuje `osmfr.parent` v {REGIONS}.")

# 5. chýbajúca hranica musí byť PÁD, nie návrat k priamemu sťahovaniu
if not re.search(r'if \[ ! -s "\$POLY" \]; then\n[^\n]*::error::', kod):
    bad.append(
        f"{PBF} nepadne, keď chýba `.poly` regiónu. Presne tam sa predošlá "
        f"verzia vrátila k priamemu sťahovaniu kraja – beh bol zelený a v mape "
        f"zase chýbali CHKO (pravidlo 8). Chýbajúca hranica musí byť "
        f"`::error::` a `exit 1`.")

for b in bad:
    print(f"::error::{b}")
print(f"Kraj sa reže z rodičovského extraktu: {len(bad)} chýb")
sys.exit(1 if bad else 0)
