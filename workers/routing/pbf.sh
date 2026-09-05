#!/usr/bin/env bash
# PBF pre navigačný graf – stiahnuť a zliať to, čo číselník rozsahu hovorí.
#
# Nie `workers/plan/pbf.sh`: ten reže kraj z rodičovského extraktu, lebo mapa
# je mapa kraja. Graf sa po krajoch nedelí, takže je to iná otázka.
#
# Nereže sa nič: hrana grafu, ktorej chýba druhý koniec, je slepá ulica a trasa
# cez ňu neprejde. Graf sa preto stavia z celých štátnych extraktov.
#
# Vstup:  AREA (kľúč v routing-areas.json), OSMFR_BASE
# Výstup: data/routing.osm.pbf a `pbf_mb` do GITHUB_OUTPUT

set -euo pipefail
mkdir -p data steps-out
T=$(date +%s)

: "${AREA:?povedz AREA – kľúč z workers/data/routing-areas.json}"
BASE="${OSMFR_BASE:-https://download.openstreetmap.fr/extracts}"

mapfile -t PBFS < <(python3 - "$AREA" <<'PY'
import json, os, sys
here = os.path.join("workers", "data", "routing-areas.json")
areas = (json.load(open(here, encoding="utf-8")).get("areas") or {})
area = areas.get(sys.argv[1])
if not area:
    sys.exit(f"::error::Rozsah `{sys.argv[1]}` nie je v workers/data/"
             f"routing-areas.json. Známe: {', '.join(sorted(areas))}.")
for p in area["pbf"]:
    print(p)
PY
)
echo "Rozsah `$AREA`: ${#PBFS[@]} extrakt(ov) – ${PBFS[*]}"

# PLÁN S ODHADOM PRED DRAHOU ČASŤOU (pravidlo 4). Hodina ticha v logu sa nedá
# odlíšiť od zaseknutého behu, a tu sa sťahujú stovky MB až jednotky GB.
echo "::group::Sťahovanie PBF"
i=0
FILES=()
for p in "${PBFS[@]}"; do
  i=$(( i + 1 ))
  out="data/$(basename "$p").osm.pbf"
  echo "[$i/${#PBFS[@]}] $BASE/$p-latest.osm.pbf"
  # `--retry` a dlhší limit: cudzí server, ktorý má výpadok na pár desiatok
  # sekúnd, nemá právo zhodiť viachodinový build.
  curl -fSL --retry 5 --retry-delay 10 --retry-all-errors --connect-timeout 60 \
    -o "$out" "$BASE/$p-latest.osm.pbf"
  echo "    $(du -h "$out" | cut -f1)"
  FILES+=("$out")
done
echo "::endgroup::"

if [ "${#FILES[@]}" -eq 1 ]; then
  mv "${FILES[0]}" data/routing.osm.pbf
else
  # `osmium merge` a nie `cat`: PBF sa zliať zreťazením NEDÁ (každý súbor má
  # vlastnú hlavičku) a duplicitné uzly na hraniciach by z grafu spravili dve
  # nespojené siete. `merge` ich zjednotí podľa id.
  echo "::group::Zlievanie ${#FILES[@]} extraktov (osmium merge)"
  osmium merge --overwrite -o data/routing.osm.pbf "${FILES[@]}"
  echo "::endgroup::"
  rm -f "${FILES[@]}"
fi

MB=$(( $(stat -c%s data/routing.osm.pbf) / 1048576 ))
echo "PBF pre graf: ${MB} MB"
echo "pbf_mb=$MB" >> "$GITHUB_OUTPUT"
printf '%s\t%s\t%s\t%s\n' "10" "PBF pre navigačný graf" "$(( $(date +%s) - T ))" \
  "${#PBFS[@]} extrakt(ov), ${MB} MB" >> steps-out/routing.tsv
