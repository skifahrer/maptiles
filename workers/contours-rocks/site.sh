#!/usr/bin/env bash
# Hotové vrstevnice a skaly z `contours-out/` do `_site/` + výstupy pre štýl.
#
# Samostatný skript preto, že tento krok majú dva joby (`contours` a `rocks`)
# a v YAMLe stál ten istý blok dvakrát – a dve kópie sa raz rozídu.
#
# Vrstevnice a skaly idú do mapy ako dva `.pmtiles` s vlastným maxzoomom,
# takže sa dajú nasadiť aj jedno bez druhého.
#
# Hodnoty sa berú z toho, čo naozaj vzniklo (`contours-out/*.txt`): maxzoom sa
# mohol znížiť kvôli veľkosti a model mohol spadnúť na Sonnyho.

set -euo pipefail
mkdir -p _site/tiles
KEY="$REGION_KEY"

# ---------- ktorá polovica ----------
# To isté `ONLY` dostal aj `build.sh`, takže tu je len odpoveď na „mal tento job
# tú polovicu vôbec počítať?". Bez neho skript hlásil chýbajúcu polovicu ako
# poruchu – dva falošné poplachy v každom behu.
ONLY="${ONLY:-all}"
case "$ONLY" in
  contours|rocks|all) ;;
  *) echo "::error::ONLY musí byť 'contours', 'rocks' alebo 'all' (dostal '$ONLY')."; exit 1 ;;
esac
# čo tento job mal vyrobiť; vypnutú vrstvu nikto nečaká, tak sa o nej nevaruje
CHCE_CONTOURS=false; [ "$ONLY" != 'rocks' ] && [ "$OPT_CONTOUR_LINES" = 'true' ] && CHCE_CONTOURS=true
CHCE_ROCKS=false;    [ "$ONLY" != 'contours' ] && [ "$OPT_ROCKS" = 'true' ] && CHCE_ROCKS=true

# ---- skaly: vlastný .pmtiles, vlastný maxzoom ----
# Idú prvé, lebo sa dajú nasadiť aj bez vrstevníc (a naopak).
RPM=contours-out/rocks.pmtiles
RZ=$(cat contours-out/rock-maxzoom.txt 2>/dev/null || echo '')
case "$RZ" in ''|*[!0-9]*) RZ="$OPT_ROCK_MAXZOOM" ;; esac
case "$RZ" in ''|*[!0-9]*) RZ=16 ;; esac
if [ "$RZ" -gt 16 ]; then RZ=16; fi
if [ "$OPT_ROCKS" = 'true' ] && [ -s "$RPM" ]; then
  cp "$RPM" "_site/tiles/$KEY-rocks.pmtiles"
  echo "rocks_enabled=true" >> "$GITHUB_OUTPUT"
  echo "Skaly do z$RZ, $(du -h "$RPM" | cut -f1)"
else
  echo "rocks_enabled=false" >> "$GITHUB_OUTPUT"
  [ "$CHCE_ROCKS" = 'true' ] \
    && echo "::warning::Skaly sa nevygenerovali – mapa pôjde bez nich."
fi
echo "rocks_maxzoom=$RZ" >> "$GITHUB_OUTPUT"

# ---- vrstevnice ----
SRC=contours-out/contours.pmtiles
if [ -s "$SRC" ]; then
  cp "$SRC" "_site/tiles/$KEY-contours.pmtiles"
  # maxzoom z toho, čo naozaj vzniklo (mohol sa znížiť kvôli veľkosti)
  CZ=$(cat contours-out/maxzoom.txt 2>/dev/null || echo '')
  case "$CZ" in ''|*[!0-9]*) CZ="$OPT_CONTOUR_MAXZOOM" ;; esac
  case "$CZ" in ''|*[!0-9]*) CZ=14 ;; esac
  if [ "$CZ" -gt 16 ]; then CZ=16; fi
  # `enabled` je o vrstevniciach, nie o súbore: pri `ziadne` je .pmtiles na
  # disku, ale prázdny
  if [ "$OPT_CONTOUR_LINES" = 'true' ]; then
    echo "enabled=true" >> "$GITHUB_OUTPUT"
  else
    echo "enabled=false" >> "$GITHUB_OUTPUT"
  fi
  echo "maxzoom=$CZ" >> "$GITHUB_OUTPUT"
else
  CZ=''
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  [ "$CHCE_CONTOURS" = 'true' ] \
    && echo "::warning::Vrstevnice sa nevygenerovali – mapa pôjde bez nich."
fi

# ---- čo platí pre obe polovice ----
# Zdroj výšok a prah sklonu si nesie cache spolu s dlaždicami. Zapisujú sa vždy,
# aj keď vrstevnice v tomto jobe nevznikli – deploy z nich skladá manifest.
DEM_USED=$(cat contours-out/dem-source.txt 2>/dev/null || echo '')
# kľúče musia sedieť s `dem-sources.json`: čo tu neprejde, spadne na Sonnyho
# a mapa by v atribúcii tvrdila iný model
case "$DEM_USED" in sonny|dmr35|dmr5) ;; *) DEM_USED=sonny ;; esac
RSLOPE=$(cat contours-out/rock-slope.txt 2>/dev/null || echo off)
RSRC=$(cat contours-out/rock-source.txt 2>/dev/null || echo off)
case "$RSRC" in sonny|dmr35|dmr5|tienovanie) ;; *) RSRC=off ;; esac
echo "dem_source=$DEM_USED" >> "$GITHUB_OUTPUT"
echo "rock_slope=$RSLOPE" >> "$GITHUB_OUTPUT"
echo "rock_source=$RSRC" >> "$GITHUB_OUTPUT"
# veľkosť tej vrstvy, ktorú tento job naozaj vyrobil
MERANY="$SRC"; [ "$ONLY" = 'rocks' ] && MERANY="$RPM"
if [ -s "$MERANY" ]; then
  echo "size_mb=$(( $(stat -c%s "$MERANY") / 1048576 ))" >> "$GITHUB_OUTPUT"
else
  echo "size_mb=0" >> "$GITHUB_OUTPUT"
fi
[ -n "$CZ" ] && echo "Vrstevnice do z$CZ, výšky: $DEM_USED, skaly: $RSLOPE"
ls -lh _site/tiles/
# keď cache trafila, výpočet sa preskočil – v súhrne to má byť riadok
if [ "$CACHE_HIT" = 'true' ]; then
  case "$ONLY" in
    rocks) POPIS="skaly z cache (nič sa nepočítalo), maxzoom $RZ" ;;
    *)     POPIS="vrstevnice z cache (nič sa nepočítalo), maxzoom ${CZ:-?}" ;;
  esac
  [ -s "$MERANY" ] && POPIS="$POPIS, $(du -h "$MERANY" | cut -f1)"
  printf '%s\t%s\t%s\t%s\n' "50" "Vrstevnice a skaly" "0" "$POPIS" \
    >> steps-out/contours.tsv
fi
