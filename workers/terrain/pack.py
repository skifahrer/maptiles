#!/usr/bin/env python3
"""Výškové dlaždice → jeden `.pmtiles` (raster, terrarium PNG).

Jeden súbor namiesto stromu tisícov PNG: rovnaká podoba na Pages aj v sklade,
rozsah a zoomy si nesie v hlavičke. Rovnaké dlaždice (rovina, hladina) sa
vďaka hashovaniu uložia raz. Zapisuje sa v Hilbertovom poradí, aby bol archív
„clustered".

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
    """Nájde `{z}/{x}/{y}.png` a vráti [(tileid, z, x, y, cesta)] zoradené."""
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
    # rozsah z dlaždíc, ktoré naozaj vznikli – a zo všetkých zoomov: tiles.py
    # vynecháva aj dlaždice bez reliéfu, takže maxzoom by opísal len hory
    w = s = e = n = None
    for _tid, z, x, y, _p in dlazdice:
        tw, ts, te, tn = tile_bounds(z, x, y)
        w = tw if w is None else min(w, tw)
        s = ts if s is None else min(s, ts)
        e = te if e is None else max(e, te)
        n = tn if n is None else max(n, tn)

    # orez na bbox behu: dlaždica na z5 má 11,25°, takže by sa jeden kraj
    # vykázal ako pol Európy. MapLibre porovnáva bounds prienikom, takže sa
    # tým nestratí ani jedna dlaždica.
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
                # PNG je už komprimovaný
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
                # bez toho `raster-dem` vykreslí farebný šum namiesto reliéfu
                "encoding": "terrarium",
                "description": "Terrarium PNG – nadmorská výška v RGB "
                               "(v = R*256 + G + B/256 − 32768)",
                # archív sa dá stiahnuť aj sám – inde model napísaný nie je
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
