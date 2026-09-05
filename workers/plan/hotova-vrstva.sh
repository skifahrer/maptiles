#!/usr/bin/env bash
# „Mám tú vrstvu už hotovú, alebo ju treba spočítať?" – jedna odpoveď pre
# vrstevnice, skaly aj tieňovanie.
#
# Skript, a nie podmienka v `if:`: odpoveď sa skladá z troch výstupov dvoch
# `restore` krokov a potrebujú ju štyri miesta v každom z troch jobov, čiže
# dvanásť kópií jednej podmienky.
#
# Tri dôvody, prečo ju môžeme mať, a nie sú rovnocenné:
#   presná zhoda kľúča   nič nové
#   predpona             nastavenia sedia, otlačky nie – to si pýta dávka nad
#                        krajinou (`reuse_layers`); hlási sa `::notice::`-om,
#                        lebo v mape je vrstva, ktorú dnešný kód nevyrobil
#   kľúč spred rozdelenia jednorazová migrácia
#
# Uložiť sa smie len to, čo sa naozaj spočítalo: vrstva vzatá po predpone by
# pod dnešným kľúčom tvrdila dnešný otlačok skriptov.
#
# Z prostredia: VRSTVA HIT MATCHED HIT_STARY
set -euo pipefail

VRSTVA="${VRSTVA:?ktorá vrstva sa rozhoduje}"
HIT="${HIT:-}"                 # `true` len pri PRESNEJ zhode kľúča
MATCHED="${MATCHED:-}"         # kľúč, ktorý sa naozaj našiel (aj po predpone)
HIT_STARY="${HIT_STARY:-}"     # presná zhoda kľúča spred rozdelenia

MAM=false
if [ "$HIT" = 'true' ]; then
  MAM=true
  echo "$VRSTVA: v cache pod dnešným kľúčom – nepočíta sa."
elif [ -n "$MATCHED" ]; then
  MAM=true
  # nahlas, a nie do logu: je to jediné miesto, kde sa dá zistiť, že v mape
  # je vrstva staršia než dnešný kód
  echo "::notice::$VRSTVA – neprepočítava sa, beriem hotovú vrstvu z predošlého behu (\`$MATCHED\`). Nastavenia sedia, otlačok skladu modelu alebo skriptov nie. Prepočíta ju výber \`rebuild\`, alebo beh bez voľby \`reuse_layers=true\`."
elif [ "$HIT_STARY" = 'true' ]; then
  MAM=true
  echo "$VRSTVA: v cache pod kľúčom spred rozdelenia kľúčov – nepočíta sa."
else
  echo "$VRSTVA: v cache nie je – počíta sa."
fi

{
  echo "mam=$MAM"
  # dve mená pre jednu vec zámerne: `if:` kroku sa lepšie číta ako „počítaj,
  # keď to nemám"
  [ "$MAM" = 'true' ] && echo "pocitaj=false" || echo "pocitaj=true"
} >> "$GITHUB_OUTPUT"
