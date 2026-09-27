#!/usr/bin/env python3
"""
Podklady pre mapu sveta – vodstvo, hranice štátov a regióny sťahovania.

ČO TO ROBÍ. Stiahne štyri cudzie zdroje a spraví z nich päť súborov, ktoré
potom Planetiler prečíta ako zdroje schémy `workers/world/world.yml`:

    data/world/water.gpkg          moria a oceány  OSM (osmdata.openstreetmap.de)
    data/world/lakes.geojson       jazerá          Natural Earth 10m
    data/world/boundaries.geojson  hranice štátov  Natural Earth 10m
    data/world/countries.geojson   štáty (popisky) Natural Earth 10m
    data/world/downloads.geojson   regióny sťahovania  Geofabrik index-v1.json

PREČO NIE `planet.osm.pbf`. Celá planéta má cez 80 GB a Planetiler nad ňou
potrebuje rádovo terabajt disku a hodiny behu; runner má ~60 GB voľných a job
strop 360 minút, ktorý sa vypnúť nedá. Mapa sveta v tejto pipeline preto stojí
na TÝCH ISTÝCH podkladoch, z akých si nízke zoomy skladá aj Planetiler sám
(Natural Earth) a na pobrežiach z OSM: `simplified-water-polygons` sú vodné
plochy odvodené z pobrežných čiar OpenStreetMap a sú robené presne na z0–z9.
Je to teda „základná mapa sveta", nie zmenšená planéta – a mapa to o sebe
hovorí v atribúcii (`world.yml`) aj v `obsah.json` v balíku.

REGIÓNY SŤAHOVANIA SÚ Z GEOFABRIKU. Otázka „na aké kusy je OSM rozdelené na
sťahovanie" má jedinú odpoveď, ktorá je v JEDNOM súbore aj s polygónmi:
`index-v1.json` (id, meno, rodič, odkazy na `.pbf`). Naše vlastné buildy
sťahujú PBF z osm.fr (`workers/plan/pbf.sh`), ktorý polygóny svojich výrezov
nepublikuje – delenie sveta je ale u oboch to isté (svetadiel → štát → kraj),
takže mapa ukazuje, kde ktorý výrez je, a `pbf` v atribútoch nesie odkaz,
ktorý naozaj existuje.

TICHO SA TU NESMIE STAŤ NIČ (pravidlo 8 v CLAUDE.md). Keď cudzí server vráti
HTML miesto dát alebo sa formát zmení, vrstva by inak ostala prázdna a mapa
by len „nemala hranice". Preto má každý výstup dolnú hranicu počtu prvkov
a pod ňou to je tvrdá chyba s návodom, čo s tým.

Použitie (dá sa spustiť aj lokálne, bez GitHubu):
    python3 workers/world/sources.py --out=data/world
    python3 workers/world/sources.py --out=data/world --only=downloads
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

# ---------- odkiaľ sa to berie ----------
# Veľkosti sú namerané `curl -sSIL` v auguste 2026 a slúžia na odhad času
# v pláne (pravidlo 4); keď sa rozídu, skript to po stiahnutí vypíše.
NE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master"
      "/geojson")
ZDROJE = {
    "countries": {
        "url": f"{NE}/ne_10m_admin_0_countries.geojson",
        "subor": "ne_10m_admin_0_countries.geojson",
        "mb": 13.3,
        "popis": "štáty (popisky) – Natural Earth 10m",
    },
    "boundaries": {
        "url": f"{NE}/ne_10m_admin_0_boundary_lines_land.geojson",
        "subor": "ne_10m_admin_0_boundary_lines_land.geojson",
        "mb": 2.3,
        "popis": "hranice štátov – Natural Earth 10m",
    },
    "lakes": {
        "url": f"{NE}/ne_10m_lakes.geojson",
        "subor": "ne_10m_lakes.geojson",
        "mb": 5.0,
        "popis": "jazerá – Natural Earth 10m",
    },
    "water": {
        "url": ("https://osmdata.openstreetmap.de/download/"
                "simplified-water-polygons-split-3857.zip"),
        "subor": "simplified-water-polygons-split-3857.zip",
        "mb": 60.0,
        "popis": "moria a oceány – z pobrežných čiar OSM (zjednodušené, z0–z9)",
    },
    "downloads": {
        "url": "https://download.geofabrik.de/index-v1.json",
        "subor": "geofabrik-index-v1.json",
        "mb": 15.0,
        "popis": "regióny sťahovania OSM – Geofabrik index-v1.json",
    },
}

# Dolná hranica počtu prvkov. Nie je to odhad, je to „toto je zjavne rozbité":
# štátov je ~250, hraníc ~750 úsekov, jazier ~1300, regiónov Geofabriku ~500.
# Keď cudzí server vráti chybovú stránku alebo sa zmení formát, spadne to tu –
# a nie ticho v mape bez hraníc.
MINIMUM = {
    "countries": 150,
    "boundaries": 200,
    "lakes": 300,
    "downloads": 100,
    "water": 1000,
}

POKUSY = 4          # cudzí server smie mať výpadok, nesmie zhodiť beh
TIMEOUT = 120       # s


def log(msg):
    print(msg, flush=True)


def human(bytes_):
    for jednotka in ("B", "kB", "MB", "GB"):
        if bytes_ < 1024 or jednotka == "GB":
            return f"{bytes_:.0f} {jednotka}" if jednotka == "B" \
                else f"{bytes_:.1f} {jednotka}"
        bytes_ /= 1024
    return f"{bytes_:.1f} GB"


def cas(sek):
    return f"{sek:.0f} s" if sek < 90 else f"{sek / 60:.1f} min"


# ---------- sťahovanie ----------

def _stiahni_raz(url, dest, popis, mb):
    """Jeden pokus. Píše postup, nech hodina ticha nevyzerá ako zaseknutie."""
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        celkom = int(r.headers.get("Content-Length") or 0)
        odhad = celkom or int(mb * 1024 * 1024)
        mam = 0
        posledny = t0
        with open(dest, "wb") as f:
            while True:
                kus = r.read(1 << 20)
                if not kus:
                    break
                f.write(kus)
                mam += len(kus)
                # Postup najviac raz za 5 s – log má byť čitateľný, nie dlhý.
                if time.time() - posledny >= 5:
                    posledny = time.time()
                    hotovo = mam / odhad if odhad else 0
                    ubehlo = time.time() - t0
                    zvysok = (ubehlo / hotovo - ubehlo) if hotovo > 0.02 else 0
                    log(f"    {human(mam)} z {human(odhad)} "
                        f"({hotovo * 100:.0f} %), zostáva ~{cas(zvysok)}")
    return mam, time.time() - t0


def stiahni(kluc, kam):
    """Stiahne zdroj do `kam`, keď tam ešte nie je. Vracia cestu k súboru.

    ZAPISUJE SA CEZ `.part` A PREMENOVANIE (pravidlo 6 v CLAUDE.md): zrušený
    beh tak nenechá polovičný súbor, ktorý by ten ďalší považoval za hotový.
    """
    z = ZDROJE[kluc]
    dest = os.path.join(kam, z["subor"])
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log(f"  {z['popis']}: už stiahnuté ✓ ({human(os.path.getsize(dest))})")
        return dest
    for pokus in range(1, POKUSY + 1):
        try:
            velkost, ubehlo = _stiahni_raz(z["url"], dest + ".part",
                                           z["popis"], z["mb"])
            os.replace(dest + ".part", dest)
            odchylka = velkost / (z["mb"] * 1024 * 1024) if z["mb"] else 1
            log(f"  {z['popis']}: {human(velkost)} za {cas(ubehlo)}"
                + (f" (odhad bol {z['mb']:.1f} MB, teda {odchylka:.1f}×)"
                   if odchylka < 0.5 or odchylka > 2 else ""))
            return dest
        except (urllib.error.URLError, OSError, TimeoutError,
                ValueError) as exc:
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            if pokus == POKUSY:
                raise SystemExit(
                    f"::error::{z['popis']} sa nepodarilo stiahnuť ani na "
                    f"{POKUSY} pokusov ({exc}). Skús beh zopakovať – ide "
                    f"o cudzí server ({z['url']}). Keď to potrvá, nahraď "
                    f"odkaz v ZDROJE vo `workers/world/sources.py` "
                    f"zrkadlom.")
            cakaj = 5 * 2 ** (pokus - 1)
            log(f"::warning::{z['popis']}: pokus {pokus} z {POKUSY} zlyhal "
                f"({exc}) – skúšam znova o {cakaj} s.")
            time.sleep(cakaj)
    return dest   # sem sa nedá dostať, ale nech je návratová hodnota jedna


# ---------- spoločné ----------

def nacitaj_geojson(path, popis):
    """GeoJSON zo súboru. Chyba tvaru je tvrdá – nie prázdna vrstva."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as exc:
        raise SystemExit(
            f"::error::{popis}: stiahnutý súbor nie je platný JSON ({exc}). "
            f"Býva to chybová stránka servera uložená ako dáta – zmaž "
            f"`{path}` a pusti beh znova.")
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise SystemExit(
            f"::error::{popis}: v `{path}` nie je FeatureCollection s prvkami. "
            f"Zmenil sa formát zdroja – pozri `workers/world/sources.py`.")
    return data["features"]


def zapis_geojson(path, prvky, kluc, popis):
    """Uloží prvky a overí, že ich je aspoň toľko, koľko má zmysel."""
    minimum = MINIMUM[kluc]
    if len(prvky) < minimum:
        raise SystemExit(
            f"::error::{popis}: vyšlo {len(prvky)} prvkov, čakalo sa aspoň "
            f"{minimum}. Taká vrstva by v mape ticho chýbala, tak radšej "
            f"padám. Pozri, či sa nezmenili mená atribútov v zdroji "
            f"(`workers/world/sources.py`).")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": prvky}, f)
    log(f"  {popis}: {len(prvky)} prvkov → {path} "
        f"({human(os.path.getsize(path))})")


def vlastnost(props, *mena, default=""):
    """Prvá vyplnená vlastnosť z uvedených mien.

    Natural Earth aj Geofabrik menia veľkosť písmen v menách polí medzi
    vydaniami (`NAME` × `name`), takže sa skúšajú obe podoby. Keď nie je ani
    jedna, vráti sa `default` – a to, či to vadí, rozhodne kontrola počtu.
    """
    for meno in mena:
        for kandidat in (meno, meno.upper(), meno.lower()):
            hodnota = props.get(kandidat)
            if hodnota not in (None, "", -99, "-99"):
                return hodnota
    return default


# pole Natural Earth → jazyk `name:xx`, len jazyky aplikácie
JAZYKY_NE = {"AR": "ar", "DE": "de", "EL": "el", "EN": "en", "ES": "es", "FR": "fr",
             "HI": "hi", "HU": "hu", "IT": "it", "JA": "ja", "KO": "ko", "NL": "nl",
             "PL": "pl", "PT": "pt", "RU": "ru", "SV": "sv", "TR": "tr", "UK": "uk",
             "ZH": "zh-Hans", "ZHT": "zh-Hant"}


def mena_v_jazykoch(props):
    """`name:xx` z polí `NAME_XX`, prázdne vynechané."""
    out = {}
    for pole, jazyk in JAZYKY_NE.items():
        meno = vlastnost(props, f"NAME_{pole}")
        if meno:
            out[f"name:{jazyk}"] = meno
    return out


# ---------- jednotlivé vrstvy ----------

def priprav_countries(src, out):
    """Štáty → body popiskov. Z 90 polí Natural Earth si necháme štyri.

    Do dlaždíc ide z tejto vrstvy LEN ŤAŽISKO (`geometry: centroid`
    v `world.yml`) – plocha štátu sa nekreslí, pevninu robí podklad pod
    vodstvom. Polygóny sa napriek tomu nechávajú: ťažisko z nich počíta
    Planetiler a je to lepší bod než `LABEL_X/LABEL_Y`, ktoré v niektorých
    vydaniach chýbajú.
    """
    von = []
    for prvok in nacitaj_geojson(src, "štáty"):
        p = prvok.get("properties") or {}
        if not prvok.get("geometry"):
            continue
        rank = vlastnost(p, "LABELRANK", default=6)
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = 6
        von.append({
            "type": "Feature",
            "geometry": prvok["geometry"],
            "properties": {
                "name": vlastnost(p, "NAME", "NAME_EN"),
                "name_en": vlastnost(p, "NAME_EN", "NAME"),
                **mena_v_jazykoch(p),
                "iso": vlastnost(p, "ISO_A2_EH", "ISO_A2"),
                "continent": vlastnost(p, "CONTINENT"),
                # Trieda popisku miesto čísla: `include_when` v schéme
                # Planetilera porovnáva hodnoty, nie rozsahy.
                "rank": "major" if rank <= 2 else
                        ("mid" if rank <= 4 else "minor"),
            },
        })
    zapis_geojson(out, von, "countries", "štáty (popisky)")


def priprav_boundaries(src, out):
    """Hranice štátov → čiary, rozdelené na isté a sporné.

    Sporný priebeh sa kreslí prerušovane – mapa nemá tvrdiť, že hranica, na
    ktorej sa strany nezhodnú, je istá.
    """
    von = []
    for prvok in nacitaj_geojson(src, "hranice štátov"):
        p = prvok.get("properties") or {}
        if not prvok.get("geometry"):
            continue
        cla = str(vlastnost(p, "FEATURECLA")).lower()
        von.append({
            "type": "Feature",
            "geometry": prvok["geometry"],
            "properties": {
                "kind": "country" if "international" in cla else "disputed",
            },
        })
    zapis_geojson(out, von, "boundaries", "hranice štátov")


def priprav_lakes(src, out):
    """Jazerá → plochy. Veľké idú do mapy skôr než malé."""
    von = []
    for prvok in nacitaj_geojson(src, "jazerá"):
        p = prvok.get("properties") or {}
        if not prvok.get("geometry"):
            continue
        rank = vlastnost(p, "SCALERANK", default=8)
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = 8
        von.append({
            "type": "Feature",
            "geometry": prvok["geometry"],
            "properties": {
                "kind": "lake",
                "name": vlastnost(p, "NAME"),
                "rank": "major" if rank <= 2 else "minor",
            },
        })
    zapis_geojson(out, von, "lakes", "jazerá")


def priprav_downloads(src, out):
    """Geofabrik `index-v1.json` → regióny sťahovania s úrovňou v strome.

    ÚROVEŇ SA POČÍTA, NEČÍTA. V súbore je pri každom regióne len `parent`,
    takže hĺbka vznikne prejdením reťaze rodičov: svetadiel (`continent`) →
    štát (`country`) → výsek (`subregion`). Podľa nej sa v schéme rozhoduje,
    od ktorého zoomu je región v dlaždiciach – všetkých ~500 naraz je pri
    pohľade na celý svet nečitateľná kaša.
    """
    prvky = nacitaj_geojson(src, "regióny sťahovania")
    rodic = {}
    for prvok in prvky:
        p = prvok.get("properties") or {}
        if p.get("id"):
            rodic[p["id"]] = p.get("parent") or ""

    def hlbka(ident):
        krok, videne = 0, set()
        while rodic.get(ident) and ident not in videne:
            videne.add(ident)
            ident = rodic[ident]
            krok += 1
            if krok > 10:      # kruh v dátach – radšej strop než nekonečno
                break
        return krok

    UROVNE = ("continent", "country", "subregion")
    von = []
    for prvok in prvky:
        p = prvok.get("properties") or {}
        if not prvok.get("geometry") or not p.get("id"):
            continue
        urls = p.get("urls") or {}
        von.append({
            "type": "Feature",
            "geometry": prvok["geometry"],
            "properties": {
                "id": p["id"],
                "name": p.get("name") or p["id"],
                "parent": p.get("parent") or "",
                "level": UROVNE[min(hlbka(p["id"]), len(UROVNE) - 1)],
                # Odkaz, ktorý sa dá naozaj stiahnuť – kvôli nemu to celé je.
                "pbf": urls.get("pbf") or "",
            },
        })
    bez_odkazu = sum(1 for f in von if not f["properties"]["pbf"])
    if bez_odkazu:
        log(f"::warning::{bez_odkazu} regiónov nemá v indexe odkaz na `.pbf` – "
            f"v mape budú, ale bez odkazu na stiahnutie.")
    zapis_geojson(out, von, "downloads", "regióny sťahovania")


def priprav_water(zip_path, out):
    """Vodné plochy z OSM: shapefile v EPSG:3857 → GeoPackage v EPSG:4326.

    PREČO OGR2OGR A NIE PRIAMO SHAPEFILE DO PLANETILERU. Zdroj je v Mercatore
    a v ZIPe; Planetiler síce shapefile prečíta, ale premietnutie by záviselo
    od toho, ako si vyloží `.prj`. Prevod tu je vidieť v logu a výsledok sa dá
    otvoriť a pozrieť – rovnako ako pri vrstevniciach (`gdal_contour` →
    GeoPackage → schéma).
    """
    if shutil.which("ogr2ogr") is None:
        raise SystemExit(
            "::error::`ogr2ogr` tu nie je. Vodné plochy sú shapefile "
            "v EPSG:3857 a treba ich premietnuť – doinštaluj `gdal-bin` "
            "(v pipeline to robí `workers/world/build.sh`).")
    # Meno súboru vnútri ZIPu sa medzi vydaniami mení, tak sa hľadá.
    with zipfile.ZipFile(zip_path) as z:
        shp = [n for n in z.namelist() if n.lower().endswith(".shp")]
    if not shp:
        raise SystemExit(
            f"::error::V `{zip_path}` nie je ani jeden `.shp`. Stiahol sa "
            f"celý súbor? Zmaž ho a pusti beh znova.")
    vstup = f"/vsizip/{os.path.abspath(zip_path)}/{shp[0]}"
    log(f"  vodné plochy: {shp[0]} v ZIPe → {out}")
    t0 = time.time()
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(
        ["ogr2ogr", "-f", "GPKG", out, vstup,
         "-nln", "water", "-t_srs", "EPSG:4326",
         "-nlt", "PROMOTE_TO_MULTI", "-makevalid",
         "-progress"],
        check=True)
    # Že v tom niečo je, sa musí OVERIŤ – prázdny GeoPackage je platný súbor
    # a mapa by z neho vyšla bez mora, bez jediného varovania.
    pocet = subprocess.run(
        ["ogrinfo", "-so", out, "water"],
        capture_output=True, text=True, check=False).stdout
    riadok = [r for r in pocet.split("\n") if "Feature Count" in r]
    kolko = int(riadok[0].split(":")[-1].strip()) if riadok else 0
    if kolko < MINIMUM["water"]:
        raise SystemExit(
            f"::error::Vodné plochy: v `{out}` je {kolko} prvkov, čakalo sa "
            f"aspoň {MINIMUM['water']}. Mapa by bola bez mora – pozri log "
            f"`ogr2ogr` vyššie.")
    log(f"  vodné plochy: {kolko} plôch za {cas(time.time() - t0)} "
        f"({human(os.path.getsize(out))})")


# ---------- beh ----------

KROKY = ("water", "boundaries", "countries", "lakes", "downloads")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/world",
                    help="kam pripravené podklady (default data/world)")
    # ZOZNAM, nie jedna vrstva: podoba `basic` mapy sveta chce hranice, štáty
    # a regióny sťahovania, ale NIE vodstvo – a ktoré to sú, vie
    # `workers/world/variant.py` z toho, na čo sa vrstvy schémy odkazujú.
    # Jedno meno ostáva platné, je to ten istý zápis o jednom prvku.
    ap.add_argument("--only", default="",
                    help="len tieto vrstvy, oddelené čiarkou: " + ", ".join(KROKY))
    args = ap.parse_args()

    kroky = ([k.strip() for k in args.only.split(",") if k.strip()]
             if args.only else list(KROKY))
    for k in kroky:
        if k not in KROKY:
            raise SystemExit(f"::error::`--only={k}` nepoznám. Vrstvy sú: "
                             f"{', '.join(KROKY)}.")
    if not kroky:
        raise SystemExit("::error::`--only` nedostal ani jednu vrstvu. "
                         f"Vrstvy sú: {', '.join(KROKY)}.")

    zdroje = os.path.join(args.out, "zdroje")
    os.makedirs(zdroje, exist_ok=True)

    # PLÁN S ODHADOM PRED DRAHOU ČASŤOU (pravidlo 4 v CLAUDE.md): hodina ticha
    # v logu sa nedá odlíšiť od zaseknutého behu, a to, čo tu trvá, je cudzia
    # sieť.
    spolu = sum(ZDROJE[k]["mb"] for k in kroky)
    log(f"Podklady pre mapu sveta – {len(kroky)} zdrojov, spolu ~{spolu:.0f} MB "
        f"na stiahnutie:")
    for i, k in enumerate(kroky, 1):
        log(f"  [{i}/{len(kroky)}] {ZDROJE[k]['popis']} (~{ZDROJE[k]['mb']:.0f} MB)")
    if "water" in kroky:
        log("Prevod vodných plôch (ogr2ogr) je z toho to najdlhšie – rátaj "
            "s jednotkami minút.")

    t_celkom = time.time()
    namerane = []
    for i, k in enumerate(kroky, 1):
        log(f"::group::[{i}/{len(kroky)}] {ZDROJE[k]['popis']}")
        t0 = time.time()
        src = stiahni(k, zdroje)
        if k == "water":
            priprav_water(src, os.path.join(args.out, "water.gpkg"))
        elif k == "boundaries":
            priprav_boundaries(src, os.path.join(args.out, "boundaries.geojson"))
        elif k == "countries":
            priprav_countries(src, os.path.join(args.out, "countries.geojson"))
        elif k == "lakes":
            priprav_lakes(src, os.path.join(args.out, "lakes.geojson"))
        elif k == "downloads":
            priprav_downloads(src, os.path.join(args.out, "downloads.geojson"))
        namerane.append((k, time.time() - t0))
        log("::endgroup::")

    # NAMERANÉ ČÍSLA NA KONCI – z nich sa opravujú odhady vyššie.
    log("Podklady sú hotové:")
    for k, sek in namerane:
        log(f"  {k:<11} {cas(sek):>8}")
    log(f"  {'spolu':<11} {cas(time.time() - t_celkom):>8}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"::error::Príkaz `{' '.join(exc.cmd[:2])}` skončil s kódom "
              f"{exc.returncode} – vyššie v logu je, na čom.")
        sys.exit(1)
