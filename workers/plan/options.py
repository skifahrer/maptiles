#!/usr/bin/env python3
"""
Rozloží voľné `kľúč=hodnota` z inputu `options` na jednotlivé nastavenia
a z troch výberov zdrojov odvodí, čo sa vlastne ide počítať.

PREČO: `workflow_dispatch` dovolí **najviac 10 inputov**. Mali sme ich 26,
a workflow sa preto prestal načítať – beh skončil ako „failure" s nula jobmi,
lebo GitHub ten súbor ani neprijal. Desať najpoužívanejších vecí ostalo
samostatnými inputmi – a to je STROP, formulár je plný, ďalší prepínač musí
ísť sem – zvyšok sa píše do jedného poľa:

    rock_res=1 rock_maxzoom=15 trails=false

Nie je to len obchádzka limitu: formulár s 26 poľami sa aj tak nedal použiť.
Takto sú v ňom veci, ktoré meníš pri každom behu, a ostatné majú rozumné
predvolené hodnoty. Ktoré to sú, sa časom mení: `rock_res` (mriežka na obrys
skál) sa prestavuje len s iným zdrojom výšok, kým rýchly test sa zapína
a vypína pri každom behu – tak si vymenili miesto. Zapnutie je switch `test`,
veľkosť štvorca ostala voľbou (`test_km2`, default 4 km²): jedno sa preklikáva
stále, druhé skoro nikdy. To isté sa stalo s nasadením na Pages: bolo to
voľbou `publish_pages`, ale je to otázka „kam to má ísť" a rozhoduje sa pri
behu, tak je z toho switch. Publikovanie na Drive ostalo voľbou `publish` –
sú to dve nezávislé páky a dá sa mať jedno bez druhého.

TRI VÝBERY ZDROJA namiesto jedného `dem_source` a zoznamu `layers`:
`contour_source` (vrstevnice), `rock_source` (skaly) a `shading_source`
(tieňovanie a 3D terén). Každý z nich vie aj `ziadne`, takže vypnutie vrstvy
je hodnota vo výbere a nie druhé pole vedľa neho – dve polia na tú istú vec
sa vždy raz rozídu („generuj vrstevnice, zdroj žiadny"). Vrstva sa tým pádom
zapína tam, kde sa vyberá jej zdroj.

Neznámy kľúč je chyba, nie ticho ignorovaná hodnota – preklep v `rock_slop=55`
by inak znamenal, že sa celý beh spustí s iným nastavením, než si myslíš.

Použitie:
    python3 workers/plan/options.py --options="rock_res=1" \\
        --rebuild=skaly --contour-source=sonny --rock-source=dmr5 \\
        --shading-source=sonny --test=true --publish-pages=true \\
        --out=$GITHUB_OUTPUT
"""
import argparse
import json
import os
import shlex
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Priečinok = job, súbor = krok; spoločné veci ležia o úroveň vyššie.
_WORKERS = os.path.dirname(_HERE)          # workers/
_DATA = os.path.join(_WORKERS, "data")     # číselníky (areas, regions, zdroje)

# „Koľko metrov je jeden pixel dlaždice" sa pýta aj tieňovanie (na inú otázku
# – či DEM zväčšuje alebo zmenšuje), tak to číslo býva vo `workers/lib/`.
sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import terrain_zoom_for, tile_m_per_px  # noqa: E402

# kľúč: (predvolená hodnota, popis)
DEFAULTS = {
    "crop_bbox": ("", "orezať región na west,south,east,north"),
    "area_bbox": ("", "vlastný výrez W,S,E,N namiesto pohoria z výberu"),
    # RÝCHLY TEST. Zapína ho switch `test` vo formulári; tu je len veľkosť
    # a miesto štvorca – oboje sa mení zriedka, kým samotné zapnutie pri
    # každom behu. Platí to len pri zapnutom switchi: `test_km2` bez neho je
    # chyba, nie ticho ignorované číslo.
    # Štyri km², nie dva: na dvoch sa skalná plocha často netrafila do ničoho
    # zaujímavého (2 km² je štvorec so stranou 1,4 km – v Tatrách sa doň zmestí
    # jedna dolina alebo ani tá) a z testu sa nedalo prečítať, či skaly vyzerajú
    # správne. Stojí to dvojnásobok DEM: sklon aj vektorizácia rastú s plochou.
    "test_km2": ("4", "veľkosť štvorca pri zapnutom switchi `test` (km²)"),
    "test_at": ("", "stred testovacieho štvorca `lon,lat` (prázdne = stred výrezu)"),
    "size_limit_mb": ("900", "rozpočet celej stránky v MB"),
    "auto_shrink": ("true", "znížiť zoom dlaždíc, keď sa nezmestia"),
    "ugkk_fallback": ("true", "keď DMR 5.0 pre výrez nie je, počítať zo Sonnyho"),
    "ugkk_urls": ("", "priame URL na ÚGKK dáta (posledná záchrana)"),
    "contour_maxzoom": ("14", "max zoom dlaždíc s vrstevnicami"),
    # Skaly majú od vrstevníc oddelený .pmtiles, takže aj vlastný maxzoom.
    # 16 je tvrdý strop Planetilera; vyššie zoomy rieši overzoom, takže sa
    # skaly zobrazujú do maximálneho zoomu mapy tak či tak – z vyššieho
    # maxzoomu je ostrejší tvar, nie väčší rozsah zoomov.
    "rock_maxzoom": ("16", "max zoom dlaždíc so skalami (strop Planetilera je 16)"),
    # Plné plochy: skala je jedna súvislá plocha bez dier a v jednej
    # triede. V mape sa kreslí jednou sivou bez priehľadnosti, takže by
    # sa každý prekryv a každá diera prejavili ako škvrna.
    "rock_plne": ("1", "1 = jedna trieda skál (žiadna plocha vnútri inej), "
                       "0 = triedy steep/cliff ako predtým"),
    # Diery v skalách sú medzery medzi vláknami siete žliabkov a police
    # vnútri stien – čiže presne ten tvar, pre ktorý sa skaly počítajú.
    # Zapnuté zapĺňanie z nich spravilo súvislé plochy bez detailu; preto
    # je vypnuté a je to samostatná voľba, nie súčasť `rock_plne`.
    "rock_zapln_diery": ("0", "1 = zaplniť diery v skalách (súvislé plochy "
                              "namiesto tvaru) – neodporúča sa"),
    # Mriežka na obrys skál. Bol to samostatný input, ale strop je desať
    # a switch rýchleho testu sa preklikáva pri každom ladení, kým mriežku má
    # zmysel prestaviť len s iným zdrojom výšok – `auto` ju vyberie z bunky
    # DEM a rozpočtu času a vypíše do logu, prečo práve tú.
    "rock_res": ("auto", "mriežka na obrys skál v metroch, alebo `auto`"),
    "contour_smoothing": ("0", "zjemnenie DEM v oblúkových sekundách"),
    "trails_maxzoom": ("14", "max zoom dlaždíc so značenými trasami"),
    # `auto` = podľa mriežky vybraného modelu: najnižší zoom, na ktorom je
    # pixel dlaždice jemnejší než bunka modelu. Sonny (20 m) → z13 (to bola
    # doterajšia pevná hodnota), DMR 3.5 (10 m) → z14, DMR 5.0 (5 m) → z15.
    # Pevná trinástka znamenala, že si síce vyberieš DMR 5.0, ale tieňovanie
    # z neho vyzerá ako zo Sonnyho – pixel z13 má 12,5 m, takže sa 5 m model
    # nemal ako prejaviť. Každý zoom navyše je ale ŠTVORNÁSOBOK dlaždíc, tak
    # `terrain-build.sh` výsledok ešte zreže na rozpočet stránky.
    "terrain_maxzoom": ("auto", "max zoom výškových dlaždíc (auto = podľa mriežky modelu)"),
    # 3D terén v štýle. `auto` = zapnúť tam, kde máme VLASTNÉ výškové
    # dlaždice (teda keď `shading_source` nie je `ziadne`); na verejné
    # AWS dlaždice sa 3D nezapína, sú globálne a hrubé.
    "terrain_3d": ("auto", "3D terén v štýle (auto = keď máme vlastné výškové dlaždice)"),
    # Značené trasy sú jediná vrstva bez výberu zdroja – berú sa z toho istého
    # PBF ako mapa, takže niet z čoho vyberať. Zapínač je preto tu a nie
    # štvrtý výber vo formulári, na ktorý už aj tak nie je miesto.
    "trails": ("true", "generovať značené trasy z OSM relácií"),
    # Krajinné prvky (workers/features/features.yml): násypy, múry, ploty, vedenia,
    # prieseky, pramene, jaskyne, rozhľadne, parkoviská, zjazdovky. Rovnako
    # ako trasy nemajú výber zdroja – idú z toho istého PBF ako mapa.
    "features": ("true", "generovať krajinné prvky, ktoré OpenMapTiles nemá"),
    # Vyhľadávací index: offline FTS5. Bez výberu zdroja - idú z toho istého
    # PBF ako mapa. Zapínač je tu namiesto vo formulári.
    "search": ("true", "generovať vyhľadávací index pre offline hľadávanie"),
    # NAVIGAČNÝ GRAF (Valhalla) pre TENTO región – ide dovnútra balíka mapy,
    # nie do vlastného ZIPu (rozpis v hlavičke `workers/deploy/publish-map.py`).
    # Bez neho je v mape, ktorú si človek stiahol, všetko okrem toho, čo ho
    # tam dovezie. Trasa v ňom končí na hranici kraja – PBF je rezaný a hrana
    # bez druhého konca je slepá ulica; cez hranicu vedie celoštátny balík
    # z `.github/workflows/navigation.yml`. Zapínač je tu a nie vo formulári,
    # lebo `workflow_dispatch` má strop 10 inputov a ten je vyčerpaný.
    "navigacia": ("true", "stavať navigačný graf (Valhalla) pre tento región"),
    # OBRAZ VALHALLY S TAGOM, nie `latest`: graf a knižnica, ktorá ho čítá
    # v telefóne, si musia sedieť a nesúlad verzií vyzerá ako pokazená trasa.
    # Predvolené je aj tak `latest` – pripnutá verzia sa zavesí a nikto ju
    # nedvihne –, ale to, čo sa NAOZAJ použilo, ide do `graf.json` v balíku.
    "valhalla_image": ("ghcr.io/valhalla/valhalla-scripted:latest",
                       "docker obraz, ktorým sa stavia navigačný graf"),
    # OBMEDZENIA NA CESTE (workers/roads/roads.yml): výška podjazdov a tunelov,
    # šírka, hmotnosť, maximálna rýchlosť, jazdné pruhy, stúpanie. Tie hodnoty
    # vrstva `transportation` OpenMapTiles nenesie vôbec, takže sa – rovnako
    # ako trasy a krajinné prvky – ťahajú z toho istého PBF druhýkrát. Zapínač
    # je tu a nie vo formulári, lebo `workflow_dispatch` má strop 10 inputov
    # a ten je vyčerpaný.
    "roads": ("true", "generovať obmedzenia na ceste (výška, šírka, rýchlosť)"),
    # 15, nie 16: štítok s obmedzením je popisok pozdĺž čiary a na z16 už
    # nepribúda, čo by ukázal – pribúdajú len bajty. Bloky schémy majú
    # `min_zoom` 12 a 14, takže na tichú stratu (min_zoom nad maxzoomom) tu
    # miesto nie je; build.sh to aj tak porovná a spadne.
    "roads_maxzoom": ("15", "max zoom dlaždíc s obmedzeniami na ceste"),
    # INTERVAL VRSTEVNÍC. Bol to input vo formulári a presťahoval sa sem, keď
    # si miesto vzal switch `wikipedia` (ten sa medzitým odsťahoval do
    # `wiki.yml`) – `workflow_dispatch` dovolí najviac 10 inputov. Je to ten
    # istý výmenný obchod, aký kedysi spravil `test_km2`:
    # z DMR 5.0 je 5 m dobrý default takmer všade a mení sa pri prechode do
    # nížin, nie pri každom behu.
    "contour_interval": ("5", "interval vrstevníc v metroch (10 = redšie)"),
    # 15, nie 14: schéma má triedy s `min_zoom: 15` (ploty, živé ploty,
    # geodetické body, hraničné kamene). Čo má min_zoom nad maxzoomom
    # archívu, Planetiler ZAHODÍ BEZ SLOVA – pri 14 ich v dlaždiciach bola
    # presne nula. Nárast je 1,6× (Andorra 248 kB → 394 kB), čo je pri
    # jednotkách MB nič.
    "features_maxzoom": ("15", "max zoom dlaždíc s krajinnými prvkami"),
    # Hotová mapa ide okrem Pages aj na Google Drive – tri ZIPy (celá mapa,
    # vrstevnice so skalami, tieňovanie) do priečinka podľa krajiny, kraja
    # a výrezu, so stálym menom, takže ďalší build tie isté súbory prepíše
    # (`workers/deploy/publish-map.py`). `publish=false` to vypne – napr. keď sa
    # ladí prah a hotová mapa v priečinku sa nemá prepisovať polotovarom.
    # OREZ DLAŽDÍC NA HRANICU REGIÓNU (`--polygon` Planetileru,
    # `workers/lib/region-clip.sh`). DOČASNE VYPNUTÝ – merania, prečo to
    # mapu nezmení a čo to stojí, sú v hlavičke toho skriptu. Späť sa zapína
    # `region_clip=true`; vypnutý sa hlási `::warning::` v každom behu, aby
    # sa nezabudlo, že sa v mape vezie územie za hranicou.
    "region_clip": ("false", "orezať dlaždice na hranicu regiónu (dočasne vypnuté)"),
    "publish": ("true", "nahrať hotovú mapu ako ZIPy na Google Drive"),
    # To isté ešte raz ako `.aar` (Apple Archive, LZFSE) – iOS a macOS ho
    # rozbalia systémovo, bez tretej knižnice v aplikácii. Robí to vlastný job
    # na macOS, lebo nástroj `aa` je súčasť macOS a inde neexistuje; keď ho
    # nechceš platiť pri každom builde, `apple_archive=false`.
    "apple_archive": ("true", "nahrať mapu aj ako .aar (Apple Archive, job na macOS)"),
    # Ktorý asset s hotovými skalami z tieňovaných dlaždíc použiť (platí len
    # pri `rock_source: tienovanie`). Prázdne = najnovší pre daný výrez,
    # takže stačí pustiť ten workflow a potom build – nič sa neprepisuje.
    # Samotný `rock_source` je samostatný input, nie voľba: prepína celý
    # zdroj skál a to sa má dať vybrať vo formulári, nie napísať do textu.
    "rock_img_asset": ("", "presné meno assetu so skalami z tieňovania (prázdne = spočítať v tomto behu)"),
    # Ladenie pipeline, ktorú si build pri `rock_source: tienovanie` volá sám
    # (shading-rocks.yml). Prahy majú vlastné predvolené hodnoty tam; sem
    # patrí len to, čo mení cenu behu (zoom) a voľné prepínače skriptu.
    "rock_img_zoom": ("auto", "zoom dlaždíc tieňovania (auto = najvyšší, čo sa zmestí do stropu)"),
    "rock_img_options": ("", "prepínače pre výpočet skál z tieňovania, napr. \"fill=40 min_hole=5\""),
    # Bol to samostatný input, ale strop je desať a tri výbery zdroja sú
    # užitočnejšie: `maxzoom` je od začiatku 16 (tvrdý limit Planetilera)
    # a znižuje sa len pri ladení veľkosti.
    "maxzoom": ("16", "max zoom mapových dlaždíc – Planetiler zvládne najviac 16"),
    "custom_pbf_url": ("", "vlastný región – URL na .osm.pbf"),
    "custom_name": ("", "vlastný región – zobrazované meno"),
    "custom_bbox": ("", "vlastný región – bbox W,S,E,N"),
}

# Voľby, ktoré sa presťahovali medzi inputy (alebo naopak). Bez tohto by
# `rock_source=…` spadlo na „neznáma voľba" a zoznam známych kľúčov by
# nepovedal, kam sa podela – pritom je vo formulári o pár riadkov vyššie.
MOVED = {
    "rock_source": "je samostatný input vo formulári (výber zdroja skál), "
                   "nie voľba",
    "test": "je switch vo formulári (rýchly test na pár km²), nie voľba. "
            "Veľkosť štvorca je voľba `test_km2`",
    # Bolo to voľbou, kým bol formulár plný. Desiate miesto sa uvoľnilo, takže
    # je z toho switch – a starý zápis nesmie ticho prejsť ako neznámy kľúč
    # ani, čo je horšie, ako platná voľba, ktorú už nikto nečíta.
    "publish_pages": "je switch vo formulári (nasadiť na GitHub Pages), "
                     "nie voľba. Publikovanie na Drive je samostatná voľba "
                     "`publish`",
    # Články z Wikipédie majú od vytiahnutia z Build map VLASTNÝ workflow
    # (`.github/workflows/wiki.yml`) a s ním vlastné inputy. Kto sem napíše
    # `wiki_langs=…`, čakal by, že build stiahne články – a ten ich už nerobí.
    "wikipedia": "už nie je: články z Wikipédie robí samostatný workflow "
                 "„Build wiki“ (wiki.yml), nie Build map",
    "wiki_langs": "je input workflowu „Build wiki“ (wiki.yml) – "
                  "angličtina a jazyk krajiny sa doplnia samy",
    "wiki_format": "je input workflowu „Build wiki“ (wiki.yml)",
    "wiki_max": "je input workflowu „Build wiki“ (wiki.yml)",
    "dem_source": "sa rozpadol na tri inputy vo formulári – `contour_source`, "
                  "`rock_source` a `shading_source`, každá vrstva má svoj "
                  "zdroj",
    "layers": "už nie je: vrstva sa zapína tým, že jej vo formulári vyberieš "
              "zdroj (`ziadne` = negenerovať). Trasy sa vypínajú voľbou "
              "`trails=false`",
    "rocks": "už nie je: skaly sa vypínajú výberom `rock_source: ziadne`",
}

# Hodnota vo výbere, ktorá vrstvu vypne. Slovom, nie prázdnym reťazcom –
# v rozbaľovacom zozname má byť vidieť, že „nič" je vedomá voľba.
NONE = "ziadne"

# Skaly majú okrem výškových modelov ešte jeden zdroj, ktorý DEM vôbec
# nečíta: hotové polygóny z workflowu „Dáta · tieňované skaly".
ROCK_FROM_SHADING = "tienovanie"

# `rebuild` je jeden výber namiesto troch zaškrtávatiek – tri booleany boli
# tri inputy a limit je desať.
#
# `tienovanie` SA VOLALO `teren`. Bolo to jediné miesto v celom repozitári,
# kde sa tá vrstva volala inak než všade inde: vyberá ju `shading_source`
# („Tieňovanie a 3D terén“), balík je `-tienovanie.zip` a v katalógu je
# `terrain_source`. Kto ju chcel prepočítať, hľadal vo výbere „tieňovanie“ –
# a keď ho nenašiel, usúdil, že sa tá vrstva pregenerovať nedá. Príznak ostal
# `terrain_rebuild`: identifikátory sú anglické, mená vo formulári slovenské.
REBUILD = {
    "nic": (),
    "vrstevnice": ("contours_rebuild",),
    "skaly": ("rocks_rebuild",),
    "tienovanie": ("terrain_rebuild",),
    # `clanky` tu už nie je: pregenerovanie článkov je switch `rebuild`
    # vo workflowe „Build wiki“, ktorý ich jediný sťahuje.
    "vsetko": ("contours_rebuild", "rocks_rebuild", "terrain_rebuild"),
}
# Staré mená hodnoty → nové. Beh sa opakuje tlačidlom „Re-run", ktoré nesie
# hodnoty pôvodného formulára, a odkazy na `rebuild: teren` sú v starších
# súhrnoch behov aj v dokumentácii. Tvrdý pád na hodnote, ktorá pred hodinou
# fungovala, by bol horší než tichý preklad – tak sa to prekladá NAHLAS
# (vypíše sa, na čo sa to zmenilo).
REBUILD_ALIAS = {"teren": "tienovanie"}
# Príznaky, ktoré `rebuild` prepína. Zoznam je jeden, nech sa nedá pridať
# hodnota do REBUILD a zabudnúť ju vypísať na výstup (príznak by ostal
# prázdny a pregenerovanie by ticho nič neurobilo).
REBUILD_FLAGS = ("contours_rebuild", "rocks_rebuild", "terrain_rebuild")

# ČO `rebuild` NEPREGENERUJE – a čím sa to teda prepíše.
#
# „Pregenerovať: vsetko" znie ako sľub o celom behu, ale `rebuild` je páka na
# TRI vrstvy: zahodí ich cache aj uloženú verziu v sklade a spočíta ich nanovo.
# Ostatné veci má beh pod kontrolou iným spôsobom a keď to nie je napísané,
# vyzerá „vsetko" ako lož – človek čaká, že sa prepočíta aj výškový model,
# a nevie, prečo mapa vyzerá rovnako. Preto sa to vypisuje, a preto sa pri
# každej položke hovorí, čím sa TÁ vec vlastne obnoví.
REBUILD_MIMO = [
    ("výškový model (DEM)",
     "z Drive sa číta raz a ostáva v sklade; jeho podobu nesie MENO SKLADU "
     "(dnes `dem-dmr5-v2`), takže keď sa zmení pravidlo, ktorým vzniká, "
     "zmení sa meno a `check-dem` si ho doplní sám"),
    ("články z Wikipédie",
     "vlastná pipeline `Mapa · Build wiki`, tam je na to `rebuild: clanky`"),
    ("balíky na Drive (ZIP/AAR) a katalóg (`maps.json`, pri teste "
     "`maps-test.json`)",
     "prepisujú sa pri KAŽDOM behu, ktorý ich vyrobí (nahraj a až potom zmaž "
     "starý); balík vrstvy, ktorú beh nevyrobil, sa zmaže"),
]


def dem_sources(path=None):
    """Zdroje z workers/data/dem-sources.json → {kľúč: celý zápis zdroja}.

    Vracia sa celý zápis, nie len `for`: okrem toho, kde sa zdroj ponúka,
    z neho treba aj `cell_m` (mriežka modelu) na `terrain_maxzoom: auto`.
    Druhé čítanie toho istého súboru vedľa tohto by bolo presne to, čo sa
    raz rozíde.
    """
    path = path or os.path.join(_DATA, "dem-sources.json")
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def pick_source(what, value, allowed):
    """Skontroluje hodnotu jedného výberu zdroja; vráti ju, alebo None pri chybe."""
    value = (value or NONE).strip()
    if value in allowed:
        return value
    print(f"::error::Neznámy zdroj „{value}“ pre {what}. Známe: "
          f"{', '.join(allowed)}", file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--options", default="")
    ap.add_argument("--rebuild", default="nic")
    ap.add_argument("--contour-source", default=NONE,
                    help="zdroj výšok pre vrstevnice, alebo `ziadne`")
    ap.add_argument("--rock-source", default=NONE,
                    help="zdroj skál: výškový model, `tienovanie`, alebo `ziadne`")
    ap.add_argument("--shading-source", default=NONE,
                    help="zdroj výšok pre tieňovanie a 3D terén, alebo `ziadne`")
    ap.add_argument("--test", default="false",
                    help="switch rýchleho testu: true = počítať len štvorec "
                         "s `test_km2` km²")
    ap.add_argument("--publish-pages", default="true",
                    help="switch nasadenia na GitHub Pages: false = mapa sa "
                         "postaví a skontroluje, ale nenasadí")
    ap.add_argument("--dem-sources", default="",
                    help="cesta k dem-sources.json (default vedľa skriptu)")
    ap.add_argument("--out", default="")
    ap.add_argument("--summary", default="",
                    help="kam pripísať blok do súhrnu behu (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()

    values = {k: v for k, (v, _) in DEFAULTS.items()}
    changed = {}

    # shlex, nie split(): hodnota môže byť v úvodzovkách, napr.
    # custom_name="Rakúsko juh"
    for token in shlex.split(args.options or ""):
        if "=" not in token:
            print(f"::error::Voľba „{token}“ nemá tvar kľúč=hodnota.", file=sys.stderr)
            return 1
        k, v = token.split("=", 1)
        k = k.strip()
        if k in MOVED:
            print(f"::error::„{k}“ {MOVED[k]}. Vymaž to z `options` "
                  f"a nastav vo formulári.", file=sys.stderr)
            return 1
        if k not in DEFAULTS:
            print(f"::error::Neznáma voľba „{k}“. Známe voľby: "
                  f"{', '.join(sorted(DEFAULTS))}", file=sys.stderr)
            return 1
        values[k] = v
        changed[k] = v

    # ---------- rýchly test na pár km² ----------
    # Zo switchu a veľkosti vyjde jedno číslo, s ktorým ďalej pracuje celý
    # workflow: 0 = ostrý beh, čokoľvek iné = strana štvorca v km². Ide do
    # mena cache aj do kľúča uložených výsledkov (`…_test4`) a inde sa
    # porovnáva s „0" ako s reťazcom, takže sa tu aj normalizuje – `4.0`
    # aj `4` dajú to isté „4".
    test_on = (args.test or "false").strip().lower()
    if test_on not in ("true", "false"):
        print(f"::error::Switch „test“ musí byť true alebo false, "
              f"nie „{args.test}“.", file=sys.stderr)
        return 1
    test_on = test_on == "true"

    size = (values["test_km2"] or "").strip()
    try:
        n = float(size)
    except ValueError:
        print(f"::error::Voľba „test_km2“ musí byť číslo v km², "
              f"nie „{size}“.", file=sys.stderr)
        return 1
    if n <= 0:
        # Vypína sa switchom, nie nulou – inak sú na to isté dve páky a raz
        # si budú protirečiť („switch zapnutý, veľkosť 0“ nie je nič).
        print(f"::error::Voľba „test_km2“ musí byť väčšia než nula "
              f"(„{size}“). Rýchly test sa vypína odškrtnutím switchu "
              f"„test“.", file=sys.stderr)
        return 1
    if "test_km2" in changed and not test_on:
        print("::error::`test_km2` má zmysel len so zapnutým switchom „test“ "
              "– takto by sa nič nespočítalo inak. Zaškrtni `test`, alebo "
              "vymaž `test_km2` z options.", file=sys.stderr)
        return 1
    values["test_km2"] = f"{n:g}" if test_on else "0"

    # ---------- tri výbery zdroja ----------
    # Čo sa smie kde vybrať, hovorí `for` v dem-sources.json – ten istý
    # zoznam, aký stráži `Kontrola · lint workflowov` proti výberom vo formulári.
    srcs = dem_sources(args.dem_sources or None)
    contour_src = pick_source(
        "vrstevnice (contour_source)", args.contour_source,
        [NONE] + [k for k, v in srcs.items() if "contours" in v.get("for", [])])
    rock_src = pick_source(
        "skaly (rock_source)", args.rock_source,
        [NONE, ROCK_FROM_SHADING]
        + [k for k, v in srcs.items() if "rocks" in v.get("for", [])])
    shading_src = pick_source(
        "tieňovanie (shading_source)", args.shading_source,
        [NONE] + [k for k, v in srcs.items() if "shading" in v.get("for", [])])
    if contour_src is None or rock_src is None or shading_src is None:
        return 1

    values["contour_source"] = contour_src
    values["rock_source"] = rock_src
    values["shading_source"] = shading_src

    # `terrain_maxzoom: auto` sa rozhodne TU a nikde inde. Vie sa to len tu:
    # závisí to od vybraného modelu, a číslo potom potrebuje kľúč cache, meno
    # assetu v sklade aj atribúcia v štýle. Keby si ho každé z tých miest
    # počítalo samo, raz by sa rozišli a beh by hľadal v sklade dlaždice pod
    # menom, pod ktorým ich druhá strana neuložila.
    tz = values["terrain_maxzoom"].strip().lower()
    if tz == "auto":
        cell = float(srcs.get(shading_src, {}).get("cell_m") or 20)
        values["terrain_maxzoom"] = str(terrain_zoom_for(cell))
        if shading_src != NONE:
            print(f"Výškové dlaždice: model {shading_src} má mriežku "
                  f"{cell:g} m → maxzoom "
                  f"z{values['terrain_maxzoom']} (pixel "
                  f"{tile_m_per_px(int(values['terrain_maxzoom'])):.1f} m). "
                  f"Pevný zoom sa dá vynútiť voľbou `terrain_maxzoom=13`.")
    elif not tz.isdigit():
        print(f"::error::Voľba „terrain_maxzoom“ musí byť číslo alebo "
              f"`auto`, nie „{values['terrain_maxzoom']}“.", file=sys.stderr)
        return 1
    # Zdroj skál, ktorý je výškový model – teda ten, z ktorého sa má počítať
    # sklon. Pri `tienovanie` a `ziadne` je prázdny a nikto nesmie sťahovať DEM.
    values["rock_dem"] = rock_src if rock_src in srcs else ""

    values["contour_lines"] = "true" if contour_src != NONE else "false"
    values["rocks"] = "true" if rock_src != NONE else "false"
    values["terrain"] = "true" if shading_src != NONE else "false"
    # `contours` je brána celého jobu, nie vrstva: vrstevnice aj skaly z neho
    # vychádzajú do jedného .pmtiles, takže beží aj vtedy, keď sú zapnuté len
    # skaly (a naopak).
    values["contours"] = ("true" if contour_src != NONE or rock_src != NONE
                          else "false")
    # Trasy nemajú výber zdroja – zapínajú sa voľbou, ktorá už je v DEFAULTS.
    # Čokoľvek iné než true/false je chyba: `trails=1` by inak trasy ticho
    # vyplo a zistilo by sa to až tým, že v mape nie sú.
    if values["trails"] not in ("true", "false"):
        print(f"::error::Voľba „trails“ musí byť true alebo false, "
              f"nie „{values['trails']}“.", file=sys.stderr)
        return 1
    # To isté pre krajinné prvky – `features=1` by ich ticho vyplo a zistilo
    # by sa to až tým, že v mape nie sú násypy ani zjazdovky.
    if values["features"] not in ("true", "false"):
        print(f"::error::Voľba „features“ musí byť true alebo false, "
              f"nie „{values['features']}“.", file=sys.stderr)
        return 1
    # To isté pre obmedzenia na ceste – `roads=1` by ich ticho vyplo a zistilo
    # by sa to až tým, že v mape nie je výška ani jedného podjazdu.
    if values["roads"] not in ("true", "false"):
        print(f"::error::Voľba „roads“ musí byť true alebo false, "
              f"nie „{values['roads']}“.", file=sys.stderr)
        return 1
    # To isté pre vyhľadávací index – `search=0` by ho ticho vyplo
    # a v aplikácii by chýbalo offline hľadávanie.
    if values["search"] not in ("true", "false"):
        print(f"::error::Voľba search=... musí byť true alebo false, "
              f"nie {values['search']}.", file=sys.stderr)
        return 1
    # A to isté pre navigáciu – `navigacia=1` by ju ticho vypla a v mape by
    # sa dalo všetko okrem toho, kvôli čomu ju človek v aute má.
    if values["navigacia"] not in ("true", "false"):
        print(f"::error::Voľba navigacia=... musí byť true alebo false, "
              f"nie {values['navigacia']}.", file=sys.stderr)
        return 1

    # A to isté pre publikovanie na Drive: `publish=0` by ho ticho vyplo
    # a mapa by nikde nepribudla bez toho, aby to niekto povedal.
    if values["apple_archive"] not in ("true", "false"):
        print(f"::error::Voľba „apple_archive“ musí byť true alebo false, "
              f"nie „{values['apple_archive']}“.", file=sys.stderr)
        return 1
    if values["publish"] not in ("true", "false"):
        print(f"::error::Voľba „publish“ musí byť true alebo false, "
              f"nie „{values['publish']}“.", file=sys.stderr)
        return 1
    # Nasadenie na Pages je switch vo formulári, takže sem chodí hotové
    # true/false z `inputs`. Kontroluje sa aj tak: skript sa dá spustiť ručne
    # a `--publish-pages=nie` by inak ticho znamenalo „nenasadzuj".
    pages_on = (args.publish_pages or "true").strip().lower()
    if pages_on not in ("true", "false"):
        print(f"::error::Switch „publish_pages“ musí byť true alebo false, "
              f"nie „{args.publish_pages}“.", file=sys.stderr)
        return 1
    values["publish_pages"] = pages_on

    # Interval vrstevníc je voľba (miesto vo formulári si vzal switch
    # `wikipedia`), takže sa musí kontrolovať tu – `contour_interval=päť` by
    # inak spadlo až v `gdal_contour`, po hodine sťahovania DEM.
    try:
        interval = float(values["contour_interval"])
    except ValueError:
        print(f"::error::Voľba „contour_interval“ musí byť číslo v metroch, "
              f"nie „{values['contour_interval']}“.", file=sys.stderr)
        return 1
    if interval <= 0:
        print(f"::error::Voľba „contour_interval“ musí byť väčšia než nula "
              f"(„{values['contour_interval']}“). Vrstevnice sa vypínajú "
              f"výberom `contour_source: ziadne`.", file=sys.stderr)
        return 1
    values["contour_interval"] = f"{interval:g}"

    rebuild = (args.rebuild or "nic").strip()
    if rebuild in REBUILD_ALIAS:
        print(f"::notice::`rebuild: {rebuild}` sa dnes volá "
              f"`{REBUILD_ALIAS[rebuild]}` – tá istá vrstva, to isté meno ako "
              f"vo `shading_source` a v balíku `-tienovanie.zip`. Beriem to "
              f"ako `{REBUILD_ALIAS[rebuild]}`.")
        rebuild = REBUILD_ALIAS[rebuild]
    if rebuild not in REBUILD:
        print(f"::error::Neznáme rebuild „{args.rebuild}“. Známe: "
              f"{', '.join(REBUILD)}", file=sys.stderr)
        return 1
    for flag in REBUILD_FLAGS:
        values[flag] = "true" if flag in REBUILD[rebuild] else "false"

    # RÝCHLY TEST PREGENERÚVA VŽDY VŠETKO, aj pri `rebuild: nic`.
    #
    # Testovací beh je na ladenie – meníš prah, interval alebo kód a chceš
    # vidieť, čo z toho vyjde. Keby sa výsledok vrátil z cache, videl by si
    # to, čo vyšlo naposledy, a ladil by si ducha. Kľúč cache síce nesie
    # nastavenia aj otlačok skriptov, ale nie všetko: pár km² prepočítať
    # stojí minúty, kým jedno takto stratené kolo ladenia stojí viac.
    #
    # Cache ostrého behu je pritom v bezpečí: kľúče vrstevníc, skál
    # a tieňovania nesú `dem_bboxkey` a ten je pri teste bboxom testovacieho
    # štvorca, takže sa maže a prepisuje len cache toho testu.
    #
    # ČLÁNKY SÚ Z TOHO VYNECHANÉ, a je to zámer: nezávisia od testovacieho
    # štvorca ani od prahov, ktoré sa ním ladia – job `wiki` číta celý
    # regionálny PBF tak či tak. Sťahovať pri každom kole ladenia terénu
    # tisíc článkov odznova by bola len daň za to, že sa ladí niečo iné.
    # Kto ich naozaj chce nanovo, má na to `rebuild: clanky`.
    if test_on:
        for flag in ("contours_rebuild", "rocks_rebuild", "terrain_rebuild"):
            values[flag] = "true"

    lines = [f"opt_{k}={v}" for k, v in values.items()]
    if args.out:
        with open(args.out, "a") as f:
            f.write("\n".join(lines) + "\n")

    # ---------- s čím beh štartuje, hneď na začiatku ----------
    # Doteraz bolo toto vidieť až v LOGU prípravného jobu – čiže po
    # rozkliknutí jobu, rozkliknutí kroku a odscrollovaní cez `env:`. A to,
    # čo z volieb naozaj vyšlo (`options` je JEDNO textové pole, z ktorého
    # sa stane tridsať nastavení), sa nedalo porovnať s tým, čo si zadal,
    # bez čítania tohto skriptu. Súhrn prípravného jobu je pritom na stránke
    # behu ako PRVÝ, takže sa dá pozrieť hneď po spustení – a keď beh o hodinu
    # spadne, je stále na očiach, s čím išiel.
    if args.summary:
        with open(args.summary, "a") as f:
            f.write("## Čo z toho vyšlo – s tým beh štartuje\n\n")
            f.write("| nastavenie | hodnota | |\n|---|---|---|\n")
            for k in sorted(values):
                mark = "**iné než default**" if k in changed else ""
                f.write(f"| `{k}` | `{values[k] or '—'}` | {mark} |\n")
            f.write("\nHodnoty bez značky sú predvolené. Tie označené si "
                    "zadal – buď vo formulári, alebo v poli `options`.\n\n")

    print("Nastavenia:")
    for k in sorted(values):
        mark = "  ←" if k in changed else ""
        d = DEFAULTS.get(
            k, ("", "z inputov formulára (zdroje / rebuild / test)"))[1]
        print(f"  {k:<20} {values[k] or '(prázdne)':<24} {d}{mark}")
    if changed:
        print(f"\nZmenené oproti predvolenému: {', '.join(sorted(changed))}")
    if test_on:
        print("Pregenerovať: VŠETKO (rýchly test počíta vždy nanovo, nech "
              f"neladíš na starom výsledku z cache; `rebuild: {rebuild}` "
              "sa tým prebíja)")
    elif rebuild != "nic":
        print(f"Pregenerovať: {rebuild}")
    if test_on or rebuild != "nic":
        # Rule 4: s čím beh ide, musí byť vidieť – vrátane toho, čo sa
        # NEPREPOČÍTA. Bez tohto riadku „vsetko" sľubuje viac, než robí.
        print("  prepočíta sa: "
              + ", ".join(f.replace("_rebuild", "")
                          for f in REBUILD_FLAGS if values[f] == "true"))
        for co, ako in REBUILD_MIMO:
            print(f"  NEprepočíta sa {co} – {ako}")
    print(f"\nVrstevnice: {contour_src}   Skaly: {rock_src}   "
          f"Tieňovanie: {shading_src}   Trasy: {values['trails']}   "
          f"Krajinné prvky: {values['features']}   "
          f"Obmedzenia na ceste: {values['roads']}")
    print("Rýchly test: " + (f"ZAPNUTÝ, terén (vrstevnice, skaly, tieňovanie) "
                             f"len na {values['test_km2']} km² zo stredu "
                             f"výrezu; mapa ostáva celý región a otvorí sa tam"
                             if test_on else "vypnutý – ostrý beh"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
