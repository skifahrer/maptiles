#!/usr/bin/env python3
"""Tam, kde výškový model nemá dáta, sa nesmie vyrobiť hladina mora.

`-dstnodata 0` znamenalo „model tu nemáme" = „nula metrov nad morom": na
hranici dát z toho bola stena (668 m na 407 m/px, teda 59°) a za ňou rovina
bez tieňovania. A dlaždice vznikli aj tam, kde model nie je nič, takže sa
nimi `pack.py` vykázal ako rozsahom – 182-tisíckrát väčším než mapa.

  1. `terrain/vyska.py` má `NODATA` mimo rozsahu skutočných výšok a
     `warp_level` ho dáva `gdalwarpu`;
  2. warpnutá mriežka ide cez `vypln_nodata`;
  3. dlaždica bez jediného platného pixela sa nezapíše;
  4. `pack.py` vie `--clip-bbox` a `terrain/build.sh` mu ho dáva.
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
