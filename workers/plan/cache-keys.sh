#!/usr/bin/env bash
# Kľúče cache pre celý build – na jednom mieste.
#
# Jeden zdroj preto, že kľúč potrebuje restore, save aj mazanie pri
# pregenerovaní; tri kópie by sa rozišli a cache by sa ticho rozsypala.
# Do kľúča patrí to, čo mení obsah, a nič viac.
#
# Tri vrstvy, tri nezávislé kľúče: spoločný kľúč znamenal, že posunutý prah
# skál zahodil aj hodinu vrstevníc.
#
# Každý kľúč je `<nastavenia vrstvy>-<otlačky>` a poradie je záväzné: prvá časť
# ide von aj samostatne (`*_hotove`) ako predpona, ktorou sa dá nájsť najnovšia
# vrstva s tými istými nastaveniami (`reuse_layers=true`). Keby otlačok stál
# vpredu, taká predpona by neexistovala.
#
# `SCHEMA_CONTOURS` a `SCHEMA_ROCKS` sú dva, nie jeden: spoločný znamenal, že
# oprava v `rocks.sh` zahodila aj vrstevnice.

set -euo pipefail
# územie, na ktorom sa počíta z DEM – pri teste testovací štvorec
B="$DEM_BBOXKEY"
# otlačok skladu na vrstvu; spoločný by po doplnení ktoréhokoľvek skladu
# zahodil cache všetkých troch
DC="$DEMKEY_CONTOURS"
DR="$DEMKEY_ROCKS"
DT="$DEMKEY_TERRAIN"
CS="$OPT_CONTOUR_SOURCE"
RS="$OPT_ROCK_SOURCE"
TS="$OPT_SHADING_SOURCE"
# výrez je v kľúči každej vrstvy – inak by sa skaly z Tatier vrátili ako
# skaly celého kraja
RA=$(printf '%s' "$AREA_IN" | tr -c 'a-zA-Z0-9' '_')

# ---------- nastavenia vrstiev (predpony kľúčov) ----------
# v11: kľúč vrstevníc už nenesie nastavenia skál a otlačky sú až za nastaveniami.
# Ladenie hladkosti je v kľúči tiež, hoci ho `SCHEMA_CONTOURS` nevidí: tie tri
# hodnoty sú v `env:` dem-layers.yml, nie v hashovaných súboroch.
C_NASTAVENIA="contours-v11-c$CS-$B-i${CONTOUR_INTERVAL}-z${OPT_CONTOUR_MAXZOOM}-s${OPT_CONTOUR_SMOOTHING}h${CONTOUR_DEM_LOWPASS}t${CONTOUR_SIMPLIFY}x${CONTOUR_SMOOTH}-a$RA"
# skaly: prvý vlastný kľúč. Zdroj je v ňom preto, že `dmr5` a `tienovanie`
# dávajú úplne iné plochy. `ROCK_ALGO`, `ROCK_VEC_RES`, `ROCK_SIMPLIFY`
# a `ROCK_SMOOTH` sú v `env:` workflowu a menia tvar obrysu.
# `v3`: skaly orezané na polygón kraja; `v2` siahali po celý bbox.
R_NASTAVENIA="rocks-v3-r$RS-$B-z${OPT_ROCK_MAXZOOM}p${OPT_ROCK_PLNE}d${OPT_ROCK_ZAPLN_DIERY}-s${ROCK_SLOPE}g${OPT_ROCK_RES}-${ROCK_ALGO}v${ROCK_VEC_RES}t${ROCK_SIMPLIFY}x${ROCK_SMOOTH}-a$RA-${OPT_ROCK_IMG_ASSET}"
# `v7`: za hranicou kraja rovina, netieňuje sa tam. Staršie: `v6` pokračovanie
# okolím, `v5` orez na hranicu regiónu. To isté číslo nesie meno assetu
# v sklade a stráži to `workers/lint/terrain.py`.
T_NASTAVENIA="terrain-v7-t$TS-$B-z${OPT_TERRAIN_MAXZOOM}"

{
  # ---------- celé kľúče: nastavenia + otlačky ----------
  echo "contours=$C_NASTAVENIA-d$DC-${SCHEMA_CONTOURS}"
  echo "rocks=$R_NASTAVENIA-d$DR-${SCHEMA_ROCKS}"
  echo "terrain=$T_NASTAVENIA-d$DT"
  # ---------- predpony „mám to už hotové" ----------
  # Končia pomlčkou zámerne: bez nej by sa `…-z1-` trafilo aj na `…-z15-…`.
  echo "contours_hotove=$C_NASTAVENIA-"
  echo "rocks_hotove=$R_NASTAVENIA-"
  echo "terrain_hotove=$T_NASTAVENIA-"
  # ---------- kľúče spred rozdelenia ----------
  # Migrácia: záznamy z behov spred rozdelenia sú hodiny výpočtu. Podáva sa
  # ako presný kľúč, nie predpona. Skaly a tieňovanie ho už nemajú – ich staré
  # záznamy siahajú za hranicu kraja.
  # Až priečinok prejde obrátkou (30 dní), dajú sa tieto riadky zmazať.
  STARY="contours-v10-c$CS$DC-r$RS$DR-$B-i${CONTOUR_INTERVAL}-z${OPT_CONTOUR_MAXZOOM}-rz${OPT_ROCK_MAXZOOM}p${OPT_ROCK_PLNE}d${OPT_ROCK_ZAPLN_DIERY}-s${OPT_CONTOUR_SMOOTHING}h${CONTOUR_DEM_LOWPASS}t${CONTOUR_SIMPLIFY}x${CONTOUR_SMOOTH}-${ROCK_SLOPE}g${OPT_ROCK_RES}a$RA-${OPT_ROCK_IMG_ASSET}-${SCHEMA_HASH}"
  echo "contours_stary=$STARY"
  # ---------- stiahnuté DEM dlaždice ----------
  # Sú v podpriečinku podľa zdroja, takže jeden job môže mať naraz dva modely.
  # `v3`: vrstevnice a skaly majú vlastný kľúč podľa vlastného zdroja.
  echo "demtiles_contours=demtiles-v3-c$CS$DC-$B"
  echo "demtiles_rocks=demtiles-v3-r$RS$DR-$B"
  echo "demtiles_terrain=demtiles-v2-t$TS$DT-$B"
  # sklad častí sklonu: v kľúči je výrez, model a mriežka – teda to, čo mení
  # obsah častí. Prah sklonu nie: uplatňuje sa až pri vektorizácii.
  # Končí pomlčkou zámerne (je to prefix): existujúci záznam sa neprepisuje,
  # takže pri pevnom kľúči by prvý beh sklad zamkol navždy. Ukladá sa pod
  # prefix + číslo behu a obnovuje cez `restore-keys`.
  echo "slope=slope-v1-${AREA_KEY}-$RS-g${OPT_ROCK_RES}-"
} >> "$GITHUB_OUTPUT"
cat "$GITHUB_OUTPUT"
