#!/usr/bin/env python3
"""Maska kraja: „patrí toto miesto (dlaždica, pixel) do kraja?"

Pýtajú sa jej vrstvy z výškového modelu: tieňovanie sa podľa nej rozhoduje,
ktoré dlaždice kresliť (`tile_touches`) a ktoré pixely v prečnievajúcich sú
ešte kraj (`pixel_mask`), vrstevnice a skaly ju dostanú ako `-cutline`.
Polygón vyrába `workers/plan/region-poly.py`.

Sú to dve hrubosti jednej odpovede a obe treba: dlaždicová sa nedá spraviť
jemnejšie než dlaždica (na z8 je široká 156 km), pixelová nemá zmysel na
dlaždici, ktorá je celá mimo.

Bez shapely zámerne: pri kraji 2,7° × 0,7° a mriežke 2048 buniek je bunka
~100 m, kým dlaždica na z14 má ~1,5 km – presnosť na pixel by nič nepriniesla.

Pol dlaždice smie prečnievať: berie sa, keď sa jej okno zväčšené o pol strany
dotýka kraja. Bez tej rezervy by v mape bola vidieť rovná hrana tam, kde ešte
má byť terén.

    m = mask_from_file("data/region.geojson", cells=2048)
    python3 workers/lib/region-mask.py --poly=… --bbox=… --zoom=14
"""
import argparse
import json
import sys


def rings_from_geojson(path):
    """GeoJSON → `[(prstenec, je_diera)]`; prstenec je zoznam `(lon, lat)`."""
    with open(path) as f:
        data = json.load(f)
    feats = (data.get("features") if data.get("type") == "FeatureCollection"
             else [data])
    out = []
    for feat in feats or []:
        geom = feat.get("geometry") if "geometry" in feat else feat
        if not geom:
            continue
        polys = ([geom.get("coordinates")] if geom.get("type") == "Polygon"
                 else geom.get("coordinates") or [])
        for poly in polys:
            for i, ring in enumerate(poly or []):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) >= 3:
                    out.append((pts, i > 0))     # prvý prstenec = obrys
    return out


def inside(rings, x, y):
    """Je bod v polygóne? Ray casting, diery odpočítané."""
    ok = False
    for ring, hole in rings:
        c = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xx = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < xx:
                    c = not c
        if c:
            ok = not hole if not hole else False
            if hole:
                return False
    return ok


class Mask:
    """Rastrová maska kraja nad daným bboxom."""

    def __init__(self, rings, bbox, cells=2048):
        self.w, self.s, self.e, self.n = bbox
        self.rings = rings
        # Mriežka drží pomer strán, nech je bunka takmer kvadratická – inak by
        # bola v jednom smere desaťkrát hrubšia a rozhodovala by nerovnako.
        span_x, span_y = self.e - self.w, self.n - self.s
        if span_x <= 0 or span_y <= 0:
            raise ValueError(f"prázdny bbox {bbox}")
        self.nx = max(16, int(cells))
        self.ny = max(16, int(cells * span_y / span_x))
        self.dx, self.dy = span_x / self.nx, span_y / self.ny
        self.grid = bytearray(self.nx * self.ny)
        for j in range(self.ny):
            y = self.s + (j + 0.5) * self.dy
            row = j * self.nx
            for i in range(self.nx):
                if inside(rings, self.w + (i + 0.5) * self.dx, y):
                    self.grid[row + i] = 1
        self.hit = sum(self.grid)

    @property
    def pct(self):
        """Koľko percent bboxu je v kraji – to isté číslo ako v region-poly."""
        return 100.0 * self.hit / (self.nx * self.ny)

    def touches(self, w, s, e, n):
        """Dotýka sa okno kraja? Okno sa berie tak, ako prišlo (už zväčšené)."""
        if e < self.w or w > self.e or n < self.s or s > self.n:
            return False
        i0 = max(0, int((w - self.w) / self.dx))
        i1 = min(self.nx - 1, int((e - self.w) / self.dx))
        j0 = max(0, int((s - self.s) / self.dy))
        j1 = min(self.ny - 1, int((n - self.s) / self.dy))
        for j in range(j0, j1 + 1):
            row = j * self.nx
            if 1 in self.grid[row + i0:row + i1 + 1]:
                return True
        # Okno menšie než bunka masky (vysoké zoomy): rozhodne stred.
        return inside(self.rings, (w + e) / 2, (s + n) / 2)


def mask_from_file(path, bbox, cells=2048):
    return Mask(rings_from_geojson(path), bbox, cells)


# ---------- maska po PIXELOCH ----------
# Dlaždicová maska hore odpovedá na „patrí táto dlaždica do kraja?" a hrubšia
# byť nemôže – dlaždica je nedeliteľná. Lenže práve preto tieňovanie za kraj
# PRESAHUJE: na z10 sa vyrobia dlaždice, ktoré sa kraja len dotýkajú, a kreslia
# sa celé. Namerané na Prešovskom kraji (10 184 km²), pokrytie vyrobených
# dlaždíc proti ploche kraja:
#
#     z8  6,2×    z10  2,2×    z12  1,4×    z14  1,11×
#
# Teda dvojnásobok kraja aj viac – presne to, čo je na mape vidieť ako
# tieňovaný reliéf za jeho hranicou. Odpoveď na to je jemnejšia otázka: „ktoré
# PIXELY rastra ležia v kraji?" Za nimi `terrain/tiles.py` výšku DOPĹŇA
# OKOLÍM (`pokracuj_okolim`), nie zrovnáva na rovinu: rovina 0 m by na hranici
# kraja spravila zvislú stenu (namerané 89,4° proti 17,9°, ktoré má terén sám)
# a v 3D múr po obvode regiónu, kým pokračovanie nepridá sklon, ktorý by terén
# nemal – a ďalej ako o kúsok za hranicu sa nedostane, lebo dlaždica bez
# jediného pixela kraja sa nezapíše.


def _edges(rings):
    """Prstence → štyri polia hrán (`x1`, `y1`, `x2`, `y2`) pre scanline."""
    x1, y1, x2, y2 = [], [], [], []
    for ring, _hole in rings:
        for i, (ax, ay) in enumerate(ring):
            bx, by = ring[(i + 1) % len(ring)]
            if ay != by:                      # vodorovná hrana nekríži riadok
                x1.append(ax)
                y1.append(ay)
                x2.append(bx)
                y2.append(by)
    return x1, y1, x2, y2


def _dilate(mask, r, np):
    """Maska rozšírená o `r` pixelov (štvorcové okolie, separabilne).

    PREČO SA VÔBEC ROZŠIRUJE. Tieňovanie sa počíta zo SUSEDNÝCH pixelov
    a klient si dlaždicu ešte prevzorkuje, takže pixel presne na hranici kraja
    by mal susedov už z doplneného okolia. S rezervou pár pixelov stojí
    tieňovanie na hranici na skutočnom teréne a dopĺňa sa až za ňou, kde je
    v štýle aj tak plocha `mimo` (`deploy/region-mask.py`).
    """
    if r <= 0:
        return mask
    out = mask.copy()
    for k in range(1, r + 1):
        out[:, k:] |= mask[:, :-k]
        out[:, :-k] |= mask[:, k:]
    mask = out.copy()
    for k in range(1, r + 1):
        out[k:, :] |= mask[:-k, :]
        out[:-k, :] |= mask[k:, :]
    return out


def pixel_mask(rings, box, width, height, grow=0):
    """Bool pole `height × width`: leží stred pixela v kraji (+ `grow` px)?

    `rings` aj `box` sú V TÝCH ISTÝCH SÚRADNICIACH – `terrain/tiles.py` ich
    podáva vo Web Mercatore, lebo v ňom je aj raster z `gdalwarp`. Prevod si
    robí volajúci: mercator je v pipeline na jednom mieste (`terrain/tiles.py`)
    a druhá kópia toho vzorca by bola druhá pravda o jednej projekcii.

    Riadok 0 je HORE, tak ako v rastri (`maxy`), a rozhoduje STRED pixela.
    Vypĺňa sa pravidlom párnosti, takže diery netreba riešiť zvlášť: prstenec
    v prstenci prevráti párnosť a vyjde z toho diera.
    """
    import numpy as np
    minx, miny, maxx, maxy = box
    dx, dy = (maxx - minx) / width, (maxy - miny) / height
    ex1, ey1, ex2, ey2 = (np.asarray(a, dtype=np.float64) for a in _edges(rings))
    mask = np.zeros((height, width), dtype=bool)
    if not len(ex1):
        return mask
    lo, hi = min(ey1.min(), ey2.min()), max(ey1.max(), ey2.max())
    for j in range(height):
        y = maxy - (j + 0.5) * dy
        if y < lo or y > hi:
            continue
        cross = (ey1 > y) != (ey2 > y)
        if not cross.any():
            continue
        xs = ex1[cross] + (y - ey1[cross]) * ((ex2 - ex1)[cross]
                                              / (ey2 - ey1)[cross])
        xs.sort()
        # Dvojice pretnutí sú vnútro. Stred pixela `i` je `minx + (i+0.5)*dx`,
        # takže z `x` vyjde index `x/dx - 0.5` a hranice sa zaokrúhľujú dnu.
        i0 = np.ceil((xs[0::2] - minx) / dx - 0.5).astype(np.int64)
        i1 = np.floor((xs[1::2] - minx) / dx - 0.5).astype(np.int64)
        row = mask[j]
        for a, b in zip(np.clip(i0, 0, width), np.clip(i1 + 1, 0, width)):
            if b > a:
                row[a:b] = True
    return _dilate(mask, int(grow), np)


def tile_box(z, x, y):
    """Okno dlaždice XYZ v stupňoch (lon/lat, Web Mercator)."""
    import math
    n = 2 ** z
    lon1 = x / n * 360.0 - 180.0
    lon2 = (x + 1) / n * 360.0 - 180.0
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat2 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon1, min(lat1, lat2), lon2, max(lat1, lat2)


def tile_touches(mask, z, x, y, grow=0.5):
    """Patrí dlaždica do kraja, keď smie prečnievať `grow` svojej strany?"""
    w, s, e, n = tile_box(z, x, y)
    gx, gy = (e - w) * grow, (n - s) * grow
    return mask.touches(w - gx, s - gy, e + gx, n + gy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poly", required=True)
    ap.add_argument("--bbox", required=True, help="west,south,east,north")
    ap.add_argument("--zoom", type=int, default=14)
    ap.add_argument("--cells", type=int, default=2048)
    args = ap.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(","))
    m = mask_from_file(args.poly, bbox, args.cells)
    print(f"Maska kraja: {m.nx}×{m.ny} buniek, v kraji {m.pct:.1f} % bboxu")
    # Koľko dlaždíc na zoome padne mimo – to je to, čo sa už nebude počítať.
    import math
    n = 2 ** args.zoom
    def xt(lon):
        return int((lon + 180.0) / 360.0 * n)
    def yt(lat):
        r = math.radians(lat)
        return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    x0, x1 = xt(bbox[0]), xt(bbox[2])
    y0, y1 = yt(bbox[3]), yt(bbox[1])
    vsetkych = (x1 - x0 + 1) * (y1 - y0 + 1)
    v_kraji = sum(1 for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
                  if tile_touches(m, args.zoom, x, y))
    print(f"z{args.zoom}: {v_kraji} z {vsetkych} dlaždíc sa dotýka kraja "
          f"(mimo {vsetkych - v_kraji}, teda "
          f"{100 * (vsetkych - v_kraji) / vsetkych:.0f} % práce odpadne)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
