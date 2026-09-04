#!/usr/bin/env bash
# Kľúče cache pre celý build – na jednom mieste.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map-region.yml` má strop 128 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# PREČO JEDEN ZDROJ. Kľúč potrebuje restore, save AJ mazanie pri pregenerovaní.
# Keby bol napísaný trikrát, stačí ho raz zabudnúť opraviť a cache sa ticho
# rozsype: ukladá sa pod iný kľúč, než sa hľadá, takže sa všetko počíta odznova
# a nikto nevie prečo.
#
# ČO PATRÍ DO KĽÚČA je vždy „to, čo mení obsah" – a nič viac. Prah sklonu
# napríklad NIE JE v kľúči skladu častí sklonu: uplatňuje sa až pri
# vektorizácii, takže po jeho zmene sa sklad použije a preráta sa len tá lacná
# časť (minúty namiesto hodiny čítania z Drive).
#
# ── TRI VRSTVY, TRI NEZÁVISLÉ KĽÚČE ───────────────────────────────────────
# Vrstevnice, skaly a tieňovanie mali dovtedy JEDEN kľúč (skaly ten istý
# s príponou `-rocks`), v ktorom stáli nastavenia všetkých troch naraz.
# Znamenalo to, že posunutý prah skál zahodil aj hodinu vrstevníc a doplnený
# model pre tieňovanie zahodil oboje – hoci ani jedna z tých vrstiev sa tým
# nemení. Odteraz má každá vlastný kľúč a v ňom LEN svoje nastavenia; kto
# posunie prah skál, prepočíta skaly a nič viac.
#
# ── NASTAVENIA DOPREDU, OTLAČKY DOZADU ────────────────────────────────────
# Každý kľúč je zložený z dvoch častí a v tomto poradí:
#
#   <nastavenia vrstvy>   čo si vybral vo formulári a v `options` – zdroj,
#                         interval, zoom, prah, mriežka, výrez
#   <otlačky>             otlačok skladu výškového modelu (`demkey`) a otlačok
#                         skriptov, ktoré vrstvu počítajú (`SCHEMA_*`)
#
# Prvá časť ide von aj samostatne (`*_hotove`) a je to PREDPONA celého kľúča.
# Kto ju podá ako `restore-keys`, dostane najnovšiu vrstvu, ktorá vznikla
# s TÝMI ISTÝMI nastaveniami – aj keď sa medzitým doplnil sklad modelu alebo
# zmenil skript. Presne to je „už som to raz spočítal, nepočítaj to znova",
# ktoré si zapína dávka nad krajinou (`reuse_layers=true`, viď
# `workers/plan/options.py`); jeden kraj sa bez neho počíta prísne ako
# doteraz, teda po každej zmene skriptu nanovo.
#
# Poradie je preto ZÁVÄZNÉ: keby otlačok stál pred nastaveniami (a stál tam),
# žiadna predpona s nastaveniami by neexistovala a „hotová vrstva" by sa
# nedala nájsť inak než náhodou.
#
# `hashFiles` je funkcia GitHubu, nie shellu – jej výsledky chodia ako
# SCHEMA_CONTOURS a SCHEMA_ROCKS. Sú DVA, nie jeden: kým bol spoločný,
# oprava v `rocks.sh` zahodila aj vrstevnice, ktoré na ňom nestoja.

set -euo pipefail
# Územie, na ktorom sa počíta z DEM – pri rýchlom teste testovací
# štvorec, inak celý región. Všetky kľúče nižšie sú o vrstvách z DEM.
B="$DEM_BBOXKEY"
# Otlačok skladu na vrstvu – každá si vyberá zdroj sama, takže
# jeden spoločný by po doplnení ktoréhokoľvek releasu zahodil cache
# všetkých troch.
DC="$DEMKEY_CONTOURS"
DR="$DEMKEY_ROCKS"
DT="$DEMKEY_TERRAIN"
CS="$OPT_CONTOUR_SOURCE"
RS="$OPT_ROCK_SOURCE"
TS="$OPT_SHADING_SOURCE"
# Výrez je v kľúči každej vrstvy – inak by sa skaly len z Tatier
# vrátili z cache ako keby to boli skaly celého kraja.
RA=$(printf '%s' "$AREA_IN" | tr -c 'a-zA-Z0-9' '_')

# ---------- nastavenia vrstiev (predpony kľúčov) ----------
# v11: kľúč vrstevníc už nenesie nastavenia skál a otlačky sú až za
# nastaveniami (rozpis v hlavičke). Bez nového čísla by sa na predponu
# `contours-v10-…` trafili staré záznamy iného tvaru.
#
# Ladenie hladkosti vrstevníc (okno na vyhladenie DEM, tolerancia
# zjednodušenia, priehyb pri zaoblení) je v kľúči TIEŽ, hoci ho
# `SCHEMA_CONTOURS` nevidí: tie tri hodnoty sú v `env:` dem-layers.yml, nie
# v žiadnom z hashovaných súborov. Bez nich by sa dala prestaviť hladkosť
# a beh by vrátil z cache staré vrstevnice – zelený, tichý a s tvarom,
# ktorý o nastavení nič nevie (pravidlo 8).
C_NASTAVENIA="contours-v11-c$CS-$B-i${CONTOUR_INTERVAL}-z${OPT_CONTOUR_MAXZOOM}-s${OPT_CONTOUR_SMOOTHING}h${CONTOUR_DEM_LOWPASS}t${CONTOUR_SIMPLIFY}x${CONTOUR_SMOOTH}-a$RA"
# Skaly: prvý vlastný kľúč, teda `v1`. Zdroj je v ňom preto, že `dmr5`
# a `tienovanie` dávajú úplne iné plochy – jedny sa nesmú vrátiť z cache
# namiesto druhých. `ROCK_ALGO`, `ROCK_VEC_RES`, `ROCK_SIMPLIFY`
# a `ROCK_SMOOTH` sú v ňom z toho istého dôvodu ako ladenie vrstevníc:
# sú v `env:` workflowu, takže ich žiadny otlačok súborov nevidí, a menia
# TVAR obrysu. (V mene uloženého assetu v sklade `dem-rocks` je `ROCK_ALGO`
# odjakživa – v cache chýbal.)
R_NASTAVENIA="rocks-v1-r$RS-$B-z${OPT_ROCK_MAXZOOM}p${OPT_ROCK_PLNE}d${OPT_ROCK_ZAPLN_DIERY}-s${ROCK_SLOPE}g${OPT_ROCK_RES}-${ROCK_ALGO}v${ROCK_VEC_RES}t${ROCK_SIMPLIFY}x${ROCK_SMOOTH}-a$RA-${OPT_ROCK_IMG_ASSET}"
# `v6`: za hranicou kraja terén POKRAČUJE OKOLÍM namiesto roviny 0 m. Rovina
# tam robila zvislú stenu po obvode regiónu (89,4° proti 17,9°, ktoré má
# terén sám) a v 3D múr; `--edge` ju posúval za hranicu, kde ju prekrýva
# plocha `mimo`, lenže schovaná stena je stále stena. Tvar dlaždíc sa
# nezmenil, len ich obsah – a bez novej verzie by ich cache vrátila
# po starom.
# `v5`: mimo kraja je v dlaždici rovina, takže tieňovanie končí na hranici
# regiónu a nie až na okraji dlaždice, ktorá sa ho dotkla (na z10 to bol
# dvojnásobok plochy kraja).
# `v4`: priemeruje sa až od dvojnásobku bunky modelu (`lib/cell.py`).
# `v3` opravilo zväčšovanie, ale v pásme tesne nad bunkou (Sonny na z12)
# ostal `average` – a s ním mriežka, ktorú bolo na mape stále vidieť.
# Staré dlaždice by sa z cache vrátili ako hotové a oprava by sa na už
# spočítanom regióne neprejavila. To isté číslo nesie meno assetu v sklade
# (`workers/terrain/build.sh`) a stráži to `workers/lint/terrain.py` – preto
# sa tu číslo NEDVÍHA kvôli poradiu polí; poradie mení len to, čo je za `v6`.
T_NASTAVENIA="terrain-v6-t$TS-$B-z${OPT_TERRAIN_MAXZOOM}"

{
  # ---------- celé kľúče: nastavenia + otlačky ----------
  echo "contours=$C_NASTAVENIA-d$DC-${SCHEMA_CONTOURS}"
  echo "rocks=$R_NASTAVENIA-d$DR-${SCHEMA_ROCKS}"
  echo "terrain=$T_NASTAVENIA-d$DT"
  # ---------- predpony „mám to už hotové" ----------
  # Končia pomlčkou zámerne: sú to PREDPONY a bez nej by sa `…-z1-` trafilo
  # aj na `…-z15-…`.
  echo "contours_hotove=$C_NASTAVENIA-"
  echo "rocks_hotove=$R_NASTAVENIA-"
  echo "terrain_hotove=$T_NASTAVENIA-"
  # ---------- kľúče spred rozdelenia ----------
  # MIGRÁCIA, nie druhá pravda. Záznamy z behov spred rozdelenia kľúčov ležia
  # v priečinku ďalej a sú to hodiny výpočtu – bez tohto by ich premenovanie
  # kľúča zahodilo a prvá dávka po zmene by celé Slovensko počítala odznova.
  # Podávajú sa ako PRESNÝ kľúč druhého `restore` kroku, nie ako predpona:
  # staré skaly ležia pod tým istým kľúčom s príponou `-rocks`, takže by ich
  # predpona vrátila ako vrstevnice – a v mape by boli skaly nakreslené ako
  # izolínie. Až priečinok prejde obrátkou (prerieďuje sa na 30 dní), dajú sa
  # tieto tri riadky aj s krokmi, ktoré ich čítajú, zmazať.
  STARY="contours-v10-c$CS$DC-r$RS$DR-$B-i${CONTOUR_INTERVAL}-z${OPT_CONTOUR_MAXZOOM}-rz${OPT_ROCK_MAXZOOM}p${OPT_ROCK_PLNE}d${OPT_ROCK_ZAPLN_DIERY}-s${OPT_CONTOUR_SMOOTHING}h${CONTOUR_DEM_LOWPASS}t${CONTOUR_SIMPLIFY}x${CONTOUR_SMOOTH}-${ROCK_SLOPE}g${OPT_ROCK_RES}a$RA-${OPT_ROCK_IMG_ASSET}-${SCHEMA_HASH}"
  echo "contours_stary=$STARY"
  echo "rocks_stary=$STARY-rocks"
  echo "terrain_stary=terrain-v6-$TS-$DT-$B-z${OPT_TERRAIN_MAXZOOM}"
  # ---------- stiahnuté DEM dlaždice ----------
  # Sú v podpriečinku podľa zdroja, takže jeden job môže mať naraz dva modely.
  # `v3`: vrstevnice a skaly majú vlastný kľúč podľa VLASTNÉHO zdroja. Kým
  # v oboch stáli oba, zmena modelu skál sťahovala model vrstevníc odznova –
  # hoci ten job o skalách nevie a `dem/` má v sebe presne to isté.
  echo "demtiles_contours=demtiles-v3-c$CS$DC-$B"
  echo "demtiles_rocks=demtiles-v3-r$RS$DR-$B"
  echo "demtiles_terrain=demtiles-v2-t$TS$DT-$B"
  # Sklad častí sklonu. V kľúči je VÝREZ, MODEL a MRIEŽKA – teda
  # presne to, čo mení obsah častí. Prah sklonu v ňom zámerne NIE
  # JE: uplatňuje sa až pri vektorizácii, takže po jeho zmene sa
  # sklad použije a preráta sa len tá lacná časť (minúty namiesto
  # hodiny čítania z Drive). Prefix musí sedieť s `restore-keys`
  # v jobe so skalami.
  # Končí pomlčkou zámerne: je to PREFIX. Existujúci záznam cache
  # sa neprepisuje, takže keby bol kľúč pevný, prvý beh by ho zabral a
  # časti dopočítané v ďalších behoch by sa už nikdy neuložili –
  # sklad by navždy ostal taký, aký bol po prvom behu. Ukladá sa
  # preto pod prefix + číslo behu a obnovuje sa cez `restore-keys`,
  # čiže vždy z najnovšieho záznamu, ktorý na prefix sedí.
  echo "slope=slope-v1-${AREA_KEY}-$RS-g${OPT_ROCK_RES}-"
} >> "$GITHUB_OUTPUT"
cat "$GITHUB_OUTPUT"
