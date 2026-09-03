#!/usr/bin/env python3
"""
Skaly z TIEŇOVANÝCH DLAŽDÍC (JPG) → vektorové plochy (GeoPackage).

Pokusná druhá cesta k skalám. Tá prvá (`workers/contours-rocks/rock-areas.py`) počíta sklon
z DEM a vektorizuje izolíniu sklonu. Táto berie hotový hillshade – dlaždice
`https://sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg` – a hľadá v ňom
TMAVÉ PLOCHY. Nič sa nepočíta z výšok, čítajú sa obrázky:

    XYZ dlaždice (JPG) → mozaika odtieňov šedej v EPSG:3857 →
    raster „tmavosti" → otvorenie (preč, čo je užšie než stena) →
    gdal_contour -p (izolínia tmavosti ako PLOCHY) →
    filter plôch → zjemnenie + zaoblenie obrysu → rock.gpkg

JEDNA TRIEDA (predvolene, `--plne`): jedno pásmo, teda žiadna plocha vnútri
inej plochy. Kým sa `steep` a `cliff` kreslili rôzne tmavo, malo zmysel mať
pásma dve; odkedy je všetko jedna sivá bez priehľadnosti, je z druhého len
dvojnásobok prstencov na obtiahnutie – a `gdal_contour` je tá najdrahšia fáza
celého behu. `--plne=0` vráti pásma `steep`/`cliff`.

DIERY OSTÁVAJÚ. Sú to medzery medzi vláknami siete žliabkov a práve ony sú tá
štruktúra – bez nich je z pol pohoria jedna súvislá plocha, v ktorej nie je
vidieť nič. `--zapln-diery=1` ich zaplní, ak by niekto chcel súvislé klaksy.

POZADIE SA ZAHADZUJE. `gdal_contour -p` nevyrobí len pásmo skál, ale VŠETKY
pásma – vrátane toho POD prahom, čiže „všetko, čo skala nie je". Je to jeden
obrovský polygón na blok a keď prejde ďalej, prekryje mapu súvislou plochou,
v ktorej nie je vidieť ani skaly, ani obrysy. Filter ho preto vyhadzuje podľa
`dmin` a beh navyše kričí, keď skaly vyjdú na viac než 60 % územia.

PREČO TO MÔŽE FUNGOVAŤ: tieňovanie je obraz sklonu. Kde je stena, tam je
tieň – a hires vrstva freemap.sk je robená z 1 m LiDARu, takže pri z18 vyjde
jeden pixel na ~0,4 m terénu. Ťaháme z17 (~0,8 m/px) – na z18 sú to 4×
dlaždice a obrysy rastú ešte rýchlejšie, pričom mapa z toho nemá nič.
Aj tak je to jemnejšie, než na čo vieme rozumne spočítať sklon sami.

PREČO TO MÔŽE KLAMAŤ: tmavý nie je len sklon, ale sklon NA ODVRÁTENEJ STRANE.
Rovnako strmá stena otočená k slnku je na hillshade najsvetlejšia zo všetkého.
Táto cesta preto systematicky nájde severozápadné steny a systematicky
prehliadne juhovýchodné. Je to POKUS, nie náhrada `rock-areas.py`; v mape sa
zapína zvlášť (`rock_source: tienovanie`).

── čo ukázala skutočná dlaždica ────────────────────────────────────────────

Namerané na výreze z tej vrstvy (1260×1933 px, Vysoké Tatry):

  * Je to FAREBNÝ hillshade, nie šedý – žltozelený nádych, tiene ťahajú do
    modra (sýtosť ~34, B−R od −95 do +50). Čítame ho ako jas (`convert("L")`,
    luma 601), kde modrý kanál váži najmenej, takže sa modré tiene ešte
    prehĺbia. To nám vyhovuje. Farba ako druhý, nezávislý signál zatiaľ
    použitá NIE JE.
  * Rozloženie jasu: medián 176, 20. percentil 135, 10. percentil 107.
    Prah `--dark 125` z toho odkrojí ~16 % plochy a sedí na skalnatý terén.
  * TMAVÉ NIE JE PLOCHA, ALE SIEŤ. Tmavé miesta nie sú súvislé steny, ale
    hustá sieť žliabkov, ryhiek a mikrotieňov v rozčlenenom teréne. Tvar tej
    siete je to, čo chceme – nie vyplnená klaksa. Preto je `--fill`
    (spriemerovanie tmavosti v okolí, ktoré zo siete spraví súvislú plochu)
    štandardne VYPNUTÉ.
  * ALE NAJTENŠIE VLÁKNA SIETE SKALA NIE SÚ a v mape sú to práve ony, čo
    škodí. Sú to vlásočnicové ryhy a mikrotiene cez celý svah; vektorizáciou
    sa z nich stane jeden prepojený polygón cez celý výrez a pri z14
    a nižšie z neho nie je sieť, ale rovnomerná SIVÁ DEKA. Namerané na
    výreze pri Gerlachu (2 km², z17, dark=125): 21,6 % plochy, najväčší
    útvar 30,6 ha, pri z14 zaliatych 20,7 % pixelov. `--open` ich zmaže
    podľa ŠÍRKY (3 m → 9,5 % plochy a pri z14 čitateľné samostatné telesá).
    Podľa plochy to nejde: celá sieť je jeden veľký útvar, takže `min_area`
    na ňu vôbec nesiaha.
  * Sieť je pospájaná: 16 útvarov pokrylo 15 % výrezu, takže počet útvarov
    neexploduje. Explodujú BODY – pri z18 to vyšlo na ~2 MB GeoPackage na km²
    skalnatého terénu.
  * Z toho vyšli aj predvolené hodnoty filtrov. Merané na tom istom výreze:

        min_area 200 m², min_hole 50 m², simplify ½ px, jemné zaoblenie →
            16 plôch,  89 dier,  3,95 MB/km²
        min_area  50 m², min_hole 10 m², simplify 1 px,  hrubšie zaoblenie →
            78 plôch, 392 dier,  1,97 MB/km²   ← toto

    Jemnejšie filtre a hrubšie zjednodušenie dali SÚČASNE viac štruktúry aj
    polovičné dáta: pol pixela a druhý prechod Chaikinom leštili obrys, ktorý
    aj tak nikto nerozozná, zatiaľ čo `min_area 200` zmazal práve tie drobné
    útvary, o ktoré ide. Predvolené `--min-area` sme podľa toho posunuli ešte
    nižšie, na 5 m² (~8 pixelov na z17) – tabuľka ostáva pri tom, čo bolo
    naozaj namerané.

── ako sa rozhoduje, čo je tmavé ────────────────────────────────────────────

Jeden prah na celú mozaiku nestačí: celý zatienený svah je tmavý bez toho,
aby bol skala, a naopak stena v presvetlenej doline býva svetlejšia než
priemerná tráva vedľa. Prah sa preto skladá z troch čísel:

    ref   = clip(miestne_pozadie − --rel, --dark-always, --dark)
    score = max(0, ref − šedá)

    šedá nad `--dark`         → nikdy nie je skala
    šedá pod `--dark-always`  → vždy je skala, nech je okolo čokoľvek
    medzi tým                 → skala len vtedy, keď je aspoň `--rel` pod
                                miestnym pozadím

Dolný strop `--dark-always` tam nie je pre ozdobu. Bez neho sa VEĽKÁ súvislá
stena nenájde: okno pozadia sa celé zmestí dovnútra nej, pozadie klesne na
tmavosť samotnej steny a nájde sa len jej okraj (namerané na skúšobných
dátach – z plochy ostal prstenec). Pod `--dark-always` už o okolí nikto
nehlasuje.

Miestne pozadie NIE JE obyčajný priemer, ale priemer tých SVETLEJŠÍCH
pixelov v okne (dva prechody: najprv priemer, potom priemer len z pixelov
nad ním). Odpoveď na otázku „ako svetlý je tu osvetlený terén" sa nesmie dať
stiahnuť dole tým, čo práve hľadáme. Okno `--local` je v METROCH na zemi,
nie v pixeloch – nastavenie tak platí na každom zoome rovnako a má byť
podstatne väčšie než najväčšia hľadaná skala.

Pozadie sa počíta na 8× zmenšenom obraze a späť sa roztiahne. Je to pole
osvetlenia, nie detail – na osemnásobne menšej mriežke vyzerá rovnako a je
64× lacnejšie na pamäť aj čas.

── prečo gdal_contour, a nie gdal_polygonize ───────────────────────────────

`gdal_polygonize` by obrys viedol po hranách pixelov (schodíky) a potreboval
by python bindings GDALu. `gdal_contour -p` nad poľom tmavosti interpoluje
medzi celými stupňami šedej, takže obrys je hladký a sub-pixelový – a je to
presne ten istý nástroj a tá istá sémantika dier, akú používa `rock-areas.py`:
pásmo [prah, ∞) je polygón s vnútornými prstencami tam, kde hodnota pod prah
klesla. Svetlé miesto vnútri tmavej plochy (polica, sneh, kosodrevina) tak
ostane DIEROU a nezafarbí sa – presne ako pri skalách z DEM.

Dve triedy naraz: úrovne sú `0,5` (trieda `steep`) a `0,5 + --cliff`
(trieda `cliff`). Trieda `cliff` leží v diere triedy `steep`, kreslí sa nad
ňou a dieru vyplní – rovnaká situácia ako u vrstevnicových pásiem.

── prečo sa vektorizuje po blokoch ─────────────────────────────────────────

Pôvodne to bol jeden `gdal_contour` nad celou mozaikou – rovnako ako
v `rock-areas.py` a z toho istého dôvodu: diera prerezaná hranicou časti sa
zmení na zárez v okraji. Nad 3,62 mld. pixelov to ale bežalo 2 h 41 min,
nedopočítalo sa a zabil to timeout jobu, pričom pamäť ostala na 0,7 GB.
Nebola to teda pamäť, ale skladanie prstencov: `-p` z izolínií zostavuje
uzavreté obrysy a v zrnitom JPEGu ich je obrovské množstvo – spájanie
segmentov rastie rýchlejšie než lineárne, takže dvojnásobný raster nestojí
dvojnásobok, ale oveľa viac.

Preto sa contour púšťa po blokoch (`--block-tiles`, default 8 = 2048 px).
Blok je malý raster: prstence sa v ňom poskladajú rýchlo, pamäť je zhora
ohraničená a čo je hotové, leží na disku – po páde sa pokračuje od prvého
nespočítaného bloku.

Cena za to je presne tá pôvodná námietka: plocha cez hranicu bloku vypadne
ako dva kusy. Rieši to `zlep_svy()` – útvary, ktoré sa hranice naozaj
dotýkajú, sa označia už pri bloku (`sev=1`) a na konci sa zlepia cez
`ST_Union` (spatialite). Nie je to únia všetkého so všetkým: dotýka sa jej
zlomok plôch. Keď spatialite chýba, beh pokračuje s rozseknutými plochami
a povie to – rozseknutá skala je horšia mapa, nie zlá mapa.

Raster tmavosti sa aj naďalej počíta po pásoch dlaždicových riadkov
s presahom kvôli oknu pozadia; to sa nemenilo.

── čo to stojí ─────────────────────────────────────────────────────────────

Nie je to štvornásobok na zoom, ako tu stálo predtým. Sťahovanie áno, ale
obrysy nie – a tie sú to drahé. Namerané na Vysokých Tatrách (beh 31222472790):

  z17   13 815 dlaždíc, 0,91 mld. buniek   obrysy ~50 min (odhad)
  z18   55 260 dlaždíc, 3,62 mld. buniek   obrysy 2 h 41 min a NEDOPOČÍTALO SA
                                           (sťahovanie pritom len 12 minút)

Preto má `auto` okrem stropu na dlaždice aj rozpočet času (`--budget-min`)
a obrysy sa nad ním zastavia s hláškou. Dlaždice sa sťahujú do `--cache-dir`
a pri opakovanom behu sa berú odtiaľ, takže ani ladenie prahov, ani krok
o zoom nižšie nestojí jeden request navyše.

── keď to spadne, netreba začínať odznova ──────────────────────────────────

Rozrobené leží v `<cache-dir>/_rozrobene/<podpis prahov>/` – teda v cache
dlaždíc, ktorá sa ukladá aj po páde a po timeoute. Ďalší beh preskočí, čo už
je hotové:

    score0000.tif …   pásy rastra tmavosti  (pás po páse)
    bloky/b00000…     obrysy po blokoch     (blok po bloku)
    bands.geojsonl    bloky zlepené do jedného prúdu
    rock.geojsonl     vyfiltrované polygóny

Každá fáza sa píše do `.part` a premenuje sa až celá, takže nedopísaný kus
sa za hotový nikdy nevydá. Po úspešnom behu sa `_rozrobene` maže – nemá
zmysel, aby cache rástla o medzivýsledky. `--fresh=1` ho zahodí dopredu.

Sťahuje sa z dobrovoľníckej služby freemap.sk – `--jobs` je zámerne nízke.

Použitie:
    python3 workers/rocks-shading/build.py --bbox=19.9,49.09,20.32,49.25 \\
        --zoom=auto --dark=110 --local=512 --rel=18 --cliff=25 --open=3 \\
        --out=data/rock.gpkg --stats=out/rock-img-stats.txt \\
        --preview=out/preview.png
"""
import argparse
import importlib.util
import math
import os
import shlex
import shutil
import sys
import time

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    """workers/*.py sa kvôli pomlčke v mene nedajú `import`-núť normálne."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# TRI FÁZY, TRI MODULY. Tento súbor je plán, náhľad a CLI; samotná práca je
# vedľa, v tom poradí, v akom ju robia tri joby `shading-rocks.yml`:
#
#   shading-tiles.py    stiahni JPG dlaždice z freemap.sk (+ mriežka, zoomy)
#   shading-raster.py   z nich raster „ako tmavé je to tu oproti okoliu"
#   shading-vector.py   z rastra obrysy po blokoch, švy, filter, vyhladenie
#
# Rozdelené preto, že spolu to malo 2023 riadkov a v takom súbore sa nedá
# rýchlo nájsť, čo sa zmenilo ani prečo to spadlo (pravidlo 5 v CLAUDE.md,
# strop 800 stráži `Kontrola · lint workflowov`). Rezy sú presne tam, kde v tom súbore už
# boli vyznačené komentárom – a kde sa delia aj tie joby.
tiles = load("shading_tiles", "tiles.py")
raster = load("shading_raster", "raster.py")
vector = load("shading_vector", "vector.py")

# Mená, ktoré tento súbor naozaj používa. Naviazané, nie prepisované na
# `tiles.…` v desiatkach miest – a hlavne na jednom mieste vidieť, čo si tento
# súbor z ktorej fázy berie.
WEBMERC, R, TILE = tiles.WEBMERC, tiles.R, tiles.TILE
TILES_PER_S, CONTOUR_CELLS_PER_S = tiles.TILES_PER_S, tiles.CONTOUR_CELLS_PER_S
BG_DOWN = raster.BG_DOWN
run = tiles.run
tile_range, tile_res, ground_res = tiles.tile_range, tiles.tile_res, tiles.ground_res
Fetcher, probe_zoom, BROWSERS = tiles.Fetcher, tiles.probe_zoom, tiles.BROWSERS
build_score_raster = raster.build_score_raster
bbox_km2, obrysy, spoj, empty_rock = (vector.bbox_km2, vector.obrysy, vector.spoj,
                                      vector.empty_rock)
zapis_stiahnute, nacitaj_stiahnute = vector.zapis_stiahnute, vector.nacitaj_stiahnute

# `hms` a `dir_mb` sú z `watch.py` – ten sa dá importovať normálne, nemá
# v mene pomlčku.
# `watch.py` je spoločný (skaly zo sklonu aj z tieňovania, dlhé kroky
# workflowu), tak leží vo `workers/lib/` a nie vedľa jedného z nich.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from watch import hms, dir_mb  # noqa: E402


# ----------------------------------------------------------------- náhľad ---

def save_preview(rows, path):
    """Zmenšená mozaika vedľa nájdených plôch – aby sa prahy dali doladiť
    pohľadom, nie hádaním. Vľavo šedá, vpravo to isté s červenou maskou."""
    if not rows:
        return
    gray = np.concatenate([g for g, _ in rows], axis=0)
    mask = np.concatenate([m for _, m in rows], axis=0)
    rgb = np.dstack([gray, gray, gray])
    hit = mask > 0
    rgb[..., 0] = np.where(hit, 255, rgb[..., 0])
    rgb[..., 1] = np.where(hit, (gray * 0.35).astype(np.uint8), rgb[..., 1])
    rgb[..., 2] = np.where(hit, (gray * 0.35).astype(np.uint8), rgb[..., 2])
    both = np.concatenate([np.dstack([gray, gray, gray]), rgb], axis=1)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(both).save(path)
    print(f"  náhľad: {path} ({both.shape[1]}×{both.shape[0]} px)", flush=True)


def histogram(rows):
    """Rozloženie odtieňov šedej – prvé, čo treba vidieť pri ladení prahu."""
    if not rows:
        return ""
    gray = np.concatenate([g for g, _ in rows], axis=0)
    hist, _ = np.histogram(gray, bins=16, range=(0, 256))
    tot = max(1, hist.sum())
    out = ["  šedá     podiel"]
    for i, v in enumerate(hist):
        pct = 100.0 * v / tot
        out.append(f"  {i * 16:>3}–{i * 16 + 15:<3} {pct:5.1f} % "
                   f"{'█' * int(round(pct / 2))}")
    return "\n".join(out)


# ------------------------------------------------------------------- plán ---

def print_plan(z, x0, y0, x1, y1, args):
    n_tiles = (x1 - x0) * (y1 - y0)
    cells = n_tiles * TILE * TILE
    dl_s = n_tiles / TILES_PER_S
    ct_s = cells / CONTOUR_CELLS_PER_S
    print("── Plán: skaly z tieňovaných dlaždíc ────────────────")
    print(f"  zoom            z{z}  ({tile_res(z):.2f} m/px v Mercatore, "
          f"~{ground_res(z, (args.bbox[1] + args.bbox[3]) / 2):.2f} m na zemi)")
    print(f"  dlaždice        {x1 - x0} × {y1 - y0} = {n_tiles}")
    print(f"  mozaika         {(x1 - x0) * TILE} × {(y1 - y0) * TILE} px "
          f"= {cells / 1e9:.2f} mld.")
    print(f"  prah tmavosti   nikdy nad {args.dark}, vždy pod {args.dark_always}"
          + (f", medzi tým {args.rel} pod pozadím "
             f"(okno {args.local:g} m = {args.local_px} px)"
             if args.local_px else ", bez miestneho pozadia"))
    print(f"  triedy          steep, cliff od {args.cliff} stupňov navyše")
    print("  užšie než       " + (f"{2 * args.open:g} m preč "
                                  f"(otvorenie {args.open_px} px) – "
                                  f"vlásočnice nie sú stena"
                                  if args.open_px else
                                  "nič (otvorenie vypnuté)"))
    print("  štruktúra       " + (f"vyplnená, okno {args.fill:g} m "
                                  f"({args.fill_px} px)" if args.fill_px
                                  else "jemná sieť žliabkov (fill vypnuté)"))
    print("  hlavičky        " + ("každý request ako iný prehliadač "
                                  f"({len(BROWSERS)} profilov)"
                                  if args.ua == "rotate" else
                                  "meno projektu" if args.ua == "project"
                                  else f"vlastné: {args.ua}"))
    print(f"  odhad sťahovanie ~{hms(dl_s)}")
    print(f"  odhad obrysy     ~{hms(ct_s)}")
    print("─────────────────────────────────────────────────────", flush=True)
    return n_tiles, cells


def apply_options(ap, args):
    """`kľúč=hodnota` z jedného textového poľa → tie isté prepínače.

    `workflow_dispatch` dovolí najviac 10 inputov (viď parse-options.py),
    takže zriedka menené veci idú do jedného poľa. Rozkladá sa to tu a nie
    v YAMLe zámerne: prepínače pozná táto trieda argparse, nie shell, a
    preklep tak vypadne ako hláška, nie ako ticho iné nastavenie.
    """
    raw = (args.options or "").strip()
    if not raw:
        return args
    known = {a.dest for a in ap._actions if a.dest not in ("help", "options")}
    extra = []
    for tok in shlex.split(raw):
        if "=" not in tok:
            print(f"::error::Voľba „{tok}“ nemá tvar kľúč=hodnota.",
                  file=sys.stderr)
            sys.exit(1)
        k, v = tok.split("=", 1)
        k = k.strip().replace("-", "_")
        if k not in known:
            print(f"::error::Neznáma voľba „{k}“. Známe voľby: "
                  f"{', '.join(sorted(known))}", file=sys.stderr)
            sys.exit(1)
        extra.append(f"--{k.replace('_', '-')}={v}")
    print(f"Z options: {' '.join(extra)}", flush=True)
    return ap.parse_args(sys.argv[1:] + extra)


def main():
    ap = argparse.ArgumentParser(
        description="Skalné plochy z tmavých miest v tieňovaných dlaždiciach.")
    ap.add_argument("--bbox", required=True, help="W,S,E,N v stupňoch")
    ap.add_argument("--url", default="https://sk-hires-shading.tiles.freemap.sk/{z}/{x}/{y}.jpg",
                    help="XYZ šablóna s {z}/{x}/{y}")
    ap.add_argument("--zoom", default="auto", help="číslo alebo `auto`")
    # z17 je strop, nie z19. Vyššie zoomy síce server dá, ale na z18 sú to 4×
    # dlaždice a obrysy rastú ešte rýchlejšie – 3,62 mld. pixelov na z18 nad
    # Vysokými Tatrami bežalo 2 h 41 min a nedopočítalo sa. Mapa z toho
    # nemá nič: z17 je ~0,8 m na pixel a plocha sa zobrazuje do maximálneho
    # zoomu tak či tak (dlaždice sa naťahujú overzoomom).
    ap.add_argument("--zoom-max", type=int, default=17,
                    help="najvyšší zoom, na ktorý sa vôbec pýtame dlaždíc "
                         "(odtiaľ `auto` skúša nadol)")
    ap.add_argument("--zoom-min", type=int, default=12)
    ap.add_argument("--max-tiles", type=int, default=60000,
                    help="strop na počet dlaždíc – `auto` pod neho zíde sám")
    # Číslo, nie `store_true`: voľby z jedného textového poľa chodia vždy ako
    # `kľúč=hodnota`, takže prepínač bez hodnoty by cez ne nešiel zadať.
    ap.add_argument("--block-tiles", type=int, default=8,
                    help="strana bloku v dlaždiciach pri obrysoch; menší blok "
                         "= menej pamäte a jemnejšie pokračovanie, ale viac "
                         "volaní GDALu (8 = 2048 px, 3 = 768 px)")
    # Vo workflowe sú z toho TRI joby, každý s vlastným stropom času – dokopy
    # sa to do jedného rozpočtu zmestiť nemusí a keď čas dôjde, padne aj to,
    # čo už bolo hotové. Medzivýsledky si podávajú cez cache:
    #
    #   stiahnut  dlaždice do cache
    #   vektor    raster tmavosti + obrysy po blokoch (`_rozrobene/…/bloky`)
    #   spojit    zlepenie blokov, švy, filter, vyhladenie → rock.gpkg
    #
    # `vsetko` je to isté v jednom kuse – tak sa to spúšťa z ruky.
    ap.add_argument("--phase", default="vsetko",
                    choices=("vsetko", "stiahnut", "vektor", "spojit"),
                    help="ktorú časť spraviť")
    ap.add_argument("--zoom-out", default="",
                    help="kam zapísať vybraný zoom (`zoom=17`) pre ďalší job")
    ap.add_argument("--fresh", type=int, default=0,
                    help="1 = zahodiť rozrobené z predošlého behu a počítať "
                         "všetko odznova (dlaždice ostávajú v cache)")
    ap.add_argument("--log-every", type=int, default=25,
                    help="po koľkých dlaždiciach vypísať riadok "
                         "(1 = každá, 0 = len každých 15 s)")
    # 0 = BEZ STROPU, a to je predvolené. Strop tu robil dve veci naraz:
    # zhora obmedzoval, aký zoom si `auto` vyberie, a v polovici obrysov
    # beh zastavil s `TimeoutError`. To druhé nezachránilo nikdy nič –
    # rozrobené bloky sa síce odkladajú, ale beh skončil chybou namiesto
    # toho, aby dopočítal zvyšok. Kto strop chce, podá `budget_min=…`.
    ap.add_argument("--budget-min", type=float, default=0,
                    help="koľko minút smú trvať obrysy; `auto` pod to zíde "
                         "sám a beh sa nad tým zastaví (0 = bez stropu, "
                         "predvolené)")
    ap.add_argument("--dark", type=int, default=125,
                    help="absolútny strop: nad touto šedou nie je skala nikdy")
    ap.add_argument("--dark-always", type=int, default=70,
                    help="pod touto šedou je skala vždy, nech je okolo čokoľvek")
    ap.add_argument("--local", type=float, default=1500.0,
                    help="okno miestneho pozadia v METROCH na zemi (0 = vypnuté)")
    ap.add_argument("--rel", type=int, default=18,
                    help="o koľko musí byť pixel pod miestnym pozadím")
    ap.add_argument("--cliff", type=int, default=25,
                    help="o koľko stupňov tmavšie začína trieda `cliff`")
    ap.add_argument("--blur", type=int, default=1,
                    help="polomer vyhladenia šedej v px (0 = vypnuté, max 2)")
    ap.add_argument("--fill", type=float, default=0.0,
                    help="spriemerovať tmavosť v okne toľkých METROV – zo "
                         "siete žliabkov spraví súvislú plochu (0 = vypnuté)")
    # Vlásočnicové ryhy a mikrotiene sú tmavé, ale nie sú to steny – a práve
    # z nich je v mape pri nižších zoomoch rovnomerná sivá deka cez celý
    # výrez. Otvorenie ich zmaže podľa ŠÍRKY (nie podľa plochy – celá sieť je
    # jeden veľký útvar, takže `min_area` na ňu nesiaha). Namerané pri
    # Gerlachu: 21,6 % plochy bez neho, 9,5 % pri 3 m. Viď `open_mask`.
    ap.add_argument("--open", type=float, default=3.0,
                    help="zmazať útvary užšie než 2× toľko METROV "
                         "(0 = vypnuté, necháva aj vlásočnice)")
    # 7 m² je ~11 pixelov na z17. Zámerne nízko: tmavé miesta v tieňovaní nie
    # sú súvislé steny, ale hustá sieť žliabkov a mikrotieňov – a práve tá
    # jemná štruktúra je to, čo z hillshade chceme (viď hlavičku súboru).
    ap.add_argument("--min-area", type=float, default=7.0,
                    help="najmenšia skalná plocha v m²")
    # Plné plochy: bez dier a bez druhého pásma. Viď `contour_blocks`
    # a `filter_stream` – dokopy z toho je „jedna skala = jedna sivá plocha".
    ap.add_argument("--plne", type=int, default=1,
                    help="1 = jedno pásmo a jedna trieda (žiadna plocha "
                         "vnútri inej), 0 = pásma steep/cliff ako predtým")
    # Zapĺňanie dier bolo kedysi súčasťou `--plne` a bola to chyba: diery sú
    # medzery medzi vláknami siete žliabkov, čiže presne tá štruktúra, pre
    # ktorú sa skaly z tieňovania robia. Zapnuté z nich spravilo súvislé
    # plochy, v ktorých nebolo vidieť nič.
    ap.add_argument("--zapln-diery", type=int, default=0,
                    help="1 = zaplniť diery (súvislé plochy namiesto siete)")
    ap.add_argument("--zlepit", type=int, default=0,
                    help="1 = zlepiť plochy rozseknuté hranicou bloku "
                         "(ST_Union, potrebuje spatialite)")
    ap.add_argument("--min-hole", type=float, default=10.0,
                    help="najmenšia diera, ktorá sa zachová, v m²")
    ap.add_argument("--simplify", type=float, default=-1,
                    help="zjednodušenie obrysu v metroch (-1 = jeden pixel)")
    ap.add_argument("--smooth", type=int, default=2,
                    help="dovolený priehyb zaobleného obrysu v ŠTVRTINÁCH "
                         "kroku mriežky dlaždice (0 = zaoblenie vypnuté)")
    # Maxzoom .pmtiles so skalami – z neho vyjde krok mriežky, podľa ktorého
    # sa zaoblený obrys vzorkuje. `rocks.yml` ide predvolene na 16 (strop
    # Planetilera, `ROCK_MAXZOOM` v build-map-region.yml) a nie je kam ho dvíhať.
    ap.add_argument("--maxzoom", type=int, default=16,
                    help="maxzoom dlaždíc so skalami (mriežka `extent`)")
    ap.add_argument("--jobs", type=int, default=12, help="paralelné sťahovanie")
    ap.add_argument("--ua", default="rotate",
                    help="`rotate` = každý request ako iný prehliadač, "
                         "`project` = priznať sa menom projektu, alebo "
                         "vlastný User-Agent doslova")
    ap.add_argument("--cache-dir", default="tiles-cache")
    ap.add_argument("--band-cells", type=float, default=150e6,
                    help="koľko pixelov naraz drží jeden pás v pamäti")
    ap.add_argument("--heartbeat", type=int, default=30)
    ap.add_argument("--preview", default="", help="kam uložiť náhľad PNG")
    ap.add_argument("--preview-down", type=int, default=16,
                    help="koľkokrát zmenšiť náhľad")
    ap.add_argument("--stats", default="", help="kam zapísať kľúč=hodnota")
    ap.add_argument("--options", default="",
                    help="zriedka menené prepínače ako `kľúč=hodnota`, "
                         "napr. `local=800 min_area=300`")
    ap.add_argument("--out", required=True)
    args = apply_options(ap, ap.parse_args())

    args.bbox = [float(v) for v in args.bbox.split(",")]
    if len(args.bbox) != 4:
        print("::error::--bbox musí byť W,S,E,N.", file=sys.stderr)
        return 1
    args.blur = max(0, min(2, args.blur))
    lat_mid = (args.bbox[1] + args.bbox[3]) / 2.0

    os.makedirs(args.cache_dir, exist_ok=True)
    fetcher = Fetcher(args.url, args.cache_dir, jobs=args.jobs, ua=args.ua,
                      log_every=args.log_every)

    if str(args.zoom).strip().lower() == "auto":
        z = probe_zoom(fetcher, args.bbox, args.zoom_max, args.zoom_min,
                       args.max_tiles, args.budget_min * 60)
        if not z:
            return 1
    else:
        z = int(args.zoom)

    # Okno pozadia je zadané v metroch na zemi – v pixeloch je až tu, keď je
    # známy zoom. Vďaka tomu má to isté nastavenie na z17 aj z18 rovnaký zmysel.
    args.local_px = (int(round(args.local / ground_res(z, lat_mid)))
                     if args.local > 0 else 0)
    args.fill_px = (int(round(args.fill / ground_res(z, lat_mid)))
                    if args.fill > 0 else 0)
    args.open_px = (max(1, int(round(args.open / ground_res(z, lat_mid))))
                    if args.open > 0 else 0)
    x0, y0, x1, y1 = tile_range(args.bbox, z)
    n_tiles, cells = print_plan(z, x0, y0, x1, y1, args)
    if n_tiles > args.max_tiles:
        print(f"::error::z{z} má {n_tiles} dlaždíc, strop je {args.max_tiles}. "
              f"Zvoľ menší výrez alebo nižší zoom (alebo zdvihni --max-tiles).",
              file=sys.stderr)
        return 2

    if args.simplify < 0:
        # Jeden pixel, nie štvrtina ako pri skalách z DEM: zdroj je 8-bitový
        # JPEG, takže pod pixel je už len zrno kompresie. Namerané na
        # skutočnej dlaždici (viď hlavičku súboru) – pol pixela a jemnejšie
        # zaoblenie stáli dvojnásobok dát za obrys, ktorý vyzerá rovnako.
        args.simplify = tile_res(z)

    # Pracovný priečinok leží v cache dlaždíc, nie vedľa výstupu. To je celý
    # trik pokračovania: cache sa ukladá aj vtedy, keď job spadne alebo ho
    # zabije timeout (`if: always()` v shading-rocks.yml), takže hotové pásy
    # rastra, obrysy aj vyfiltrované polygóny prežijú a ďalší beh ich len
    # prevezme. Podpis v mene: iné prahy = iný medzivýsledok, takže sa dva
    # rôzne behy nemôžu pomiešať.
    podpis = (f"z{z}-d{args.dark}-a{args.dark_always}-r{args.rel}"
              f"-c{args.cliff}-l{args.local:g}-f{args.fill:g}-b{int(args.blur)}"
              # Otvorenie mení RASTER tmavosti, teda aj obrysy v blokoch –
              # bez neho v podpise by ďalší beh nadviazal na bloky spočítané
              # s iným (alebo žiadnym) otvorením.
              f"-o{args.open:g}"
              f"-m{args.min_area:g}-h{args.min_hole:g}"
              # Plné plochy menia PÁSMA, teda aj obsah blokov – bez toho
              # by po prepnutí nadviazal na obrysy z iného nastavenia.
              f"{'-plne' if args.plne else ''}"
              f"-zd{int(bool(args.zapln_diery))}")
    tmp = os.path.join(args.cache_dir, "_rozrobene", podpis)
    # `fresh` znamená „nenadväzuj na rozrobené z PREDOŠLÉHO behu". To je vec
    # fáz, ktoré rozrobené vyrábajú. Fáza `spojit` ho len číta – a beží ako
    # samostatný job PO fáze `vektor`, takže by nezmazala starú prácu, ale tú,
    # ktorú pred pár minútami vyrobil job vedľa. Skončilo by to na „Chýbajú
    # obrysy blokov" a vyzeralo by to ako stratená cache. (Presne to sa aj
    # stalo, keď build začal posielať `fresh=1` do všetkých troch fáz.)
    if args.fresh and args.phase != "spojit":
        shutil.rmtree(tmp, ignore_errors=True)
    elif args.fresh:
        print("  `fresh` sa vo fáze `spojit` ignoruje: zlepuje sa to, čo "
              "vyrobila fáza `vektor` v tomto behu.", flush=True)
    os.makedirs(tmp, exist_ok=True)
    if os.listdir(tmp):
        print(f"── Rozrobené z predošlého behu ──────────────────────")
        print(f"  {tmp}")
        for f in sorted(os.listdir(tmp)):
            print(f"    {f}  {dir_mb(os.path.join(tmp, f)):.0f} MB")
        print("  hotové fázy sa preskočia; `options: fresh=true` to zahodí")
        print("─────────────────────────────────────────────────────", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    t_all = time.time()
    # Prah je 0,5, nie 1: dáta sú celé čísla, takže izolínia v polovici kroku
    # ide presne stredom medzi „nie je tmavé" a „je tmavé" a obrys vyjde
    # sub-pixelový.
    cliff_level = 0.5 + args.cliff
    merc = math.cos(math.radians(lat_mid)) ** 2
    dl_s = sc_s = vec_s = 0.0

    if args.phase == "spojit":
        # Zlepovanie číta obrysy blokov, nie obrázky – sťahovať ich znova by
        # bolo len zbytočné klopanie na cudzí server. Čísla o dlaždiciach idú
        # z toho, čo si odložila fáza sťahovania.
        print("── Dlaždice: preskočené (fáza spojenia) ─────────────", flush=True)
        dl = nacitaj_stiahnute(args.cache_dir, n_tiles)
    else:
        print("── Sťahovanie dlaždíc ───────────────────────────────", flush=True)
        dl_s = fetcher.fetch_all(z, x0, y0, x1, y1)
        if fetcher.n_ok + fetcher.n_cached == 0:
            print("::error::Nestiahla sa ani jedna dlaždica – bez dát sa nedá "
                  "nič vektorizovať.", file=sys.stderr)
            return 1
        dl = zapis_stiahnute(args.cache_dir, fetcher, n_tiles)

        # Vybraný zoom von, nech ho ďalší job nemusí hádať znova. Pri `auto`
        # ho určuje sonda a rozpočet – deterministické to je, ale spoliehať sa
        # na to, že dva behy dopadnú rovnako, je zbytočné riziko.
        if args.zoom_out:
            with open(args.zoom_out, "a") as f:
                f.write(f"zoom={z}\n")

        if args.phase == "stiahnut":
            print("── Hotovo (len sťahovanie) ──────────────────────────")
            print(f"  zoom            z{z}")
            print(f"  dlaždice        {n_tiles} ({fetcher.bytes / 1048576:.0f} MB "
                  f"stiahnutých, {fetcher.n_cached} z cache)")
            print(f"  čas             {hms(dl_s)}")
            print("  Vektorizácia je vlastný job – dlaždice si vezme z cache.")
            print("─────────────────────────────────────────────────────", flush=True)
            return 0

    if args.phase != "spojit":
        print("── Raster tmavosti ──────────────────────────────────", flush=True)
        preview_rows = [] if args.preview else None
        tifs, sc_s = build_score_raster(fetcher, z, x0, y0, x1, y1, args, tmp,
                                        preview_rows)

        print("── Obrysy po blokoch ────────────────────────────────", flush=True)
        t_vec = time.time()
        try:
            n_blokov = obrysy(tifs, args, tmp, cliff_level)
        except RuntimeError as exc:
            # Napr. kontrola jednotiek. Hláška je zrozumiteľná, traceback nie.
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        except TimeoutError:
            # Odhad bol vedľa. Povedať to s číslom a s tým, čo zmeniť, je
            # užitočnejšie než traceback – a stiahnuté dlaždice ostávajú
            # v cache, takže ďalší beh na nižšom zoome nesťahuje nič.
            print(f"::error::Obrysy sa nestihli do {args.budget_min:g} min. "
                  f"Skús nižší zoom (`zoom: {z - 1}`), menší výrez, alebo "
                  f"zdvihni rozpočet (`options: budget_min=…`). Dlaždice sú "
                  f"v cache, takže ďalší beh ich neťahá znova.",
                  file=sys.stderr)
            return 2
        vec_s = time.time() - t_vec

        # Náhľad a histogram vznikajú pri rastri tmavosti, nie z hotových
        # polygónov – patria teda sem a nie do jobu, ktorý bloky zlepuje.
        if args.preview:
            save_preview(preview_rows, args.preview)
        hist = histogram(preview_rows) if preview_rows else ""
        if hist:
            print("── Rozloženie odtieňov šedej ────────────────────────")
            print(hist)
            print("─────────────────────────────────────────────────────",
                  flush=True)

        if args.phase == "vektor":
            print("── Hotovo (len obrysy) ──────────────────────────────")
            print(f"  bloky           {n_blokov}")
            print(f"  čas             tmavosť {hms(sc_s)}, obrysy {hms(vec_s)}")
            print("  Zlepenie, filter a vyhladenie sú vlastný job – "
                  "rozrobené si vezme z cache.")
            print("─────────────────────────────────────────────────────",
                  flush=True)
            return 0

    print("── Spojenie blokov a filter ─────────────────────────", flush=True)
    t_sp = time.time()
    try:
        st = spoj(args, tmp, args.out, cliff_level, merc,
                  uzemie_km2=bbox_km2(args.bbox))
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    sp_s = time.time() - t_sp
    if not st.get("n"):
        print("::warning::Nenašla sa ani jedna skalná plocha – prahy sú "
              "pravdepodobne prísne. Pozri náhľad a histogram z fázy obrysov.")
        empty_rock(args.out)

    total_km2 = st.get("total_m2", 0.0) / 1e6
    print("── Hotovo ───────────────────────────────────────────")
    print(f"  plôch           {st.get('n', 0)} "
          f"(z toho {st.get('cliff', 0)} `cliff`), "
          f"{st.get('n_in', 0) - st.get('n', 0)} pod {args.min_area:g} m² preč")
    print(f"  spolu           {total_km2:.2f} km², "
          f"najväčšia {st.get('max_m2', 0) / 1e4:.1f} ha")
    print(f"  diery           {st.get('holes', 0)}")
    # Koľko dát na km² skál. To je to číslo, ktoré rozhoduje, či sa vrstva
    # zmestí do rozpočtu mapy – nie počet plôch. Jemná sieť žliabkov má málo
    # útvarov a veľa bodov.
    out_mb = dir_mb(args.out)
    per_km2 = out_mb / total_km2 if total_km2 > 0.001 else 0.0
    print(f"  výstup          {args.out} ({out_mb:.1f} MB"
          + (f", {per_km2:.1f} MB na km² skál)" if per_km2 else ")"))
    print(f"  čas             sťahovanie {hms(dl_s)}, tmavosť {hms(sc_s)}, "
          f"obrysy {hms(vec_s)}, spojenie {hms(sp_s)}, "
          f"spolu {hms(time.time() - t_all)}")
    if args.phase == "spojit":
        print("  (čas sťahovania a obrysov je z ich vlastných jobov)")
    print("─────────────────────────────────────────────────────", flush=True)

    if args.stats:
        os.makedirs(os.path.dirname(os.path.abspath(args.stats)) or ".",
                    exist_ok=True)
        with open(args.stats, "w") as f:
            for k, v in [
                ("count", st.get("n", 0)), ("cliff", st.get("cliff", 0)),
                ("total_km2", f"{total_km2:.3f}"),
                ("max_m2", int(st.get("max_m2", 0))),
                ("holes", st.get("holes", 0)),
                ("holes_dropped", st.get("holes_dropped", 0)),
                ("dropped", st.get("n_in", 0) - st.get("n", 0)),
                ("zoom", z), ("tiles", dl["tiles"]),
                ("tiles_missing", dl["tiles_missing"]),
                ("tiles_failed", dl["tiles_failed"]),
                ("mb_downloaded", dl["mb_downloaded"]),
                ("ua", args.ua), ("ua_profiles", dl["ua_profiles"]),
                ("cells", cells), ("px_m", f"{ground_res(z, lat_mid):.2f}"),
                ("dark", args.dark), ("dark_always", args.dark_always),
                ("local_m", f"{args.local:g}"), ("local_px", args.local_px),
                ("rel", args.rel),
                ("cliff_delta", args.cliff), ("blur", args.blur),
                ("fill_m", f"{args.fill:g}"),
                ("open_m", f"{args.open:g}"), ("open_px", args.open_px),
                ("out_mb", f"{out_mb:.1f}"), ("mb_per_km2", f"{per_km2:.1f}"),
                ("min_area_m2", f"{args.min_area:g}"),
                ("plne", int(bool(args.plne))),
                ("zapln_diery", int(bool(args.zapln_diery))),
                ("zlepene", int(bool(args.zlepit))),
                ("min_hole_m2", f"{args.min_hole:g}"),
                ("simplify_m", f"{args.simplify:.2f}"), ("smooth", args.smooth),
                ("seconds", int(time.time() - t_all)),
            ]:
                f.write(f"{k}={v}\n")

    # Až TERAZ preč: rozrobené má zmysel držať len dovtedy, kým beh nedobehol.
    # Inak by cache dlaždíc rástla o medzivýsledky každého behu.
    shutil.rmtree(tmp, ignore_errors=True)
    print("Rozrobené zmazané – beh dobehol celý.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
