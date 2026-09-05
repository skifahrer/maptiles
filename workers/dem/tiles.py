#!/usr/bin/env python3
"""Ľubovoľný výškový raster → dlaždice 1°×1° v EPSG:4326, pomenované podľa
juhozápadného rohu (N49E019.tif), teda tak, ako ich čaká build mapy.

Sonny distribuuje viac produktov: 1″ a 3″ sú .hgt presne po stupňoch, ale
„20m" a „50m" sú GeoTIFFy, ktoré môžu byť v metrickej projekcii a pokrývať
celú krajinu. Viac vstupov sa najprv zlepí do jedného VRT.

`--window` drží meno dlaždice pravdivým: stupeň, ktorý do okna nepadne celý,
sa neukladá (prevod do WGS84 okno vydúva a presahy sú cudzie stupne), a stupeň,
ktorý doň padne celý a nemá ani jednu výšku, sa uloží prázdny – ako záznam,
že sa tam pozeralo.

„Prázdny stupeň" rozhoduje `has_elevations` presným priechodom, nie
vzorkovaním, a hotová prázdna dlaždica sa podpíše verziou tej kontroly
(`EMPTY_CHECK`).

Použitie:
    python3 workers/dem/tiles.py --out tiles/ Slovakia_20m.tif [ďalšie.tif …]
    python3 workers/dem/tiles.py --out tiles/ --window=21,49,22,50 nation.tif
"""
import argparse
import json
import math
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
# ktorým resamplingom, rozhoduje `workers/lib/cell.py` – tá istá otázka, akú
# si kladie tieňovanie aj čítanie DMR 5.0 z Drive
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import M_PER_DEG_LAT, resampling  # noqa: E402


# bez toho si `gdalinfo -stats` odkladá štatistiky do `.aux.xml`
NO_PAM = {**os.environ, "GDAL_PAM_ENABLED": "NO"}

# prázdna dlaždica nesie, kto ju vyhlásil za prázdnu: „v tomto stupni terén
# nie je" je odpoveď, ktorej ďalšie behy veria a nikto ten stupeň už neprečíta.
# Keď sa kontrola zmení, zmení sa verzia a `dem/coverage.py` staré prázdne
# dlaždice vyhodí.
EMPTY_PX = 60                  # strana prázdnej dlaždice v pixeloch
EMPTY_TAG = "EMPTY_CHECK"      # meno položky v metadátach GDALu
# v1 = vzorkovanie, v2 = overené presným priechodom
EMPTY_CHECK = "v2-presne"
# nad túto veľkosť to prázdna dlaždica byť nemôže (60×60 px je pár kB, skutočný
# stupeň v 5 m stovky MB) – podľa toho vie `dem/trust.py`, čo sa oplatí otvoriť
EMPTY_MAX_BYTES = 1 << 20


def gdalinfo(path, stats=""):
    """`stats`: prázdne = bez štatistiky, `approx` = vzorkovaná, `exact` = presná."""
    flag = {"": [], "approx": ["-approx_stats"], "exact": ["-stats"]}[stats]
    cmd = ["gdalinfo", "-json"] + flag + [path]
    out = subprocess.run(
        cmd, capture_output=True, text=True, check=True, env=NO_PAM
    ).stdout
    return json.loads(out)


def elevation_range(path, exact=False):
    """(min, max) výšok, alebo None, keď sa nenašiel platný pixel.

    `exact=False` je vzorkovaná odpoveď – smie sa z nej robiť len záver
    „výšky tu sú" (viď `has_elevations`).
    """
    try:
        b = gdalinfo(path, stats="exact" if exact else "approx")["bands"][0]
        return b["minimum"], b["maximum"]
    except Exception:
        return None


def has_elevations(path):
    """Je v rastri aspoň jedna platná výška? Odpoveď musí byť presná.

    `-approx_stats` číta len každý n-tý blok, takže pri štvorcovom rastri
    prejde po uhlopriečke – a keď terén leží mimo nej (pohraničný stupeň, kde
    krajina zaberá roh), nenájde nič. Presne tak zmizla polovica Bratislavského
    kraja: dlaždica s 25 miliónmi platných buniek sa zahodila ako prázdna.

    Vzorkovanie sa preto berie ako rýchle „áno" a jeho „nie" sa vždy overí
    presným priechodom – ten je drahý, ale platí sa len za dlaždice, ktoré
    vyzerajú prázdne.
    """
    rng = elevation_range(path)
    if rng is not None:
        return rng
    rng = elevation_range(path, exact=True)
    if rng is not None:
        print(f"  (vzorkovanie v {os.path.basename(path)} výšky nenašlo, "
              f"presný priechod áno: {rng[0]:.1f} … {rng[1]:.1f} m)")
    return rng


def wgs84_bounds(info):
    """Rozsah rastra v stupňoch – aj keď je sám v metrickej projekcii."""
    ext = info.get("wgs84Extent")
    if not ext or not ext.get("coordinates"):
        raise SystemExit("Raster nemá zistiteľný rozsah vo WGS84 (chýba projekcia?).")
    pts = []
    def walk(node):
        if isinstance(node[0], (int, float)):
            pts.append(node)
        else:
            for n in node:
                walk(n)
    walk(ext["coordinates"])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def is_geographic(info):
    """Zemepisná (stupne) alebo projektovaná (metre) sústava?

    Rozhoduje typ vo WKT – hľadať jednotku „degree" v texte je krehké.
    COMPOUNDCRS je tu preto, že raster s prevedenými výškami má vodorovnú
    zložku v stupňoch, ale WKT začína `COMPOUNDCRS[` – bez toho vyzeral ako
    metrický a gdalwarp mal z jedného stupňa vyrobiť dlaždicu širokú
    1,2 miliardy pixelov.
    """
    wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
    wkt = wkt.strip().upper()
    if wkt.startswith("COMPOUNDCRS"):
        # vodorovná zložka je prvá vnorená CRS
        inner = wkt.split("[", 1)[1] if "[" in wkt else ""
        inner = inner.split(",", 1)[1].lstrip() if "," in inner else ""
        return inner.startswith(("GEOGCRS", "GEOGCS", "BASEGEOGCRS"))
    return wkt.startswith(("GEOGCRS", "GEOGCS", "BASEGEOGCRS"))


def pixel_degrees(info, lat):
    """Veľkosť pixela v stupňoch; pri metrickej projekcii cez cos(šírky)."""
    gt = info["geoTransform"]
    px, py = abs(gt[1]), abs(gt[5])
    if is_geographic(info):
        return px, py
    return px / (111320 * math.cos(math.radians(lat))), py / 110540


def tile_name(lon, lat):
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def plan_tiles(bounds, window, dlon, dlat):
    """Ktoré stupne sa idú písať – jedna odpoveď pre celý súbor.

    Vracia `(write, partial)`: `write` sú `(lon, lat, name, has_data)`, kde
    `has_data` False znamená prázdnu dlaždicu ako záznam, že sa tam pozeralo;
    `partial` sú stupne, ktoré okno neprečítalo celé – tie sa neukladajú.

    Bez okna sú to stupne, ktoré raster pretína. S oknom sa mriežka berie
    z okna, nie z rastra: prevod do WGS84 okno vydúva a presahy sú cudzie stupne.
    """
    w, s, e, n = bounds
    lat_range = range(math.floor(s), math.ceil(n))
    lon_range = range(math.floor(w), math.ceil(e))
    if window is not None:
        # únia okna a rastra: okno preto, že stupeň bez výšok sa musí uložiť
        # prázdny; raster preto, že presahy prevodu sa majú dať vypísať
        lat_range = range(min(lat_range.start, math.floor(window[1])),
                          max(lat_range.stop, math.ceil(window[3])))
        lon_range = range(min(lon_range.start, math.floor(window[0])),
                          max(lon_range.stop, math.ceil(window[2])))

    write, partial = [], []
    for lat in lat_range:
        for lon in lon_range:
            # zdroje presahujú celý stupeň o polpixel, takže „aspoň pár pixelov"
            over_x = min(lon + 1, e) - max(lon, w)
            over_y = min(lat + 1, n) - max(lat, s)
            thin = over_x <= 2 * dlon or over_y <= 2 * dlat
            name = tile_name(lon, lat)
            if window is None:
                if not thin:
                    write.append((lon, lat, name, True))
                continue
            # tolerancia je pixel: okno sa rozširuje na celé stupne
            if (lon < window[0] - dlon or lon + 1 > window[2] + dlon
                    or lat < window[1] - dlat or lat + 1 > window[3] + dlat):
                if not thin:
                    partial.append(name)
                continue
            write.append((lon, lat, name, not thin))
    return write, partial


def empty_tile(dst, lon, lat, dtype, nodata, px=EMPTY_PX):
    """Prázdna dlaždica pre celý stupeň – „pozerali sme sa a nič tu nie je".

    Píše sa cez VRT bez zdroja, takže vznikne bez ohľadu na to, kam raster
    dosiahol, a má kilobajty namiesto stoviek MB.

    Podpíše sa `EMPTY_CHECK` s verziou kontroly, ktorá o prázdnote rozhodla,
    a overí sa, že je naozaj prázdna: keby VRT vrátil nuly namiesto nodaty,
    ležala by v sklade dlaždica s výškou 0 m – a nula je v mape more.
    Vracia True, keď vznikla.
    """
    nd = nodata if nodata is not None else (
        -9999.0 if dtype.startswith("Float") else -32768)
    vrt = dst + ".vrt"
    with open(vrt, "w") as f:
        f.write(
            f'<VRTDataset rasterXSize="{px}" rasterYSize="{px}">'
            f'<SRS>EPSG:4326</SRS>'
            f'<GeoTransform>{lon}, {1.0 / px}, 0, {lat + 1}, 0, {-1.0 / px}'
            f'</GeoTransform>'
            f'<VRTRasterBand dataType="{dtype}" band="1">'
            f'<NoDataValue>{nd!r}</NoDataValue></VRTRasterBand></VRTDataset>')
    try:
        subprocess.run(
            ["gdal_translate", "-q", "-of", "GTiff", "-a_nodata", repr(nd),
             "-mo", f"{EMPTY_TAG}={EMPTY_CHECK}",
             "-co", "COMPRESS=DEFLATE", vrt, dst],
            check=True, env=NO_PAM)
    except subprocess.CalledProcessError as exc:
        print(f"::warning::Prázdnu dlaždicu {os.path.basename(dst)} sa "
              f"nepodarilo vyrobiť ({exc}) – doplnenie sa na ten stupeň bude "
              f"pýtať znova.")
        return False
    finally:
        os.remove(vrt)
    if elevation_range(dst, exact=True) is not None:
        os.remove(dst)
        print(f"::warning::Prázdna dlaždica {os.path.basename(dst)} nevyšla "
              f"prázdna (GDAL do nej dal hodnoty namiesto nodaty) – radšej ju "
              f"neukladám, nula v mape je more.")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+", help="vstupné rastre")
    ap.add_argument("--out", required=True)
    # prázdne = nech rozhodne pomer pixel/bunka (`lib/cell.py`). Natvrdo tu
    # bolo `bilinear` a práve pri rovnakej mierke to dobré nie je: fáza
    # interpolácie sa naprieč rastrom posúva a v tieňovaní je z toho pruhovanie.
    ap.add_argument("--resampling", default="",
                    help="natvrdo zvolený resampling; prázdne = podľa pomeru "
                         "pixel/bunka (workers/lib/cell.py)")
    ap.add_argument("--window", default="",
                    help="W,S,E,N – okno, ktoré volajúci NAOZAJ prečítal. "
                         "Stupeň, ktorý doň nepadne celý, sa neuloží; stupeň "
                         "bez výšok sa uloží prázdny (rozpis v hlavičke).")
    args = ap.parse_args()

    window = None
    if args.window.strip():
        vals = [float(v) for v in args.window.split(",")]
        if len(vals) != 4:
            raise SystemExit(f"::error::--window chce W,S,E,N: „{args.window}“")
        window = tuple(vals)

    temps = []
    src = args.src[0]
    if len(args.src) > 1:
        # jeden VRT nad všetkými vstupmi – rieši aj prekryvy
        src = os.path.join(args.out or ".", "_dem-tiles.vrt")
        os.makedirs(args.out, exist_ok=True)
        subprocess.run(["gdalbuildvrt", "-q", "-resolution", "highest", src, *args.src],
                       check=True)
        temps.append(src)
        print(f"Zlepené do VRT: {len(args.src)} rastrov")

    info = gdalinfo(src)

    # výšky uložené ako celé čísla so škálou by sa bez rozbalenia dostali do
    # mapy desaťkrát väčšie; gdalwarp škálu sám neuplatňuje
    band = info["bands"][0]
    scale, offset = band.get("scale", 1) or 1, band.get("offset", 0) or 0
    if scale != 1 or offset != 0:
        print(f"Výšky sú škálované (scale={scale}, offset={offset}) – rozbaľujem na metre")
        os.makedirs(args.out, exist_ok=True)
        unscaled = os.path.join(args.out, "_dem-tiles-unscaled.tif")
        subprocess.run(
            ["gdal_translate", "-q", "-unscale", "-ot", "Float32",
             "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3", src, unscaled],
            check=True,
        )
        temps.append(unscaled)
        src = unscaled
        info = gdalinfo(src)

    w, s, e, n = wgs84_bounds(info)
    dtype = info["bands"][0]["type"]
    predictor = "3" if dtype.startswith("Float") else "2"
    lat_mid = (s + n) / 2
    dlon, dlat = pixel_degrees(info, lat_mid)
    nodata = info["bands"][0].get("noDataValue")
    same_grid = is_geographic(info)
    print(
        f"{os.path.basename(src)}: {w:.3f},{s:.3f} … {e:.3f},{n:.3f}, "
        f"{dtype}, mriežka {dlon * 3600:.2f}″ × {dlat * 3600:.2f}″"
        f"{'' if same_grid else ' (prepočítané z metrov)'}"
    )

    # iné jednotky alebo nerozbalená škála sa prejavia tu – a nie až tým, že
    # mapa bude samá skala
    rng = has_elevations(src)
    if rng:
        lo, hi = rng
        print(f"Výšky v zdroji: {lo:.1f} … {hi:.1f} m")
        if lo < -500 or hi > 9000:
            print("::warning::Rozsah výšok nevyzerá ako metre nad morom – "
                  "skontroluj jednotky zdroja (decimetre? stopy?).")

    # `near` pri zhodnej mriežke je zámer: zdroj aj cieľ sú v stupňoch s tým
    # istým krokom, takže je to čisté posunutie o zlomok pixela.
    # Pri metrickom zdroji sa mení projekcia, ale nie mierka, takže pomer
    # pixel/bunka je 1 a kernel vyberá `lib/cell.py` rovnako ako tieňovanie.
    bunka_m = dlat * M_PER_DEG_LAT
    how = args.resampling or resampling(bunka_m, bunka_m)
    if not same_grid:
        print(f"Prevzorkovanie do WGS84: `{how}`"
              + (" (zvolené natvrdo)" if args.resampling else
                 f" – bunka {bunka_m:.1f} m sa nemení, mení sa projekcia, "
                 f"takže sa musí filtrovať rovnako všade"))

    os.makedirs(args.out, exist_ok=True)
    made = []
    empty = []
    write, partial = plan_tiles((w, s, e, n), window, dlon, dlat)
    for lon, lat, name, has_data in write:
        dst = os.path.join(args.out, f"{name}.tif")
        if not has_data:
            # stupeň v okne, ktorý raster vôbec nepretína: prázdna dlaždica sa
            # píše bez warpu – gdalwarp s `-te` mimo zdroja je zbytočná operácia
            if empty_tile(dst, lon, lat, dtype, nodata):
                empty.append(name)
                print(f"  ○ {name} (v okne, ale model tam nedosahuje)")
            continue
        cmd = [
            "gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:4326",
            "-te", str(lon), str(lat), str(lon + 1), str(lat + 1),
            "-tr", repr(dlon), repr(dlat),
            "-r", "near" if same_grid else how,
            "-co", "COMPRESS=DEFLATE", "-co", f"PREDICTOR={predictor}",
            "-co", "TILED=YES", "-multi",
        ]
        if nodata is not None:
            cmd += ["-dstnodata", repr(nodata)]
        subprocess.run(cmd + [src, dst], check=True)
        # `has_elevations`, nie `elevation_range`: vzorkovanie tu smie povedať
        # len „výšky sú", jeho „nie sú" sa musí overiť presne
        if has_elevations(dst) is None:
            if window is None:
                # celá dlaždica je nodata – do skladu nemá čo pridať
                os.remove(dst)
                continue
            # s oknom je prázdna dlaždica odpoveď: „tento stupeň sme prečítali
            # celý a terén v ňom nie je". Prepíše sa za hrubú, nech nezaberá.
            os.remove(dst)
            # koľko z toho stupňa raster vôbec pretínal – prázdny stupeň,
            # do ktorého raster siahal na polovicu, je podozrivý
            over = (max(0.0, min(lon + 1, e) - max(lon, w))
                    * max(0.0, min(lat + 1, n) - max(lat, s))) * 100.0
            if empty_tile(dst, lon, lat, dtype, nodata):
                empty.append(name)
                print(f"  ○ {name} (prečítaný celý, výšky v ňom nie sú; "
                      f"raster pretínal {over:.0f} % stupňa)")
            continue
        made.append(name)
        print(f"  ✓ {name}")

    for t in temps:
        if os.path.exists(t):
            os.remove(t)
    if partial:
        # nie warning: je to správny výsledok správne prečítaného okna. Ale
        # musí byť v logu, inak sa „prečo tam nie je N48E021" hľadá v sklade.
        print(f"Mimo okna, neukladá sa: {' '.join(sorted(set(partial)))} – "
              f"okno {args.window} tie stupne neprečítalo celé a meno "
              f"dlaždice je sľub o celom stupni.")
    if not made and not empty:
        raise SystemExit("Raster nepokrýva ani jednu celú 1° dlaždicu.")

    print(f"{len(made)} dlaždíc: {' '.join(sorted(set(made)))}"
          + (f" (+ {len(empty)} prázdnych: {' '.join(sorted(set(empty)))})"
             if empty else ""))


if __name__ == "__main__":
    sys.exit(main())
