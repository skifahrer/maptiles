#!/usr/bin/env bash
# Hotové vrstevnice a skaly z `contours-out/` do `_site/` + výstupy pre štýl.
#
# PREČO SAMOSTATNÝ SKRIPT: `build-map.yml` má strop 500 kB a nad ním ho GitHub
# ticho neprijme (stráži to „Kontrola · lint workflowov"). A hlavne: TENTO KROK MAJÚ DVA
# JOBY. `contours` a `rocks` vychádzajú z jedného výpočtu a každý si z neho
# berie svoju polovicu, takže v YAMLe stál ten istý blok dvakrát – a dve kópie
# sa vždy raz rozídu. (Tá druhá už aj prišla o všetky komentáre.)
#
# ČO SA TU ROZHODUJE. Vrstevnice a skaly idú do mapy ako DVA `.pmtiles`
# s vlastným maxzoomom – dajú sa teda nasadiť aj jedno bez druhého. Kým boli
# v jednom súbore, vypnuté vrstevnice znamenali aj žiadne skaly.
#
# Hodnoty sa berú z toho, ČO NAOZAJ VZNIKLO (`contours-out/*.txt`), a až keď
# tam nie sú, siahne sa na vstup z formulára: maxzoom sa mohol počas výpočtu
# znížiť kvôli veľkosti a model mohol spadnúť na Sonnyho. Atribúcia v mape
# potom nesmie tvrdiť DMR 5.0 tam, kde je Sonny.

set -euo pipefail
mkdir -p _site/tiles
KEY="$REGION_KEY"

# ---------- ktorá polovica ----------
# To isté `ONLY` dostal aj `contours-build.sh`, takže tu je len odpoveď na
# otázku „mal tento job tú polovicu vôbec počítať?", nie druhé rozhodovanie.
#
# Bez neho tento skript hlásil chýbajúcu polovicu ako poruchu: job „Vrstevnice"
# varoval „Skaly sa nevygenerovali" a job „Skaly" varoval „Vrstevnice sa
# nevygenerovali" – dva falošné poplachy v KAŽDOM behu, teda presne to, po čom
# si človek prestane warningov všímať. Horšie: pri chýbajúcich vrstevniciach sa
# skript končil `exit 0` ešte pred zápisom `rock_slope` a `rock_source`, takže
# job „Skaly" ich vracal prázdne. Manifest mapy aj súhrn behu potom tvrdili
# `rock_slope=off`, `rock_source=off` a „skaly: (nebežalo)" nad skalami, ktoré
# sa práve spočítali.
ONLY="${ONLY:-all}"
case "$ONLY" in
  contours|rocks|all) ;;
  *) echo "::error::ONLY musí byť 'contours', 'rocks' alebo 'all' (dostal '$ONLY')."; exit 1 ;;
esac
# Čo tento job mal vyrobiť. Zapnutosť vrstvy vo formulári je druhá podmienka:
# vypnutú vrstvu nikto nečaká, tak sa o nej ani nevaruje.
CHCE_CONTOURS=false; [ "$ONLY" != 'rocks' ] && [ "$OPT_CONTOUR_LINES" = 'true' ] && CHCE_CONTOURS=true
CHCE_ROCKS=false;    [ "$ONLY" != 'contours' ] && [ "$OPT_ROCKS" = 'true' ] && CHCE_ROCKS=true

# ---- skaly: vlastný .pmtiles, vlastný maxzoom ----
# Idú prvé, lebo sa dajú nasadiť aj vtedy, keď vrstevnice nie sú
# (a naopak). Kým boli v jednom súbore, vypnuté vrstevnice znamenali
# aj žiadne skaly.
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
  # Maxzoom berieme z toho, čo sa naozaj vygenerovalo (mohol sa znížiť
  # kvôli veľkosti); ak súbor chýba, padáme späť na vstup.
  CZ=$(cat contours-out/maxzoom.txt 2>/dev/null || echo '')
  case "$CZ" in ''|*[!0-9]*) CZ="$OPT_CONTOUR_MAXZOOM" ;; esac
  case "$CZ" in ''|*[!0-9]*) CZ=14 ;; esac
  if [ "$CZ" -gt 16 ]; then CZ=16; fi
  # `enabled` je odteraz o VRSTEVNICIACH, nie o súbore: pri
  # `contour_source: ziadne` je .pmtiles síce na disku, ale prázdny,
  # a štýl doň nemá čo odkazovať.
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
# Zdroj výšok a prah sklonu skál si nesie cache spolu s dlaždicami –
# pri cache hite sa krok s DEM vôbec nespustí. Zapisujú sa VŽDY, aj keď
# vrstevnice v tomto jobe nevznikli: job „Skaly" ich vracia ako svoje
# výstupy a deploy z nich skladá manifest mapy.
DEM_USED=$(cat contours-out/dem-source.txt 2>/dev/null || echo '')
# Kľúče musia sedieť s workers/data/dem-sources.json – čo tu neprejde,
# spadne na Sonnyho a mapa by potom v atribúcii tvrdila iný model,
# než z ktorého naozaj je. (`dmr35` a `dmr5` tu kedysi chýbali.)
case "$DEM_USED" in sonny|dmr35|dmr5) ;; *) DEM_USED=sonny ;; esac
RSLOPE=$(cat contours-out/rock-slope.txt 2>/dev/null || echo off)
RSRC=$(cat contours-out/rock-source.txt 2>/dev/null || echo off)
case "$RSRC" in sonny|dmr35|dmr5|tienovanie) ;; *) RSRC=off ;; esac
echo "dem_source=$DEM_USED" >> "$GITHUB_OUTPUT"
echo "rock_slope=$RSLOPE" >> "$GITHUB_OUTPUT"
echo "rock_source=$RSRC" >> "$GITHUB_OUTPUT"
# Veľkosť tej vrstvy, ktorú tento job naozaj vyrobil – v jobe „Skaly" je to
# `rocks.pmtiles`, inak `contours.pmtiles`.
MERANY="$SRC"; [ "$ONLY" = 'rocks' ] && MERANY="$RPM"
if [ -s "$MERANY" ]; then
  echo "size_mb=$(( $(stat -c%s "$MERANY") / 1048576 ))" >> "$GITHUB_OUTPUT"
else
  echo "size_mb=0" >> "$GITHUB_OUTPUT"
fi
[ -n "$CZ" ] && echo "Vrstevnice do z$CZ, výšky: $DEM_USED, skaly: $RSLOPE"
ls -lh _site/tiles/
# Keď cache trafila, celý výpočet vyššie sa preskočil – v súhrne to
# má byť vidieť ako riadok, nie ako chýbajúce kroky.
if [ "$CACHE_HIT" = 'true' ]; then
  case "$ONLY" in
    rocks) POPIS="skaly z cache (nič sa nepočítalo), maxzoom $RZ" ;;
    *)     POPIS="vrstevnice z cache (nič sa nepočítalo), maxzoom ${CZ:-?}" ;;
  esac
  [ -s "$MERANY" ] && POPIS="$POPIS, $(du -h "$MERANY" | cut -f1)"
  printf '%s\t%s\t%s\t%s\n' "50" "Vrstevnice a skaly" "0" "$POPIS" \
    >> steps-out/contours.tsv
fi
