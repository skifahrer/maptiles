#!/usr/bin/env bash
# Hranice území a ich názvy z OSM → `{región}-boundaries.pmtiles`.
#
# ČO TO JE A PREČO: rozpis je v hlavičke `workers/boundaries/boundaries.yml`.
# Krátko – hranica v mape je čiara BEZ MENA územia, ktoré ohraničuje, takže sa
# z nej nedá povedať, v ktorej obci alebo v ktorom okrese je nejaký bod. Táto
# vrstva je tá odpoveď: územia ako plochy s menom a úrovňou, k tomu čiary
# a body sídel. Je to VRSTVA NA POUŽITIE, nie druhé kreslenie – hranice v mape
# kreslí ďalej základná mapa (rovnaký vzťah ako pri dopravnej sieti).
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map-region.yml` má strop 128 kB a nad ním ho
# GitHub ticho neprijme (stráži „Kontrola · lint workflowov").
#
# PREDFILTER MUSÍ DOŤAHOVAŤ ČLENOV RELÁCIÍ, a to je celý rozdiel oproti
# ostatným vrstvám: hranica obce je v OSM RELÁCIA, ktorej členmi sú cesty,
# a tie samy `boundary=administrative` nemajú. Bez nich by Planetiler dostal
# relácie bez geometrie, nemal by z čoho zložiť polygón a v dlaždiciach by
# TICHO nebolo nič. `osmium tags-filter` ich doťahuje SÁM a vypína sa to až
# `-R`/`--omit-referenced` – preto tu žiadny taký prepínač nie je.
# (`-r` neexistuje, osmium na ňom skončí s „unrecognised option".)
#
# Podiel na veľkosti stránky berie z `BUDGET_BOUNDARIES_PCT` (env workflowu).

set -euo pipefail
mkdir -p _site/tiles data steps-out
sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool

# ---- 1. predfilter: hranice, ich členovia a body sídel ----
T_F=$(date +%s)
osmium tags-filter --overwrite -o data/boundaries.osm.pbf \
  data/region.osm.pbf --expressions=workers/boundaries/filter.txt

BEFORE=$(stat -c%s data/region.osm.pbf)
AFTER=$(stat -c%s data/boundaries.osm.pbf)
echo "Predfilter: $(du -h data/region.osm.pbf | cut -f1) → $(du -h data/boundaries.osm.pbf | cut -f1)"
printf '%s\t%s\t%s\t%s\n' "63" "Predfilter hraníc" "$(( $(date +%s) - T_F ))" \
  "$(( BEFORE / 1048576 )) MB → $(( AFTER / 1048576 )) MB" \
  >> steps-out/boundaries.tsv

# Prázdny výsledok nie je chyba – 4 km² rýchleho testu môže padnúť doprostred
# obce bez jedinej hranice. Že vrstva v mape nie je, povie `obsah.json`.
if [ "$AFTER" -lt 2000 ]; then
  echo "::warning::V tomto území nie je ani jedna administratívna hranica ani sídlo – balík \`hranice\` sa nevyrobí."
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ---- 2. dlaždice ----
BZ_="$OPT_BOUNDARIES_MAXZOOM"
case "$BZ_" in ''|*[!0-9]*) BZ_=12 ;; esac
if [ "$BZ_" -gt 16 ]; then BZ_=16; fi

# Poistka proti tichej strate: čo má v schéme `min_zoom` nad maxzoomom,
# Planetiler zahodí BEZ SLOVA. Tá istá poistka ako v jobe `transport`.
TOPZ=$(grep -oE 'min_zoom: [0-9]+' workers/boundaries/boundaries.yml \
       | grep -oE '[0-9]+' | sort -n | tail -1)
if [ "${TOPZ:-0}" -gt "$BZ_" ]; then
  echo "::error::workers/boundaries/boundaries.yml má bloky s min_zoom až ${TOPZ}, ale dlaždice idú po z${BZ_} – tie sa do nich vôbec nedostanú (pri dedinách a osadách je to väčšina sídel). Zdvihni boundaries_maxzoom na ${TOPZ}, alebo tým blokom zníž min_zoom."
  exit 1
fi

# HRANICE SA NEOREZÁVAJÚ NA REGIÓN, a je to jediná vrstva, kde to tak je.
# Hranica kraja je hranicou aj pre suseda a orezaním presne po nej by z nej
# ostala polovica čiary; plocha okresu na okraji by sa navyše zrezala na
# obdĺžnik bboxu a odpoveď „v ktorom okrese som" by pri kraji bola nesprávna,
# nie chýbajúca. PBF je aj tak vyrezaný po hranicu regiónu (`plan/pbf.sh`),
# takže „všetko, čo v ňom je" je presne to, čo sa má nakresliť.
T_PM=$(date +%s)
OUT="_site/tiles/${REGION_KEY}-boundaries.pmtiles"
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema=workers/boundaries/boundaries.yml \
  --output="$OUT" \
  --maxzoom="$BZ_" --render_maxzoom="$BZ_" \
  --simplify_tolerance_at_max_zoom=0 \
  --min_feature_size_at_max_zoom=0 \
  --force

MB=$(( $(stat -c%s "$OUT") / 1048576 ))

LIMIT_MB="$SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
BBUDGET_MB=$(( LIMIT_MB * BUDGET_BOUNDARIES_PCT / 100 ))
if [ "$MB" -gt "$BBUDGET_MB" ]; then
  echo "::warning::Hranice majú ${MB} MB, čo je nad podielom ${BBUDGET_MB} MB z rozpočtu stránky. Zníž boundaries_maxzoom alebo zdvihni BUDGET_BOUNDARIES_PCT."
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "maxzoom=$BZ_" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
ls -lh "$OUT"
printf '%s\t%s\t%s\t%s\n' "64" "Hranice → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "maxzoom $BZ_, $(du -h "$OUT" | cut -f1)" \
  >> steps-out/boundaries.tsv
