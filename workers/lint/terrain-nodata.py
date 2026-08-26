#!/usr/bin/env python3
"""
Tam, kde výškový model nemá dáta, sa NESMIE vyrobiť hladina mora.

PREČO TO EXISTUJE. Terrarium je RGB a nemá podobu „hodnota tu nie je" – do
dlaždice sa teda niečo zapísať musí. `warp_level` na to dlho dával
`-dstnodata 0`, čiže „model tu nemáme" = „nula metrov nad morom". Dve veci,
ktoré z toho vyšli, a ani jedna nespadla:

  * NA HRANICI DÁT VZNIKLA STENA. Hillshade je derivácia výšky, takže pokles
    zo 600 m na 0 m medzi dvoma pixelmi je pre neho zvislý útes a nakreslí ho
    ako ostrú svetlo-tmavú čiaru cez mapu – „divný orez" na mieste, kde
    o žiadnu hranicu nejde. Namerané na publikovanom
    `bratislavsky_test4-terrain.pmtiles`: najväčší skok 668 m na 407 m/px
    (z8), teda sklon 59°; na z9 69°.
  * ZA ŇOU BOLA ROVINA, čiže plocha BEZ tieňovania. Na z5 malo 99,6 % dlaždice
    presne 0 m, na z9 43 %, na z10 35 %.

A k tomu tretia vec, ktorá je z toho istého koreňa: keď je nodata zapísaná ako
platná výška, dlaždice vzniknú aj tam, kde model nie je nič – a `pack.py` sa
tými dlaždicami vykázal ako rozsahom. Hlavička hovorila 11,25 / 40,98 / 22,50 /
48,92, kým mapa je 0,027° × 0,018°, teda rozsah 182-tisíckrát väčší než územie,
ktoré popisuje. Rozsah je pritom sľub (pravidlo 2), rovnako ako meno assetu.

ČO SA KONTROLUJE:

  1. `terrain/vyska.py` má `NODATA` mimo rozsahu skutočných výšok a
     `warp_level` v `terrain/tiles.py` ho dáva `gdalwarpu` – nie nulu ani inú
     platnú výšku,
  2. warpnutá mriežka ide cez `vypln_nodata` (bez toho by sentinel skončil
     rovno v dlaždici, čo je stena stokrát vyššia než tá pôvodná),
  3. dlaždica bez jediného platného pixela sa nezapíše,
  4. `terrain/pack.py` vie `--clip-bbox` a `terrain/build.sh` mu ho DÁVA –
     inak sa hlavička vykáže zjednotením celých dlaždíc a tá na z5 má 11,25°.

Spustiť sa dá aj lokálne (je to statická kontrola, bez GDALu a bez dát):
    python3 workers/lint/terrain-nodata.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
TILES = os.path.join(_WORKERS, "terrain", "tiles.py")
# Sentinel a obe výplne bývajú vo `vyska.py` vedľa – `tiles.py` je plán, warp
# a kódovanie. Kontrola sa preto pozerá do oboch: konštanta a výplň sú tam,
# `-dstnodata` a zahodenie prázdnej dlaždice tu.
VYSKA = os.path.join(_WORKERS, "terrain", "vyska.py")
PACK = os.path.join(_WORKERS, "terrain", "pack.py")
BUILD = os.path.join(_WORKERS, "terrain", "build.sh")


def kod(path):
    """Súbor bez celých zakomentovaných riadkov – kontrola je textová a
    komentár, ktorý JU SAMU popisuje, by ju inak uspokojil."""
    with open(path, encoding="utf-8") as f:
        return "\n".join(r for r in f.read().splitlines()
                         if not r.lstrip().startswith("#"))


bad = []
tiles, vyska, pack, build = kod(TILES), kod(VYSKA), kod(PACK), kod(BUILD)

# ---- 1. sentinel mimo rozsahu skutočných výšok ----
m = re.search(r"^NODATA\s*=\s*(-?[\d.]+)", vyska, re.M)
if not m:
    bad.append(
        f"{VYSKA}: chýba konštanta `NODATA`. Hodnota, ktorou sa označí "
        f"„model tu nie je“, musí byť pomenovaná na jednom mieste – warp ju "
        f"zapisuje a slučka podľa nej pozná prázdnu dlaždicu.")
else:
    v = float(m.group(1))
    # Zem má −430 m (Mŕtve more) až 8849 m. Čokoľvek v tomto rozsahu je
    # platná výška a v terrariu sa od chýbajúcej hodnoty neodlíši.
    if -430 <= v <= 8849:
        bad.append(
            f"{VYSKA}: `NODATA = {v}` je PLATNÁ nadmorská výška, takže sa "
            f"„model tu nie je“ nedá odlíšiť od nameranej hodnoty. Presne "
            f"toto robila nula: na hranici dát z nej bola stena (nameraných "
            f"668 m na 407 m/px = 59°) a za ňou rovina bez tieňovania.")

if not re.search(r'"-dstnodata",\s*str\(NODATA\)', tiles):
    bad.append(
        f"{TILES}: `gdalwarp` nedostáva `-dstnodata str(NODATA)`. Keď sa "
        f"sentinel a to, čo sa naozaj zapíše, rozídu, výplň nemá čo nájsť "
        f"a v dlaždici ostane hodnota, ktorú nikto nečakal.")

# ---- 2. a 3. warpnutá mriežka sa dopĺňa a prázdna dlaždica sa nezapíše ----
if "def vypln_nodata" not in vyska:
    bad.append(
        f"{VYSKA}: chýba `vypln_nodata` – výplň dier v modeli. Konštanta by "
        f"na ich hranici spravila stenu, tak sa dopĺňa okolím.")
if "vypln_nodata(" not in tiles:
    bad.append(
        f"{TILES}: `vypln_nodata` sa nikde nepoužíva. Bez nej ide sentinel "
        f"({m.group(1) if m else '−9999'} m) rovno do dlaždice a stena je "
        f"stokrát vyššia než tá, ktorú to malo odstrániť.")

if not (re.search(r"chyba\[[^\]]*\][^\n]*\.all\(\)", tiles)
        and "bez_modelu += 1" in tiles):
    bad.append(
        f"{TILES}: nekontroluje sa dlaždica, ktorá nemá ANI JEDEN platný "
        f"pixel. Taká sa nesmie zapísať – nie je to rovina, je to územie, "
        f"o ktorom model nič nehovorí, a zapísať doň výšku znamená tvrdiť, "
        f"že tam terén je (pravidlo 2).")

# ---- 4. hlavička sa reže na bbox behu ----
if "--clip-bbox" not in pack:
    bad.append(
        f"{PACK}: chýba `--clip-bbox`. Bez neho je rozsah v hlavičke "
        f"zjednotenie CELÝCH dlaždíc a tá na z5 má 11,25°, takže pyramída "
        f"nad jedným krajom sľubuje pol Európy.")
if "--clip-bbox" not in build:
    bad.append(
        f"{BUILD}: `pack.py` sa volá bez `--clip-bbox`. Prepínač, ktorý sa "
        f"nedáva, je to isté ako prepínač, ktorý nie je.")

for b in bad:
    print(f"::error::{b}")
print(f"tieňovanie nevyrába terén tam, kde model nie je: {len(bad)} chýb")
sys.exit(1 if bad else 0)
