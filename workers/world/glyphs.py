#!/usr/bin/env python3
"""
Z fontov ostanú len tie rozsahy znakov, ktoré sú v menách na mape.

PREČO. V balíku mapy sveta nie sú to drahé dlaždice, ale PÍSMO. `glyphs.sh`
už rozsahy raz oreže – necháva latinku, gréčtinu, cyriliku a interpunkciu,
lebo pri mape kraja nevie, aké mená v nej budú, a chýbajúci rozsah znamená na
mape prázdne štvorčeky. Tu sa to ale VIE: mapa sveta píše dve veci, mená
štátov a mená regiónov sťahovania. Merané na 516 menách z Natural Earth
(`name` aj `name_en`) padnú VŠETKY do jediného rozsahu 0–255, takže z ~1,2 MB
na stack ostanú stovky kB. Pri balíku so stropom 15 MB to stojí za to.

(Kým `glyphs.sh` rozsahy nerezal, bol stack celý unicode – 33 MB v 256
súboroch – a tento skript bol jediné, čo `basic` do 15 MB vôbec vopchalo.)

MERIA SA, NEHÁDA. Rozsahy sa nezapisujú do číselníka ako „Latinka stačí":
prečítajú sa z pripravených podkladov, teda z tých istých mien, ktoré pôjdu do
dlaždíc. Keby Geofabrik raz pomenoval región po japonsky, rozsah pribudne sám.
Keby sa naopak zoznam nedal prečítať, NEOREŽE SA NIČ – ostane to, čo nechal
`glyphs.sh`, teda o pár MB väčší balík. Mapa s chýbajúcim písmom má na tom
mieste prázdne štvorčeky a nikto nepovie prečo (pravidlo 8 v CLAUDE.md).

Použitie:
    python3 workers/world/glyphs.py --fonts=_site/fonts --data=data/world
"""
import argparse
import glob
import json
import os
import sys

# Čo štýl vypisuje ako text (`workers/world/style.mjs`): meno štátu s náhradou
# a meno regiónu sťahovania. Keď v štýle pribudne ďalší `text-field`, patrí
# sem – inak sa oreže rozsah, ktorý mapa potrebuje.
TEXTOVE = ("name", "name_en")

# Rozsah 0–255 sa nechá VŽDY, aj keby v podkladoch nebol: sú v ňom číslice
# a základná latinka, teda to, čím sa dá nakresliť čokoľvek náhradné.
VZDY = {0}


def rozsahy_z_geojsonu(cesta):
    """Ktoré 256-znakové rozsahy sa v menách v tomto súbore vyskytujú."""
    with open(cesta, encoding="utf-8") as f:
        data = json.load(f)
    out = set()
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        for kluc in TEXTOVE:
            hodnota = props.get(kluc)
            if isinstance(hodnota, str):
                out.update(ord(z) // 256 for z in hodnota)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", default="_site/fonts")
    ap.add_argument("--data", default="data/world",
                    help="pripravené podklady (`*.geojson` s menami)")
    args = ap.parse_args()

    stacky = sorted(d for d in glob.glob(os.path.join(args.fonts, "*"))
                    if os.path.isdir(d))
    if not stacky:
        print(f"Vo `{args.fonts}` nie sú fonty – niet čo orezať.")
        return 0

    zdroje = sorted(glob.glob(os.path.join(args.data, "*.geojson")))
    treba = set(VZDY)
    precitane = []
    for z in zdroje:
        try:
            r = rozsahy_z_geojsonu(z)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # Nečitateľný podklad NESMIE viesť k orezaniu: radšej balík
            # o pár MB väčší (to, čo nechal `glyphs.sh`) než mapa
            # s prázdnymi štvorčekmi namiesto mien.
            print(f"::warning::Podklad {z} sa nedá prečítať ({exc}) – fonty sa "
                  f"NEOREŽÚ a v balíku ostane celé písmo.")
            return 0
        treba |= r
        precitane.append((os.path.basename(z), len(r)))

    if not precitane:
        print(f"::warning::Vo `{args.data}` nie je ani jeden `.geojson` "
              f"s menami – fonty sa NEOREŽÚ.")
        return 0

    print("Rozsahy znakov v menách na mape:")
    for meno, kolko in precitane:
        print(f"  {meno:<24} {kolko} rozsahov")
    print("  spolu: " + ", ".join(f"{r * 256}-{r * 256 + 255}"
                                  for r in sorted(treba)))

    zmazane = ostale = 0
    pred = po = 0
    for stack in stacky:
        for pbf in glob.glob(os.path.join(stack, "*.pbf")):
            meno = os.path.basename(pbf)
            velkost = os.path.getsize(pbf)
            pred += velkost
            try:
                lo = int(meno.split("-", 1)[0])
            except ValueError:
                po += velkost
                ostale += 1
                continue
            if lo // 256 in treba:
                po += velkost
                ostale += 1
            else:
                os.remove(pbf)
                zmazane += 1

    print(f"Fonty: ostalo {ostale} súborov ({po / 1048576:.1f} MB), "
          f"zmazaných {zmazane} ({(pred - po) / 1048576:.1f} MB ušetrených "
          f"z {pred / 1048576:.1f} MB).")
    if not ostale:
        print("::error::Po orezaní neostal ani jeden súbor písma – to by bola "
              "mapa bez nápisov. Skontroluj `--fonts` a `--data`.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
