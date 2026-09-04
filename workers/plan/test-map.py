#!/usr/bin/env python3
"""Obrázok „kde presne ten testovací výrez je" + súradnice a odkaz do mapy.

Z čísel sa nedá povedať, či štvorec padol na hrebeň so stenami, alebo na lúku –
a keď na lúku, „nenašlo ani jednu skalu" nehovorí nič o prahoch.

Podklad je to isté tieňovanie z freemap.sk ako pri skalách z obrázka. Keď sa
nestiahne, obrázok sa nakreslí na prázdnom podklade – diagnostika nesmie zhodiť
beh, ktorý ide o niečom inom.

Použitie:
    python3 workers/plan/test-map.py \\
        --bbox=20.10,49.163,20.12,49.176 --full-bbox=19.9,49.09,20.32,49.25 \\
        --name=\"Vysoké Tatry – test 4 km²\" --png=out/kde-to-je.png \\
        --md=out/kde-to-je.md --pages-url=https://user.github.io/fricomaps/
"""
import argparse
import io
import math
import os
import random
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

TILE = 256
R = 6378137.0
# ten istý podklad ako v shading-rocks; prehľadový zoom = jednotky dlaždíc,
# tak sa tu ani nerotujú hlavičky – pri takom objeme je slušnejšie priznať sa
SHADING_URL = "https://sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg"
UA = ("fricomaps/1.0 (+https://github.com/skifahrer/fricomaps) "
      "testovaci-vyrez-nahlad")

CERVENA = (231, 60, 60)
MODRA = (60, 120, 231)
POZADIE = (232, 232, 228)


def lonlat_to_px(lon, lat, z):
    """WGS84 → pixel v Web Mercatore na danom zoome."""
    n = TILE * 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    lat = max(-85.05112878, min(85.05112878, lat))
    sy = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sy) / (1 - sy)) / (4 * math.pi)) * n
    return x, y


def ground_res(z, lat):
    """Metre na pixel na danej šírke."""
    return 2.0 * math.pi * R * math.cos(math.radians(lat)) / (TILE * 2.0 ** z)


def stiahni(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def mozaika(w, s, e, n, max_px, max_tiles):
    """Podklad pre okno `w,s,e,n`: (obrázok, zoom, ľavý-horný pixel).

    Zoom je najvyšší, pri ktorom sa okno zmestí do `max_px` aj do `max_tiles`.
    Keď sa nestiahne ani jedna dlaždica, vráti prázdny podklad – volajúci
    kreslí rámčeky tak či tak.
    """
    for z in range(16, 5, -1):
        x0, y0 = lonlat_to_px(w, n, z)
        x1, y1 = lonlat_to_px(e, s, z)
        sirka, vyska = x1 - x0, y1 - y0
        tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
        tx1, ty1 = int(x1 // TILE), int(y1 // TILE)
        n_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if max(sirka, vyska) <= max_px and n_tiles <= max_tiles:
            break
    else:
        z = 6

    x0, y0 = lonlat_to_px(w, n, z)
    x1, y1 = lonlat_to_px(e, s, z)
    tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
    tx1, ty1 = int(x1 // TILE), int(y1 // TILE)
    sirka = (tx1 - tx0 + 1) * TILE
    vyska = (ty1 - ty0 + 1) * TILE
    obraz = Image.new("RGB", (sirka, vyska), POZADIE)

    ok = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = SHADING_URL.format(z=z, x=tx, y=ty)
            for pokus in range(3):
                try:
                    dlazdica = Image.open(io.BytesIO(stiahni(url))).convert("RGB")
                    obraz.paste(dlazdica, ((tx - tx0) * TILE, (ty - ty0) * TILE))
                    ok += 1
                    break
                except Exception as exc:            # noqa: BLE001 – viď docstring
                    if pokus == 2:
                        print(f"  podklad: {url} sa nestiahol ({exc})",
                              file=sys.stderr)
                    else:
                        time.sleep(0.5 * (pokus + 1) + random.random() * 0.3)
    print(f"  podklad: z{z}, {ok} z {(tx1 - tx0 + 1) * (ty1 - ty0 + 1)} "
          f"dlaždíc, {sirka}×{vyska} px", flush=True)
    return obraz, z, (tx0 * TILE, ty0 * TILE)


# Bežné cesty k DejaVu na runneri aj v balíku Pillow. Vstavaný font PIL je
# bitmapový a len ASCII, takže by z popisu spravil „Vysok? Tatry".
FONTY = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
)


def pismo(velkost):
    """(font, výška riadku) – font je None, keď TTF nikde nie je."""
    for cesta in FONTY:
        try:
            f = ImageFont.truetype(cesta, velkost)
            return f, velkost + 4
        except OSError:
            continue
    return None, 11


def bez_diakritiky(text):
    prevod = str.maketrans({
        "á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i", "ĺ": "l",
        "ľ": "l", "ň": "n", "ó": "o", "ô": "o", "ŕ": "r", "š": "s", "ť": "t",
        "ú": "u", "ý": "y", "ž": "z", "Á": "A", "Č": "C", "Ď": "D", "É": "E",
        "Í": "I", "Ľ": "L", "Ň": "N", "Ó": "O", "Ô": "O", "Š": "S", "Ť": "T",
        "Ú": "U", "Ý": "Y", "Ž": "Z", "²": "2", "×": "x", "·": "|", "–": "-",
    })
    return text.translate(prevod)


def obdlznik(kresli, bbox, z, posun, farba, hrubka):
    w, s, e, n = bbox
    x0, y0 = lonlat_to_px(w, n, z)
    x1, y1 = lonlat_to_px(e, s, z)
    box = (x0 - posun[0], y0 - posun[1], x1 - posun[0], y1 - posun[1])
    kresli.rectangle(box, outline=farba, width=hrubka)
    return box


def okno(test, full, najmenej, najviac):
    """Výsek, ktorý sa má nakresliť, ako násobok testovacieho štvorca.

    Prvá voľba je CELÝ výrez aj s okrajom – „kde to je" má odpovedať vzhľadom
    na pohorie, nie na najbližší kopec. Dve poistky: pri malom výreze sa okno
    roztiahne aspoň na `najmenej`-násobok štvorca (inak by z obrázka bol ten
    istý štvorec ešte raz), pri celom kraji sa zmenší na `najviac`-násobok
    (inak by z testovaného územia boli dva pixely).
    """
    w, s, e, n = test
    clon, clat = (w + e) / 2, (s + n) / 2
    sw, sh = e - w, n - s

    if full:
        fw, fs, fe, fn = full
        mw, mh = (fe - fw) * 0.06, (fn - fs) * 0.06
        vysek = [fw - mw, fs - mh, fe + mw, fn + mh]
        kolko = max((vysek[2] - vysek[0]) / sw, (vysek[3] - vysek[1]) / sh)
        if najmenej <= kolko <= najviac:
            return vysek
        kolko = min(max(kolko, najmenej), najviac)
    else:
        kolko = najmenej

    dlon, dlat = sw * kolko / 2, sh * kolko / 2
    return [clon - dlon, clat - dlat, clon + dlon, clat + dlat]


def link_zoom(bbox, sirka_px=900):
    """Zoom, na ktorom testovací štvorec vyplní okno prehliadača."""
    w, s, e, n = bbox
    clat = (s + n) / 2
    strana_m = (e - w) * 111320.0 * math.cos(math.radians(clat))
    if strana_m <= 0:
        return 15
    z = math.log2(2 * math.pi * R * math.cos(math.radians(clat))
                  * sirka_px / (TILE * strana_m))
    return max(9, min(18, int(round(z))))


def zapis(args, test, clat, clon, strana_km, vyska_km, km2, cely_vidno):
    """Súradnice a odkazy – na stdout a (voliteľne) ako kúsok pre súhrn behu."""
    w, s, e, n = test
    zl = link_zoom(test)
    mapa = ""
    if args.pages_url.strip():
        base = args.pages_url.strip().rstrip("/") + "/"
        # `#map=` a nie holý `#`: MapLibre v tomto tvare necháva v hashi aj
        # ostatné parametre, takže sa vedľa polohy zmestí aj výber regiónu.
        mapa = f"{base}#map={zl}/{clat:.5f}/{clon:.5f}"
        if args.region.strip():
            mapa += f"&region={args.region.strip()}"
    osm = f"https://www.openstreetmap.org/#map={zl}/{clat:.5f}/{clon:.5f}"
    freemap = f"https://www.freemap.sk/?map={zl}/{clat:.5f}/{clon:.5f}"

    riadky = [
        f"### Testovací výrez – {km2:.2f} km²", "",
        f"**{args.name}**" + (f" · {args.layers}" if args.layers else ""), "",
        "| | |", "|---|---|",
        f"| stred | `{clat:.5f}, {clon:.5f}` |",
        f"| bbox | `{w:.6f},{s:.6f},{e:.6f},{n:.6f}` |",
        f"| veľkosť | {strana_km:.2f} × {vyska_km:.2f} km |", "",
        "Vrstevnice, skaly a tieňovanie sú len na tomto štvorci – **mapa "
        "okolo neho je celý región** podľa nastavení behu.", "",
    ]
    odkazy = []
    if mapa:
        odkazy.append(f"**[Otvoriť v mape]({mapa})**")
    odkazy += [f"[OSM]({osm})", f"[Freemap]({freemap})"]
    riadky += [" · ".join(odkazy), ""]
    legenda = ("červený štvorec = testovaný výrez"
               + (", modrý = celý výrez" if cely_vidno else ""))
    if args.img_url.strip():
        riadky += [f"![kde to je]({args.img_url.strip()})", f"*{legenda}*", ""]
    elif args.png.strip():
        riadky += [f"Obrázok s okolím (`{os.path.basename(args.png)}`) je "
                   f"v artefakte tohto behu – {legenda}.", ""]

    if args.md:
        os.makedirs(os.path.dirname(os.path.abspath(args.md)) or ".",
                    exist_ok=True)
        with open(args.md, "w") as f:
            f.write("\n".join(riadky) + "\n")
        print(f"  súhrn    {args.md}", flush=True)
    if mapa:
        print(f"  mapa     {mapa}", flush=True)
    print("─────────────────────────────────────────────────────", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Obrázok a odkaz na miesto testovacieho výrezu.")
    ap.add_argument("--bbox", required=True, help="testovací výrez W,S,E,N")
    ap.add_argument("--full-bbox", default="", help="celý výrez pre kontext")
    ap.add_argument("--name", default="testovací výrez")
    ap.add_argument("--layers", default="", help="čo sa na ňom počíta")
    ap.add_argument("--png", default="out/kde-to-je.png")
    ap.add_argument("--md", default="", help="kam zapísať kúsok pre súhrn")
    ap.add_argument("--img-url", default="",
                    help="URL, na ktorej obrázok bude – vloží sa do súhrnu")
    ap.add_argument("--pages-url", default="",
                    help="adresa mapy, napr. https://user.github.io/fricomaps/")
    ap.add_argument("--region", default="", help="kľúč regiónu do odkazu")
    ap.add_argument("--context", type=float, default=10.0,
                    help="najmenej koľkonásobok testovacieho štvorca ukázať")
    ap.add_argument("--max-context", type=float, default=90.0,
                    help="najviac koľkonásobok – nad tým je testovaný štvorec "
                         "už len bod a obrázok nič nepovie")
    ap.add_argument("--max-px", type=int, default=1400)
    ap.add_argument("--max-tiles", type=int, default=48)
    args = ap.parse_args()

    test = [float(v) for v in args.bbox.split(",")]
    if len(test) != 4:
        print("::error::--bbox musí byť W,S,E,N.", file=sys.stderr)
        return 1
    full = ([float(v) for v in args.full_bbox.split(",")]
            if args.full_bbox.strip() else None)

    w, s, e, n = test
    clon, clat = (w + e) / 2, (s + n) / 2
    strana_km = (e - w) * 111.32 * math.cos(math.radians(clat))
    vyska_km = (n - s) * 110.54
    km2 = strana_km * vyska_km

    print(f"── Kde je testovací výrez ───────────────────────────")
    print(f"  {args.name}")
    print(f"  stred    {clat:.5f}, {clon:.5f}")
    print(f"  bbox     {w:.6f},{s:.6f},{e:.6f},{n:.6f}")
    print(f"  veľkosť  {strana_km:.2f} × {vyska_km:.2f} km = {km2:.2f} km²",
          flush=True)

    # Bez `--png` sa nekreslí nič a nesťahuje sa ani jedna dlaždica – len
    # súradnice a odkazy. Tak to volá súhrn behu: obrázok už raz vyrobila
    # príprava a leží na stránke, druhé sťahovanie by bolo len záťaž navyše.
    if not args.png.strip():
        return zapis(args, test, clat, clon, strana_km, vyska_km, km2,
                     cely_vidno=bool(full))

    vysek = okno(test, full, args.context, args.max_context)
    obraz, z, posun = mozaika(*vysek, args.max_px, args.max_tiles)
    kresli = ImageDraw.Draw(obraz)
    cely_vidno = False
    if full:
        fbox = obdlznik(kresli, full, z, posun, MODRA, 2)
        cely_vidno = (fbox[0] >= -1 and fbox[1] >= -1
                      and fbox[2] <= obraz.width + 1
                      and fbox[3] <= obraz.height + 1)
    box = obdlznik(kresli, test, z, posun, CERVENA, 3)
    # Nitkový kríž cez celý obrázok: pri 4 km² na prehľadovom zoome je
    # štvorček taký malý, že sa v teréne inak hľadá očami.
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for a, b in (((cx, 0), (cx, box[1] - 6)), ((cx, box[3] + 6), (cx, obraz.height)),
                 ((0, cy), (box[0] - 6, cy)), ((box[2] + 6, cy), (obraz.width, cy))):
        kresli.line([a, b], fill=CERVENA, width=1)

    popis = (f"{args.name}   ·   {clat:.5f}, {clon:.5f}   ·   "
             f"{strana_km:.2f} × {vyska_km:.2f} km = {km2:.2f} km²"
             + (f"   ·   {args.layers}" if args.layers else ""))
    font, vyska_pisma = pismo(16)
    if font is None:
        # Vstavaný bitmapový font je len ASCII – „Vysoké" by z neho vyšlo
        # ako „Vysok?". Radšej bez dĺžňov než s otáznikmi.
        popis = bez_diakritiky(popis)
    pruh = vyska_pisma + 8
    kresli.rectangle([0, obraz.height - pruh, obraz.width, obraz.height],
                     fill=(20, 20, 20))
    kresli.text((8, obraz.height - pruh + 4), popis, fill=(255, 255, 255),
                font=font)

    os.makedirs(os.path.dirname(os.path.abspath(args.png)) or ".", exist_ok=True)
    obraz.save(args.png)
    print(f"  obrázok  {args.png} ({obraz.width}×{obraz.height} px)", flush=True)

    return zapis(args, test, clat, clon, strana_km, vyska_km, km2, cely_vidno)


if __name__ == "__main__":
    sys.exit(main())
