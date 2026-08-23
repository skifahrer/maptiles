#!/usr/bin/env python3
"""
Výškové dlaždice → JEDEN `.pmtiles` (raster, terrarium PNG).

PREČO NIE STROM PNG SÚBOROV. Doteraz išlo tieňovanie na Pages ako
`terrain/{z}/{x}/{y}.png`, teda tisíce malých súborov, a do skladu na Drive
ako `.tar.zst`. Boli s tým tri problémy naraz a všetky rieši ten istý formát,
v ktorom už aj tak máme mapu, vrstevnice, skaly aj trasy:

  1. POČET SÚBOROV. Jeden beh nahrával na Pages stovky až desaťtisíce
     položiek; artefakty medzi jobmi ich prenášali po jednej a `upload-pages`
     tiež. `.pmtiles` je jeden súbor a klient si z neho ťahá dlaždice cez
     HTTP Range – presne ako z ostatných vrstiev.
  2. DVE PODOBY TEJ ISTEJ VECI. Na Pages strom, v sklade `.tar.zst` – čiže
     balenie a rozbaľovanie pri každom behu a dve cesty, ktoré sa môžu
     rozísť. Teraz je to jeden súbor: čo je v sklade, to sa aj nasadí.
  3. HRANICA ÚZEMIA. Raster zdroj v štýle nevie, kde dlaždice sú, takže sa
     mu musela dopisovať `bounds` zvlášť (inak z každého posunu mapy padali
     stovky 404). `.pmtiles` si rozsah aj zoomy nesie v hlavičke sám.

ROVNAKÉ DLAŽDICE SA UKLADAJÚ RAZ. Writer si ich hashuje, a pri teréne to nie
je maličkosť: rovina, hladina a územie za hranicou modelu dávajú identické
PNG. Koľko sa tým ušetrilo, skript vypíše.

PORADIE ZÁPISU JE HILBERTOVO, NIE PO RIADKOCH. `tileid` rastie po Hilbertovej
krivke, a keď sa dlaždice zapíšu v tom poradí, archív je „clustered" –
susedné dlaždice ležia v súbore vedľa seba a klient si ich vypýta jedným
Range namiesto štyroch. Preto sa najprv pozbierajú cesty, zoradia sa podľa
`tileid` a až potom sa čítajú; v pamäti je len zoznam ciest, nie dáta.

Použitie:
    python3 workers/terrain/pack.py --in=terrain-out \\
        --out=_site/tiles/presovsky-terrain.pmtiles --name=presovsky
"""
import argparse
import math
import os
import sys

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

TILE = 256


def tile_bounds(z, x, y):
    """Zemepisný obdĺžnik dlaždice XYZ (west, south, east, north)."""
    n = 2.0**z
    w = x / n * 360.0 - 180.0
    e = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return w, south, e, north


def zbierka(src):
    """Nájde `{z}/{x}/{y}.png` a vráti [(tileid, z, x, y, cesta)] zoradené.

    Zoradenie podľa `tileid` je to, čo z archívu spraví „clustered" – viď
    hlavičku súboru. Číta sa až potom, takže v pamäti je len zoznam ciest.
    """
    out = []
    for zd in os.listdir(src):
        if not zd.isdigit():
            continue                      # `maxzoom.txt` a spol.
        z = int(zd)
        zpath = os.path.join(src, zd)
        if not os.path.isdir(zpath):
            continue
        for xd in os.listdir(zpath):
            if not xd.isdigit():
                continue
            x = int(xd)
            xpath = os.path.join(zpath, xd)
            for name in os.listdir(xpath):
                base, ext = os.path.splitext(name)
                if ext != ".png" or not base.isdigit():
                    continue
                y = int(base)
                out.append((zxy_to_tileid(z, x, y), z, x, y,
                            os.path.join(xpath, name)))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True,
                    help="adresár s dlaždicami {z}/{x}/{y}.png")
    ap.add_argument("--out", dest="dst", required=True, help="cieľový .pmtiles")
    ap.add_argument("--name", default="terrain", help="meno do metadát")
    ap.add_argument("--clip-bbox", default="",
                    help="west,south,east,north – rozsah, na ktorý sa hlavička "
                         "oreže (bbox behu). Bez neho sa berie celý rozsah "
                         "dlaždíc, čiže na nízkom zoome pol Európy.")
    ap.add_argument("--source", default="",
                    help="kľúč výškového modelu (`sonny`, `dmr5`…) do metadát")
    args = ap.parse_args()

    dlazdice = zbierka(args.src)
    if not dlazdice:
        print(f"::error::V {args.src} nie je ani jedna dlaždica – "
              f"nie je čo zabaliť.", file=sys.stderr)
        return 1

    minz = min(d[1] for d in dlazdice)
    maxz = max(d[1] for d in dlazdice)
    # Rozsah sa počíta z dlaždíc, ktoré NAOZAJ vznikli, nie z bboxu zadania:
    # tie mimo kraja sa vynechávajú (viď `--poly` v tiles.py), takže bbox
    # zadania by sľuboval územie, ktoré v archíve nie je. Meno je sľub
    # o rozsahu a hlavička `.pmtiles` tiež – klient sa podľa nej rozhoduje,
    # kde vôbec pýtať dlaždice.
    #
    # ZO VŠETKÝCH ZOOMOV, nie z maxzoomu. Kým sa vynechávali len dlaždice mimo
    # kraja, bola množina na maxzoome tá najväčšia a stačila. `tiles.py` ale
    # vynecháva aj dlaždice bez reliéfu – rovina má vlastnú dlaždicu len na
    # nízkom zoome – takže by rozsah z maxzoomu opísal hory a klient by nad
    # rovinou nepýtal dlaždice ANI na tých nízkych zoomoch, kde sú.
    w = s = e = n = None
    for _tid, z, x, y, _p in dlazdice:
        tw, ts, te, tn = tile_bounds(z, x, y)
        w = tw if w is None else min(w, tw)
        s = ts if s is None else min(s, ts)
        e = te if e is None else max(e, te)
        n = tn if n is None else max(n, tn)

    # A POTOM SA TO OREŽE NA BBOX BEHU. Rozsah dlaždíc je zjednotenie CELÝCH
    # dlaždíc, a dlaždica na z5 má 11,25° – pyramída nad jedným krajom sa ním
    # teda vykáže ako pol Európy. Namerané na publikovanom
    # `bratislavsky_test4-terrain.pmtiles`: hlavička hovorila
    # 11,25 / 40,98 / 22,50 / 48,92, kým mapa je 17,167 / 48,321 / 17,195 /
    # 48,340 – rozsah 350-tisíckrát väčší než územie, ktoré popisuje.
    #
    # Klientovi to NEUBERIE ani jednu dlaždicu: MapLibre porovnáva `bounds`
    # s dlaždicou PRIENIKOM (`TileBounds.contains` si z bboxu spočíta rozsah
    # x/y na danom zoome), takže dlaždica z5, do ktorej kraj padne, ostáva
    # v rozsahu aj po orezaní. Ubudne len sľub o území, ktoré v archíve nie je.
    if args.clip_bbox:
        cw, cs, ce, cn = (float(v) for v in args.clip_bbox.split(","))
        w, s = max(w, cw), max(s, cs)
        e, n = min(e, ce), min(n, cn)
        if e <= w or n <= s:
            print(f"::error::Orez hlavičky na {args.clip_bbox} nepretína "
                  f"rozsah dlaždíc – to znamená, že dlaždice sú z iného "
                  f"územia, než hovorí bbox behu.", file=sys.stderr)
            return 1

    surovo = 0
    with open(args.dst, "wb") as f:
        wr = Writer(f)
        for _tid, _z, _x, _y, p in dlazdice:
            with open(p, "rb") as t:
                data = t.read()
            surovo += len(data)
            wr.write_tile(_tid, data)
        wr.finalize(
            {
                "tile_type": TileType.PNG,
                # PNG je už komprimovaný – druhé balenie by pridalo čas
                # a nič neušetrilo.
                "tile_compression": Compression.NONE,
                "min_zoom": minz,
                "max_zoom": maxz,
                "min_lon_e7": int(w * 1e7),
                "min_lat_e7": int(s * 1e7),
                "max_lon_e7": int(e * 1e7),
                "max_lat_e7": int(n * 1e7),
                "center_zoom": maxz,
                "center_lon_e7": int((w + e) / 2 * 1e7),
                "center_lat_e7": int((s + n) / 2 * 1e7),
            },
            {
                "name": args.name,
                "format": "png",
                # Bez tohto sa z archívu nedá zistiť, že farba je nadmorská
                # výška – a `raster-dem` bez správneho `encoding` vykreslí
                # namiesto reliéfu farebný šum.
                "encoding": "terrarium",
                "description": "Terrarium PNG – nadmorská výška v RGB "
                               "(v = R*256 + G + B/256 − 32768)",
                # Z ČOHO to je. Atribúcia v mape ide zo štýlu, ale archív
                # sa dá stiahnuť aj sám – a potom je toto jediné miesto,
                # kde je napísané, ktorý model to vlastne bol.
                **({"source": args.source} if args.source else {}),
            },
        )

    velkost = os.path.getsize(args.dst)
    usetrene = surovo - velkost
    print(f"{args.dst}: {len(dlazdice)} dlaždíc z{minz}–z{maxz}, "
          f"{velkost / 1048576:.1f} MB "
          f"(z {surovo / 1048576:.1f} MB v samostatných súboroch – "
          f"{'ušetrené' if usetrene >= 0 else 'navyše'} "
          f"{abs(usetrene) / 1048576:.1f} MB na zhodných dlaždiciach "
          f"a réžii súborov)")
    print(f"  rozsah {w:.4f},{s:.4f},{e:.4f},{n:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
