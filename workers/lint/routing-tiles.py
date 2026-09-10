#!/usr/bin/env python3
"""Čo nie je v slovníku, sa do telefónu nedostane – a nikto to nepovie.

  1. slovník: každý kľúč má práve jeden druh a vymenované hodnoty sú platné;
  2. trieda, podľa ktorej sa way berie do grafu, sa aj vezie;
  3. voľba profilu stojí na `key=value`, ktoré slovník pozná;
  4. krajina so známkou musí byť medzi hodnotami `krajina`;
  5. telo dlaždice sa zapíše a prečíta na to isté;
  6. archívy behu (keď sú zadané): jeden slovník, jedno poradie, dlaždice
     v rozpočte a prekryv susedov sa nesmie rozísť.
"""
import argparse
import gzip
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
REL_TAGS = "workers/data/routing-tags.json"


def load(name, filename, folder):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_WORKERS, folder, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Lint:
    def __init__(self):
        self.bad = 0

    def err(self, path, msg):
        print(f"::error file={path}::{msg}")
        self.bad += 1


def skus_telo(fmt, lint):
    """Zápis a čítanie musia dať to isté – inak sa archív číta ako iný graf."""
    d = {"vyska": False, "poradie": True, "slovnik_id": 0x01020304,
         "poradie_id": 0x05060708, "zxy": [9, 283, 175],
         "bbox": [1, -2, 3, 4],
         "uzly": [(10, 490000000, 190000000, 0, 1),
                  (2000000000000, 490010000, 190020000, 0, 9)],
         "hrany": [{"od": 0, "do": 1, "tagset": 0, "dlzka_cm": 1234,
                    "smer": fmt.S_VPRED, "geom": [(490005000, 190010000)]}],
         "tagsety": [[(0, 1), (4, 0)]], "retazce": ["Hlavná"],
         "zakazy": [{"druh": 0, "vynimky": 3, "hrany": [(10, 20), (20, 30)]}],
         "okraj": [1]}
    try:
        spat = fmt.citaj(fmt.zapis(d))
    except Exception as e:                                        # noqa: BLE001
        lint.err("workers/routing/format.py",
                 f"telo dlaždice sa nedá prečítať späť: {type(e).__name__}: {e}")
        return
    for kluc, cakane in d.items():
        if spat[kluc] != cakane:
            lint.err("workers/routing/format.py",
                     f"pole `{kluc}` sa po zápise a čítaní zmenilo "
                     f"({cakane} → {spat[kluc]}). Telefón by na tom mieste "
                     f"čítal iný graf a trasa by vyšla – len iná.")


def slovnik_sam(slovnik, raw, lint):
    for kluc, spec in raw["kluce"].items():
        druhy = [k for k in ("z_siete", "pristup", "hodnoty", "cislo", "volny")
                 if spec.get(k)]
        if len(druhy) != 1:
            lint.err(REL_TAGS, f"kľúč `{kluc}` má druhy {druhy or '—'}; má mať "
                               f"práve jeden. Dva druhy znamenajú dve kódovania "
                               f"tej istej hodnoty.")
    for kluc in slovnik.kluce:
        hodnoty = slovnik.hodnoty[kluc]
        if slovnik.druh[kluc] == "hodnoty" and not hodnoty:
            lint.err(REL_TAGS, f"kľúč `{kluc}` je vymenovaný, ale nemá ani "
                               f"jednu hodnotu – zahodí sa každá.")
        if len(set(hodnoty)) != len(hodnoty):
            lint.err(REL_TAGS, f"kľúč `{kluc}` má hodnotu dvakrát. Index by "
                               f"ukázal na prvú a druhá by sa nedala zapísať.")
    for kluc in slovnik.siet:
        if slovnik.druh.get(kluc) != "hodnoty":
            lint.err(REL_TAGS, f"`siet` berie way podľa `{kluc}`, ale ten kľúč "
                               f"sa nevezie. Používateľ by si vypol typ cesty, "
                               f"ktorý v archíve nie je, a trasa by po ňom "
                               f"viedla ďalej.")


def profil_proti_slovniku(slovnik, lint):
    with open(os.path.join(_DATA, "routing-profiles.json"), encoding="utf-8") as f:
        options = json.load(f)["options"]
    for key, spec in options.items():
        if not isinstance(spec, dict):
            continue
        for para in spec.get("osm") or []:
            kluc, _, hodnota = para.partition("=")
            if slovnik.index(kluc) is None:
                lint.err(REL_TAGS,
                         f"voľba `{key}` stojí na `{para}`, ale kľúč `{kluc}` "
                         f"do dlaždice nejde. V telefóne sa tá voľba nemá "
                         f"o čo oprieť a ticho nespraví nič.")
            elif slovnik.hodnota_index(kluc, hodnota) is None:
                lint.err(REL_TAGS,
                         f"voľba `{key}` stojí na `{para}`, ale hodnota "
                         f"`{hodnota}` nie je medzi hodnotami `{kluc}`. "
                         f"`tiles.py` ju zahodí a voľba nespraví nič.")


def znamky_proti_slovniku(slovnik, lint):
    with open(os.path.join(_DATA, "vignettes.json"), encoding="utf-8") as f:
        krajiny = json.load(f)["countries"]
    for kod, c in krajiny.items():
        if not c.get("ma_znamku"):
            continue
        if slovnik.hodnota_index("krajina", kod) is None:
            lint.err(REL_TAGS,
                     f"`{kod}` má diaľničnú známku, ale nie je medzi hodnotami "
                     f"`krajina`. Hrana by o svojej krajine nepovedala nič "
                     f"a známka by sa nemala k čomu vzťahovať.")


def archivy(cesty, slovnik, fmt, lint):
    try:
        from pmtiles.reader import MmapSource, Reader, all_tiles
    except ImportError:
        lint.err("workers/lint/routing-tiles.py",
                 "archívy sa majú skontrolovať, ale `pmtiles` v tomto "
                 "prostredí nie je (`pip install pmtiles`).")
        return
    poradia, obsah = {}, {}
    for cesta in cesty:
        with open(cesta, "rb") as f:
            r = Reader(MmapSource(f))
            graf = (r.metadata() or {}).get("graf")
            if not graf:
                lint.err(cesta, "archív nemá v metadátach `graf`, takže o sebe "
                                "nepovie ani formát, ani slovník. Nesúlad "
                                "verzií vyzerá ako pokazená trasa.")
                continue
            if graf.get("slovnik") != f"{slovnik.id:08x}":
                lint.err(cesta, f"archív je proti slovníku `{graf.get('slovnik')}`, "
                                f"kým v repozitári je `{slovnik.id:08x}`. Index "
                                f"značky by ukazoval na inú hodnotu – postav "
                                f"archív znova.")
            poradia.setdefault(graf.get("poradie"), []).append(cesta)
            for (z, x, y), telo in all_tiles(MmapSource(f)):
                if len(telo) > fmt.ROZPOCET_KB * 1024:
                    lint.err(cesta, f"dlaždica {z}/{x}/{y} má {len(telo)//1024} kB, "
                                    f"čo je nad rozpočtom {fmt.ROZPOCET_KB} kB.")
                try:
                    d = fmt.citaj(gzip.decompress(telo))
                except Exception as e:                            # noqa: BLE001
                    lint.err(cesta, f"dlaždica {z}/{x}/{y} sa nedá prečítať: "
                                    f"{type(e).__name__}: {e}")
                    continue
                if d["zxy"] != [z, x, y]:
                    lint.err(cesta, f"dlaždica {z}/{x}/{y} sa vnútri hlási ako "
                                    f"{d['zxy']} – archív by sa spojil na "
                                    f"nesprávnom mieste.")
                _tagsety(cesta, z, x, y, d, slovnik, lint)
                obsah.setdefault((z, x, y), {})[cesta] = d
    if len(poradia) > 1:
        lint.err("workers/routing/order.py",
                 "archívy jedného behu majú rôzne poradie uzlov: "
                 + "; ".join(f"{p or 'žiadne'} → {', '.join(map(os.path.basename, c))}"
                             for p, c in poradia.items())
                 + ". Spojiť sa nesmú a klient to musí odmietnuť.")
    _prekryv(obsah, lint)


def _tagsety(cesta, z, x, y, d, slovnik, lint):
    for i, ts in enumerate(d["tagsety"]):
        for kluc_idx, kod in ts:
            if kluc_idx >= len(slovnik.kluce):
                lint.err(cesta, f"dlaždica {z}/{x}/{y}, sada značiek {i} má "
                                f"kľúč {kluc_idx}, ktorý slovník nemá.")
                continue
            kluc = slovnik.kluce[kluc_idx]
            if slovnik.druh[kluc] == "hodnoty" and kod >= len(slovnik.hodnoty[kluc]):
                lint.err(cesta, f"dlaždica {z}/{x}/{y}: `{kluc}` má hodnotu "
                                f"{kod}, ale slovník ich má "
                                f"{len(slovnik.hodnoty[kluc])}.")
            if slovnik.druh[kluc] == "volny" and kod >= len(d["retazce"]):
                lint.err(cesta, f"dlaždica {z}/{x}/{y}: `{kluc}` ukazuje na "
                                f"reťazec {kod}, ktorý v dlaždici nie je.")


def _prekryv(obsah, lint):
    """Tú istú hranu musia dva archívy povedať rovnako – inak sa spojiť nedá."""
    spolocne, rozporov = 0, 0
    for zxy, podla_archivu in obsah.items():
        if len(podla_archivu) < 2:
            continue
        spolocne += 1
        cesty = list(podla_archivu)
        prvy = _hrany_podla_id(podla_archivu[cesty[0]])
        for dalsi in cesty[1:]:
            druhy = _hrany_podla_id(podla_archivu[dalsi])
            rozpor = [k for k in set(prvy) & set(druhy) if prvy[k] != druhy[k]]
            if rozpor:
                rozporov += 1
                lint.err(dalsi, f"dlaždica {zxy[0]}/{zxy[1]}/{zxy[2]} je aj "
                                f"v {os.path.basename(cesty[0])} a {len(rozpor)} "
                                f"spoločných hrán sa v nich líši. Telefón ich "
                                f"spája podľa OSM id, takže by si vybral jednu "
                                f"z dvoch právd.")
    if spolocne and not rozporov:
        print(f"  prekryv susedov: {spolocne} spoločných dlaždíc, hrany sedia")


def _hrany_podla_id(d):
    von = {}
    for h in d["hrany"]:
        kluc = (d["uzly"][h["od"]][0], d["uzly"][h["do"]][0])
        von[kluc] = (h["dlzka_cm"], h["smer"],
                     tuple(sorted(d["tagsety"][h["tagset"]])),
                     tuple(d["retazce"][k] for _, k in
                           sorted(d["tagsety"][h["tagset"]])
                           if k < len(d["retazce"])))
    return von


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivy", nargs="*",
                    help="`.pmtiles` behu – bez nich sa kontroluje len číselník")
    args = ap.parse_args()

    lint = Lint()
    fmt = load("routing_format", "format.py", "routing")
    tags = load("routing_tags", "tags.py", "routing")
    slovnik = tags.slovnik()
    with open(os.path.join(_DATA, "routing-tags.json"), encoding="utf-8") as f:
        raw = json.load(f)

    if len(set(fmt.DRUHY_ZAKAZOV)) != len(fmt.DRUHY_ZAKAZOV):
        lint.err("workers/routing/format.py", "`DRUHY_ZAKAZOV` má druh dvakrát "
                                              "– index by ukázal na prvý.")
    if len(set(fmt.VYNIMKY)) != len(fmt.VYNIMKY):
        lint.err("workers/routing/format.py", "`VYNIMKY` má vozidlo dvakrát.")

    slovnik_sam(slovnik, raw, lint)
    profil_proti_slovniku(slovnik, lint)
    znamky_proti_slovniku(slovnik, lint)
    skus_telo(fmt, lint)
    if args.archivy:
        archivy(args.archivy, slovnik, fmt, lint)

    if lint.bad:
        print(f"\n{lint.bad} problém(ov) v smerovacích dlaždiciach.")
        return 1
    print(f"Smerovacie dlaždice sú celé: slovník `{slovnik.id:08x}` v{slovnik.verzia} "
          f"({len(slovnik.kluce)} kľúčov) pokrýva každú voľbu profilu aj každú "
          f"krajinu so známkou, telo dlaždice sa číta späť na to isté"
          + (f", {len(args.archivy)} archív(ov) sedí." if args.archivy else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
