#!/usr/bin/env python3
"""Graf križovatiek → `<kraj>-routing.pmtiles`: dlaždice so značkami, nie s cenami."""
import argparse
import gzip
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import format as fmt                                              # noqa: E402
import tags as slovnik_modul                                      # noqa: E402

# tá istá mriežka ako mapa; okrajové dlaždice susedných krajov tak na seba
# sadnú a telefón ich spojí podľa z/x/y
ZOOM = 9
# meno pod hustým mestom sa nezmestí do rozpočtu, tak sa dlaždica reže hlbšie
ZOOM_MAX = 13
E7 = 1e7


def dlazdica_z(lat_e7, lon_e7, z=ZOOM):
    lat, lon = lat_e7 / E7, lon_e7 / E7
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    f = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1.0 - math.asinh(math.tan(f)) / math.pi) / 2.0 * n)
    return z, min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def okno(z, x, y):
    """Zemepisný obdĺžnik dlaždice v e7 (west, south, east, north)."""
    n = 2.0 ** z
    w = x / n * 360.0 - 180.0
    e = (x + 1) / n * 360.0 - 180.0
    sever = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    juh = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (round(w * E7), round(juh * E7), round(e * E7), round(sever * E7))


class Dlazdica:
    def __init__(self, zxy, slovnik):
        self.zxy = zxy
        self.slovnik = slovnik
        self.uzly = {}                 # osm id -> (lat, lon, vyska, rank)
        self.hrany = []
        self.zakazy = []
        self._tagsety = {}
        self._retazce = {}

    def tagset(self, tagy):
        """Index sady značiek; rovnaké sady sú v archíve raz."""
        polozky = []
        for kluc, hodnota in tagy.items():
            i = self.slovnik.index(kluc)
            druh = self.slovnik.druh[kluc]
            if druh == slovnik_modul.VYMENOVANY:
                kod = self.slovnik.hodnota_index(kluc, hodnota)
            elif druh == slovnik_modul.CISLO:
                kod = fmt.zigzag(int(hodnota))
            else:
                kod = self._retazce.setdefault(hodnota, len(self._retazce))
            polozky.append((i, kod))
        polozky.sort()
        kluc = tuple(polozky)
        return self._tagsety.setdefault(kluc, len(self._tagsety))

    def telo(self, slovnik_id, poradie_id, s_poradim):
        poradie = sorted(self.uzly)
        idx = {osm: i for i, osm in enumerate(poradie)}
        uzly = [(osm, *self.uzly[osm]) for osm in poradie]
        lat_min = min(u[1] for u in uzly)
        lat_max = max(u[1] for u in uzly)
        lon_min = min(u[2] for u in uzly)
        lon_max = max(u[2] for u in uzly)
        for h in self.hrany:
            for lat, lon in h["geom"]:
                lat_min, lat_max = min(lat_min, lat), max(lat_max, lat)
                lon_min, lon_max = min(lon_min, lon), max(lon_max, lon)

        w, s, e, n = okno(*self.zxy)
        okraj = [i for i, u in enumerate(uzly)
                 if not (w <= u[2] <= e and s <= u[1] <= n)]

        return fmt.zapis({
            "vyska": False,
            "poradie": s_poradim,
            "slovnik_id": slovnik_id,
            "poradie_id": poradie_id,
            "zxy": list(self.zxy),
            "bbox": [lon_min, lat_min, lon_max, lat_max],
            "uzly": uzly,
            "hrany": [{"od": idx[h["od"]], "do": idx[h["do"]],
                       "tagset": h["tagset"], "dlzka_cm": h["dlzka_cm"],
                       "smer": h["smer"], "geom": h["geom"]} for h in self.hrany],
            "tagsety": [list(k) for k, _ in
                        sorted(self._tagsety.items(), key=lambda kv: kv[1])],
            "retazce": [s for s, _ in
                        sorted(self._retazce.items(), key=lambda kv: kv[1])],
            "zakazy": self.zakazy,
            "okraj": okraj,
        })


def po_dlazdiciach(siet, hrany, zakazy, z):
    """Hrana patrí do dlaždice svojho prvého uzla – to je vlastnosť OSM, nie kraja."""
    skupiny = {}
    for h in hrany:
        lat, lon = siet.uzly[h["od"]]
        skupiny.setdefault(dlazdica_z(lat, lon, z), ([], []))[0].append(h)
    for zakaz in zakazy:
        lat, lon = siet.uzly[zakaz["cez"]]
        skupina = skupiny.get(dlazdica_z(lat, lon, z))
        if skupina is None:
            continue
        skupina[1].append(zakaz)
    return skupiny


def postav(zxy, hrany, zakazy, siet, slovnik, krajina, poradie):
    d = Dlazdica(zxy, slovnik)
    for h in hrany:
        tagy = dict(h["tagy"])
        if krajina:
            tagy["krajina"] = krajina
        for ref in (h["od"], h["do"]):
            if ref not in d.uzly:
                d.uzly[ref] = (*siet.uzly[ref], 0, poradie.rank(ref))
        d.hrany.append({"od": h["od"], "do": h["do"], "geom": h["geom"],
                        "dlzka_cm": h["dlzka_cm"], "smer": h["smer"],
                        "tagset": d.tagset(tagy)})
    for zakaz in zakazy:
        d.zakazy.append({"druh": zakaz["druh"], "vynimky": zakaz["vynimky"],
                         "hrany": zakaz["hrany"]})
    return d


def rozdel(siet, slovnik, krajina, poradie, rozpocet=None):
    """Dlaždice z9; ktorej sa telo nezmestí do rozpočtu, tá sa reže hlbšie.

    Delí sa tá istá mriežka, takže dieťa celé leží vo svojej z9 a na jej
    `z/x/y` nie je potom nič – telefón tam nenájde dlaždicu a zostúpi.
    """
    strop = fmt.ROZPOCET_KB * 1024 if rozpocet is None else rozpocet
    telá = {}
    fronta = list(po_dlazdiciach(siet, siet.hrany, siet.zakazy, ZOOM).items())
    while fronta:
        zxy, (hrany, zakazy) = fronta.pop()
        d = postav(zxy, hrany, zakazy, siet, slovnik, krajina, poradie)
        telo = gzip.compress(d.telo(slovnik.id, poradie.id, bool(poradie)), 9)
        if len(telo) > strop and zxy[0] < ZOOM_MAX:
            fronta.extend(po_dlazdiciach(siet, hrany, zakazy, zxy[0] + 1).items())
            continue
        telá[zxy] = telo
    return telá


class Poradie:
    """Rank na uzol – aj pre uzol, ktorý v poradí nie je."""

    def __init__(self, cesta=""):
        self.id, self._rank = 0, {}
        if cesta:
            with open(cesta, encoding="utf-8") as f:
                raw = json.load(f)
            self.id = int(raw["id"], 16)
            self._rank = {int(k): v for k, v in raw["rank"].items()}
        self._koniec = len(self._rank)

    def __bool__(self):
        return bool(self._rank)

    def rank(self, osm_id):
        """Uzol pribudnutý po výpočte poradia ide na koniec, podľa OSM id.

        Je to stále GLOBÁLNE poradie – OSM id je jedno na celý svet, takže dva
        kraje dosadia tomu istému uzlu to isté číslo. Bez toho by sa poradie
        muselo prepočítať pri každej zmene siete a archívy postavené pred ňou
        a po nej by sa nedali spojiť.
        """
        r = self._rank.get(osm_id)
        return r if r is not None else self._koniec + osm_id

    def chybajuce(self, uzly):
        return sum(1 for u in uzly if u not in self._rank)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--region-key", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--krajina", default="",
                    help="ISO kód krajiny archívu – vstup pre diaľničnú známku")
    ap.add_argument("--poradie", default="",
                    help="súbor s poradím uzlov z workers/routing/order.py")
    args = ap.parse_args()

    import network                                                # noqa: PLC0415

    slovnik = slovnik_modul.slovnik()
    if args.krajina and slovnik.hodnota_index("krajina", args.krajina) is None:
        print(f"::error::Krajina `{args.krajina}` nie je v `krajina` vo "
              f"workers/data/routing-tags.json, takže by sa do archívu "
              f"nedostala a diaľničná známka by v ňom nemala na čom stáť.",
              file=sys.stderr)
        return 1

    t0 = time.time()
    siet = network.nacitaj(args.pbf, slovnik)
    print(f"Sieť: {siet.ciest} ciest → {len(siet.uzly)} križovatiek, "
          f"{len(siet.hrany)} hrán, {len(siet.zakazy)} zákazov "
          f"({time.time() - t0:.0f} s)")

    poradie = Poradie(args.poradie)
    if args.poradie:
        chyba = poradie.chybajuce(siet.uzly)
        if chyba:
            print(f"::warning::{chyba} z {len(siet.uzly)} uzlov v poradí "
                  f"z {args.poradie} nie je – sieť sa od jeho výpočtu zmenila. "
                  f"Dostanú rank na konci podľa OSM id, takže sa archívy dajú "
                  f"spojiť ďalej; keď ich je veľa, prepočítaj poradie "
                  f"(workflow „Navigácia · poradie uzlov“).")
    else:
        print("::warning::Archív ide BEZ PORADIA UZLOV (`--poradie`). Trasa "
              "sa z neho spočíta, ale telefón si musí poradie dorátať sám – "
              "a to je jediná drahá časť CCH, ktorá do telefónu nepatrí "
              "(docs/navigation.md §11).")

    telá = rozdel(siet, slovnik, args.krajina, poradie)
    if not telá:
        print("::warning::V tomto území nie je ani jedna cesta, po ktorej by "
              "sa dalo ísť – archív so smerovaním sa nevyrobí.")
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    zoom_max = max(z for z, _, _ in telá)
    delene = sum(1 for z, _, _ in telá if z > ZOOM)

    velke = sorted(((len(b), zxy) for zxy, b in telá.items()), reverse=True)
    nad = [(n, zxy) for n, zxy in velke if n > fmt.ROZPOCET_KB * 1024]
    for n, zxy in nad:
        print(f"::warning::Dlaždica {zxy[0]}/{zxy[1]}/{zxy[2]} má "
              f"{n // 1024} kB, čo je nad rozpočtom {fmt.ROZPOCET_KB} kB aj "
              f"na z{ZOOM_MAX}, hlbšie sa už nedelí. Páka je slovník značiek "
              f"(workers/data/routing-tags.json).")

    graf = {
        "rozsah": "region",
        "kluc": args.region_key,
        "name": args.name or args.region_key,
        "format": "rtil",
        "format_verzia": fmt.VERZIA,
        "slovnik": f"{slovnik.id:08x}",
        "slovnik_verzia": slovnik.verzia,
        "poradie": f"{poradie.id:08x}" if poradie else None,
        "krajina": args.krajina or None,
        "zoom": ZOOM,
        "zoom_max": zoom_max,
        "delenych": delene,
        "dlazdic": len(telá),
        "uzlov": len(siet.uzly),
        "hran": len(siet.hrany),
        "zakazov": len(siet.zakazy),
        "vyska": False,
        "multimodal": False,
        # dlaždica sa reže mriežkou, nie hranicou kraja: susedné kraje majú
        # okrajové dlaždice tej istej z/x/y a telefón ich spojí podľa OSM id
        "spojenie": "podľa OSM id uzlov; okrajové dlaždice susedov sa "
                    "prekrývajú a spájajú sa po prvkoch, nie po dlaždiciach",
        # hustá dlaždica je nahradená deťmi, na jej vlastnom z/x/y nie je nič
        "delenie": "na z/x/y bez dlaždice zostúp o zoom nižšie, až po zoom_max",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run": os.environ.get("GITHUB_RUN_NUMBER", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }

    # až tu, nech si tiler naimportuje aj lint, ktorý pmtiles mať nemusí
    from pmtiles.tile import (Compression, TileType,                # noqa: PLC0415
                              zxy_to_tileid)
    from pmtiles.writer import Writer                               # noqa: PLC0415

    with open(args.out, "wb") as f:
        wr = Writer(f)
        for zxy in sorted(telá, key=lambda t: zxy_to_tileid(*t)):
            wr.write_tile(zxy_to_tileid(*zxy), telá[zxy])
        w = min(okno(*z)[0] for z in telá)
        s = min(okno(*z)[1] for z in telá)
        e = max(okno(*z)[2] for z in telá)
        n = max(okno(*z)[3] for z in telá)
        wr.finalize(
            {"tile_type": TileType.UNKNOWN, "tile_compression": Compression.GZIP,
             "min_zoom": ZOOM, "max_zoom": zoom_max,
             "min_lon_e7": w, "min_lat_e7": s, "max_lon_e7": e, "max_lat_e7": n,
             "center_zoom": ZOOM, "center_lon_e7": (w + e) // 2,
             "center_lat_e7": (s + n) // 2},
            {"name": f"{args.region_key}-routing", "format": "rtil",
             "description": "Smerovacia sieť so značkami – cenu počíta telefón",
             "graf": graf},
        )

    velkost = os.path.getsize(args.out)
    print(json.dumps(graf, ensure_ascii=False, indent=2))
    print(f"{args.out}: {len(telá)} dlaždíc (z{ZOOM}–z{zoom_max}, {delene} "
          f"delených), {velkost / 1048576:.1f} MB, "
          f"najväčšia {velke[0][0] // 1024} kB")
    zahodene = siet.zahodene.most_common(10)
    if zahodene:
        print("Hodnoty mimo slovníka (zahodené): "
              + ", ".join(f"{k}×{n}" for k, n in zahodene))
    if siet.preskocene:
        print("Preskočené: "
              + ", ".join(f"{k}×{n}" for k, n in siet.preskocene.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
