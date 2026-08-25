#!/usr/bin/env bash
# Základná mapa sveta → `_site` (dlaždice, štýly, glyfy, manifest).
#
# PREČO SAMOSTATNÝ SKRIPT A NIE `run:` VO WORKFLOWE: súbor s workflowom má
# strop 128 KiB a nad ním ho GitHub ticho NEPRIJME (pravidlo 3 v CLAUDE.md).
# Bokom od toho sa to takto dá spustiť lokálne a nie „pushni a pozri sa".
#
# ČO ROBÍ, V PORADÍ:
#   0. podoba          `workers/world/variant.py` → schéma, zdroje, meno, strop
#   1. nástroje (GDAL kvôli vodným plochám, Planetiler)
#   2. podklady        `workers/world/sources.py` → data/world/
#   3. dlaždice        Planetiler nad orezanou schémou z kroku 0
#   4. glyfy a štýly   `workers/assets/glyphs.sh`, `workers/world/style.mjs`
#   5. manifest        čo v tejto mape je – jediný súbor, z ktorého to appka
#                      aj `workers/deploy/publish-map.py` zistia
#
# Hodnoty z prostredia (viď job „Mapa sveta" vo `world-map.yml`):
#   OPT_VARIANT OPT_MAXZOOM OPT_LIMIT_MB GLYPHS_ZIP
# Bbox, ľudské meno ANI KĽÚČ REGIÓNU sa nepodávajú: kľúč vyjde z podoby
# (`plna` → `svet`, `basic` → `svet_basic`) a meno s bboxom z
# `workers/data/regions.json`. Druhá kópia by sa raz rozišla (pravidlo 1).
set -euo pipefail

T_CELKOM=$(date +%s)
mkdir -p _site/tiles _site/styles data/world steps-out

# ---------- 0. podoba ----------
# ČO SA VLASTNE IDE STAVAŤ – a je to vidieť PRED prácou, nie podľa toho, čo
# vypadne (pravidlo 4). Podoba rozhoduje o vrstvách, o tom, ktoré podklady sa
# vôbec sťahujú, o mene balíka a o strope veľkosti; číselník je
# `workers/data/world-variants.json`.
VARIANT="${OPT_VARIANT:-plna}"
# Obe vypadnú do `data/world/`, nie do koreňa repozitára: skript sa má dať
# spustiť lokálne (CLAUDE.md, „Než niečo pushneš") a po takom behu nemajú
# v `git status` pribudnúť súbory, ktoré tam nepatria.
SCHEMA=data/world/schema.yml
python3 workers/world/variant.py --variant="$VARIANT" \
  --schema-out="$SCHEMA" --out=data/world/variant.json
REGION=$(jq -r '.region' data/world/variant.json)
SOURCES=$(jq -r '.sources | join(",")' data/world/variant.json)
MAP_LAYERS=$(jq -r '.map_layers' data/world/variant.json)
VARIANT_LIMIT=$(jq -r '.limit_mb' data/world/variant.json)
GLYPHS_MODE=$(jq -r '.glyphs' data/world/variant.json)
NAME=$(jq -r --arg r "$REGION" '.[$r].name // ""' workers/data/regions.json)
BBOX=$(jq -r --arg r "$REGION" '.[$r].bbox // [] | join(",")' workers/data/regions.json)
if [ -z "$NAME" ] || [ -z "$BBOX" ]; then
  echo "::error::Región '$REGION' nie je vo workers/data/regions.json (alebo nemá meno a bbox). Kľúč si berie podoba z `workers/data/world-variants.json` – keď tam pribudla nová, dopíš jej región aj do regions.json."
  exit 1
fi

# Planetiler vie dlaždice najviac po zoom 16; svet ich toľko nepotrebuje ani
# omylom – pri z8 má vodstvo stovky MB a mapa je stále len podklad pod výber
# regiónu. Preto je strop 8 a dno 3.
Z="$OPT_MAXZOOM"
case "$Z" in ''|*[!0-9]*) Z=6 ;; esac
if [ "$Z" -gt 8 ]; then
  echo "::warning::maxzoom $Z je na mapu sveta priveľa (vodstvo rastie zhruba 3× na úroveň a mapa je len podklad pod výber regiónu). Používam 8."
  Z=8
fi
if [ "$Z" -lt 3 ]; then Z=3; fi

# `auto` = strop podľa podoby (plná 250 MB, basic 15 MB). Číslo vo formulári
# ho prebije. Bez `auto` by basic dedil strop plnej mapy a 15 MB by nikto
# nestrážil – rozpočet je pritom to, čo tú podobu vôbec definuje.
LIMIT_MB="${OPT_LIMIT_MB:-auto}"
case "$LIMIT_MB" in ''|auto) LIMIT_MB="$VARIANT_LIMIT" ;; esac
case "$LIMIT_MB" in *[!0-9]*) LIMIT_MB="$VARIANT_LIMIT" ;; esac

echo "Mapa sveta: $NAME ($BBOX), podoba $VARIANT, maxzoom $Z, strop veľkosti ${LIMIT_MB} MB"

# ---------- 1. nástroje ----------
# GDAL kvôli `ogr2ogr` – vodné plochy z OSM sú shapefile v EPSG:3857 a treba
# ich premietnuť (rozpis vo `workers/world/sources.py`).
T0=$(date +%s)
# GDAL je tu KVÔLI VODE. Keď ju podoba nemá (basic), nemá sa čo inštalovať –
# je to ~1 min a 200 MB za nástroj, ktorý v tom behu nikto nezavolá.
if [ "${SOURCES#*water}" != "$SOURCES" ] && ! command -v ogr2ogr >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq gdal-bin
fi
workers/lib/planetiler.sh
echo "Nástroje hotové za $(( $(date +%s) - T0 )) s"

# ---------- 2. podklady ----------
# Sťahovanie z cudzích serverov a prevod. Skript si píše vlastný plán
# s odhadom aj postup – hodina ticha v logu sa nedá odlíšiť od zaseknutia.
T_SRC=$(date +%s)
echo "::group::Podklady ($SOURCES)"
# LEN TO, ČO SCHÉMA PODOBY NAOZAJ ČÍTA. Zoznam nie je napísaný tu, ale vyšiel
# zo `sources:` orezanej schémy – pri `basic` tak odpadne 60 MB vodných
# polygónov aj ich prevod, a nedá sa stať, že by sa zoznamy rozišli.
python3 workers/world/sources.py --out=data/world --only="$SOURCES"
echo "::endgroup::"
echo "Podklady: $(du -sh data/world | cut -f1) za $(( $(date +%s) - T_SRC )) s"

# ---------- 3. dlaždice ----------
# ČO MÁ V SCHÉME VYŠŠÍ `min_zoom`, NEŽ JE MAXZOOM ARCHÍVU, PLANETILER ZAHODÍ –
# a nepovie o tom nič. Presne to raz zmazalo z mapy všetky ploty (rozpis
# v `workers/features/features.yml`), tak sa to tu porovná vopred.
NAJVYSSI=$(python3 -c "
import yaml
d = yaml.safe_load(open('data/world/schema.yml'))
print(max((f.get('min_zoom', 0) for l in d['layers'] for f in l['features']),
          default=0))
")
if [ "$NAJVYSSI" -gt "$Z" ]; then
  echo "::warning::Schéma má prvky až od zoomu $NAJVYSSI, ale dlaždice sa robia po $Z – tie prvky (najmä výseky regiónov sťahovania) v mape NEBUDÚ. Zdvihni maxzoom na $NAJVYSSI, alebo to ber ako zámer."
fi

T_PM=$(date +%s)
OUT="_site/tiles/${REGION}.pmtiles"
echo "::group::Planetiler – mapa sveta ($VARIANT), maxzoom $Z"
# `--simplify_tolerance` a `--min_feature_size` sa NECHÁVAJÚ NA PREDVOLENÝCH
# HODNOTÁCH – naopak než pri vrstevniciach, kde sa vypínajú. Tam ide o presný
# tvar terénu, tu o prehľad sveta: neusporiadané ostrovčeky veľkosti pixela
# nikto neuvidí a zaplatí sa za ne miestom v balíku.
java -Xmx4g -jar planetiler.jar generate-custom \
  --schema="$SCHEMA" \
  --output="$OUT" \
  --minzoom=0 --maxzoom="$Z" --render_maxzoom="$Z" \
  --force
echo "::endgroup::"

MB=$(( $(stat -c%s "$OUT") / 1048576 ))
echo "Dlaždice: $(du -h "$OUT" | cut -f1) (${MB} MB) za $(( $(date +%s) - T_PM )) s"
if [ "$MB" -gt "$LIMIT_MB" ]; then
  echo "::warning::Dlaždice majú ${MB} MB, čo je nad stropom ${LIMIT_MB} MB podoby $VARIANT. Zníž maxzoom (teraz $Z) – vodstvo rastie zhruba 3× na úroveň – prepni na podobu `basic` (bez vodstva a jazier), alebo zdvihni input `limit_mb`, ak je taký balík v poriadku."
fi

# ---------- 4. glyfy a štýly ----------
# Glyfy sťahuje TEN ISTÝ skript ako pri mape kraja: „ako sa dostanú fonty do
# `_site`" je jedna otázka a dve kópie by sa raz rozišli.
#
# DO BALÍKA UŽ NEJDÚ. `publish-map.py` ich nebalí nikam – appka si tri orezané
# stacky nesie v sebe (`skifahrer/rikimaps`, `GlyphStore`) a `glyphs` si pri
# načítaní prepíše na ne. Kroky nižšie teda tvarujú už len `_site`, teda to, čo
# uvidí lokálny náhľad; na veľkosť balíka nemajú vplyv. Nechávajú sa preto, že
# `_site` má hovoriť pravdu o tom, z čoho sa mapa skladá – nie preto, že by
# ešte niečo šetrili.
T_A=$(date +%s)
workers/assets/glyphs.sh
# KURZÍVA IDE PREČ. Štýl sveta má popisky len v dvoch rezoch (`Noto Sans
# Regular` a `Bold`, viď `workers/world/style.mjs`), tak sa tretí nebalí.
# Mapa kraja si berie všetky tri – tam kurzívu používajú vodné toky
# a geografické názvy.
#
# Kedysi to bola najväčšia položka balíka: stack bol celý unicode (~34 MB),
# tri teda 102 MB. Odkedy `glyphs.sh` reže rozsahy sám, je stack ~1,2 MB
# a tento riadok šetrí toľko – robí sa ďalej, lebo nebaliť rez, ktorý štýl
# nepoužíva, je správne aj keď je lacný.
rm -rf "_site/fonts/Noto Sans Italic"
# A PRI `basic` IDE PREČ AJ VÄČŠINA ZVYŠKU. `glyphs.sh` necháva latinku,
# gréčtinu, cyriliku a interpunkciu (~2,4 MB v dvoch stackoch), lebo pri mape
# kraja nevie, aké mená v nej budú. Tu sa to VIE: mená štátov a regiónov
# sťahovania sú v podkladoch, a tie padnú do jediného rozsahu 0–255. Rozsahy
# sa preto MERAJÚ, nie hádajú (rozpis vo `workers/world/glyphs.py`) – bez toho
# sa `basic` do svojich 15 MB zmestí, ale zbytočne tesnejšie.
if [ "$GLYPHS_MODE" = 'podla_dat' ]; then
  python3 workers/world/glyphs.py --fonts=_site/fonts --data=data/world
fi
node workers/world/style.mjs --out=_site/styles --region="$REGION" \
  --variant="$VARIANT" --maxzoom="$Z"
echo "Glyfy ($(du -sh _site/fonts 2>/dev/null | cut -f1)) a štýly za $(( $(date +%s) - T_A )) s"

# ---------- 5. manifest ----------
# JEDINÝ SÚBOR, Z KTORÉHO SA DÁ ZISTIŤ, ČO V TEJTO MAPE JE: číta ho appka aj
# `workers/deploy/publish-map.py` (a cez neho sa z neho skladá položka
# v `maps.json` – bbox, maxzoom a cesta k dlaždiciam). Tvar je ten istý ako
# pri mape kraja (`workers/deploy/site.sh`), lebo ho číta ten istý kód; polia
# o vrstvách, ktoré svet nemá (vrstevnice, skaly, terén), v ňom jednoducho
# nie sú – prázdna hodnota by znamenala „vrstva je, len je prázdna".
# Ktorá téma je v ktorom súbore. Kľúč je téma (`svetla`, `tmava`, …), hodnota
# cesta v balíku – appka tak nemusí mená štýlov skladať a uhádnuť.
STYLY=$(find _site/styles -name '*.json' -printf '%f\n' | sort \
  | jq -R -s --arg r "$REGION" \
      'split("\n") | map(select(length > 0))
       | map({key: (sub("^\($r)-"; "") | sub("\\.json$"; "")),
              value: ("styles/" + .)}) | from_entries')
jq -n \
  --arg region "$REGION" \
  --arg name "$NAME" \
  --arg bbox "$BBOX" \
  --arg built "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg variant "$VARIANT" \
  --arg layers "$MAP_LAYERS" \
  --argjson maxzoom "$Z" \
  --argjson size_mb "$MB" \
  --argjson styles "$STYLY" \
  '{
    default_region: $region,
    kind: "svet",
    # Ktorá podoba – bez toho sa z rozbaleného balíka nedá zistiť, či v ňom
    # more chýba preto, že je to `basic`, alebo preto, že sa build pokazil.
    variant: $variant,
    layers: ($layers | split(",") | map(select(length > 0))),
    built_at: $built,
    maxzoom: $maxzoom,
    # GLYFY V BALÍKU NIE SÚ – appka si ich nesie v sebe (`skifahrer/rikimaps`,
    # `GlyphStore`) a `publish-map.py` ich preto nebalí ani sem. Adresa tu je
    # pre toho, kto appka nie je: rozbalený balík vo webovom vieweri. Tá istá
    # verejná služba, na akú siaha `site.sh` aj `styles/build.mjs` bez lokálnych
    # glyfov – a tá istá, akú si píše `workers/world/style.mjs`, lebo je to to
    # isté tvrdenie a dve kópie by sa raz rozišli.
    glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
    styles: $styles,
    default_style: ("styles/" + $region + "-svetla.json"),
    attribution: "© OpenStreetMap prispievatelia, Geofabrik, Natural Earth",
    regions: {
      ($region): {
        name: $name,
        bbox: ($bbox | split(",") | map(tonumber)),
        pmtiles: ("tiles/" + $region + ".pmtiles"),
        maxzoom: $maxzoom,
        size_mb: $size_mb
      }
    }
  }' > _site/tiles/manifest.json
cat _site/tiles/manifest.json

echo "maxzoom=$Z" >> "$GITHUB_OUTPUT"
echo "size_mb=$MB" >> "$GITHUB_OUTPUT"
echo "name=$NAME" >> "$GITHUB_OUTPUT"
# Kľúč regiónu a zoznam vrstiev do katalógu vypadli z podoby, takže ich pozná
# len tento krok. Ide to VÝSTUPOM, nie druhým prepisom vo workflowe: to isté
# potrebuje aj job, čo dobalí `.aar` (položku katalógu prepisuje navrch), a dve
# miesta s tou istou hodnotou sa raz rozídu.
echo "variant=$VARIANT" >> "$GITHUB_OUTPUT"
echo "region_key=$REGION" >> "$GITHUB_OUTPUT"
echo "map_layers=$MAP_LAYERS" >> "$GITHUB_OUTPUT"
du -sh _site
printf '%s\t%s\t%s\t%s\n' "10" "Mapa sveta" "$(( $(date +%s) - T_CELKOM ))" \
  "$VARIANT, maxzoom $Z, ${MB} MB" >> steps-out/world.tsv
