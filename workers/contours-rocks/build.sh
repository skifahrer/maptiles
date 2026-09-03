#!/usr/bin/env bash
# Vrstevnice a skalné plochy z výškových modelov → contours-out/contours.pmtiles.
#
# PREČO SAMOSTATNÝ SKRIPT A NIE `run:` V WORKFLOWE: súbor s workflowom má
# strop, nad ktorým ho GitHub NEPRIJME – a nepovie to; po pushi len vyrobí
# beh bez jobov, pomenovaný cestou k súboru, ktorý vyzerá, že sa workflow
# spustil sám. Dvadsať kilobajtov bashu je preto tu. Bokom od toho je to aj
# tak správnejšie: rovnako sú na tom `fetch-dem.sh`, `rock-areas.py`
# či `build-terrain.py`.
#
# Hodnoty z formulára a z prípravy chodia cez prostredie (viď krok
# „Vrstevnice a skaly z DEM" v build-map-region.yml):
#   REGION_BBOX REGION_KEY AREA_KEY_IN AREA_NAME_IN AREA_BBOX_IN AREA_KM2
#   CONTOUR_INTERVAL OPT_CONTOUR_LINES OPT_CONTOUR_SOURCE
#   OPT_CONTOUR_SMOOTHING OPT_CONTOUR_MAXZOOM OPT_ROCK_MAXZOOM
#   ROCK_SLOPE_IN ROCK_RES_IN OPT_ROCKS OPT_ROCK_DEM OPT_ROCK_SOURCE
#   OPT_ROCK_PLNE OPT_ROCK_ZAPLN_DIERY
#   OPT_ROCK_IMG_ASSET OPT_ROCKS_REBUILD
#   OPT_SIZE_LIMIT_MB OPT_UGKK_FALLBACK
# a k tomu `env:` celého workflowu (ROCK_*, *_STORE, BUDGET_CONTOURS_PCT,
# BUDGET_ROCKS_PCT) plus prihlásenie na Drive: GDRIVE_CREDENTIALS, alebo
# premenná DRIVE_CLIENT so secretmi DRIVE_SECRET / DRIVE_REFRESH.

set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq gdal-bin libsqlite3-mod-spatialite zstd
python3 -m pip install --quiet numpy
# `work/` sú medzivýsledky (orez, surové izolínie) – zámerne mimo
# `dem/`, ktoré ide celé do cache. `clip.tif` má aj gigabajty.
#
# `slope-chunks/` je NIEČO INÉ než medzivýsledok: je to sklad častí rastra
# sklonu. Má vlastnú cache aj vlastný sklad na Drive, lebo práve on robí to,
# že zrušený alebo spadnutý beh nezahodí hodinu čítania z Drive. Preto sa ani
# na konci nemaže. (`SLOPE_DIR` je ten adresár, `SLOPE_STORE` meno skladu na
# Drive – dve rôzne veci, ktoré sa kedysi obe volali „store".)
SLOPE_DIR="${SLOPE_DIR:-slope-chunks}"
mkdir -p dem data work contours-out "$SLOPE_DIR"

BBOX="$REGION_BBOX"
IFS=, read -r W S E N <<< "$BBOX"

# OREZ NA POLYGÓN KRAJA, nie len na jeho obdĺžnik. Bbox kraja je oveľa väčší
# než kraj (pri Prešovskom 16 107 km² proti 10 184, teda 37 % mimo) a za jeho
# hranicou je DMR 5.0 PRÁZDNE. Hranica dát a nodaty je pritom pre `gdaldem
# slope` zvislá stena – sklon 90° – takže z okrajov vychádzali falošné skaly:
# v behu 31635772047 z nich bolo 13 403 km² „skalnej plochy" (bbox má 16 107),
# zlepovanie švov to nedalo dokopy a spadlo na náhradné riešenie.
#
# `-cutline` mimo polygónu zapíše nodatu, `-crop_to_cutline` sa NEPOUŽÍVA:
# okno má ostať to isté (bbox), nech sa dlaždice a kľúče cache nemenia.
CUT=()
if [ -s data/region.geojson ]; then
  CUT=(-cutline data/region.geojson)
  echo "Orez na kraj: data/region.geojson (mimo kraja bude nodata)"
else
  echo "::warning::Polygón kraja nie je (data/region.geojson) – počíta sa celý bbox regiónu, teda aj mimo kraj. Za hranicou Slovenska je DMR 5.0 prázdne a z hrany dát vychádzajú falošné skaly."
fi
INTERVAL="$CONTOUR_INTERVAL"
case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=10 ;; esac

# ---------- výrez na testovanie ----------
# Vyriešila ho príprava (workers/plan/area.py), tu sa už len
# preberá – aby check-dem, zrkadlo ÚGKK aj tento výpočet pracovali
# s tým istým územím a nie s tromi mierne odlišnými.
AREA_KEY="$AREA_KEY_IN"
AREA_NAME="$AREA_NAME_IN"
AREA_BBOX="$AREA_BBOX_IN"
if [ "$AREA_KEY" != "cely" ]; then
  # „Nechaj input `area` prázdny" tu stálo dovtedy, kým bol `area` textové
  # pole. Dnes je to `choice` a prázdna hodnota sa v ňom vybrať NEDÁ, takže
  # rada viedla do slepej uličky – celý región je voľba `cely_region`.
  echo "::warning::Vrstevnice aj skaly sa počítajú LEN na výreze „$AREA_NAME“ ($AREA_BBOX, ${AREA_KM2} km²). Vo zvyšku regiónu nebude v mape ani jedno – toto je beh na testovanie, nie na nasadenie. Pre celý región zvoľ v inpute „area“ hodnotu „cely_region“."
  # Vrstevnice sa ďalej trasujú z výrezu, nie z celého regiónu.
  IFS=, read -r W S E N <<< "$AREA_BBOX"
fi

# ---------- ktorá polovica ----------
# Vrstevnice a skaly sú DVA SAMOSTATNÉ JOBY (viď build-map-region.yml), ale jeden
# skript: obe polovice stoja na tom istom výreze, tom istom DEM a tom istom
# rozpočte, takže dve kópie by sa časom rozišli. Čo sa má počítať, hovorí
# `ONLY` – a keďže sa každá polovica gatuje premennou, ktorú si už skript
# aj tak čítal, nie je to nová vetva, len jej vypnutie.
#
# Prečo dva joby: kým to bol jeden, z „Vrstevnice a skaly" trvajúceho 14 minút
# sa nedalo povedať, ktorá polovica ten čas žerie – a strop času platí na job,
# takže pomalé skaly vzali so sebou aj hotové vrstevnice.
ONLY="${ONLY:-all}"
case "$ONLY" in
  contours) OPT_ROCK_DEM=""; OPT_ROCKS=false ;;
  rocks)    OPT_CONTOUR_LINES=false ;;
  all)      ;;
  *) echo "::error::ONLY musí byť 'contours', 'rocks' alebo 'all' (dostal '$ONLY')."; exit 1 ;;
esac
echo "Táto polovica: $ONLY"

# ---------- výškové modely ----------
# Sťahovanie DEM je v samostatnom skripte – potrebuje ho aj job
# s tieňovaním a dve kópie by časom zaostali jedna za druhou.
#
# Vrstevnice a skaly majú vlastný výber zdroja, takže tu môžu byť
# naraz DVA modely. Každý ide do `dem/<zdroj>/`; keď je zdroj ten
# istý, druhé volanie nájde hotovú mozaiku a nesťahuje nič.
#
# Dlaždicové modely sa sťahujú pre CELÝ región: sú v cache pod
# kľúčom regiónu, takže čiastočné stiahnutie by sa nabudúce vrátilo
# ako keby bolo úplné. ÚGKK sa naopak pýta po výrezoch a pri 1 m je
# celý kraj mimo možností – tam ide len výrez.

fetch_dem() { # $1 = zdroj → DEM_VRT, DEM_GOT (čo sa NAOZAJ použilo)
  local src="$1" fbbox rc
  if [ -s "dem/$src/all.vrt" ]; then
    DEM_VRT="dem/$src/all.vrt"; DEM_GOT="$src"
    echo "DEM $src: mozaika už je ✓"
    return 0
  fi
  # DMR 5.0 na výrez je jeden COG presne pre ten výrez, takže sa pýta jeho
  # bboxom; všetko ostatné sú dlaždice pre celý región.
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
    # Ten model pre toto územie nemáme. Buď to zhodíme, alebo dopočítame
    # zo Sonnyho – ale nikdy ticho: `dem-source.txt` nesie, čo sa NAOZAJ
    # použilo, takže atribúcia v mape nebude tvrdiť DMR 5.0 tam, kde je Sonny.
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

# ---------- čo sa vlastne ide počítať ----------
# Bez tohto je z logu vidieť len „Vrstevnice a skaly z DEM" a potom
# desiatky minút ticha. Rozmer rastra a počet buniek povedia, či
# ide o minúty alebo o hodinu, a to ešte pred prvým gdalwarpom.
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

# Zdroje z formulára. `opt_rock_dem` je prázdny, keď skaly idú
# z tieňovania alebo sú vypnuté – vtedy sa na DEM kvôli nim nesiaha.
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
  # DMR 5.0 sa na skaly NESŤAHUJE VCELKU. Sklon si ho prečíta z Drive po
  # častiach (`slope-chunks.py --drive`) a každú časť si odloží do skladu,
  # takže zrušený beh o hotové časti nepríde. Sťahovať popri tom ešte celý
  # výrez ako jeden COG by znamenalo prejsť tie isté dáta dvakrát – raz do
  # `ugkk-<vyrez>.tif` a druhý raz po častiach.
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

# Zjemnenie DEM pred trasovaním vrstevníc. Priemerovanie na hrubšiu
# mriežku vyhladí šum, ale zároveň zje detail terénu. Default 0 =
# žiadne zjemnenie, len orez na bbox v plnom rozlíšení.
T_CONT=$(date +%s)

make_empty_gpkg() { # $1 = súbor, $2 = vrstva, $3 = typ geometrie
  # Schéma odkazuje na obe vrstvy vždy, takže súbor musí existovať
  # aj vtedy, keď je vrstva vypnutá alebo sa nič nenašlo.
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

  # ---------- vyhladenie SAMOTNÉHO DEM ----------
  # TOTO JE TÁ PÁKA, KTORÁ ZUBATOSŤ NAOZAJ ODSTRÁNI, a `-simplify` s Chaikinom
  # nie sú jej náhrada. Dôvod je v tom, odkiaľ zubatosť pochádza: `gdal_contour`
  # interpoluje priesečník na hrane bunky, takže z HLADKÉHO poľa výšok vyjde
  # hladká čiara aj bez akýchkoľvek úprav. Čo ju krčí, je mikroreliéf
  # v LiDARovom DTM – kry, balvany, šum merania na úrovni decimetrov.
  #
  # LENŽE JE TO AJ TÁ PÁKA, KTORÁ VRSTEVNICE ZAOBLÍ PRIVIAC, a preto tu okno
  # nie je také veľké, ako bolo. V okne totiž nie je len šum: rebro, žľab
  # či terasa široká pár metrov sú tvary, ktoré v teréne NAOZAJ SÚ, a priemer
  # 5×5 ich zmaže spolu s krami. Vrstevnica potom nie je zubatá, ale ani sa
  # nedrží terénu – vedie oblým oblúkom tam, kde má mať zálom.
  #
  # Merané na simulovanom teréne so šumom AJ reálnymi tvarmi: okno 5×5 nechalo
  # z 12 m tvaru 27 % a odchýlku 1,52 m, okno 3×3 nechá 63 % a 0,70 m – a lomy
  # sú pritom MENŠIE, čiže menšie okno nie je ústupok zubatosti. Tabuľka je
  # v docs/pipeline.md, prepočíta ju `workers/contours-rocks/measure-smoothing.py`.
  #
  # OKNO SA ZADÁVA V METROCH, NIE V BUNKÁCH, a to je celé, prečo sa smie zapnúť
  # predvolene. Dva metre sú na 1 m LiDARe okno 3×3 (zmaže kry a šum, rebro
  # nechá), na 5 m dlaždiciach DMR 5.0 aj na Sonnyho 20 m vyjde jedna bunka –
  # hrubý model mikroreliéf neobsahuje, je v ňom spriemerovaný už zo zdroja,
  # a okno „3×3 buniek" by tam zmazalo desiatky metrov terénu. `0` to vypne.
  #
  # Priemer robia dva gdalwarpy – zmenšenie s `-r average` a zväčšenie späť
  # s `-r cubicspline` – lacnejšie a pamäťovo bezpečnejšie než gigabajtový
  # raster cez numpy, a na tejto mierke to robí to isté.
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
# Okno musí byť nepárny násobok bunky – `2r+1`. Keď vyjde r = 0, model je na
# mikroreliéf privhrubý a nevyhladzuje sa vôbec.
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
      # Pôvodný orez už netreba a má aj gigabajty – na disku runnera je to
      # rozdiel medzi „prejde" a „no space left on device".
      rm -f work/clip.tif
    fi
  fi

  # `-q` je preč a ide to cez watch.py: gdal_contour nad krajom beží
  # desiatky minút a doteraz pri tom nepovedal ani slovo.
  python3 workers/lib/watch.py --label="vrstevnice" --watch-file=work/raw.gpkg \
    -- gdal_contour -a ele -i "$INTERVAL" -f GPKG -nln contours \
       "$CONTOUR_RASTER" work/raw.gpkg

  # `level` rozdelí vrstevnice na hlavné/polovičné/základné, aby sa
  # dali zapínať podľa zoomu a kresliť rôzne hrubo. Hranice sa počítajú
  # z intervalu, nie natvrdo zo 100/50 – pri interval=5 by inak bola
  # zvýraznená každá dvadsiata čiara namiesto každej desiatej a pri
  # interval=25 by sa `mid` netrafilo nikdy. Zvýrazňuje sa každá
  # desiata (major) a každá piata (mid) vrstevnica, čo je pri
  # štandardných 10 m presne doterajších 100 a 50 m.
  MAJOR=$(( INTERVAL * 10 ))
  MID=$(( INTERVAL * 5 ))
  echo "Vrstevnice: interval ${INTERVAL} m z modelu $CONTOUR_DEM, zvýraznená každá ${MAJOR} m (major) a ${MID} m (mid)"

  # ---------- zjednodušenie a zaoblenie ----------
  # Presne tá istá dvojica ako pri skalách (viď ROCK_SIMPLIFY / ROCK_SMOOTH)
  # a z toho istého dôvodu: vrstevnica je izolínia nad rastrom, čiže chodí
  # po hranách buniek. Pri 1 m DEM je jeden schodík meter a pixel dlaždice
  # má pri z16 1,57 m – takže tie schodíky sú v mape vidieť ako zúbky.
  #
  # PORADIE JE PODSTATNÉ: najprv sa zmažú schodíky (`-simplify`), až potom
  # sa zaoblia rohy, ktoré po nich ostali. Opačne by sa zaoblil každý schodík
  # zvlášť, počet bodov by narástol a čiara by bola stále schodíková, len
  # s oblými schodmi.
  #
  # Tolerancia je vo VRSTVE, teda v stupňoch (vrstevnice sú EPSG:4326).
  # ZÁPORNÉ ČÍSLO = KOĽKO ŠTVRTÍN BUNKY DEM, teda `-1` je štvrtina bunky
  # a `-2` polovica. Jednotkou je štvrtina, lebo to bola prvá hodnota, ktorú
  # sme merali, a číslo tak ostalo porovnateľné s tým, čo je v histórii.
  # `0` = vypnuté. Kladné číslo sa berie v METROCH a prepočíta sa na stupne
  # na šírke tohto výrezu – metre sú to, v čom sa o teréne rozmýšľa, stupne
  # to, v čom je uložený.
  #
  # ŠTVRTINA BUNKY, nie polovica – a je to tá istá otázka ako pri okne vyššie.
  # Zjednodušenie nerobí čiaru oblou samo, ale predlžuje segmenty, a Chaikin
  # potom reže rohy dlhé štvrtinu SEGMENTU: čím dlhší segment, tým väčší kus
  # tvaru sa odreže (pri 1/2 bunky prežije z 12 m tvaru 52 %, pri 1/4 už 63 %).
  C_SIMPLIFY="${CONTOUR_SIMPLIFY:--1}"
  # Vypíše dve čísla: toleranciu v stupňoch (tá ide do ogr2ogr) a tú istú
  # toleranciu v metroch (tá ide do logu, lebo v stupňoch si ju nikto
  # nepredstaví). Prepočet je na jednom mieste, nie dvakrát.
  set +e
  SIMPL_OUT=$(python3 - "$C_SIMPLIFY" "$CONTOUR_RASTER" <<'PY'
import json, subprocess, sys
want, raster = float(sys.argv[1]), sys.argv[2]
# DLHŠÍ z dvoch stupňov – ten po ŠÍRKE (110 540 m). Stupeň po dĺžke má u nás
# len ~73 000 m, takže je to on, kto rozhoduje o najhoršom prípade, a ten sa
# tu musí použiť dvakrát:
#   metre → stupne  … väčší deliteľ dá menšiu toleranciu, čiže na zemi nikdy
#                     nebude väčšia, než sa žiadalo, nech ide svah akokoľvek
#   stupne → metre  … do logu ide najväčšia možná, nie najmenšia; opačne by
#                     riadok tvrdil menšiu toleranciu, než sa naozaj použila
m_per_deg = 110540
if want == 0:
    deg = 0.0
elif want > 0:
    deg = want / m_per_deg          # zadané v metroch
else:
    # Raster, z ktorého sa NAOZAJ trasovalo – pri zapnutom vyhladení je to
    # `clip-smooth.tif` a `clip.tif` už neexistuje. Mriežka je tá istá, ale
    # pýtať sa súboru, ktorý sme zmazali, by znamenalo pád.
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", raster],
        capture_output=True, text=True, check=True).stdout)
    gt = info["geoTransform"]
    # -1 = štvrtina bunky, -2 = polovica, -4 = celá. Nad polovicou sa čiara
    # začína odliepať od terénu (merané: pri 3/4 bunky vyskočí odchýlka od
    # skutočnej izolínie zo 0,58 na 1,29 bunky), tak sa vyššie nechodí.
    deg = min(abs(gt[1]), abs(gt[5])) * (-want) / 4
print(f"{deg:.10f} {deg * m_per_deg:.2f}")
PY
)
  SIMPL_RC=$?
  set -e
  SIMPL_ARGS=()
  if [ "$SIMPL_RC" -ne 0 ] || [ -z "$SIMPL_OUT" ]; then
    # Tolerancia sa nedá zistiť (napr. gdalinfo nad orezom zlyhal). Vrstevnice
    # sú spočítané, tak sa kvôli kozmetike nezhadzuje beh – ale musí byť
    # počuť, prečo ostali schodíkové.
    echo "::warning::Tolerancia zjednodušenia vrstevníc sa nedá spočítať – idú bez neho (schodíky po hranách buniek ostanú)."
  else
    read -r SIMPL_DEG SIMPL_M <<< "$SIMPL_OUT"
    # Nula sa píše `0.0000000000` (formát je pevný, `%.10f`) – porovnáva sa
    # teda reťazec, nie číslo, a je to zámerné: bash desatinné čísla nevie.
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

  # Zaoblenie – rohy po zjednodušení nahradí LIMITNÁ KRIVKA (kvadratický
  # B-spline). Dva prechody Chaikina, čo tu boli doteraz, sa k nej len blížia
  # a robia to LOKÁLNE: zo 120° rohu ostane vyše 30°, a keďže rohy sedia
  # v rozostupe vrcholov po Douglas–Peuckerovi, je z toho PRAVIDELNÝ zub (na
  # hotovej mape 14,7/km). Číslo je dovolený PRIEHYB TETIVY v štvrtinách kroku
  # mriežky dlaždice na maxzoome vrstevníc – preto sa sem maxzoom podáva.
  # Rozpis a merania: `contours-rocks/smooth-shapes.py`; `0` to vypne.
  C_SMOOTH="${CONTOUR_SMOOTH:-2}"
  case "$C_SMOOTH" in ''|*[!0-9]*) C_SMOOTH=2 ;; esac
  if [ "$C_SMOOTH" -gt 0 ]; then
    echo "Zaoblenie vrstevníc: limitná krivka, priehyb ${C_SMOOTH}/4 kroku mriežky z${OPT_CONTOUR_MAXZOOM}"
    if ! python3 workers/contours-rocks/smooth-shapes.py --in=work/level.gpkg \
           --out=data/contours.gpkg --layer=contours \
           --maxzoom="$OPT_CONTOUR_MAXZOOM" --sag="$C_SMOOTH"; then
      # Zaoblenie je kozmetika nad hotovými vrstevnicami – keby zlyhalo,
      # nemá to zhodiť beh, ktorý ich už má spočítané. Ale MUSÍ to byť
      # počuť, inak by sa „prečo sú zase zubaté" hľadalo v štýle.
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

# ---------- skaly: najstrmšie úseky terénu ----------
# Celý výpočet je vo workers/contours-rocks/rock-areas.py – po častiach, aby sa
# jemná mriežka zmestila do pamäte aj na disk. Bbox kraja má pri
# 2 m vyše 3 miliardy buniek (~13 GB na jeden raster), takže naraz
# sa to spočítať nedá.
T_ROCK=$(date +%s)
ROCK_SLOPE="$ROCK_SLOPE_IN"
case "$ROCK_SLOPE" in ''|*[!0-9]*) ROCK_SLOPE=50 ;; esac
ROCK_CLIFF=$(( ROCK_SLOPE + ROCK_CLIFF_PLUS ))
# `auto` = mriežku vyberie rock-areas.py: najjemnejšiu, ktorá sa
# zmestí do rozpočtu času a má pri danom DEM ešte zmysel. Nedá sa
# to spočítať tu, lebo to závisí od plochy výrezu aj od bunky DEM.
RR="$ROCK_RES_IN"
case "$RR" in
  auto|'') RR=auto ;;
  *[!0-9.]*) RR="$ROCK_RES" ;;
esac
# Najmenšiu skalu (= jedna bunka mriežky) dopočíta rock-areas.py,
# lebo pri `auto` sa mriežka vyberá až tam.

make_empty_rock() { make_empty_gpkg data/rock.gpkg rock POLYGON; }

if [ "$OPT_ROCKS" = 'true' ]; then
  ROCK_READY=""
  ROCK_SRC="výpočet"

  # ---------- skaly z tieňovaných dlaždíc (rock_source: tienovanie) ----------
  # Tie sa v TOMTO jobe nepočítajú – spravil to job `shading-rocks`
  # o kus vyššie v tom istom behu (stiahol tieňované dlaždice
  # z freemap.sk a hotové polygóny nahral do skladu na Drive). Tu sa
  # už len stiahne výsledok. Keď je vyplnený `rock_img_asset`, ten job
  # nebežal a berie sa presne ten súbor.
  if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
    IMG_ASSET="$OPT_ROCK_IMG_ASSET"
    echo "::group::Skaly z tieňovania – $AREA_NAME, sklad $ROCK_IMG_STORE"
    if [ -z "$IMG_ASSET" ]; then
      # Najnovší súbor pre tento výrez. Zoradiť sa musí podľa času
      # nahratia, nie podľa mena: v mene sú prahy, takže abecedne
      # by vyhral ten s najväčším číslom, nie ten posledný. Robí to
      # `--latest` v sklade, aby to poradie bolo napísané raz.
      IMG_ASSET=$(python3 workers/drive/store.py --latest \
        --store="$ROCK_IMG_STORE" --prefix="rockimg-${AREA_KEY}-" \
        --suffix=".gpkg.zst" 2>/dev/null || true)
    fi
    if [ -z "$IMG_ASSET" ]; then
      echo "::endgroup::"
      echo "::error::V sklade $ROCK_IMG_STORE nie je pre výrez '$AREA_KEY' žiadny súbor (rockimg-${AREA_KEY}-*.gpkg.zst). Pozri job „Skaly z tieňovania\" v tomto behu – ten ich mal vyrobiť; keď spadol, hovorí prečo. Alebo vo výbere rock_source zvoľ výškový model (sonny / dmr35 / dmr5 / ugkk)."
      exit 1
    fi
    rm -rf /tmp/rockimg && mkdir -p /tmp/rockimg
    if ! python3 workers/drive/store.py --get --store="$ROCK_IMG_STORE" \
           --name="$IMG_ASSET" --dir=/tmp/rockimg; then
      echo "::endgroup::"
      echo "::error::Súbor $IMG_ASSET sa zo skladu $ROCK_IMG_STORE nedal stiahnuť."
      exit 1
    fi
    echo "  beriem: $IMG_ASSET ($(du -h "/tmp/rockimg/$IMG_ASSET" | cut -f1))"
    unzstd -q -f -o data/rock.gpkg "/tmp/rockimg/$IMG_ASSET"
    ROCK_READY=1
    ROCK_SRC="sklad $ROCK_IMG_STORE ($IMG_ASSET)"
    # Výrez sa tu NEOREZÁVA na bbox regiónu zámerne: asset vznikol
    # presne pre tento výrez a orezanie by len prerezalo polygóny
    # na hranici. Keby výrez presahoval región, dlaždice mimo neho
    # aj tak nikto nevykreslí.
    echo "::endgroup::"
  fi

  # Hotové skaly pre tento región a tieto nastavenia sú v sklade –
  # nastavenia sú v mene súboru, takže sa nikdy nepomiešajú. Výpočet
  # je na desiatky minút, stiahnutie na sekundy. `rocks_rebuild` ten
  # súbor zahodí a počíta odznova.
  # Výrez je v mene súboru: skaly len z Tatier sa nesmú nabudúce
  # vydávať za skaly celého kraja.
  ROCK_ASSET="rock-${REGION_KEY}-${AREA_KEY}-${ROCK_DEM_USED:-none}-s${ROCK_SLOPE}-g${RR}-${ROCK_ALGO}.gpkg.zst"
  # TESTOVACÍ BEH SA SKLADU NESMIE DOTKNÚŤ. Pri `area: cely_region` totiž kľúč
  # výrezu ostáva `cely` aj v teste (prípona `_test4` by prepla podobu DMR 5.0
  # – viď workers/plan/area.py), takže by testovacie skaly zo 4 km² ležali
  # v sklade pod menom skál CELÉHO KRAJA a ďalší ostrý beh by si ich stiahol
  # ako hotové. To je ten istý druh tichého omylu ako dlaždica, ktorá sľubuje
  # celý stupeň – meno musí hovoriť, čo v súbore naozaj je. Sklad častí sklonu
  # to má rovnako (`--no-store` nižšie), lebo tam ide o to isté.
  ROCK_STORE_OK=1
  if [ "${OPT_TEST_KM2:-0}" != '0' ]; then
    ROCK_STORE_OK=""
    echo "Rýchly test (${OPT_TEST_KM2} km²): skaly sa do skladu $ROCK_STORE neukladajú ani sa z neho neberú – ostrý beh by ich inak vydával za celý výrez."
  fi
  if [ -n "$ROCK_READY" ]; then
    : # skaly už sú (z tieňovania) – DEM sa na ne vôbec nečíta
  elif [ -z "$ROCK_STORE_OK" ]; then
    : # testovací beh – počíta sa nanovo a nikam sa to neodkladá
  elif [ "$OPT_ROCKS_REBUILD" = 'true' ]; then
    echo "rocks_rebuild=áno – zahadzujem uloženú verziu a počítam nanovo."
    python3 workers/drive/store.py --rm --store="$ROCK_STORE" \
      --name="$ROCK_ASSET" || true
  elif python3 workers/drive/store.py --get --store="$ROCK_STORE" \
         --name="$ROCK_ASSET" --dir=/tmp >/dev/null 2>&1; then
    unzstd -q -f -o data/rock.gpkg "/tmp/$ROCK_ASSET" && ROCK_READY=1
    [ -n "$ROCK_READY" ] && ROCK_SRC="sklad $ROCK_STORE" \
      && echo "Skaly zo skladu $ROCK_STORE ✓ ($ROCK_ASSET)"
  fi

  if [ -z "$ROCK_READY" ]; then
    echo "::group::Skaly z modelu $ROCK_DEM_USED – $AREA_NAME, sklon ≥ ${ROCK_SLOPE}° (steny od ${ROCK_CLIFF}°), mriežka ${RR}, zaoblenie ${ROCK_SMOOTH}×"
    # Skaly sú bonus nad vrstevnicami: keby ich výpočet zlyhal (alebo
    # v rovine nič nenašiel), nemá to zhodiť hodinový build.
    # Exit 2 = „toto sa nedá spočítať" (nezmestí sa to do pamäte,
    # alebo je zlé zadanie – priveľa častí, chýbajúca mozaika). To
    # nie je bonus, ktorý sa dá preskočiť – build sa má zastaviť
    # hneď, nie nasadiť mapu bez skál po hodine práce. Iný nenulový
    # kód je skutočné zlyhanie výpočtu a tam prázdna vrstva stačí.
    # ČAS MEDZI TÝMI DÔVODMI NIE JE: keď je vektorizácia nad
    # rozpočtom, povie to a beží ďalej (viď workers/contours-rocks/rock-areas.py).
    # ---- 1. odkiaľ sa číta výška ----
    # `dmr5` ide priamo z Drive po častiach; ostatné modely sú lokálne
    # dlaždice, ktoré už stiahol `fetch_dem`.
    SRC_ARGS=(--dem "$ROCK_VRT")
    [ "$ROCK_DEM_USED" = 'dmr5' ] && SRC_ARGS=(--drive --dem-cell-m 1)

    # Testovací beh a pregenerovanie sa skladu nesmú dotknúť: test počíta
    # pár km² s inými nastaveniami a jeho časti by v sklade vyzerali ako
    # plnohodnotné, `rocks_rebuild` zase znamená „never ničomu uloženému".
    STORE_ARGS=()
    [ "${OPT_TEST_KM2:-0}" != '0' ] && STORE_ARGS+=(--no-store)
    [ "$OPT_ROCKS_REBUILD" = 'true' ] && STORE_ARGS+=(--rebuild)

    # ---- 2. mriežka ----
    # Vyberá ju `slope-chunks.py`, lebo ju musí poznať skôr, než začne
    # počítať; `rock-areas.py` ju potom dostane hotovú. Dva výbery toho
    # istého by sa raz rozišli a vektorizovalo by sa niečo iné, než sa
    # počítalo.
    set +e
    RES=$(python3 workers/contours-rocks/slope-chunks.py --bbox="$AREA_BBOX" --res="$RR" \
      "${SRC_ARGS[@]}" --budget-min="$ROCK_BUDGET_MIN" \
      --chunk-cells="$ROCK_CHUNK_CELLS" --print-res)
    RC=$?
    set -e
    if [ "$RC" -ne 0 ] || [ -z "$RES" ]; then
      echo "::error::Nepodarilo sa vybrať mriežku pre skaly."
      exit 1
    fi

    # ---- 3. sklon po častiach (sklad prežije zrušený beh) ----
    set +e
    python3 workers/contours-rocks/slope-chunks.py --bbox="$AREA_BBOX" --res="$RES" \
      "${SRC_ARGS[@]}" "${STORE_ARGS[@]}" \
      --out="$SLOPE_DIR" --jobs="${SLOPE_JOBS:-6}" \
      --store="${SLOPE_STORE:-dem-slope}" \
      --stats=contours-out/slope-stats.txt
    RC=$?
    set -e
    if [ "$RC" -ne 0 ]; then
      echo "::error::Sklon po častiach zlyhal – skaly sa počítať nedajú."
      exit 1
    fi
    SLOPE_VRT=$(sed -n 's/^vrt=//p' contours-out/slope-stats.txt)

    # ---- 4. vektorizácia jedným priechodom nad celou mozaikou ----
    set +e
    python3 workers/contours-rocks/rock-areas.py --slope-vrt="$SLOPE_VRT" --bbox="$AREA_BBOX" \
      --res="$RES" --vec-res="${ROCK_VEC_RES:-auto}" \
      --slope="$ROCK_SLOPE" --cliff="$ROCK_CLIFF" \
      --dem="$ROCK_VRT" \
      --min-area=-1 --simplify="$ROCK_SIMPLIFY" \
      --plne="${OPT_ROCK_PLNE:-1}" \
      --zapln-diery="${OPT_ROCK_ZAPLN_DIERY:-0}" \
      --smooth="$ROCK_SMOOTH" --maxzoom="$OPT_ROCK_MAXZOOM" \
      --stats=contours-out/rock-stats.txt \
      --budget-min="$ROCK_BUDGET_MIN" \
      --block-px="${ROCK_BLOCK_PX:-4096}" \
      --max-rss-gb="$ROCK_MAX_RSS_GB" --heartbeat="$ROCK_HEARTBEAT_S" \
      --out=data/rock.gpkg
    RC=$?
    set -e
    if [ "$RC" -eq 2 ]; then
      echo "::endgroup::"
      echo "::error::Výpočet skál sa nedal dokončiť – zadanie je nad možnosti runnera (viď hlášky vyššie: pamäť alebo počet častí). Uprav rock_res alebo area a spusti znova."
      exit 1
    fi
    if [ "$RC" -eq 0 ] && [ -z "$ROCK_STORE_OK" ]; then
      ls -lh data/rock.gpkg
      echo "Do skladu $ROCK_STORE sa neukladá – je to rýchly test."
    elif [ "$RC" -eq 0 ]; then
      ls -lh data/rock.gpkg
      # Ulož ich, nech ich nabudúce netreba počítať znova. Zlyhanie
      # uloženia NESMIE zhodiť beh – skaly sú spočítané a v `rock.gpkg`.
      zstd -q -19 -T0 -f -o "/tmp/$ROCK_ASSET" data/rock.gpkg
      python3 workers/drive/store.py --put --store="$ROCK_STORE" \
          --file="/tmp/$ROCK_ASSET" \
          --note="Vektorové skaly zo sklonu výškového modelu – meno nesie región, výrez, model a nastavenia (prah sklonu, mriežka obrysu)" \
        && echo "Uložené do skladu $ROCK_STORE ako $ROCK_ASSET" \
        || echo "::warning::Skaly sa nepodarilo uložiť do skladu $ROCK_STORE – nabudúce sa budú počítať znova."
    else
      echo "::warning::Skalné plochy sa nevygenerovali – vrstva bude prázdna."
      make_empty_rock
    fi
    echo "::endgroup::"
  fi

  # Štatistika ide do contours-out, takže ju nesie aj cache – pri
  # cache hite sa tento krok vôbec nespustí, ale súhrn čísla má.
  ROCK_N=$(ogrinfo -so data/rock.gpkg rock 2>/dev/null \
    | awk -F': ' '/^Feature Count/ {print $2}')
  # Skaly z tieňovania nemajú ani sklon, ani mriežku – písať ich do
  # merania by bolo číslo, ktoré nikde nevzniklo.
  if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
    ROCK_HOW="tmavé plochy v tieňovaní"
  else
    ROCK_HOW="$ROCK_DEM_USED, sklon ≥ ${ROCK_SLOPE}°, mriežka ${RR} m"
  fi
  printf '%s\t%s\t%s\t%s\n' "40" "Skalné plochy" "$(( $(date +%s) - T_ROCK ))" \
    "${ROCK_N:-0} plôch, $AREA_NAME, ${ROCK_HOW} ($ROCK_SRC)" \
    >> steps-out/contours.tsv
  # Keď skaly prišli z releasu, script nebežal a štatistiku nemá kto
  # napísať – aspoň to základné, nech súhrn nie je plný otáznikov.
  if [ ! -s contours-out/rock-stats.txt ]; then
    # `min_area_m2` sa tu nedopĺňa: dopočítava ho rock-areas.py
    # z vybranej mriežky a ten práve nebežal. Súhrn si s chýbajúcou
    # hodnotou poradí (`${min_area_m2:-?}`) – dosadiť sem premennú,
    # ktorá nikde nevzniká, by pri `set -u` zhodilo celý build.
    if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
      # Skaly z tieňovania sú z iného sveta – ani sklon, ani mriežka
      # pre ne neexistujú. Súhrn podľa `source` vypíše inú tabuľku.
      { echo "source=tienovanie"; echo "count=${ROCK_N:-0}"
        printf "asset='%s'\n" "$ROCK_SRC"
      } > contours-out/rock-stats.txt
    else
      { echo "source=dem"; echo "count=${ROCK_N:-0}"; echo "grid_m=$RR"
        echo "slope_deg=$ROCK_SLOPE"; echo "cliff_deg=$ROCK_CLIFF"
      } > contours-out/rock-stats.txt
    fi
  fi
  # Z ktorého modelu sú skaly – do súhrnu. Pri `tienovanie` je
  # prázdny, lebo tam žiadny výškový model nefiguruje.
  printf "rock_dem='%s'\n" "$ROCK_DEM_USED" >> contours-out/rock-stats.txt
  # Výrez do štatistiky, nech je v súhrne vidieť, že skaly nie sú
  # všade – aj keď sa tento krok nabudúce vezme z cache.
  # Hodnoty v apostrofoch: súhrn si súbor načíta cez `.` a meno
  # výrezu má medzeru („celý región").
  { printf "area_key='%s'\n" "$AREA_KEY"
    printf "area_name='%s'\n" "$AREA_NAME"
    printf "area_bbox='%s'\n" "$AREA_BBOX"; } >> contours-out/rock-stats.txt
else
  make_empty_rock
  echo "Skaly: vypnuté (prázdna vrstva)."
fi

CZ="$OPT_CONTOUR_MAXZOOM"
case "$CZ" in ''|*[!0-9]*) CZ=14 ;; esac
if [ "$CZ" -gt 16 ]; then CZ=16; fi

# Skaly majú VLASTNÝ .pmtiles a vlastný maxzoom. Každý .pmtiles má totiž
# len jeden a tie dve vrstvy ho chcú úplne iný: vrstevnice sú čiary cez
# celý kraj a rozpočet minú okolo z14, skaly sú plochy len tam, kde je
# terén strmý, takže sa do z16 zmestia. Kým boli v jednom súbore, museli
# sa obe uskromniť na to nižšie – a na skalách to bolo vidieť, lebo
# práve pri priblížení sa pozerá, či obrys sedí na terén.
# 16 je tvrdý strop Planetilera; vyššie zoomy rieši overzoom, takže sa
# skaly zobrazujú až do maximálneho zoomu mapy tak či tak.
RZ="$OPT_ROCK_MAXZOOM"
case "$RZ" in ''|*[!0-9]*) RZ=16 ;; esac
if [ "$RZ" -gt 16 ]; then RZ=16; fi

# Vrstevnice, skaly a mapa idú na tú istú stránku, takže si rozpočet
# delia. Prepočet z hotového GPKG je lacný (sekundy), na rozdiel od
# sťahovania DEM.
LIMIT_MB="$OPT_SIZE_LIMIT_MB"
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
CBUDGET_MB=$(( LIMIT_MB * BUDGET_CONTOURS_PCT / 100 ))
RBUDGET_MB=$(( LIMIT_MB * BUDGET_ROCKS_PCT / 100 ))

# Planetiler s rozpočtom: keď je výsledok nad stropom, skúsi o zoom
# nižšie. Použitý maxzoom ostane v `PM_Z` – návratová hodnota by sa
# miešala s výstupom Planetilera, ktorý ide na stdout.
# Hľadanie zoomu, ktorý sa zmestí do rozpočtu stránky, je vo vlastnom súbore:
# je to iná otázka než „ako vzniká vrstevnica" a `contours-build.sh` narazil na
# strop 800 riadkov. Funkcia po sebe nechá `PM_Z` (použitý zoom) a `PM_MB`.
# shellcheck source=workers/lib/pmtiles-budget.sh
. workers/lib/pmtiles-budget.sh

T_PM=$(date +%s)
# Balí sa len tá polovica, ktorú tento job počítal. Druhá má vlastný job
# a vlastný `.pmtiles`; keby sa tu vyrobil prázdny, prepísal by v deploy
# ten skutočný, ktorý prišiel z toho druhého (a mapa by ticho prišla
# o vrstvu, ktorá sa spočítala správne).
if [ "$ONLY" != 'rocks' ]; then
  # Ôsmy parameter je STROP ZOOMU, po ktorý sa smie ísť hore, keď v rozpočte
  # ostane miesto (rozpis pri funkcii). `contour_maxzoom` je teda želanie aj
  # dno: pod ňu sa ide len kvôli rozpočtu, nad ňu po 16 – tvrdý strop
  # Planetilera, kde má mriežka dlaždice 0,098 m.
  pmtiles_do_rozpoctu workers/contours-rocks/contours.yml contours-out/contours.pmtiles \
    "$CZ" "$CBUDGET_MB" 10 "Vrstevnice" \
    "zvýš contour_interval (napr. 20 m) alebo ich pre toto územie vypni." 16
  CZ="$PM_Z"
fi

if [ "$ONLY" != 'contours' ]; then
  # Skaly majú `rock_maxzoom` predvolene 16 (strop Planetilera) – dvíhať niet kam.
  pmtiles_do_rozpoctu workers/contours-rocks/rocks.yml contours-out/rocks.pmtiles \
    "$RZ" "$RBUDGET_MB" 12 "Skaly" \
    "zvýš rock_min_area alebo zmenši výrez."
  RZ="$PM_Z"
  echo "$RZ" > contours-out/rock-maxzoom.txt
fi

# Skutočne použitý maxzoom si odloží aj cache, nech štýl vie, po
# ktorý zoom vrstevnice naozaj existujú. To isté platí pre zdroj
# výšok (ide do atribúcie mapy) a prah sklonu skál (do manifestu).
echo "$CZ" > contours-out/maxzoom.txt
# Do atribúcie ide model, z ktorého sú vrstevnice; keď sú vypnuté,
# ten, z ktorého sú skaly – v tej vrstve je aj tak len jedno z nich.
# Dva riadky namiesto vnorenej expanzie `${A:-${B:-...}`: tá končí
# dvomi zloženými zátvorkami za sebou a GitHub taký súbor NEPRIJME –
# workflow sa po pushnutí objaví ako beh bez jobov, pomenovaný
# cestou k súboru. Stráži to krok „Zátvorky výrazov v run blokoch"
# v „Kontrola · lint workflowov"; aj tento komentár preto tie dve zátvorky
# opisuje slovami.
DEM_FOR_STYLE="$CONTOUR_DEM"
[ -n "$DEM_FOR_STYLE" ] || DEM_FOR_STYLE="$ROCK_DEM_USED"
echo "$DEM_FOR_STYLE" > contours-out/dem-source.txt
# Prah sklonu má zmysel len pri skalách z DEM. Pri `tienovanie` žiadny
# sklon neexistuje, takže do manifestu ide `off` a namiesto neho
# sa tam píše zdroj skál.
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
# Do merania ide LEN tá polovica, ktorú tento job počítal. Kým sa tu `du`
# púšťalo na oba súbory, job „Skaly" meral aj `contours.pmtiles`, ktorý
# zámerne nevyrobil – v súhrne z toho bolo „vrstevnice z14 ()“, teda riadok
# o vrstve, ktorá v tom jobe vôbec nebežala.
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
