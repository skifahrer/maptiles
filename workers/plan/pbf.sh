#!/usr/bin/env bash
# PBF regiónu na disk – stiahnutie, prípadné orezanie, kľúč a bbox pre build.
#
# Samostatný skript preto, že `build-map-region.yml` má strop 128 kB, nad
# ktorým ho GitHub ticho neprijme. `set -e` bez `-u` a bez `pipefail` je zámer:
# presne v tomto režime kód bežal, kým bol v YAMLe.
#
# Poradie: vezmi PBF (vlastná URL alebo rodičovský extrakt) → prečítaj z neho
# presnú hranicu regiónu (`region-poly.py`) a vyrež kraj podľa nej → voliteľne
# orež → vypíš `key`, `name`, `bbox`, `bboxkey`.
#
# Hranica sa číta z toho istého PBF, akým sa reže – je v OSM dátach, takže sa
# nedá spočítať skôr; preto je volanie tu a nie v YAMLe.
#
# Kraj sa reže z rodiča, hotový export kraja sa nepoužíva: nie je referenčne
# úplný a viacpolygónovú plochu presahujúcu do susedného kraja Planetiler
# zahodí celú (miznú celé CHKO a lesy). `-S types=multipolygon,boundary` je
# nutné – predvolený `smart` dopĺňa len `type=multipolygon`, kým CHKO je
# `type=boundary`.
set -e

T0=$(date +%s)
mkdir -p data
CUSTOM_URL="$OPT_CUSTOM_PBF_URL"

# keď PBF (už aj orezané) leží z predošlého behu, sťahovať netreba
CACHED=""
if [ -s data/region.osm.pbf ]; then
  CACHED=1
  echo "PBF z cache ✓ ($(du -h data/region.osm.pbf | cut -f1))"
fi

# `$2` je cieľový súbor: rodičovský extrakt sa sťahuje bokom
download() { # $1 = URL, $2 = súbor
  [ -n "$CACHED" ] && return 0
  echo "Skúšam: $1"
  curl -fL --retry 3 --retry-delay 5 -o "${2:-data/region.osm.pbf}" "$1"
}

need_osmium() {
  command -v osmium >/dev/null && return 0
  sudo apt-get update -qq && sudo apt-get install -y -qq osmium-tool
}

# `ogr2ogr` so SpatiaLite na pretnutie hranice so štátom; bez neho sa reže
# plnou geometriou relácie a trvá to dlhšie (povie to `::warning::`)
need_gdal() {
  command -v ogr2ogr >/dev/null && return 0
  sudo apt-get update -qq \
    && sudo apt-get install -y -qq gdal-bin libsqlite3-mod-spatialite
}

POLY="${REGION_POLY:-data/region.poly}"

# presná hranica regiónu do `$POLY` a `data/region.geojson` – jedna hranica
# pre osmium, Planetiler, vrstvy z DEM aj viewer
hranica_z() { # $1 = PBF, z ktorého sa hranica číta
  need_osmium
  need_gdal
  python3 workers/plan/region-poly.py --region="$KEY" --from-pbf="$1" \
    --out=data/region.geojson --poly-out="$POLY" \
    --summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
}

if [ -n "$CUSTOM_URL" ]; then
  # ----- vlastný región (Európa / svet) -----
  NAME="$OPT_CUSTOM_NAME"
  [ -n "$NAME" ] || NAME=$(basename "$CUSTOM_URL" .osm.pbf)
  KEY=$(echo "$NAME" | LC_ALL=C.UTF-8 iconv -f utf8 -t ascii//TRANSLIT | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/^_//;s/_*$//')
  download "$CUSTOM_URL" || { echo "::error::Nepodarilo sa stiahnuť $CUSTOM_URL"; exit 1; }

  BBOX="$OPT_CUSTOM_BBOX"
  if [ -z "$BBOX" ]; then
    need_osmium
    # žiadna rúra z `osmium`: `head -1` zavrie rúru pod stále píšucim
    # producentom a `pipefail` z EPIPE spraví pád
    BOXES=$(osmium fileinfo -g header.boxes data/region.osm.pbf)
    BBOX=$(head -1 <<<"$BOXES" | tr -d '() ')
  fi
  if [ -z "$BBOX" ]; then
    echo "::error::PBF nemá bbox v hlavičke – vyplň input custom_bbox (west,south,east,north)."
    exit 1
  fi
else
  # ----- prednastavený región z workers/data/regions.json -----
  KEY="$REGION"
  NAME=$(jq -r --arg r "$KEY" '.[$r].name' workers/data/regions.json)
  BBOX=$(jq -r --arg r "$KEY" '.[$r].bbox | join(",")' workers/data/regions.json)
  DIR=$(jq -r --arg r "$KEY" '.[$r].osmfr.dir' workers/data/regions.json)
  # rodič je kľúč iného regiónu v tom istom číselníku, nie druhá URL
  PARENT=$(jq -r --arg r "$KEY" '.[$r].osmfr.parent // ""' workers/data/regions.json)
  if [ "$NAME" = "null" ]; then echo "::error::Neznámy región: $KEY"; exit 1; fi

  # osm.fr mená svojich súborov občas prehodí; berie sa prvý existujúci
  slugs() { jq -r --arg r "$1" '.[$r].osmfr.slugs[]' workers/data/regions.json; }

  if [ -z "$PARENT" ]; then
    # ----- región bez rodiča (Slovensko ako celok) – hotový export -----
    OK=""
    for SLUG in $(slugs "$KEY"); do
      if download "$OSMFR_BASE/$DIR/$SLUG.osm.pbf"; then OK=1; break; fi
    done
    if [ -z "$OK" ]; then
      echo "::error::PBF pre '$KEY' sa nepodarilo stiahnuť. Obsah $OSMFR_BASE/$DIR/ (uprav slugs vo workers/data/regions.json):"
      curl -sL "$OSMFR_BASE/$DIR/" | grep -oE 'href="[^"]+\.osm\.pbf"' | sort -u || true
      echo "…alebo vyplň custom_pbf_url s priamou URL na .osm.pbf."
      exit 1
    fi
    # hotový export z osm.fr je okolo štátnej hranice rozšírený, takže je
    # v ňom pás cudziny; reže sa rovnako ako kraj, len `admin_level=2`
    if [ -z "$CACHED" ]; then
      hranica_z data/region.osm.pbf
      if [ ! -s "$POLY" ]; then
        echo "::error::Hranica regiónu ($POLY) nie je – bez nej by mapa „$NAME“ niesla pás cudziny za štátnou hranicou a nikto by to z behu nezistil. Robí ju workers/plan/region-poly.py z relácie `boundary=administrative` v stiahnutom PBF; keď hranicu nenašla, povedala prečo o riadok vyššie."
        exit 1
      fi
      need_osmium
      # plán s odhadom: rez celého štátu je drahší než rez kraja, bboxový
      # predfilter tu nezahodí nič
      echo "Režem $NAME presne na štátnu hranicu ($POLY) – pri celom štáte sú to jednotky až desiatky minút."
      TCUT=$(date +%s)
      if ! osmium extract --overwrite -s smart -S types=multipolygon,boundary \
           --polygon "$POLY" -o data/region-cut.osm.pbf data/region.osm.pbf; then
        echo "::error::Rez na štátnu hranicu zlyhal. Skús beh zopakovať; keď padá stále, pozri sa, či je $POLY platný \`.poly\` (workers/plan/region-poly.py)."
        exit 1
      fi
      mv data/region-cut.osm.pbf data/region.osm.pbf
      echo "Vyrezané za $(( $(date +%s) - TCUT )) s → $(du -h data/region.osm.pbf | cut -f1)"
    fi
  elif [ -z "$CACHED" ]; then
    # ----- kraj: rez z rodiča (prečo, hovorí hlavička súboru) -----
    PDIR=$(jq -r --arg r "$PARENT" '.[$r].osmfr.dir' workers/data/regions.json)
    PNAME=$(jq -r --arg r "$PARENT" '.[$r].name' workers/data/regions.json)
    if [ "$PDIR" = "null" ]; then
      echo "::error::Región '$KEY' má \`osmfr.parent: $PARENT\`, ale taký región v workers/data/regions.json nie je (alebo nemá \`osmfr.dir\`). Oprav číselník."
      exit 1
    fi

    need_osmium
    # plán s odhadom pred drahou časťou – hodina ticha v logu sa nedá odlíšiť
    # od zaseknutého behu
    echo "Kraj sa reže z rodiča – $PNAME (~373 MB, potom rez ~1 min)."
    echo "  dôvod: hotový export kraja nemá členov plôch, čo presahujú do susedného kraja (CHKO, veľké lesy), a Planetiler ich zahodí celé"
    OK=""
    for SLUG in $(slugs "$PARENT"); do
      if download "$OSMFR_BASE/$PDIR/$SLUG.osm.pbf" data/parent.osm.pbf; then OK=1; break; fi
    done
    if [ -z "$OK" ]; then
      echo "::error::Rodičovský extrakt '$PARENT' sa nepodarilo stiahnuť. Obsah $OSMFR_BASE/$PDIR/ (uprav slugs vo workers/data/regions.json):"
      curl -sL "$OSMFR_BASE/$PDIR/" | grep -oE 'href="[^"]+\.osm\.pbf"' | sort -u || true
      exit 1
    fi
    # presná hranica kraja z rodiča, teda z tých istých dát, akými sa reže
    hranica_z data/parent.osm.pbf

    # hranica musí byť, inak sa nereže nič. Návrat na priame sťahovanie kraja
    # bol tichý omyl: beh zelený a v mape zase chýbali CHKO.
    if [ ! -s "$POLY" ]; then
      echo "::error::Hranica regiónu ($POLY) nie je, takže sa kraj nemá z čoho vyrezať – a hotový export kraja sa nepoužíva (chýbali by v ňom plochy presahujúce do susedného kraja). Robí ju workers/plan/region-poly.py z relácie `boundary=administrative` v rodičovskom extrakte (náhrada je `.poly` z osm.fr); keď zlyhalo oboje, povedala prečo o riadok vyššie – skús beh zopakovať."
      exit 1
    fi

    echo "Rodič stiahnutý ($(du -h data/parent.osm.pbf | cut -f1)), režem $NAME podľa $POLY …"

    # `-s smart` = celé cesty a doplnení členovia relácií, teda presne to, čo
    # hotovému exportu chýba; `-S types=…` kvôli `type=boundary` (CHKO)
    TCUT=$(date +%s)
    if ! osmium extract --overwrite -s smart -S types=multipolygon,boundary \
         --polygon "$POLY" -o data/region.osm.pbf data/parent.osm.pbf; then
      echo "::error::Rez kraja z rodičovského extraktu zlyhal. Skús beh zopakovať; keď padá stále, pozri sa, či je $POLY platný \`.poly\` (workers/plan/region-poly.py)."
      exit 1
    fi
    # 373 MB preč hneď: PBF si o kus ďalej ešte pýta miesto na orez testu
    rm -f data/parent.osm.pbf
    echo "Vyrezané za $(( $(date +%s) - TCUT )) s → $(du -h data/region.osm.pbf | cut -f1)"
  fi

  # hranicu pri PBF z cache: cache drží PBF, nie hranicu, a potrebujú ju aj
  # joby, ktoré nerežú nič. Číta sa z toho istého PBF – druhé sťahovanie rodiča
  # by bolo 373 MB za niečo, čo už na disku je.
  if [ ! -s "$POLY" ]; then
    hranica_z data/region.osm.pbf
  fi
fi

# ----- voliteľné orezanie na menšie územie -----
# Orezáva PBF, teda samotnú mapu; dá sa použiť spolu s testom (`crop_bbox`
# oreže mapu a test z nej vyberie štvorec).
CROP="$OPT_CROP_BBOX"
if [ -n "$CROP" ]; then
  if [ -z "$CACHED" ]; then
    need_osmium
    echo "Orezávam na bbox $CROP …"
    if ! osmium extract --overwrite -b "$CROP" -s smart \
         -S types=multipolygon,boundary \
         -o data/region-crop.osm.pbf data/region.osm.pbf; then
      echo "::error::Orezanie na bbox '$CROP' zlyhalo – očakávaný formát je west,south,east,north (napr. 18.98,49.18,19.20,49.28)."
      exit 1
    fi
    mv data/region-crop.osm.pbf data/region.osm.pbf
  fi
  BBOX="$CROP"
  KEY="${KEY}_crop"
  NAME="$NAME (výrez)"
fi

# rýchly test zmenšuje celý beh na štvorec zo stredu výrezu – aj samotnú mapu,
# nie len vrstvy z výškového modelu. Orez je ten istý `osmium extract`, aký robí
# `crop_bbox`, takže `bbox` behu sa rovná `dem_bbox`.
# Celý kraj s terénom len na štvorci sa dá dostať cez prázdny `crop_bbox`,
# odškrtnutý `test` a `area` na pohorie.
TEST_KM2="$OPT_TEST_KM2"
# okno pre vrstvy z výškového modelu. `pad_bbox` ho zväčšuje o `BORDER_BUFFER_M`,
# čo je dnes 0 – režeme presne na hranicu. Volanie ostáva preto, že keby sa
# presah zase zapol, okno sa musí zväčšiť spolu s ním.
DEM_BBOX=$(python3 - "$BBOX" <<'PY'
import sys
sys.path.insert(0, "workers/plan")
from area import pad_bbox, BORDER_BUFFER_M
w, s, e, n = pad_bbox([float(v) for v in sys.argv[1].split(",")], BORDER_BUFFER_M)
print(f"{w},{s},{e},{n}")
PY
)
if [ "${TEST_KM2:-0}" != "0" ]; then
  AREA="$AREA_IN"
  AREA_BBOX="$OPT_AREA_BBOX"
  [ -n "$AREA_BBOX" ] && AREA="$AREA_BBOX"
  RES=$(python3 workers/plan/area.py \
    --region-bbox="$BBOX" --area="$AREA" \
    --test-km2="$TEST_KM2" \
    --test-at="$OPT_TEST_AT")
  DEM_BBOX=$(printf '%s\n' "$RES" | sed -n 's/^bbox=//p')
  [ -n "$DEM_BBOX" ] || { echo "::error::Testovací štvorec sa nepodarilo spočítať."; exit 1; }
  # okolie pre obrázok „kde to je" je celý výrez pred zmenšením – z mapy
  # Slovenska by bol štvorec so 4 km² neviditeľný bod
  printf '%s\n' "$RES" | sed -n 's/^full_bbox=/full_bbox=/p' >> "$GITHUB_OUTPUT"
  echo "test_bbox=$DEM_BBOX" >> "$GITHUB_OUTPUT"
  # a odlož celú odpoveď pre krok „Vyrieš testovací výrez": je v nej aj kľúč
  # s príponou `_test4`, ktorý mu druhým výpočtom vyjsť nemôže
  printf '%s\n' "$RES" > /tmp/vyrez.txt
  # kľúč ide do mien cache aj uložených výsledkov – testovací beh sa nesmie
  # tváriť ako ostrý. `-s smart -S types=…` je tu z toho istého dôvodu ako pri
  # reze z rodiča, len sa prejaví skôr: zo štvorca so 4 km² vytŕča skoro každá
  # plocha.
  if [ -z "$CACHED" ]; then
    need_osmium
    echo "Orezávam MAPU na testovací štvorec $DEM_BBOX …"
    if ! osmium extract --overwrite -b "$DEM_BBOX" -s smart \
         -S types=multipolygon,boundary \
         -o data/region-test.osm.pbf data/region.osm.pbf; then
      echo "::error::Orez mapy na testovací štvorec ($DEM_BBOX) zlyhal. Skús beh bez switchu \`test\`, alebo iný stred cez \`options: test_at=lon,lat\`."
      exit 1
    fi
    mv data/region-test.osm.pbf data/region.osm.pbf
  fi
  # mapa je odteraz ten štvorec, takže `bbox` behu je on; `full_bbox` ostáva
  # celý výrez kvôli obrázku „kde to je"
  BBOX="$DEM_BBOX"
  KEY="${KEY}_test${TEST_KM2}"
  NAME="$NAME – test ${TEST_KM2} km²"
  echo "Testovací režim: celý beh (mapa aj terén) na $TEST_KM2 km² → $DEM_BBOX"
fi

# čo z toho PBF vypadne, musí byť vidieť: plocha bez všetkých členov sa
# nezmenší, Planetiler ju zahodí celú a build je pri tom zelený
if command -v osmium >/dev/null; then
  python3 workers/plan/pbf-areas.py data/region.osm.pbf \
    --summary="${GITHUB_STEP_SUMMARY:-/dev/null}" || true
fi

echo "key=$KEY"   >> "$GITHUB_OUTPUT"
echo "name=$NAME" >> "$GITHUB_OUTPUT"
echo "bbox=$BBOX" >> "$GITHUB_OUTPUT"
echo "dem_bbox=$DEM_BBOX" >> "$GITHUB_OUTPUT"
# bezpečná podoba bboxu do kľúča cache. Z `dem_bbox`, lebo ho používajú len
# cache vrstevníc, skál a tieňovania – tie sa pri teste počítajú na štvorci
echo "dem_bboxkey=$(echo "$DEM_BBOX" | tr ',.-' '___')" >> "$GITHUB_OUTPUT"
echo "Región: $NAME (key=$KEY, bbox=$BBOX)"
ls -lh data/region.osm.pbf
printf '%s\t%s\t%s\t%s\n' "10" "PBF regiónu" "$(( $(date +%s) - T0 ))" \
  "$NAME, $(du -h data/region.osm.pbf | cut -f1)$([ -n "$CACHED" ] && echo ' (z cache)')" \
  >> steps-out/plan.tsv
