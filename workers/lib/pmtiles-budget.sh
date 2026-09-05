#!/usr/bin/env bash
# „Koľko zoomov sa zmestí do rozpočtu stránky" – jedna otázka, jeden súbor.
#
# Definuje `pmtiles_do_rozpoctu`, ktorú sourcuje `contours-build.sh`. Vlastný
# súbor preto, že je to iná otázka než „ako vzniká vrstevnica" – a preto, že
# `contours-build.sh` narazil na strop 800 riadkov.
#
# Po návrate drží použitý zoom `PM_Z` a veľkosť `PM_MB` – návratová hodnota by
# sa miešala s výstupom Planetilera na stdout.
#
#     . workers/lib/pmtiles-budget.sh
#     pmtiles_do_rozpoctu <schéma> <výstup> <maxzoom> <strop MB> <dno> \
#                         <popis> <rada pri prekročení> [<strop zoomu>]

# rozpočet sa hľadá oboma smermi – dole, keď sa výsledok nezmestí, a hore,
# keď v ňom ostalo miesto. To druhé kvôli zubatým vrstevniciam pri max zoome:
# krok mriežky dlaždice určuje zoom (z14 0,391 m, z16 0,098 m) a práve ten
# vidno ako schodíky – lomov nad 30° je pri z14 11,5 % namiesto 1,6 %.
# Jediná páka je maxzoom, tak sa dvíha po jednej, vždy meraním.
pmtiles_do_rozpoctu() { # $1 schéma $2 výstup $3 maxzoom $4 strop MB $5 dno $6 popis $7 rada $8 strop zoomu
  PM_Z="$3"
  local strop="${8:-$3}" znizovane=""
  while : ; do
    java -Xmx5g -jar planetiler.jar generate-custom \
      --schema="$1" \
      --output="$2" \
      --maxzoom="$PM_Z" --render_maxzoom="$PM_Z" \
      --simplify_tolerance_at_max_zoom=0 \
      --min_feature_size_at_max_zoom=0 \
      --force

    PM_MB=$(( $(stat -c%s "$2") / 1048576 ))
    echo "$6 maxzoom $PM_Z → ${PM_MB} MB (strop ${4} MB)"

    if [ "$PM_MB" -gt "$4" ]; then
      if [ "$PM_Z" -le "$5" ]; then
        echo "::warning::$6 majú ${PM_MB} MB ani pri maxzoome ${5} – $7"
        break
      fi
      PM_Z=$(( PM_Z - 1 ))
      # Keď sa raz znižovalo, už sa nedvíha: inak by sa beh hojdal medzi
      # dvomi zoomami donekonečna (zmestí sa → skús vyššie → nezmestí sa →
      # späť → zmestí sa…), a každé hojdanie je celý beh Planetilera.
      znizovane=1
      echo "::warning::$6 sú nad stropom ${4} MB – skúšam maxzoom ${PM_Z}."
      continue
    fi

    # Zmestilo sa. Ostalo miesto na ďalšiu úroveň? Odhad je dvojnásobok (úroveň
    # navyše pridá asi toľko, koľko je všetko pod ňou); keby bol prihrubý,
    # vetva vyššie to vráti späť.
    if [ -z "$znizovane" ] && [ "$PM_Z" -lt "$strop" ] \
       && [ $(( PM_MB * 2 )) -le "$4" ]; then
      PM_Z=$(( PM_Z + 1 ))
      echo "$6: v rozpočte ostalo miesto (${PM_MB} MB z ${4} MB, ďalšia úroveň" \
           "vyjde asi na $(( PM_MB * 2 )) MB) – skúšam maxzoom ${PM_Z}," \
           "aby pri max zoome neboli schodíky z mriežky dlaždice."
      continue
    fi
    break
  done
}
