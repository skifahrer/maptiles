#!/usr/bin/env bash
# Vrstevnice a skalné plochy z výškových modelov → contours-out/contours.pmtiles.
#
# Samostatný skript preto, že súbor s workflowom má strop, nad ktorým ho GitHub
# ticho neprijme. Hodnoty z formulára a z prípravy chodia cez prostredie (viď
# krok „Vrstevnice a skaly z DEM" v build-map-region.yml), k tomu `env:` celého
# workflowu a prihlásenie na Drive.

set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq gdal-bin libsqlite3-mod-spatialite zstd
python3 -m pip install --quiet numpy
# `work/` sú medzivýsledky (`clip.tif` má aj gigabajty) – zámerne mimo `dem/`,
# ktoré ide celé do cache.
# `slope-chunks/` je sklad častí rastra sklonu, vďaka ktorému zrušený beh
# nezahodí hodinu čítania z Drive; preto sa ani na konci nemaže.
SLOPE_DIR="${SLOPE_DIR:-slope-chunks}"
mkdir -p dem data work contours-out "$SLOPE_DIR"

BBOX="$REGION_BBOX"
IFS=, read -r W S E N <<< "$BBOX"

# orez na polygón kraja, nie len na bbox: za hranicou kraja je DMR 5.0 prázdne
# a hranica dát je pre `gdaldem slope` zvislá stena, teda falošné skaly.
# `-crop_to_cutline` sa nepoužíva – okno má ostať to isté, nech sa nemenia kľúče.
CUT=()
if [ -s data/region.geojson ]; then
  CUT=(-cutline data/region.geojson)
  echo "Orez na kraj: data/region.geojson (mimo kraja bude nodata)"
else
  echo "::warning::Polygón kraja nie je (data/region.geojson) – počíta sa celý bbox regiónu, teda aj mimo kraj. Za hranicou Slovenska je DMR 5.0 prázdne a z hrany dát vychádzajú falošné skaly."
fi
INTERVAL="$CONTOUR_INTERVAL"
case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=10 ;; esac

# výrez vyriešila príprava (`workers/plan/area.py`), tu sa už len preberá
AREA_KEY="$AREA_KEY_IN"
AREA_NAME="$AREA_NAME_IN"
AREA_BBOX="$AREA_BBOX_IN"
if [ "$AREA_KEY" != "cely" ]; then
  # `area` je dnes `choice` a prázdna hodnota sa v ňom vybrať nedá –
  # celý región je voľba `cely_region`
  echo "::warning::Vrstevnice aj skaly sa počítajú LEN na výreze „$AREA_NAME“ ($AREA_BBOX, ${AREA_KM2} km²). Vo zvyšku regiónu nebude v mape ani jedno – toto je beh na testovanie, nie na nasadenie. Pre celý región zvoľ v inpute „area“ hodnotu „cely_region“."
  # vrstevnice sa ďalej trasujú z výrezu, nie z celého regiónu
  IFS=, read -r W S E N <<< "$AREA_BBOX"
fi

# vrstevnice a skaly sú dva joby, ale jeden skript: obe polovice stoja na tom
# istom výreze, DEM aj rozpočte. Čo sa počíta, hovorí `ONLY`.
# Dva joby preto, že strop času platí na job – pomalé skaly brali so sebou aj
# hotové vrstevnice.
ONLY="${ONLY:-all}"
case "$ONLY" in
  contours) OPT_ROCK_DEM=""; OPT_ROCKS=false ;;
  rocks)    OPT_CONTOUR_LINES=false ;;
  all)      ;;
  *) echo "::error::ONLY musí byť 'contours', 'rocks' alebo 'all' (dostal '$ONLY')."; exit 1 ;;
esac
echo "Táto polovica: $ONLY"

# sťahovanie DEM je v samostatnom skripte – potrebuje ho aj job s tieňovaním.
# Vrstevnice a skaly majú vlastný výber zdroja, takže tu môžu byť naraz dva
# modely; keď je zdroj ten istý, druhé volanie nesťahuje nič.
# Dlaždicové modely sa sťahujú pre celý región (cache je pod kľúčom regiónu),
# ÚGKK po výrezoch – pri 1 m je celý kraj mimo možností.

fetch_dem() { # $1 = zdroj → DEM_VRT, DEM_GOT (čo sa NAOZAJ použilo)
  local src="$1" fbbox rc
  if [ -s "dem/$src/all.vrt" ]; then
    DEM_VRT="dem/$src/all.vrt"; DEM_GOT="$src"
    echo "DEM $src: mozaika už je ✓"
    return 0
  fi
  # DMR 5.0 na výrez je jeden COG presne pre ten výrez
  if [ "$src" = 'dmr5' ] && [ "$AREA_KEY_IN" != 'cely' ]; then
    fbbox="$AREA_BBOX"
  else
    fbbox="$BBOX"
  fi
  set +e
  workers/dem/fetch.sh "$fbbox" "dem/$src" steps-out/contours.tsv \
    "$src" "$AREA_KEY_IN"
  rc=$?
  set -e
  if [ "$rc" -eq 3 ]; then
    # ten model pre toto územie nemáme. Nikdy ticho: `dem-source.txt` nesie,
    # čo sa naozaj použilo
    local how
    if [ "$src" = 'dmr5' ] && [ "$AREA_KEY_IN" != 'cely' ]; then
      how="workflow 'Dáta · DMR 5.0' s area: $AREA_KEY_IN"
    elif [ "$src" = 'dmr5' ]; then
      how="workflow 'Dáta · DMR 5.0' s area: cele_slovensko"
    else
      how="workflow 'Dáta · výškové modely' so zdrojom $src"
    fi
    if [ "$OPT_UGKK_FALLBACK" != 'true' ]; then
      echo "::error::Model $src pre toto územie nie je k dispozícii a ugkk_fallback je vypnutý. Naplň ho ($how), zapni fallback, alebo vyber iný zdroj."
      exit 1
    fi
    echo "::warning::Model $src pre toto územie nie je k dispozícii – počíta sa zo Sonnyho (20 m). Mapa bude, len s hrubším modelom. Doplní ho $how."
    fetch_dem sonny
    return 0
  elif [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  DEM_VRT="dem/$src/all.vrt"; DEM_GOT="$src"
}

# rozmer rastra a počet buniek povedia, či ide o minúty alebo o hodinu –
# ešte pred prvým gdalwarpom
dem_info() { # $1 = popis, $2 = mozaika
  echo "── Vstupný DEM: $1 ──────────────────────────────"
  gdalinfo "$2" 2>/dev/null \
    | grep -E "^Size is|^Pixel Size|^Upper Left|^Lower Right" || true
  python3 - "$W" "$S" "$E" "$N" "$2" <<'PY'
import json, math, subprocess, sys
w, s, e, n = map(float, sys.argv[1:5])
try:
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", sys.argv[5]],
        capture_output=True, text=True, check=True).stdout)
    gt = info["geoTransform"]
    dx, dy = abs(gt[1]), abs(gt[5])
    cells = ((e - w) / dx) * ((n - s) / dy)
    lat = (s + n) / 2
    print(f"  výrez        {e-w:.3f}° × {n-s:.3f}°  "
          f"(~{(e-w)*111.32*math.cos(math.radians(lat)):.0f} × "
          f"{(n-s)*110.54:.0f} km)")
    print(f"  bunka DEM    {dx*111320*math.cos(math.radians(lat)):.0f} × "
          f"{dy*110540:.0f} m")
    print(f"  buniek       {cells/1e6:.1f} mil.")
except Exception as exc:
    print(f"  (rozmer sa nedá zistiť: {exc})")
PY
  echo "─────────────────────────────────────────────────────"
}

# `opt_rock_dem` je prázdny, keď skaly idú z tieňovania alebo sú vypnuté
CONTOUR_SRC="$OPT_CONTOUR_SOURCE"
ROCK_DEM="$OPT_ROCK_DEM"
CONTOUR_VRT=""; CONTOUR_DEM=""
ROCK_VRT=""; ROCK_DEM_USED=""

if [ "$OPT_CONTOUR_LINES" = 'true' ]; then
  fetch_dem "$CONTOUR_SRC"
  CONTOUR_VRT="$DEM_VRT"; CONTOUR_DEM="$DEM_GOT"
  dem_info "vrstevnice ($CONTOUR_DEM)" "$CONTOUR_VRT"
fi
if [ -n "$ROCK_DEM" ]; then
  # DMR 5.0 sa na skaly nesťahuje vcelku: sklon si ho číta z Drive po častiach
  # a každú si odloží do skladu. Celý COG by znamenal prejsť dáta dvakrát.
  if [ "$ROCK_DEM" = 'dmr5' ]; then
    ROCK_VRT=""; ROCK_DEM_USED=dmr5
    echo "DEM skaly (dmr5): číta sa z Drive po častiach, nesťahuje sa vcelku"
  else
    fetch_dem "$ROCK_DEM"
    ROCK_VRT="$DEM_VRT"; ROCK_DEM_USED="$DEM_GOT"
    [ "$ROCK_VRT" = "$CONTOUR_VRT" ] \
      || dem_info "skaly ($ROCK_DEM_USED)" "$ROCK_VRT"
  fi
fi

# zjemnenie DEM pred trasovaním; default 0 = len orez na bbox
T_CONT=$(date +%s)

make_empty_gpkg() { # $1 = súbor, $2 = vrstva, $3 = typ geometrie
  # schéma odkazuje na obe vrstvy vždy, takže súbor musí existovať aj vtedy,
  # keď je vrstva vypnutá
  echo '{"type":"FeatureCollection","features":[]}' > work/empty.geojson
  ogr2ogr -f GPKG "$1" work/empty.geojson -nln "$2" -overwrite \
    -nlt "$3" -a_srs EPSG:4326 -lco GEOMETRY_NAME=geom
}

if [ "$OPT_CONTOUR_LINES" != 'true' ]; then
  echo "Vrstevnice: vypnuté (contour_source: ziadne) – prázdna vrstva."
  make_empty_gpkg data/contours.gpkg contours LINESTRING
else
  SMOOTH="$OPT_CONTOUR_SMOOTHING"
  case "$SMOOTH" in ''|*[!0-9.]*) SMOOTH=0 ;; esac
  if [ "${SMOOTH%%.*}" -gt 0 ] 2>/dev/null; then
    RES=$(python3 -c "print(f'{$SMOOTH / 3600:.8f}')")
    echo "Zjemnenie DEM: ${SMOOTH}″ (mriežka $RES°)"
    python3 workers/lib/watch.py --label="orez DEM" --watch-file=work/clip.tif \
      -- gdalwarp -overwrite -te "$W" "$S" "$E" "$N" "${CUT[@]}" \
         -tr "$RES" "$RES" -r average "$CONTOUR_VRT" work/clip.tif
  else
    echo "Zjemnenie DEM: vypnuté – vrstevnice sa trasujú z plného rozlíšenia."
    python3 workers/lib/watch.py --label="orez DEM" --watch-file=work/clip.tif \
      -- gdalwarp -overwrite -te "$W" "$S" "$E" "$N" "${CUT[@]}" \
         "$CONTOUR_VRT" work/clip.tif
  fi

  # ---------- vyhladenie samotného DEM ----------
  # Toto zubatosť naozaj odstráni: `gdal_contour` interpoluje priesečník na
  # hrane bunky, takže z hladkého poľa výšok vyjde hladká čiara aj bez úprav.
  # Čo ju krčí, je mikroreliéf v LiDARovom DTM.
  #
  # Okno ale nesmie byť veľké – nie je v ňom len šum: rebro či terasa široká
  # pár metrov je tvar, ktorý v teréne naozaj je (5×5 nechalo z 12 m tvaru 27 %,
  # 3×3 nechá 63 %). Zadáva sa v metroch, nie v bunkách, preto sa smie zapnúť
  # predvolene: na hrubom modeli vyjde jedna bunka a nehladí sa nič. `0` to vypne.
  #
  # Priemer robia dva gdalwarpy (zmenšenie `average`, zväčšenie `cubicspline`) –
  # lacnejšie a pamäťovo bezpečnejšie než gigabajtový raster cez numpy.
  CONTOUR_RASTER=work/clip.tif
  LOWPASS_M="${CONTOUR_DEM_LOWPASS:-2}"
  case "$LOWPASS_M" in ''|*[!0-9.]*) LOWPASS_M=2 ;; esac
  set +e
  LP_OUT=$(python3 - "$LOWPASS_M" <<'PY'
import json, subprocess, sys
want_m = float(sys.argv[1])
info = json.loads(subprocess.run(["gdalinfo", "-json", "work/clip.tif"],
                                 capture_output=True, text=True,
                                 check=True).stdout)
gt = info["geoTransform"]
cell_deg = min(abs(gt[1]), abs(gt[5]))
cell_m = cell_deg * 110540          # stupeň po šírke, viď nižšie pri tolerancii
# okno musí byť nepárny násobok bunky (`2r+1`); r = 0 znamená, že model je na
# mikroreliéf privhrubý
r = int(round(want_m / cell_m / 2)) if cell_m > 0 else 0
print(f"{2 * r + 1} {cell_deg:.10f} {cell_m:.2f}")
PY
)
  LP_RC=$?
  set -e
  if [ "$LP_RC" -ne 0 ] || [ -z "$LP_OUT" ]; then
    echo "::warning::Veľkosť okna na vyhladenie DEM sa nedá spočítať – vrstevnice sa trasujú z nevyhladeného modelu."
  else
    read -r LP_WIN LP_CELL_DEG LP_CELL_M <<< "$LP_OUT"
    if [ "$LP_WIN" -le 1 ]; then
      echo "Vyhladenie DEM: vypnuté – bunka modelu má ${LP_CELL_M} m, čo je viac než okno ${LOWPASS_M} m (mikroreliéf v ňom nie je)."
    else
      LP_COARSE=$(python3 -c "print(f'{$LP_CELL_DEG * $LP_WIN:.10f}')")
      echo "Vyhladenie DEM: okno ${LP_WIN}×${LP_WIN} buniek (~$(python3 -c "print(f'{$LP_CELL_M * $LP_WIN:.1f}')") m) – priemer, potom späť na pôvodnú mriežku"
      python3 workers/lib/watch.py --label="vyhladenie DEM (priemer)" \
        --watch-file=work/lp.tif \
        -- gdalwarp -overwrite -r average -tr "$LP_COARSE" "$LP_COARSE" \
           work/clip.tif work/lp.tif
      python3 workers/lib/watch.py --label="vyhladenie DEM (späť na mriežku)" \
        --watch-file=work/clip-smooth.tif \
        -- gdalwarp -overwrite -r cubicspline -te "$W" "$S" "$E" "$N" \
           -tr "$LP_CELL_DEG" "$LP_CELL_DEG" work/lp.tif work/clip-smooth.tif
      rm -f work/lp.tif
      CONTOUR_RASTER=work/clip-smooth.tif
      # pôvodný orez má aj gigabajty – na disku runnera je to rozdiel medzi
      # „prejde" a „no space left on device"
      rm -f work/clip.tif
    fi
  fi

  # cez watch.py: gdal_contour nad krajom beží desiatky minút a doteraz pri tom
  # nepovedal ani slovo
  python3 workers/lib/watch.py --label="vrstevnice" --watch-file=work/raw.gpkg \
    -- gdal_contour -a ele -i "$INTERVAL" -f GPKG -nln contours \
       "$CONTOUR_RASTER" work/raw.gpkg

  # `level` rozdelí vrstevnice na hlavné/polovičné/základné. Hranice sa počítajú
  # z intervalu, nie natvrdo zo 100/50 – zvýrazňuje sa každá desiata a piata.
  MAJOR=$(( INTERVAL * 10 ))
  MID=$(( INTERVAL * 5 ))
  echo "Vrstevnice: interval ${INTERVAL} m z modelu $CONTOUR_DEM, zvýraznená každá ${MAJOR} m (major) a ${MID} m (mid)"

  # ---------- zjednodušenie a zaoblenie ----------
  # Tá istá dvojica ako pri skalách: vrstevnica je izolínia nad rastrom, čiže
  # chodí po hranách buniek a tie schodíky sú v mape vidieť.
  # Poradie je podstatné – najprv sa zmažú schodíky, až potom sa zaoblia rohy;
  # opačne by sa zaoblil každý schodík zvlášť.
  # Tolerancia je v stupňoch (vrstevnice sú EPSG:4326). Záporné číslo = koľko
  # štvrtín bunky DEM, `0` = vypnuté, kladné = metre.
  # Štvrtina bunky, nie polovica: zjednodušenie predlžuje segmenty a zaoblenie
  # reže rohy dlhé štvrtinu segmentu, takže dlhší segment odreže väčší kus tvaru.
  C_SIMPLIFY="${CONTOUR_SIMPLIFY:--1}"
  # dve čísla: tolerancia v stupňoch (do ogr2ogr) a tá istá v metroch (do logu).
  # Prepočet je na jednom mieste.
  set +e
  SIMPL_OUT=$(python3 - "$C_SIMPLIFY" "$CONTOUR_RASTER" <<'PY'
import json, subprocess, sys
want, raster = float(sys.argv[1]), sys.argv[2]
# dlhší z dvoch stupňov – ten po šírke (110 540 m): rozhoduje o najhoršom
# prípade v oboch smeroch prepočtu
m_per_deg = 110540
if want == 0:
    deg = 0.0
elif want > 0:
    deg = want / m_per_deg          # zadané v metroch
else:
    # raster, z ktorého sa naozaj trasovalo – pri zapnutom vyhladení je to
    # `clip-smooth.tif` a `clip.tif` už neexistuje
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", raster],
        capture_output=True, text=True, check=True).stdout)
    gt = info["geoTransform"]
    # -1 = štvrtina bunky, -2 = polovica, -4 = celá. Nad polovicou sa čiara
    # začína odliepať od terénu.
    deg = min(abs(gt[1]), abs(gt[5])) * (-want) / 4
print(f"{deg:.10f} {deg * m_per_deg:.2f}")
PY
)
  SIMPL_RC=$?
  set -e
  SIMPL_ARGS=()
  if [ "$SIMPL_RC" -ne 0 ] || [ -z "$SIMPL_OUT" ]; then
    # vrstevnice sú spočítané, tak sa kvôli kozmetike nezhadzuje beh – ale
    # musí byť počuť, prečo ostali schodíkové
    echo "::warning::Tolerancia zjednodušenia vrstevníc sa nedá spočítať – idú bez neho (schodíky po hranách buniek ostanú)."
  else
    read -r SIMPL_DEG SIMPL_M <<< "$SIMPL_OUT"
    # nula sa píše `0.0000000000` (formát `%.10f`) – porovnáva sa reťazec,
    # lebo bash desatinné čísla nevie
    if [ "$SIMPL_DEG" = "0.0000000000" ]; then
      echo "Zjednodušenie vrstevníc: vypnuté (CONTOUR_SIMPLIFY=0)."
    else
      SIMPL_ARGS=(-simplify "$SIMPL_DEG")
      echo "Zjednodušenie vrstevníc: ${SIMPL_DEG}° (~${SIMPL_M} m)"
    fi
  fi

  python3 workers/lib/watch.py --label="triedenie vrstevníc" \
    --watch-file=work/level.gpkg \
    -- ogr2ogr -f GPKG work/level.gpkg work/raw.gpkg -nln contours \
    "${SIMPL_ARGS[@]}" \
    -dialect SQLITE -sql "SELECT *, CASE
         WHEN CAST(ele AS INTEGER) % $MAJOR = 0 THEN 'major'
         WHEN CAST(ele AS INTEGER) % $MID  = 0 THEN 'mid'
         ELSE 'minor' END AS level
       FROM contours WHERE ele IS NOT NULL"

  # zaoblenie: rohy po zjednodušení nahradí limitná krivka (kvadratický
  # B-spline). Chaikin sa k nej len blíži a robí to lokálne – zo 120° rohu
  # ostane vyše 30°, čiže pravidelný zub. Číslo je dovolený priehyb tetivy
  # v štvrtinách kroku mriežky dlaždice; `0` to vypne.
  C_SMOOTH="${CONTOUR_SMOOTH:-2}"
  case "$C_SMOOTH" in ''|*[!0-9]*) C_SMOOTH=2 ;; esac
  if [ "$C_SMOOTH" -gt 0 ]; then
    echo "Zaoblenie vrstevníc: limitná krivka, priehyb ${C_SMOOTH}/4 kroku mriežky z${OPT_CONTOUR_MAXZOOM}"
    if ! python3 workers/contours-rocks/smooth-shapes.py --in=work/level.gpkg \
           --out=data/contours.gpkg --layer=contours \
           --maxzoom="$OPT_CONTOUR_MAXZOOM" --sag="$C_SMOOTH"; then
      # zaoblenie je kozmetika nad hotovými vrstevnicami; keby zhodilo beh,
      # prišli by sme o spočítané. Ale musí to byť počuť.
      echo "::warning::Zaoblenie vrstevníc zlyhalo – idú zubaté, tak ako predtým."
      cp work/level.gpkg data/contours.gpkg
    fi
  else
    echo "Zaoblenie vrstevníc: vypnuté (contour_smooth=0)."
    cp work/level.gpkg data/contours.gpkg
  fi
  ls -lh data/contours.gpkg
  printf '%s\t%s\t%s\t%s\n' "30" "Vrstevnice (gdal_contour)" "$(( $(date +%s) - T_CONT ))" \
    "interval ${INTERVAL} m z $CONTOUR_DEM, $(du -h data/contours.gpkg | cut -f1)" \
    >> steps-out/contours.tsv
fi

# druhá polovica výpočtu je vo `workers/contours-rocks/rocks.sh` – tento súbor
# prerástol 800 riadkov. Číta sa cez `.`, nie ako vlastný proces: obe polovice
# si podávajú premenné (`ROCK_SLOPE`, `ROCK_DEM_USED`, `RR`).
# shellcheck source=workers/contours-rocks/rocks.sh
. workers/contours-rocks/rocks.sh

CZ="$OPT_CONTOUR_MAXZOOM"
case "$CZ" in ''|*[!0-9]*) CZ=14 ;; esac
if [ "$CZ" -gt 16 ]; then CZ=16; fi

# skaly majú vlastný .pmtiles a vlastný maxzoom: vrstevnice sú čiary cez celý
# kraj a rozpočet minú okolo z14, skaly sú plochy len tam, kde je terén strmý,
# takže sa do z16 zmestia. 16 je tvrdý strop Planetilera, vyššie rieši overzoom.
RZ="$OPT_ROCK_MAXZOOM"
case "$RZ" in ''|*[!0-9]*) RZ=16 ;; esac
if [ "$RZ" -gt 16 ]; then RZ=16; fi

# vrstevnice, skaly a mapa si delia rozpočet stránky; prepočet z hotového GPKG
# je lacný
LIMIT_MB="$OPT_SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
CBUDGET_MB=$(( LIMIT_MB * BUDGET_CONTOURS_PCT / 100 ))
RBUDGET_MB=$(( LIMIT_MB * BUDGET_ROCKS_PCT / 100 ))

# hľadanie zoomu, ktorý sa zmestí do rozpočtu, je vo vlastnom súbore.
# Funkcia po sebe nechá `PM_Z` (použitý zoom) a `PM_MB` – návratová hodnota by
# sa miešala s výstupom Planetilera.
. workers/lib/pmtiles-budget.sh

T_PM=$(date +%s)
# balí sa len tá polovica, ktorú tento job počítal; prázdny `.pmtiles` by
# v deploy prepísal ten skutočný z druhého jobu
if [ "$ONLY" != 'rocks' ]; then
  # ôsmy parameter je strop zoomu, po ktorý sa smie ísť hore, keď v rozpočte
  # ostane miesto – `contour_maxzoom` je teda želanie aj dno
  pmtiles_do_rozpoctu workers/contours-rocks/contours.yml contours-out/contours.pmtiles \
    "$CZ" "$CBUDGET_MB" 10 "Vrstevnice" \
    "zvýš contour_interval (napr. 20 m) alebo ich pre toto územie vypni." 16
  CZ="$PM_Z"
fi

if [ "$ONLY" != 'contours' ]; then
  # skaly majú `rock_maxzoom` predvolene 16 (strop Planetilera)
  pmtiles_do_rozpoctu workers/contours-rocks/rocks.yml contours-out/rocks.pmtiles \
    "$RZ" "$RBUDGET_MB" 12 "Skaly" \
    "zvýš rock_min_area alebo zmenši výrez."
  RZ="$PM_Z"
  echo "$RZ" > contours-out/rock-maxzoom.txt
fi

# skutočne použitý maxzoom, zdroj výšok (do atribúcie) a prah sklonu (do
# manifestu) si odloží aj cache
echo "$CZ" > contours-out/maxzoom.txt
# do atribúcie ide model, z ktorého sú vrstevnice; keď sú vypnuté, ten zo skál.
# Dva riadky namiesto vnorenej expanzie: tá končí dvomi zloženými zátvorkami
# za sebou a GitHub taký súbor neprijme.
DEM_FOR_STYLE="$CONTOUR_DEM"
[ -n "$DEM_FOR_STYLE" ] || DEM_FOR_STYLE="$ROCK_DEM_USED"
echo "$DEM_FOR_STYLE" > contours-out/dem-source.txt
# prah sklonu má zmysel len pri skalách z DEM; pri `tienovanie` ide do
# manifestu `off` a namiesto neho zdroj skál
if [ "$OPT_ROCKS" = 'true' ] \
   && [ "$OPT_ROCK_SOURCE" != 'tienovanie' ]; then
  echo "$ROCK_SLOPE" > contours-out/rock-slope.txt
else
  echo "off" > contours-out/rock-slope.txt
fi
if [ "$OPT_ROCKS" = 'true' ]; then
  echo "$OPT_ROCK_SOURCE" > contours-out/rock-source.txt
else
  echo "off" > contours-out/rock-source.txt
fi
ls -lh contours-out/
# do merania ide len tá polovica, ktorú tento job počítal – inak by súhrn
# hlásil vrstvu, ktorá v tom jobe vôbec nebežala
MERANIE=""
if [ "$ONLY" != 'rocks' ]; then
  MERANIE="vrstevnice z$CZ ($(du -h contours-out/contours.pmtiles | cut -f1))"
fi
if [ "$ONLY" != 'contours' ]; then
  [ -n "$MERANIE" ] && MERANIE="$MERANIE, "
  MERANIE="${MERANIE}skaly z$RZ ($(du -h contours-out/rocks.pmtiles | cut -f1))"
fi
printf '%s\t%s\t%s\t%s\n' "50" "Vrstevnice a skaly → PMTiles" "$(( $(date +%s) - T_PM ))" \
  "$MERANIE" >> steps-out/contours.tsv
