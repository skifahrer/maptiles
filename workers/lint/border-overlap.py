#!/usr/bin/env python3
"""
Hranica regiónu: presná z OSM, bez presahu – a uložené vrstvy to musia niesť.

PREČO. Mapa kraja sa dlho orezávala `.poly`-gónom z osm.fr, ktorý je okolo
hranice ROZŠÍRENÝ (susedné kraje sa v ňom prekrývajú o 2 – 4 km), a nad tým sa
polygón ešte nafukoval o `BORDER_BUFFER_M` (2 500 m). Mapa, vrstevnice, skaly
aj tieňovanie tak siahali kilometre do susedného kraja a za štátnu hranicu.
Teraz sa hranica číta PRESNE z OSM relácie (`workers/plan/boundary.py`)
a `BORDER_BUFFER_M` je 0.

Obe polovice tej zmeny sa dajú stratiť potichu, tak ich stráži táto kontrola:

  1. `BORDER_BUFFER_M` je stále na JEDNOM mieste (`workers/plan/area.py`) –
     dve čísla by znamenali okno DEM nafúknuté inak než polygón.
  2. Meno uloženej vrstvy (tieňovanie, skaly) to číslo NESIE. Hotové vrstvy sa
     odkladajú na Drive a nabudúce sa len stiahnu – a meno v sklade to číslo
     dlho nenieslo. Beh potom vrátil vrstvu orezanú ešte podľa STAREJ hranice,
     tvrdil, že je hotová, a nikde nezaznelo nič. Namerané na balíku
     Trnavského kraja z 3. 9. 2026 (build 33738121698): `trnavsky.pmtiles` aj
     `region.geojson` v ňom už mali nafúknutý rozsah (16,8812 … 48,9226), kým
     `trnavsky-terrain.pmtiles` z toho istého balíka ešte tesný bbox kraja
     (16,915 … 48,9) – mapa pokračovala za hranicu, reliéf pod ňou nie. To je
     pravidlo 8 v čistej podobe.
  3. `workers/plan/pbf.sh` si hranicu naozaj pýta Z PBF (`--from-pbf`). Bez
     toho prepínača spadne `region-poly.py` na náhradný `.poly` z osm.fr –
     mapa vznikne, bude o 2 – 4 km väčšia než kraj a nikto to nezistí.
  4. `boundary.py` vie hranicu prečítať aj PRETNÚŤ so štátom. Prienik je to
     jediné, čo drží mapu kraja vnútri republiky aj vtedy, keď je relácia
     kraja v OSM pokazená.
  5. Šev so susedmi sa naďalej MERIA a meria sa OBOJE – medzera aj prekryv.
     Kým sa merala len medzera, prekryv 2 – 4 km vychádzal ako „šev zavretý ✓".

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
POLY = "workers/plan/region-poly.py"
HRANICA = "workers/plan/boundary.py"
PBF = "workers/plan/pbf.sh"
SEV = "workers/plan/seam.py"

bad = []


def cti(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------- 1. jedno miesto pre `BORDER_BUFFER_M` ----------
text = cti(ZDROJ)
if not re.search(r"^BORDER_BUFFER_M\s*=\s*\d+", text, re.M):
    print(f"::error file={ZDROJ}::`BORDER_BUFFER_M` tu nie je – presah za "
          f"hranicu regiónu má byť definovaný na JEDNOM mieste a všetci ho "
          f"majú brať odtiaľto. Keď sa presunul, uprav aj túto kontrolu.")
    sys.exit(1)

# ---------- 2. meno uloženej vrstvy to číslo nesie ----------
for path, premenna in SUBORY.items():
    text = cti(path)
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
            f"nenesie presah za hranicu kraja "
            f"(`BORDER_BUFFER_M` z {ZDROJ} ako `-o…`). Bez neho sklad po "
            f"zmene presahu vráti vrstvu orezanú po starom, beh ju vydá za "
            f"hotovú a v mape ostane pás, kde je mapa a pod ňou nie je nič.")
    else:
        print(f"{path}: `{premenna}` nesie presah za hranicu ✓")

# ---------- 3. hranica sa naozaj číta z PBF ----------
pbf = cti(PBF)
kod = "\n".join(r for r in pbf.splitlines() if not r.lstrip().startswith("#"))
if "region-poly.py" not in kod or "--from-pbf=" not in kod:
    bad.append(
        f"::error file={PBF}::Hranica regiónu sa nepýta z PBF "
        f"(`region-poly.py --from-pbf=…`). Bez toho sa spadne na náhradný "
        f"`.poly` z osm.fr, ktorý je okolo hranice rozšírený – mapa vznikne, "
        f"bude o 2 – 4 km väčšia než kraj a nikto to nezistí (pravidlo 8).")
else:
    print(f"{PBF}: hranica sa číta z PBF (`--from-pbf`) ✓")

# ---------- 4. `boundary.py` vie čítať aj pretínať ----------
hranica = cti(HRANICA)
for meno, preco in (
        ("def hranice_z_pbf",
         "z PBF sa nemá ako prečítať relácia hranice"),
        ("ST_Intersection",
         "kraj sa nepretne so štátom, takže pokazená relácia kraja pretiahne "
         "mapu za štátnu hranicu")):
    if meno not in hranica:
        bad.append(f"::error file={HRANICA}::`{meno}` tu nie je – {preco}.")
if "ST_Buffer" in cti(POLY):
    bad.append(
        f"::error file={POLY}::Polygón kraja sa zase NAFUKUJE (`ST_Buffer`). "
        f"Presah za hranicu bol náhrada za nepresný `.poly` z osm.fr; odkedy "
        f"je hranica presná z OSM, robí už len mapu a vrstvy z výškového "
        f"modelu kilometre vnútri susedného kraja a za štátnou hranicou.")

# ---------- 5. šev sa meria, a meria sa oboje ----------
poly = cti(POLY)
if "seam" not in poly or "zmeraj_sev" not in poly:
    bad.append(
        f"::error file={POLY}::Šev so susedmi sa už nemeria "
        f"(`seam.zmeraj_sev`). Je to jediné, čo o dvoch susedných mapách "
        f"povie, či na seba nadväzujú – bez merania sa o medzere medzi nimi "
        f"nedozvie nikto, kým ju niekto neuvidí v teréne.")
else:
    print(f"{POLY}: šev so susedmi sa meria ✓")

sev = cti(SEV)
if '"prekryv_m"' not in sev or '"medzera_m"' not in sev:
    bad.append(
        f"::error file={SEV}::Meranie švu nedáva obe čísla (`medzera_m` "
        f"a `prekryv_m`). Kým sa merala len medzera, vychádzal prekryv "
        f"2 – 4 km do susedného kraja ako „šev zavretý“ – a práve kvôli "
        f"nemu sa hranica menila.")
else:
    print(f"{SEV}: meria sa medzera aj prekryv ✓")

for m in bad:
    print(m)
sys.exit(1 if bad else 0)
