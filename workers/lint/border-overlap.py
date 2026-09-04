#!/usr/bin/env python3
"""
Kontrola: uložená vrstva z DEM nesmie prežiť zmenu prekryvu so susedom.

PREČO. `workers/plan/region-poly.py` nafúkne polygón kraja o
`BORDER_BUFFER_M` (workers/plan/area.py) VON, aby na mapu jedného kraja
nadviazala mapa toho vedľajšieho. Tým istým číslom sa nafukuje aj okno pre
vrstvy z výškového modelu (`dem_bbox`), takže to číslo mení OBSAH aj ROZSAH
tieňovania a skál.

Lenže hotové tieňovanie aj hotové skaly sa odkladajú na Drive a nabudúce sa
len stiahnu – a meno v sklade to číslo dlho nenieslo. Beh potom vrátil vrstvu
orezanú ešte podľa PÔVODNEJ, tesnej hranice, tvrdil, že je hotová, a nikde
nezaznelo nič. Namerané na balíku Trnavského kraja z 3. 9. 2026 (build
33738121698): `trnavsky.pmtiles` aj `region.geojson` v ňom už mali nafúknutý
rozsah (16,8812 … 48,9226), kým `trnavsky-terrain.pmtiles` z toho istého
balíka ešte tesný bbox kraja (16,915 … 48,9) – mapa pokračovala za hranicu,
reliéf pod ňou nie. To je pravidlo 8 v čistej podobe: meno assetu musí
hovoriť, čo v súbore naozaj je.

Táto kontrola to povie pri pushi. Nepozerá sa na hodnotu čísla – len na to,
že sa meno assetu o `BORDER_BUFFER_M` opiera.

Spustiť sa dá aj lokálne:
    python3 workers/lint/border-overlap.py
"""
import re
import sys

# Súbor → premenná, v ktorej sa skladá meno assetu v sklade.
SUBORY = {
    "workers/terrain/build.sh": "asset_name",
    # `rocks.sh` je DRUHÁ POLOVICA `contours-rocks/build.sh` (ten prerástol
    # 800 riadkov, tak sa rozdelil a číta sa cez `.`) – meno assetu so skalami
    # sa skladá tam, takže sa tam aj kontroluje.
    "workers/contours-rocks/rocks.sh": "ROCK_ASSET",
}
ZDROJ = "workers/plan/area.py"

bad = []

text = open(ZDROJ, encoding="utf-8").read()
if not re.search(r"^BORDER_BUFFER_M\s*=\s*\d+", text, re.M):
    print(f"::error file={ZDROJ}::`BORDER_BUFFER_M` tu nie je – prekryv so "
          f"susedným krajom má byť definovaný na JEDNOM mieste a všetci ho "
          f"majú brať odtiaľto. Keď sa presunul, uprav aj túto kontrolu.")
    sys.exit(1)

for path, premenna in SUBORY.items():
    text = open(path, encoding="utf-8").read()
    # Meno assetu sa skladá z premennej, ktorá vznikla z `BORDER_BUFFER_M`
    # (`area.py` sa `import`-ne jednoriadkovým `python3 -c`). Kontroluje sa
    # oboje: že si to číslo súbor pýta a že sa naozaj dostalo do mena.
    # Riadky, kde sa meno skladá: `ROCK_ASSET="…"` aj `asset_name() { … }`
    # (funkcia, teda bez `=`), plus `sed`, ktorý sklad prehľadáva.
    riadky = [r for r in text.splitlines()
              if premenna in r and not r.lstrip().startswith("#")]
    meno = "\n".join(riadky)
    pyta = "BORDER_BUFFER_M" in text
    v_mene = re.search(r"-o\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", meno) is not None
    if not pyta or not v_mene:
        bad.append(
            f"::error file={path}::Meno uloženej vrstvy (`{premenna}`) "
            f"nenesie prekryv so susedným krajom "
            f"(`BORDER_BUFFER_M` z {ZDROJ} ako `-o…`). Bez neho sklad po "
            f"zmene prekryvu vráti vrstvu orezanú po starom, beh ju vydá za "
            f"hotovú a v mape ostane pás, kde je mapa a pod ňou nie je nič.")
    else:
        print(f"{path}: `{premenna}` nesie prekryv ✓")

# A samotné meranie švu: keď sa prestane volať, prestane byť vidieť, či na
# mapu kraja tá susedná vôbec nadväzuje.
POLY = "workers/plan/region-poly.py"
text = open(POLY, encoding="utf-8").read()
if "seam" not in text or "zmeraj_sev" not in text:
    bad.append(
        f"::error file={POLY}::Šev so susedmi sa už nemeria "
        f"(`seam.zmeraj_sev`). Prekryv na hranici je jediné, čo drží mapy "
        f"dvoch susedných krajov pokope – bez merania sa o medzere medzi "
        f"nimi nedozvie nikto, kým ju niekto neuvidí v teréne.")
else:
    print(f"{POLY}: šev so susedmi sa meria ✓")

for m in bad:
    print(m)
sys.exit(1 if bad else 0)
