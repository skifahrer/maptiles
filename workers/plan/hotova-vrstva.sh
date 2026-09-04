#!/usr/bin/env bash
# „Mám tú vrstvu už hotovú, alebo ju treba spočítať?" – jedna odpoveď pre
# vrstevnice, skaly aj tieňovanie.
#
# PREČO SKRIPT A NIE PODMIENKA V `if:`. Odpoveď sa skladá z troch výstupov
# dvoch `restore` krokov a potrebujú ju ŠTYRI miesta v každom z troch jobov
# (počítať?, uložiť?, čo napísať do súhrnu, čo podať `site.sh`). Napísané
# v YAMLe by to bolo dvanásť kópií jednej podmienky – a stačí jednu z nich
# raz zabudnúť opraviť, aby sa vrstva počítala nanovo a hneď nato uložila pod
# kľúč, pod ktorým už niečo je. To je pravidlo 3 v CLAUDE.md.
#
# TRI DÔVODY, PREČO JU MÔŽEME MAŤ, A NIE SÚ ROVNOCENNÉ:
#
#   presná zhoda kľúča   výsledok vznikol s tými istými nastaveniami, tým istým
#                        skladom modelu a tými istými skriptami. Nič nové.
#   hotová z predošlého  nastavenia sedia, otlačky nie – teda vrstva vznikla
#   behu (predpona)      predtým, než sa doplnil sklad alebo zmenil skript.
#                        Toto je to, čo si dávka nad krajinou pýta
#                        (`reuse_layers=true`): raz spočítané sa nepočíta
#                        druhýkrát. Preto sa hlási `::notice::` – v mape je
#                        vrstva, ktorú dnešný kód nevyrobil, a to má byť vidieť.
#   kľúč spred rozdelenia jednorazová migrácia (viď `workers/plan/cache-keys.sh`).
#
# ULOŽIŤ SA SMIE LEN TO, ČO SA NAOZAJ SPOČÍTALO. Keby sa vrstva vzatá po
# predpone uložila pod dnešný kľúč, tvrdila by o sebe dnešný otlačok skriptov –
# a najbližší prísny beh (jeden kraj, bez `reuse_layers`) by ju vzal ako
# presnú zhodu. Tichá stará vrstva s novým menom je presne to, čomu sa celý
# tento súbor vyhýba.
#
# Hodnoty z prostredia (dáva ich krok, viď `.github/workflows/dem-layers.yml`):
#   VRSTVA HIT MATCHED HIT_STARY
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
  # Nahlas, a nie do logu: je to jediné miesto, kde sa dá zistiť, že v mape
  # je vrstva staršia než dnešný kód. Kto to nechce, spustí kraj bez
  # `reuse_layers=true`, alebo si vyberie `rebuild`.
  echo "::notice::$VRSTVA – neprepočítava sa, beriem hotovú vrstvu z predošlého behu (\`$MATCHED\`). Nastavenia sedia, otlačok skladu modelu alebo skriptov nie. Prepočíta ju výber \`rebuild\`, alebo beh bez voľby \`reuse_layers=true\`."
elif [ "$HIT_STARY" = 'true' ]; then
  MAM=true
  echo "$VRSTVA: v cache pod kľúčom spred rozdelenia kľúčov – nepočíta sa."
else
  echo "$VRSTVA: v cache nie je – počíta sa."
fi

{
  echo "mam=$MAM"
  # Dve mená pre jednu vec zámerne: `if:` kroku sa číta oveľa lepšie ako
  # „počítaj, keď to nemám" než ako „keď nie je pravda, že to mám".
  [ "$MAM" = 'true' ] && echo "pocitaj=false" || echo "pocitaj=true"
} >> "$GITHUB_OUTPUT"
