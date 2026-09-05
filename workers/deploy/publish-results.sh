#!/usr/bin/env bash
# Medzivýsledky behu do skladu na Drive – to, čo predtým ostávalo ako artefakt.
#
# Do GitHubu sa nepublikuje nič; krátkodobé artefakty (`retention-days: 1`) sú
# prepravky medzi jobmi jedného behu, nie publikovanie. Vlastný skript preto,
# že ten istý zoznam pýtali dva joby a tretí (`shading-rocks.yml`) to isté
# balenie aj pomenovanie.
#
# Meno nesie, čo v tom je, a je jedinečné: nastavenia sú v `NAZOV`, dátum
# a číslo behu sa pridá tu, takže sa dva behy neprepíšu. Sklad `vysledky`
# prerieďuje `cleanup-cache.yml` na 90 dní.
#
# Jeden súbor ide sám, viac sa zabalí do `.tar.zst`. Zlyhanie nesmie zhodiť
# beh – je to vec na pozretie, nie vstup pre nikoho.
#
#   CO=teren NAZOV=teren-vysoke_tatry-s45-g2   workers/deploy/publish-results.sh
#   NAZOV=nahlad-vysoke_tatry-z16 SUBORY=out/preview.png  …
set -uo pipefail

NAZOV="${NAZOV:?meno bez prípony}"
CO="${CO:-subory}"

case "$CO" in
  teren)
    # Skaly a vrstevnice: zdrojová geometria (GPKG) aj hotové dlaždice.
    FILES=(data/rock.gpkg data/contours.gpkg
           contours-out/contours.pmtiles contours-out/rocks.pmtiles
           contours-out/rock-stats.txt)
    POPIS="Vrstevnice a skaly jedného behu – GPKG aj PMTiles"
    ;;
  trasy)
    FILES=(data/trails.geojson steps-out/trail-stats.txt)
    POPIS="Značené trasy jedného behu – GeoJSON pred tilovaním"
    ;;
  subory)
    # `${SUBORY:-}` a kontrola zvlášť, nie `${SUBORY:?…}`: pri `CO=teren`
    # a `CO=trasy` sa `SUBORY` nepodáva, a kontrola „skripty vo workers
    # dostávajú svoje env" berie `:?` ako „toto mi krok MUSÍ dať".
    if [ -z "${SUBORY:-}" ]; then
      echo "::error::CO=subory potrebuje SUBORY – cesty oddelené medzerou alebo riadkom."
      exit 1
    fi
    # shellcheck disable=SC2206  # delenie na slová je tu zámer
    FILES=(${SUBORY})
    POPIS="${POPIS:-Medzivýsledok behu na pozretie}"
    ;;
  *)
    echo '::error::CO nepoznám – sú to `teren`, `trasy` a `subory`.'
    exit 1
    ;;
esac

# Čo neexistuje, sa vynechá a napíše sa to. Prázdny archív je horší než chyba:
# v sklade by vyzeral ako výsledok. `-d` zvlášť: `SUBORY` môže byť aj adresár
# (tak sa ukladajú stiahnuté dlaždice tieňovania).
MAM=()
for f in "${FILES[@]}"; do
  if [ -d "$f" ] || [ -s "$f" ]; then
    MAM+=("$f")
  else
    echo "  (nie je $f – vynechávam)"
  fi
done
if [ ${#MAM[@]} -eq 0 ]; then
  echo "::warning::Ani jeden zo súborov ($CO) nevznikol – do skladu nejde nič."
  exit 0
fi

# Dátum, čas a číslo behu robia meno jedinečným – dva behy sa neprepíšu.
STAMP="$(date -u +%Y%m%d-%H%M)-r${GITHUB_RUN_NUMBER:-0}"
TMP="${RUNNER_TEMP:-/tmp}"

if [ ${#MAM[@]} -eq 1 ] && [ -f "${MAM[0]}" ]; then
  # Jediný SÚBOR ide sám a s vlastnou príponou, nech sa dá na Drive otvoriť.
  # Adresár nie: `cp` bez `-r` by na ňom spadol a rozbalený priečinok na Drive
  # aj tak nie je to, čo si niekto príde stiahnuť.
  BASE="$(basename "${MAM[0]}")"
  PRIPONA="${BASE##*.}"
  [ "$PRIPONA" = "$BASE" ] && PRIPONA="dat"
  POSLI="$TMP/${NAZOV}-${STAMP}.${PRIPONA}"
  cp "${MAM[0]}" "$POSLI"
elif command -v zstd >/dev/null 2>&1; then
  POSLI="$TMP/${NAZOV}-${STAMP}.tar.zst"
  tar --use-compress-program='zstd -9 -T0' -cf "$POSLI" "${MAM[@]}"
else
  # `zstd` na runneri je, ale job, ktorý si ho neinštaloval, ho mať nemusí.
  POSLI="$TMP/${NAZOV}-${STAMP}.tar.gz"
  tar -czf "$POSLI" "${MAM[@]}"
fi

if [ ! -s "$POSLI" ]; then
  echo "::warning::Balenie medzivýsledkov ($CO) zlyhalo – do skladu nejde nič."
  exit 0
fi
echo "Do skladu vysledky: $(basename "$POSLI") ($(du -h "$POSLI" | cut -f1)), v ňom ${MAM[*]}"

python3 workers/drive/store.py --put --store=vysledky \
    --file="$POSLI" --note="$POPIS" \
  || echo "::warning::Medzivýsledky ($CO) sa do skladu nepodarilo uložiť. Mapa tým netrpí – je to vec na pozretie."
rm -f "$POSLI"
exit 0
