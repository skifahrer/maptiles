#!/usr/bin/env python3
"""Katalóg máp `maps.json` – čo sa doň píše a kam.

Volá to `publish-map.py`; `catalog.sh` ten istý súbor commitne. Samostatne sa
dá spýtať len `--subor` (ostrý alebo testovací katalóg).
"""
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
_DRIVE = os.path.join(_WORKERS, "drive")


def _load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


folder = _load("drive_folder", os.path.join(_DRIVE, "folder.py"))
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))
katalog_balikov = _load("deploy_baliky", os.path.join(_HERE_DIR, "baliky.py"))


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def log(msg):
    print(msg, flush=True)


def rozdel_test(key):
    """`vysoke_tatry_test4km2` → (`vysoke_tatry`, `4`), inak `(key, "")`."""
    cut = key.rfind("_test")
    if cut < 0 or not key.endswith("km2"):
        return key, ""
    stred = key[cut + 5:-3]
    return (key[:cut], stred) if stred.replace(".", "").isdigit() else (key, "")


# jedno miesto, ktoré hovorí, ktorý katalóg sa píše – pýtajú sa naň traja
KATALOG = "maps.json"
KATALOG_TEST = "maps-test.json"


def katalog_subor(base=KATALOG):
    """`maps.json`, alebo `maps-test.json` pri teste. Prázdne = nezapisuj."""
    if not base:
        return ""
    test_km2 = env("TEST_KM2", "0")
    if test_km2 in ("", "0"):
        return base
    koren, _, pripona = base.rpartition(".")
    kmen = koren or base
    # `-test` sa nesmie pripojiť dvakrát: odpoveď chodí pipeline ďalej
    if kmen.endswith("-test"):
        return base
    return f"{kmen}-test" + (f".{pripona}" if koren else "")


def region_entry(man):
    """Položka regiónu z `manifest.json` – zoomy, bbox, zdroje výšok."""
    key = man.get("default_region")
    return ((man.get("regions") or {}).get(key) or {}) if key else {}


VRSTVY_TILES = ("pmtiles", "contours", "rocks", "trails", "features", "points",
                "transport", "boundaries", "water")


def tiles_paths(man, reg):
    """Cesty k `.pmtiles` v balíku; berú sa z manifestu, z kľúča sa odvodiť nedajú."""
    out = {k: reg[k] for k in VRSTVY_TILES if reg.get(k)}
    dem = (man.get("dem") or "").rstrip("/")
    if dem.endswith(".pmtiles"):
        out["terrain"] = "tiles/" + dem.rsplit("/", 1)[-1]
    return out


# jediný zoznam hotových máp; štruktúra sedí s cestou na Drive, `_` = metadáta

def katalog_meno(regions, key, kind):
    """Ľudské meno kraja/výseku/krajiny – z číselníkov, nie vymyslené."""
    key, test = rozdel_test(key)
    chvost = f" – rýchly test {test} km²" if test else ""
    if kind == "area":
        try:
            with open(os.path.join(_DATA, "areas.json")) as f:
                meno = (json.load(f).get(key) or {}).get("name") or key
        except (OSError, ValueError):
            meno = key
        return meno + chvost
    r = regions.get(key) or {}
    return (r.get("name") or key) + chvost


# dva zápisy toho istého okamihu: `…_at` sa číta očami, `…_ts` sa odčítava
def teraz():
    """(ISO 8601 UTC, sekundy od epochy) – jeden okamih v oboch podobách."""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), int(t)


def zapis_balik(mapy, kind, name, velkost, fid, fmt, kedy="", kedy_ts=None):
    """Jeden balík v jednom formáte do `maps` položky katalógu.

    Vrch položky ukazuje na ZIP kvôli starším čitateľom, `.aar` ho neprepisuje.
    """
    zaznam = {
        "file": name,
        "size": velkost,
        "link": folder.file_link(fid),
        "download": folder.download_link(fid),
        # pôvod je pri balíku, nie len pri kraji: wiki robí iná pipeline
        "run": env("GITHUB_RUN_NUMBER"),
    }
    if kedy:
        zaznam["updated_at"] = kedy
    if kedy_ts is not None:
        zaznam["updated_ts"] = kedy_ts
    polozka = mapy.setdefault(kind or "mapa", {})
    polozka.setdefault("formats", {})[fmt] = zaznam
    if fmt == "zip":
        polozka.update(zaznam)
    # meno a ikona balíka z číselníka; kľúč, ktorý v ňom nie je, sa nedopĺňa
    try:
        meta = katalog_balikov.balik(kind or "mapa")
    except SystemExit:
        return
    polozka["app"] = meta["app"]
    polozka["symbol"] = meta["symbol"]
    polozka["popis"] = meta["popis"]


# odkaz, za ktorým už súbor nie je; `zive=None` = neoverovalo sa, nemaže sa nič

def odkaz_id(zaznam):
    """Id súboru z `download`/`link` jedného zápisu balíka, alebo ""."""
    if not isinstance(zaznam, dict):
        return ""
    return (folder.id_z_odkazu(zaznam.get("download"))
            or folder.id_z_odkazu(zaznam.get("link")))


def mrtvy(zaznam, zive, chranene):
    """Ukazuje tento zápis na súbor, ktorý na Drive už nie je?"""
    fid = odkaz_id(zaznam)
    return bool(fid) and fid not in zive and fid not in chranene


def ozivenie(zaznam, zive):
    """Nové id súboru toho istého mena v priečinku, alebo "".

    Mŕtvy odkaz väčšinou znamená, že sa zápis katalógu nedostal do vetvy –
    súbor tam je, len pod novým id. Pri dvoch zhodách radšej nič.
    """
    meno = zaznam.get("file") if isinstance(zaznam, dict) else None
    if not meno:
        return ""
    zhody = [fid for fid, nazov in zive.items() if nazov == meno]
    return zhody[0] if len(zhody) == 1 else ""


def oziv(zaznam, zive):
    """Prepíš odkazy zápisu na živý súbor toho mena. True = podarilo sa."""
    fid = ozivenie(zaznam, zive)
    if not fid:
        return False
    zaznam["link"] = folder.file_link(fid)
    zaznam["download"] = folder.download_link(fid)
    return True


def precisti_mrtve(mapy, zive, chranene=()):
    """Zrovnaj odkazy položky so skutočným priečinkom. `(opravené, vyhodené)`.

    Ide po formátoch, nie po balíkoch; vrch položky je zrkadlo ZIPu, prepisuje
    sa tiež.
    """
    opravene, vyhodene = [], []
    for kind in sorted(mapy):
        polozka = mapy[kind]
        if not isinstance(polozka, dict):
            continue
        padli = []
        formaty = polozka.get("formats")
        if isinstance(formaty, dict):
            for fmt in sorted(formaty):
                if not mrtvy(formaty[fmt], zive, chranene):
                    continue
                popis = f"{kind}/{fmt} ({formaty[fmt].get('file') or '?'})"
                if oziv(formaty[fmt], zive):
                    opravene.append(popis)
                else:
                    padli.append(popis)
                    del formaty[fmt]
            if not formaty:
                polozka.pop("formats", None)
        zive_formaty = polozka.get("formats") or {}
        if zive_formaty:
            if mrtvy(polozka, zive, chranene):
                polozka.update(zive_formaty.get("zip")
                               or zive_formaty[sorted(zive_formaty)[0]])
            vyhodene += padli
            continue
        # bez formátov rozhoduje sám vrch; jedna hláška, nie dve
        if mrtvy(polozka, zive, chranene):
            popis = f"{kind} ({polozka.get('file') or '?'})"
            if oziv(polozka, zive):
                opravene.append(popis)
                vyhodene += padli
            else:
                vyhodene.append(popis)
                del mapy[kind]
        else:
            vyhodene += padli
    return opravene, vyhodene


def uprac(mapy, zrusene=(), zive=None, chranene=()):
    """Vyhoď z položky, čo do nej už nepatrí – a povedz o tom."""
    for kind in zrusene:
        if mapy.pop(kind, None) is not None:
            log(f"Balík `{kind}` už neexistuje (obsah je v základnej mape) – "
                f"z položky katalógu vypadol.")
    if zive is None:
        return
    opravene, vyhodene = precisti_mrtve(mapy, zive, chranene)
    for popis in opravene:
        log(f"::warning::Odkaz na {popis} v katalógu ukazoval do prázdna, ale "
            f"súbor toho mena v priečinku mapy JE – prepísal som odkaz naň. "
            f"(Balík nahral beh, ktorému sa zápis katalógu nedostal do vetvy.)")
    for popis in vyhodene:
        log(f"::warning::V katalógu bol odkaz na {popis}, ale taký súbor "
            f"v priečinku mapy na Drive nie je ani pod iným id – vypadol.")


def zapis(path, data, popis):
    """Zapíše katalóg, keď sa naozaj zmenil. True = súbor je iný.

    Minifikovane (číta to appka), ale `sort_keys=True` – nech `git diff` ukáže
    len skutočnú zmenu.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True) + "\n"
    try:
        with open(path) as f:
            if f.read() == text:
                log(f"{path}: to isté ako doteraz – bez zmeny.")
                return False
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(text)
    log(f"{path}: {popis}")
    return True


def zapis_casti(mapy, casti):
    """Koľko z balíka `mapa` je hľadanie.

    Hľadanie nemá vlastný balík, takže inde sa jeho veľkosť nedá prečítať.
    Píše sa aj `0`; `casti` sa prepisuje, nie dopĺňa. `raw_size` je pred
    zabalením, `size` po ňom.
    """
    polozka = mapy.get("mapa")
    if polozka is None:
        return                        # tento beh základnú mapu nenahral
    if not casti:
        polozka.pop("casti", None)
        return
    polozka["casti"] = {k: dict(v) for k, v in casti.items()}


def zapis_katalog(path, parts, regions, baliky, man, iba="", merge=False,
                  kat=None, layers=None, spravuje=None, casti=None,
                  zrusene=(), zive=None):
    """Doplň (alebo prepíš) položku v `maps.json`. Vracia True, keď sa zmenil.

    `baliky` je `(druh, meno, veľkosť, id, formát)` toho, čo sa nahralo.
    `kat` je cesta v katalógu, keď sa líši od cesty na Drive (rýchly test).
    `merge=True` = beh nahral len ďalší formát, balíky sa dopĺňajú.
    `casti` = kúsky bez vlastného balíka; `None` = tento beh ich nepočítal.
    `spravuje` = druhy balíkov, o ktorých beh rozhoduje; ostatné ostávajú.
    `zrusene` = balíky, ktoré už neexistujú – vypadnú vždy.
    `zive` = id súborov, čo na Drive teraz sú; `None` = neoverovalo sa.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    je_test = os.path.basename(path) == KATALOG_TEST
    data.setdefault("_comment",
                    ("Rýchle TESTOVACIE behy" if je_test else
                     "Katalóg hotových máp na Google Drive")
                    + " – ktoré sú a kde. "
                    + ("Terén (vrstevnice, skaly, tieňovanie) je v nich len na "
                       "pár km² zo stredu výrezu, takže to NIE SÚ mapy na "
                       "stiahnutie; hotové mapy sú v maps.json. " if je_test
                       else "")
                    + "Hlavný kľúč je krajina, pod ňou `regions` (kraj) a "
                    "`subregions` (výsek); kľúče na `_` sú metadáta katalógu, "
                    "nie krajiny. Dopisuje ho na konci buildu "
                    "workers/deploy/publish-map.py (krok „Zapíš mapu do "
                    "maps.json“); ručne sa needituje. Odkazy otvorí ten, kto "
                    "má prístup k priečinku s mapami.")
    data["_updated_at"], data["_updated_ts"] = teraz()

    kat = kat or parts
    krajina = data.setdefault(kat[0], {})
    krajina.setdefault("name", katalog_meno(regions, kat[0], "region"))
    uzol = krajina                      # build celej krajiny končí tu
    if len(kat) > 1:
        regs = krajina.setdefault("regions", {})
        uzol = regs.setdefault(kat[1], {})
        uzol.setdefault("name", katalog_meno(regions, kat[1], "region"))
    if len(kat) > 2:
        subs = uzol.setdefault("subregions", {})
        uzol = subs.setdefault(kat[2], {})
        uzol.setdefault("name", katalog_meno(regions, kat[2], "area"))

    reg = region_entry(man)
    if iba:
        # doplnenie, nie prepis: samostatná pipeline vie len o svojom balíku
        uzol.setdefault("name", katalog_meno(regions, kat[-1], "region"))
        uzol.setdefault("drive", "/".join(parts))
        # `updated_at` a `run` pri kraji hovoria, ktorý beh vyrobil mapu
        uzol.setdefault("updated_at", data["_updated_at"])
        uzol.setdefault("updated_ts", data["_updated_ts"])
        uzol.setdefault("run", env("GITHUB_RUN_NUMBER"))
        mapy = uzol.setdefault("maps", {})
        for kind, name, velkost, fid, fmt in baliky:
            zapis_balik(mapy, kind, name, velkost, fid, fmt,
                        kedy=data["_updated_at"], kedy_ts=data["_updated_ts"])
        # `casti` sa tu neprepisujú; zrušený balík a mŕtvy odkaz sa upratujú
        uprac(mapy, zrusene, zive, {fid for _k, _n, _v, fid, _f in baliky})
        return zapis(path, data,
                     f"doplnený balík {iba} k {'/'.join(kat)}")
    polozka = {
        "name": uzol.get("name"),
        "drive": "/".join(parts),
        # čas tohto behu; položka sa zapisuje celá, takže vznik = prepis
        "updated_at": data["_updated_at"],
        "updated_ts": data["_updated_ts"],
        "run": env("GITHUB_RUN_NUMBER"),
        "layers": list(layers or []),
        # balík × formát; vrch položky ukazuje na ZIP kvôli starším čitateľom
        "maps": {},
    }
    # čo treba vedieť pri výbere, nie až po rozbalení. Strop zoomu musí byť pri
    # každej vrstve, čo ho má vlastný, a každá vrstva z DEM musí povedať zdroj.
    for k in ("bbox", "maxzoom", "contours_maxzoom", "contour_interval",
              "rocks_maxzoom", "rock_slope", "dem_source", "rock_source",
              "trails_maxzoom", "features_maxzoom", "points_maxzoom",
              "transport_maxzoom", "boundaries_maxzoom", "water_maxzoom"):
        if reg.get(k) is not None:
            polozka[k] = reg[k]
    # cesty k dlaždiciam sa neodvodzujú z kľúča uzla (viď `tiles_paths`)
    tiles = tiles_paths(man, reg)
    if tiles:
        polozka["tiles"] = tiles
    if tiles.get("terrain"):
        if man.get("dem_maxzoom") is not None:
            polozka["terrain_maxzoom"] = man["dem_maxzoom"]
        if man.get("dem_source"):
            polozka["terrain_source"] = man["dem_source"]
    area_bbox = env("AREA_BBOX")
    test_km2 = env("TEST_KM2", "0")
    if test_km2 not in ("", "0"):
        # pri teste najdôležitejšie číslo: mapa je kraj, terén len ten štvorec
        polozka["test_km2"] = test_km2
    if area_bbox and (len(parts) > 2 or test_km2 not in ("", "0")):
        try:
            polozka["area_bbox"] = [float(v) for v in area_bbox.split(",")]
        except ValueError:
            pass
    stare_maps = uzol.get("maps") or {}
    if merge:
        polozka["maps"] = {k: dict(v) for k, v in stare_maps.items()}
    else:
        # prepis sa týka len toho, o čom tento beh rozhoduje
        if spravuje is None:
            raise SystemExit(
                "::error::`zapis_katalog` bez `spravuje=`: nedá sa povedať, "
                "ktoré balíky tento beh rieši a ktoré patria inej pipeline. "
                "Podaj druhy z `baliky` (robí to `publish-map.py`).")
        riesi = set(spravuje)
        polozka["maps"] = {k: dict(v) for k, v in stare_maps.items()
                           if k not in riesi}
    if merge:
        # čo tento beh nevie, to nesmie zmazať – pri `merge` je základom katalóg
        zaklad = {k: v for k, v in uzol.items()
                  if k not in ("maps", "regions", "subregions")}
        zaklad.update(polozka)
        polozka = zaklad
    for kind, name, velkost, fid, fmt in baliky:
        zapis_balik(polozka["maps"], kind, name, velkost, fid, fmt,
                    kedy=data["_updated_at"], kedy_ts=data["_updated_ts"])
    if casti is not None:
        zapis_casti(polozka["maps"], casti)
    # až teraz, keď sú v položke aj balíky tohto behu; tie sú `chranene`
    uprac(polozka["maps"], zrusene, zive,
          {fid for _k, _n, _v, fid, _f in baliky})

    # `subregions` patria uzlu, nie tejto mape
    zachovaj = {k: uzol[k] for k in ("regions", "subregions") if k in uzol}
    uzol.clear()
    uzol.update(polozka)
    uzol.update(zachovaj)

    # koľko balíkov ostalo po inej pipeline – nech je to vidieť na logu
    cudzie = [k for k in polozka["maps"]
              if k not in {(kind or "mapa") for kind, *_ in baliky}]
    return zapis(path, data, f"zapísaná mapa {'/'.join(kat)} "
                             f"({len(polozka['maps'])} balíkov, "
                             + (f"z toho {len(cudzie)} z inej pipeline "
                                f"({', '.join(sorted(cudzie))}), " if cudzie else "")
                             + f"priečinok {'/'.join(parts)})")


if __name__ == "__main__":
    # jediná otázka, na ktorú sa dá spýtať z príkazového riadka
    if sys.argv[1:] == ["--subor"]:
        print(katalog_subor())
    else:
        raise SystemExit(
            "::error::workers/deploy/catalog.py sa samostatne pýta len na "
            "`--subor` (ktorý katalóg zapisovať – maps.json, alebo pri "
            "rýchlom teste maps-test.json). Katalóg zapisuje "
            "workers/deploy/publish-map.py.")
