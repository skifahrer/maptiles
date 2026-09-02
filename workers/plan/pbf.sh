#!/usr/bin/env bash
# PBF regiónu na disk – stiahnutie, prípadné orezanie, kľúč a bbox pre build.
#
# PREČO SAMOSTATNÝ SKRIPT A NIE `run:` V WORKFLOWE: `build-map.yml` má strop
# 128 kB, nad ktorým ho GitHub NEPRIJME – a nepovie to; po pushi len vyrobí beh
# bez jobov s červeným krížikom a prázdnym logom. Toto bol jeho najväčší `run:`
# blok (128 riadkov). Bokom od toho je to aj tak správnejšie: takto sa dá
# spustiť lokálne a nie „pushni a pozri sa, čo z toho vyšlo".
#
# `set -e` BEZ `-u` A BEZ `pipefail` je zámer, nie nedbalosť: presne v tomto
# režime tento kód bežal, kým bol v YAMLe (predvolený shell kroku je
# `bash -e {0}`), a presun do súboru to nemá meniť. Sťahovanie skúša viac ciest
# a spolieha sa, že neúspešná vetva len vráti nenulový kód.
#
# ČO ROBÍ, V PORADÍ:
#   1. vezme PBF – z vlastnej URL, alebo si kraj VYREŽE z rodičovského
#      extraktu (`osmfr.parent`); keď už leží z cache, nesťahuje sa
#   2. voliteľne ho oreže – `crop_bbox`, alebo štvorec rýchleho testu
#   3. vypíše `key`, `name`, `bbox`, `bboxkey` do $GITHUB_OUTPUT
#
# ═══ KRAJ SA REŽE Z RODIČA, HOTOVÝ EXPORT KRAJA SA NEPOUŽÍVA ═══
#
# osm.fr má pre každý kraj vlastný `{kraj}-latest.osm.pbf` (36 MB) a chvíľu sa
# sťahoval priamo – bolo to o krok kratšie a o 337 MB lacnejšie než Slovensko.
# Lenže ten súbor NIE JE REFERENČNE ÚPLNÝ: viacpolygónová plocha, ktorá
# pokračuje do susedného kraja, v ňom nemá všetkých členov, a Planetiler taký
# objekt ZAHODÍ CELÝ – teda aj tú polovicu, ktorá v kraji leží. Nie je to
# kozmetika na hranici; v mape zmizli celé CHKO a celé lesy uprostred kraja.
#
# Namerané na `bratislavsky-latest.osm.pbf` (osmium check-refs: 92 953 ciest,
# na ktoré sa relácie odkazujú, v súbore nie je). Z 3075 plošných relácií malo
# 250 chýbajúceho člena, z toho 49 krajinnej pokrývky a ochrany prírody:
#
#     r4163631   CHKO Malé Karpaty        chýba  6/17 členov
#     r7017139   CHKO Záhorie             chýba  7/38
#     r4610709   CHKO Dunajské luhy       chýba  3/5
#     r20142854  Aluvium Moravy (NPR)     chýba  4/18
#     r1270451   les Záhoria (bez mena)   chýba 187/1011
#     r3062407   Zdrž Hrušov (vodstvo)    chýba 10/68
#
# Po reze z rodiča (`slovakia-latest`, 373 MB) ostane z tých 49 päť – a všetky
# sú na rakúskej hranici pozdĺž Dunaja a Moravy (Nationalpark Donau-Auen,
# Dunaj), takže ich členovia nie sú v Slovensku vôbec a doplniť by ich vedel až
# extrakt Európy. Tie masku naozaj nepresiahnu; tie hore áno.
#
# `-S types=multipolygon,boundary` NIE JE OZDOBA. Predvolene `smart` dopĺňa
# členov len reláciám `type=multipolygon`, kým CHKO je `type=boundary` – bez
# toho prepínača ostali všetky tri CHKO rozbité aj po reze z rodiča (namerané:
# 9 zvyšných plôch namiesto 5).
#
# CENA (namerané, Bratislavský kraj): +337 MB sťahovania a 29 s rezania.
# Výstup má 37 MB proti 36 MB hotového exportu, čas buildu sa nemení.
# Pravidlo 7 („nesťahuj viac, než treba") tým porušené nie je – toto sťahovanie
# TREBA, lebo bez neho v mape chýbajú plochy, ktoré v nej majú byť.
#
# PREČO RODIČ A NIE SUSEDNÉ KRAJE: CHKO Malé Karpaty leží v troch krajoch,
# takže by k tomu musel byť číselník susedov – a keď v ňom raz jeden chýba,
# plocha ticho zmizne presne ako teraz. Jeden rodič je jedna odpoveď (pravidlo 1).
set -e

T0=$(date +%s)
mkdir -p data
CUSTOM_URL="$OPT_CUSTOM_PBF_URL"

# Cache: keď PBF (už aj orezané) leží z predošlého behu, sťahovať netreba –
# kľúč nesie región, orez aj dátum.
CACHED=""
if [ -s data/region.osm.pbf ]; then
  CACHED=1
  echo "PBF z cache ✓ ($(du -h data/region.osm.pbf | cut -f1))"
fi

# `$2` je cieľový súbor (default samotné PBF regiónu): rodičovský extrakt sa
# sťahuje bokom a až rez z neho je `data/region.osm.pbf`.
download() { # $1 = URL, $2 = súbor
  [ -n "$CACHED" ] && return 0
  echo "Skúšam: $1"
  curl -fL --retry 3 --retry-delay 5 -o "${2:-data/region.osm.pbf}" "$1"
}

need_osmium() {
  command -v osmium >/dev/null && return 0
  sudo apt-get update -qq && sudo apt-get install -y -qq osmium-tool
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
    # ŽIADNA RÚRA Z `osmium`: `head -1` (aj `sed …q`) zavrie rúru pod stále
    # píšucim producentom, ten dostane EPIPE a `pipefail` zhodí priradenie.
    # Výstup ide najprv do premennej, prvý riadok sa berie až z nej.
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
  # Rodič je KĽÚČ INÉHO REGIÓNU v tom istom číselníku, nie druhá URL – adresa
  # Slovenska je zapísaná raz, pri `slovensko` (pravidlo 1).
  PARENT=$(jq -r --arg r "$KEY" '.[$r].osmfr.parent // ""' workers/data/regions.json)
  if [ "$NAME" = "null" ]; then echo "::error::Neznámy región: $KEY"; exit 1; fi

  # `slugs` je zoznam kandidátov, lebo osm.fr mená svojich súborov občas
  # prehodí; berie sa prvý, ktorý existuje.
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
  elif [ -z "$CACHED" ]; then
    # ----- kraj: REZ Z RODIČA (prečo, hovorí hlavička súboru) -----
    PDIR=$(jq -r --arg r "$PARENT" '.[$r].osmfr.dir' workers/data/regions.json)
    PNAME=$(jq -r --arg r "$PARENT" '.[$r].name' workers/data/regions.json)
    if [ "$PDIR" = "null" ]; then
      echo "::error::Región '$KEY' má \`osmfr.parent: $PARENT\`, ale taký región v workers/data/regions.json nie je (alebo nemá \`osmfr.dir\`). Oprav číselník."
      exit 1
    fi

    # HRANICA MUSÍ BYŤ, INAK SA NEREŽE NIČ. Predošlá podoba tohto kroku mala
    # v tomto mieste NÁVRAT na priame sťahovanie kraja – a to je presne tichý
    # omyl (pravidlo 8): keď sa `.poly` nestiahol, beh bol zelený a v mape
    # zase chýbali CHKO. Radšej spadnúť tu, za pár sekúnd, s návodom.
    POLY="${REGION_POLY:-data/region.poly}"
    if [ ! -s "$POLY" ]; then
      echo "::error::Hranica regiónu ($POLY) nie je, takže sa kraj nemá z čoho vyrezať – a hotový export kraja sa nepoužíva (chýbali by v ňom plochy presahujúce do susedného kraja). Robí ju krok „Polygón kraja“ (workers/plan/region-poly.py) a musí bežať PRED týmto; keď spadol on, zopakuj beh."
      exit 1
    fi

    need_osmium
    # PLÁN S ODHADOM pred drahou časťou (pravidlo 4) – hodina ticha v logu sa
    # nedá odlíšiť od zaseknutého behu. Čísla sú namerané na Bratislavskom
    # kraji, viď hlavičku.
    echo "Kraj sa reže z rodiča – $PNAME (~373 MB, potom rez ~30 s)."
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
    echo "Rodič stiahnutý ($(du -h data/parent.osm.pbf | cut -f1)), režem $NAME podľa $POLY …"

    # `-s smart` = celé cesty a DOPLNENÍ ČLENOVIA relácií, teda presne to,
    # čo hotovému exportu chýba. `-S types=multipolygon,boundary` je nutné:
    # bez neho `smart` dopĺňa len `type=multipolygon` a CHKO (`type=boundary`)
    # ostanú rozbité – namerané, viď hlavičku.
    TCUT=$(date +%s)
    if ! osmium extract --overwrite -s smart -S types=multipolygon,boundary \
         --polygon "$POLY" -o data/region.osm.pbf data/parent.osm.pbf; then
      echo "::error::Rez kraja z rodičovského extraktu zlyhal. Skús beh zopakovať; keď padá stále, pozri sa, či je $POLY platný \`.poly\` (workers/plan/region-poly.py)."
      exit 1
    fi
    # 373 MB preč hneď, nie na konci jobu: runner má ~60 GB voľných a PBF si
    # o kus ďalej ešte pýta miesto na orez rýchleho testu.
    rm -f data/parent.osm.pbf
    echo "Vyrezané za $(( $(date +%s) - TCUT )) s → $(du -h data/region.osm.pbf | cut -f1)"
  fi
fi

# ----- voliteľné orezanie na menšie územie -----
# Menšie územie = výrazne menší .pmtiles, takže sa dá ísť na maxzoom 16.
# Toto orezáva PBF, čiže samotnú mapu – rovnako ako rýchly test o kus nižšie,
# len na zadaný obdĺžnik namiesto štvorca zo stredu výrezu. Dá sa použiť oboje
# naraz: `crop_bbox` oreže mapu a test z nej potom vyberie ten štvorec.
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

# RÝCHLY TEST (switch `test`, predvolene ODŠKRTNUTÝ, 4 km²) zmenšuje
# CELÝ BEH na štvorec zo stredu výrezu: vrstevnice, skaly a tieňovanie
# z výškového modelu (to naozaj drahé – na kraji desiatky minút, na
# 4 km² jednotky minút) a od zmeny v #172 aj SAMOTNÚ MAPU.
#
# Kým sa mapa nechávala celá, bol testovací beh polovičný: kraj sa
# stiahol, prehnal Planetilerom, zabalil a nahral v plnej veľkosti,
# takže sa okolo štvorca s pár km² terénu viezol celý kraj – dlaždice,
# trasy, prvky aj ZIP. Chcelo to štvorec vidieť „v mape, do ktorej
# patrí"; lenže na to je obrázok „kde to je" (workers/plan/test-map.py)
# a mapa sveta pod výberom, a nie štyridsať minút a stovky MB na to,
# aby sa dal pozrieť prah sklonu. Test má byť minimálny – teraz je.
#
# Orez je ten istý `osmium extract`, aký robí `crop_bbox` o kus vyššie,
# takže sa mapa aj vrstvy z DEM režú JEDNÝM spôsobom; `bbox` behu sa
# tým rovná `dem_bbox` a maska, dlaždice aj katalóg dostanú to isté
# územie. Celý kraj s terénom len na štvorci sa dá stále dostať –
# `crop_bbox` prázdny a switch `test` odškrtnutý plus `area` na pohorie.
TEST_KM2="$OPT_TEST_KM2"
# NAFÚKNUTÉ O PREKRYV SO SUSEDOM (`workers/plan/area.py::BORDER_BUFFER_M`) –
# TO ISTÉ ČÍSLO, o aké `region-poly.py` nafúkol `.poly`/`region.geojson`
# (rozpis tam: nezávisle zjednodušené hranice susedných krajov nechávajú
# medzi stiahnutými mapami medzeru 3 – 5 km). TIEŇOVANIE ČÍTA PRIAMO TOTO
# OKNO (je vždy na celý región, nie na `area`, viď input `shading_source`
# vyššie) – bez nafúknutia by `-cutline` v ňom vytŕčal z okna, ktoré ho má
# orezať, a nafúknutý pás by na hillshade nebol vidieť. Vrstevnice a skaly
# dostanú to isté nafúknutie cez `workers/plan/area.py` (`AREA_BBOX`, ten
# istý `pad_bbox`) o kus nižšie. Len `dem_bbox`, nie `bbox`: mapa (dlaždice,
# katalóg, rozpočet stránky) toto nafúknutie nepotrebuje o nič viac, než už
# má – kraj je aj bez neho len zlomok svojho obdĺžnika (rozpis vyššie).
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
  # Okolie pre obrázok „kde to je" je CELÝ výrez pred zmenšením
  # (napr. Vysoké Tatry), nie celý región – z mapy Slovenska by
  # bol štvorec so 4 km² neviditeľný bod.
  printf '%s\n' "$RES" | sed -n 's/^full_bbox=/full_bbox=/p' >> "$GITHUB_OUTPUT"
  echo "test_bbox=$DEM_BBOX" >> "$GITHUB_OUTPUT"
  # A ODLOŽ CELÚ ODPOVEĎ pre krok „Vyrieš testovací výrez": je v nej
  # už všetko, čo ten krok potrebuje – vrátane kľúča s príponou
  # `_test4`, ktorý mu druhým výpočtom vyjsť nemôže (prečo, hovorí
  # komentár v tom kroku). Rátať sa to má RAZ.
  printf '%s\n' "$RES" > /tmp/vyrez.txt
  # Kľúč ide do mien cache aj uložených výsledkov – testovací beh sa
  # nesmie tváriť ako ostrý a prepísať mu vrstevnice na celý kraj.
  # A TERAZ AJ MAPA. Bez tohto orezu je „rýchly test" rýchly len v terénnych
  # vrstvách, kým dlaždice, trasy, prvky a ZIP sa robia na celom kraji.
  # `-s smart -S types=multipolygon,boundary` je tu z toho istého dôvodu ako
  # pri reze z rodiča, len sa to prejaví oveľa skôr: zo štvorca s 4 km² vytŕča
  # skoro každá plocha, takže bez dopĺňania členov by v testovacej mape nebol
  # les ani chránené územie takmer nikde. Namerané na štvorci v Malých
  # Karpatoch: bez `-S types=` zmizli „Záhorie (vojenský obvod)" a „Turecký
  # vrch", s ním neostala ani jedna zahodená plocha.
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
  # Mapa je odteraz ten štvorec, takže `bbox` behu je on – ide do dlaždíc,
  # masky regiónu, rozpočtu stránky aj do katalógu. `full_bbox` vyššie ostáva
  # celý výrez, lebo obrázok „kde to je" potrebuje okolie.
  BBOX="$DEM_BBOX"
  KEY="${KEY}_test${TEST_KM2}"
  NAME="$NAME – test ${TEST_KM2} km²"
  echo "Testovací režim: celý beh (mapa aj terén) na $TEST_KM2 km² → $DEM_BBOX"
fi

# ČO Z TOHO PBF VYPADNE, MUSÍ BYŤ VIDIEŤ. Plocha bez všetkých členov sa
# nezmenší – Planetiler ju zahodí celú a build je pri tom zelený, takže je to
# presne ten druh chyby, na ktorý je pravidlo 8. Stojí to ~1 s (dve volania
# `osmium`), tak sa to počíta pri každom behu, nie na požiadanie.
if command -v osmium >/dev/null; then
  python3 workers/plan/pbf-areas.py data/region.osm.pbf \
    --summary="${GITHUB_STEP_SUMMARY:-/dev/null}" || true
fi

echo "key=$KEY"   >> "$GITHUB_OUTPUT"
echo "name=$NAME" >> "$GITHUB_OUTPUT"
echo "bbox=$BBOX" >> "$GITHUB_OUTPUT"
echo "dem_bbox=$DEM_BBOX" >> "$GITHUB_OUTPUT"
# bezpečná podoba bboxu do kľúča cache. Je z `dem_bbox`, lebo ho
# používajú len cache vrstevníc, skál a tieňovania – a tie sa pri
# teste počítajú na štvorci, takže si nesmú sadnúť na ostré.
echo "dem_bboxkey=$(echo "$DEM_BBOX" | tr ',.-' '___')" >> "$GITHUB_OUTPUT"
echo "Región: $NAME (key=$KEY, bbox=$BBOX)"
ls -lh data/region.osm.pbf
printf '%s\t%s\t%s\t%s\n' "10" "PBF regiónu" "$(( $(date +%s) - T0 ))" \
  "$NAME, $(du -h data/region.osm.pbf | cut -f1)$([ -n "$CACHED" ] && echo ' (z cache)')" \
  >> steps-out/plan.tsv
