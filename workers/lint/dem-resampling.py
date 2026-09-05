#!/usr/bin/env python3
"""Kontrola: resampling výškového modelu si nikto nevyberá sám.

Odpovedá `workers/lib/cell.py` – lenže odpovedať sa dá aj tak, že sa do
príkazu napíše `-r average`. `dmr5-cut.py` tak robil z 4 m pyramídy 5 m bunky:
pri pomere 1,25 `average` nepriemeruje, ale každý štvrtý pixel preskočí,
a z toho rytmu je v mape pravidelná mriežka.

  1. `resampling(5, 4)` nesmie byť `average` (inak by stačilo stiahnuť
     `AVERAGE_RATIO` na 1 a mriežka sa vráti);
  2. kto prevzorkúva model, pýta sa `lib/cell.py` – žiadny kernel natvrdo;
  3. pyramída sa vyberá v `dmr5-cut.pyramid_level`, nie cez `-ovr AUTO`:
     z úrovne vyplýva pomer pixel/bunka.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
import cell  # noqa: E402

# Súbory, ktoré VYRÁBAJÚ výškový model (nie tie, čo z neho robia dlaždice –
# tie stráži `workers/lint/terrain.py`). Kernel v nich musí prísť z `cell.py`.
VYRABAJU = [
    os.path.join("workers", "drive", "dmr5-cut.py"),
    os.path.join("workers", "drive", "dmr5-raster.py"),
    os.path.join("workers", "dem", "tiles.py"),
]

# Kernely GDALu, ktoré sa dajú napísať natvrdo. `near` medzi nimi NIE JE:
# pri zhodnej mriežke je to čisté posunutie o zlomok pixela, teda jediná
# voľba, ktorá nefiltruje vôbec – a `dem/tiles.py` ju tak aj používa.
KERNELY = ("average", "bilinear", "cubic", "cubicspline", "lanczos", "mode")

# Riadky, ktoré smú kernel menovať aj bez `cell.py`. Každá výnimka musí
# povedať, PREČO – inak je to len tichý návrat do pôvodného stavu.
VYNIMKY = {
    # Prehľadové úrovne COG sa robia zmenšovaním 2×, čo je práve
    # `AVERAGE_RATIO` – priemer je tam poctivý aj lacný.
    "RESAMPLING=AVERAGE",
}


def kod_bez_komentarov(text):
    """Riadky kódu – komentáre o resamplingu HOVORIŤ smú, kód ho nesmie voliť."""
    out = []
    for r in text.splitlines():
        if r.lstrip().startswith("#"):
            continue
        out.append(r.split("  #")[0])
    return out


def main():
    bad = []

    # ---------- 1. doktrína ----------
    # Pyramídy DMR 5.0 sú 2, 4, 8 … m, cieľ dlaždíc je 5 m – teda sa vždy
    # číta zo 4 m a pomer je 1,25. Toto je to jediné číslo, na ktorom celá
    # oprava stojí.
    if cell.resampling(5.0, 4.0) == "average":
        bad.append(
            "`cell.resampling(5, 4)` vrátila `average`. Presne pri tomto pomere "
            "(1,25) GDAL nepriemeruje, ale preskakuje každú štvrtú zdrojovú "
            "bunku – a z toho rytmu spraví hillshade pravidelnú mriežku. Tak "
            "vznikla mriežka v tieňovaní aj zubatosť vrstevníc; namerané "
            "v `workers/dem/measure-resampling.py`.")
    if cell.AVERAGE_RATIO < 2.0:
        bad.append(f"`AVERAGE_RATIO` je {cell.AVERAGE_RATIO:g}, čiže sa smie "
                   f"priemerovať aj tam, kde cieľový pixel neprekryje ani dve "
                   f"bunky. To je celá tá mriežka – hranica je 2 a je meraná.")
    # A druhá strana: pri poctivom zmenšovaní sa priemerovať MUSÍ, inak by
    # sa 1 m LiDAR na 5 m bral vzorkovaním a stratil by sa detail, ktorý tam
    # je (`dmr5-raster.whole_country` ide 1 m → 5 m, pomer 5).
    if cell.resampling(5.0, 1.0) != "average":
        bad.append("`cell.resampling(5, 1)` nevrátila `average` – z 1 m na 5 m "
                   "je pomer 5, tam je priemer poctivý aj lacný a vzorkovanie "
                   "by zahodilo detail, ktorý v modeli je.")

    # ---------- 2. kernel sa nepíše natvrdo ----------
    for rel in VYRABAJU:
        cesta = os.path.join(os.path.dirname(_WORKERS), rel)
        if not os.path.exists(cesta):
            bad.append(f"{rel} neexistuje – keď sa premenoval, uprav aj "
                       f"`workers/lint/dem-resampling.py`, inak táto kontrola "
                       f"ticho nekontroluje nič.")
            continue
        text = open(cesta, encoding="utf-8").read()
        if "from cell import" not in text:
            bad.append(f"{rel} prevzorkúva výškový model, ale nepýta sa "
                       f"`workers/lib/cell.py` – kernel si teda vyberá sám "
                       f"a raz sa s doktrínou rozíde.")
        for i, riadok in enumerate(kod_bez_komentarov(text), 1):
            if any(v in riadok for v in VYNIMKY):
                continue
            for k in KERNELY:
                if re.search(r'"-r",\s*"%s"' % k, riadok) or \
                        re.search(r'"%s"\s*,\s*"-of"' % k, riadok):
                    bad.append(
                        f"{rel}:{i}: kernel `{k}` napísaný natvrdo. Ktorým "
                        f"resamplingom sa ide, hovorí `cell.resampling(cieľ, "
                        f"zdroj)` – práve takto napísané `-r average` pri pomere "
                        f"1,25 zapieklo mriežku do dlaždíc v sklade.")

    # ---------- 3. pyramída sa vyberá na jednom mieste ----------
    cut = os.path.join(os.path.dirname(_WORKERS), "workers", "drive", "dmr5-cut.py")
    drive = os.path.join(os.path.dirname(_WORKERS), "workers", "drive", "dmr5.py")
    if os.path.exists(cut):
        text = open(cut, encoding="utf-8").read()
        if "def pyramid_level" not in text:
            bad.append("Vo `workers/drive/dmr5-cut.py` nie je `pyramid_level` – "
                       "z ktorej pyramídy sa číta, musí odpovedať jedno miesto: "
                       "to isté číslo vypisuje plán a podľa neho sa vyberá "
                       "resampling.")
        for i, riadok in enumerate(kod_bez_komentarov(text), 1):
            if '"-ovr", "AUTO"' in riadok.replace("'", '"'):
                bad.append(
                    f"workers/drive/dmr5-cut.py:{i}: `-ovr AUTO` necháva výber "
                    f"pyramídy na GDALe. Z tej úrovne ale vyplýva pomer "
                    f"pixel/bunka, ktorým sa riadi resampling – dve odpovede "
                    f"na jednu otázku (pravidlo 1). Úroveň vyberá "
                    f"`pyramid_level` a podáva sa do `-ovr`.")
    if os.path.exists(drive):
        text = open(drive, encoding="utf-8").read()
        if "pyramid_level" not in text:
            bad.append("`workers/drive/dmr5.py` si počet čítaných pixelov "
                       "počíta bez `pyramid_level` – plán by potom hovoril o "
                       "inej pyramíde, než z akej sa naozaj číta.")

    if bad:
        for b in bad:
            print(f"::error::{b}")
        return 1
    print(f"DEM resampling: kernel vyberá `lib/cell.py` "
          f"(resampling(5, 4) = `{cell.resampling(5.0, 4.0)}`, "
          f"AVERAGE_RATIO = {cell.AVERAGE_RATIO:g}), pyramídu `pyramid_level` ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
