#!/usr/bin/env python3
"""Slovník značiek pre smerovanie – jediný prístup k `workers/data/routing-tags.json`."""
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
CISELNIK = os.path.join(os.path.dirname(_HERE), "data", "routing-tags.json")

# druhy kľúčov; hodnota v dlaždici sa kóduje podľa nich
VYMENOVANY, CISLO, VOLNY = "hodnoty", "cislo", "volny"


class Slovnik:
    """Kľúče a hodnoty, ktoré smú do dlaždice – aj s poradím, ktoré je index."""

    def __init__(self, path=CISELNIK):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.verzia = raw["verzia"]
        self.siet = {k: v for k, v in raw["siet"].items() if not k.startswith("_")}
        pristup = raw["_pristup"]["hodnoty"]

        self.kluce = []                    # poradie = index kľúča v dlaždici
        self.druh = {}
        self.hodnoty = {}
        for kluc, spec in raw["kluce"].items():
            if spec.get("z_siete"):
                druh, hodnoty = VYMENOVANY, list(self.siet[kluc])
            elif spec.get("pristup"):
                druh, hodnoty = VYMENOVANY, list(pristup)
            elif spec.get(VYMENOVANY):
                druh, hodnoty = VYMENOVANY, list(spec[VYMENOVANY])
            elif spec.get(CISLO):
                druh, hodnoty = CISLO, []
            elif spec.get(VOLNY):
                druh, hodnoty = VOLNY, []
            else:
                raise SystemExit(
                    f"::error file=workers/data/routing-tags.json::kľúč "
                    f"`{kluc}` nemá druh (`hodnoty`, `cislo`, `volny`, "
                    f"`pristup` ani `z_siete`). Bez druhu sa nedá zakódovať "
                    f"ani prečítať – telefón by na tom mieste čítal iné číslo.")
            self.kluce.append(kluc)
            self.druh[kluc] = druh
            self.hodnoty[kluc] = hodnoty
        self._idx = {k: i for i, k in enumerate(self.kluce)}
        self._hidx = {k: {v: i for i, v in enumerate(vs)}
                      for k, vs in self.hodnoty.items()}
        self.id = _id(self.verzia, self.siet, self.kluce, self.druh, self.hodnoty)

    def index(self, kluc):
        return self._idx.get(kluc)

    def hodnota_index(self, kluc, hodnota):
        return self._hidx.get(kluc, {}).get(hodnota)

    def trieda(self, tags):
        """Čím je way cesta – `(kľúč, hodnota)`, alebo `None`."""
        for kluc, hodnoty in self.siet.items():
            v = tags.get(kluc)
            if v in hodnoty:
                return kluc, v
        return None

    def vyber(self, tags):
        """Značky, ktoré sa vezú – neznáma hodnota sa zahodí a vráti sa zvlášť."""
        out, zahodene = {}, []
        for kluc, v in tags.items():
            druh = self.druh.get(kluc)
            if druh is None:
                continue
            v = v.strip()
            if druh == VYMENOVANY:
                if kluc in self._hidx and v in self._hidx[kluc]:
                    out[kluc] = v
                else:
                    zahodene.append((kluc, v))
            elif druh == CISLO:
                try:
                    out[kluc] = str(int(v))
                except ValueError:
                    zahodene.append((kluc, v))
            elif v:
                out[kluc] = v
        return out, zahodene


def _id(verzia, siet, kluce, druh, hodnoty):
    """Id slovníka z jeho obsahu – ručne písané by sa pri zmene neposunulo."""
    telo = {
        "verzia": verzia,
        "siet": {k: list(v) for k, v in siet.items()},
        "kluce": [[k, druh[k], hodnoty[k]] for k in kluce],
    }
    raw = json.dumps(telo, ensure_ascii=False, sort_keys=False,
                     separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


_CACHE = None


def slovnik():
    global _CACHE
    if _CACHE is None:
        _CACHE = Slovnik()
    return _CACHE


if __name__ == "__main__":
    s = slovnik()
    print(f"slovník v{s.verzia}, id {s.id:08x}, {len(s.kluce)} kľúčov")
    for kluc in s.kluce:
        n = len(s.hodnoty[kluc])
        print(f"  {s.index(kluc):2d}  {kluc:22s} {s.druh[kluc]:8s}"
              f"{f' ({n} hodnôt)' if n else ''}")
    sys.exit(0)
