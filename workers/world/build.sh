#!/usr/bin/env bash
# Základná mapa sveta → `_site` (dlaždice, štýly, glyfy, manifest).
#
# Vlastný skript, lebo workflow má strop 128 KiB – a takto sa dá spustiť lokálne.
#
# V poradí: podoba (`world/variant.py` → schéma, zdroje, meno, strop),
# nástroje, podklady (`world/sources.py`), dlaždice (Planetiler nad orezanou
# schémou), glyfy a štýly, manifest.
#
# Z prostredia: OPT_VARIANT OPT_MAXZOOM OPT_LIMIT_MB GLYPHS_ZIP. Bbox, meno ani
# kľúč regiónu sa nepodávajú – kľúč vyjde z podoby a zvyšok z `regions.json`.
set -euo pipefail

T_CELKOM=$(date +%s)
mkdir -p _site/tiles _site/styles data/world steps-out

# 0. podoba: čo sa ide stavať, a je to vidieť pred prácou. Rozhoduje
# o vrstvách, o sťahovaných podkladoch, o mene balíka aj o strope veľkosti.
VARIANT="${OPT_VARIANT:-plna}"
# obe vypadnú do `data/world/`, nie do koreňa: po lokálnom behu nemajú
# v `git status` pribudnúť súbory, ktoré tam nepatria
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

# Planetiler vie najviac z16; svet toľko nepotrebuje – pri z8 má vodstvo
# stovky MB a mapa je stále len podklad pod výber regiónu
Z="$OPT_MAXZOOM"
case "$Z" in ''|*[!0-9]*) Z=6 ;; esac
if [ "$Z" -gt 8 ]; then
  echo "::warning::maxzoom $Z je na mapu sveta priveľa (vodstvo rastie zhruba 3× na úroveň a mapa je len podklad pod výber regiónu). Používam 8."
  Z=8
fi
if [ "$Z" -lt 3 ]; then Z=3; fi

# `auto` = strop podľa podoby (plná 250 MB, basic 15 MB). Bez neho by basic
# dedil strop plnej mapy, hoci rozpočet je to, čo tú podobu definuje.
LIMIT_MB="${OPT_LIMIT_MB:-auto}"
case "$LIMIT_MB" in ''|auto) LIMIT_MB="$VARIANT_LIMIT" ;; esac
case "$LIMIT_MB" in *[!0-9]*) LIMIT_MB="$VARIANT_LIMIT" ;; esac

echo "Mapa sveta: $NAME ($BBOX), podoba $VARIANT, maxzoom $Z, strop veľkosti ${LIMIT_MB} MB"

# 1. nástroje
T0=$(date +%s)
# GDAL je tu kvôli vode – keď ju podoba nemá, nemá sa čo inštalovať
# (~1 min a 200 MB za nástroj, ktorý nikto nezavolá)
if [ "${SOURCES#*water}" != "$SOURCES" ] && ! command -v ogr2ogr >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq gdal-bin
fi
workers/lib/planetiler.sh
echo "Nástroje hotové za $(( $(date +%s) - T0 )) s"

# 2. podklady: sťahovanie z cudzích serverov a prevod. Skript si píše vlastný
# plán aj postup – hodina ticha sa nedá odlíšiť od zaseknutia.
T_SRC=$(date +%s)
echo "::group::Podklady ($SOURCES)"
# len to, čo schéma podoby naozaj číta: zoznam vyšiel zo `sources:` orezanej
# schémy, takže pri `basic` odpadne 60 MB vodných polygónov
python3 workers/world/sources.py --out=data/world --only="$SOURCES"
echo "::endgroup::"
echo "Podklady: $(du -sh data/world | cut -f1) za $(( $(date +%s) - T_SRC )) s"

# 3. dlaždice. Čo má v schéme vyšší `min_zoom` než maxzoom archívu, Planetiler
# zahodí a nepovie nič – raz to zmazalo z mapy všetky ploty.
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
# `--simplify_tolerance` a `--min_feature_size` ostávajú predvolené, naopak
# než pri vrstevniciach: tam ide o presný tvar terénu, tu o prehľad sveta
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

# 4. glyfy a štýly. Sťahuje ich ten istý skript ako pri mape kraja.
# Do balíka už nejdú – appka si tri orezané stacky nesie v sebe a `glyphs` si
# pri načítaní prepíše. Kroky nižšie tvarujú už len `_site`, ktorý má hovoriť
# pravdu o tom, z čoho sa mapa skladá.
T_A=$(date +%s)
workers/assets/glyphs.sh
# kurzíva ide preč: štýl sveta má popisky len v dvoch rezoch. Kedysi to bola
# najväčšia položka balíka (stack celý unicode ~34 MB); odkedy `glyphs.sh`
# reže rozsahy sám, je stack ~1,2 MB.
rm -rf "_site/fonts/Noto Sans Italic"
# pri `basic` ide preč aj väčšina zvyšku. `glyphs.sh` necháva latinku,
# gréčtinu, cyriliku a interpunkciu, lebo pri mape kraja nevie, aké mená v nej
# budú – tu sa to vie a rozsahy sa merajú, nie hádajú.
if [ "$GLYPHS_MODE" = 'podla_dat' ]; then
  python3 workers/world/glyphs.py --fonts=_site/fonts --data=data/world
fi
node workers/world/style.mjs --out=_site/styles --region="$REGION" \
  --variant="$VARIANT" --maxzoom="$Z"
echo "Glyfy ($(du -sh _site/fonts 2>/dev/null | cut -f1)) a štýly za $(( $(date +%s) - T_A )) s"

# 5. manifest: jediný súbor, z ktorého sa dá zistiť, čo v tejto mape je –
# číta ho appka aj `deploy/publish-map.py`. Tvar je ten istý ako pri mape
# kraja; polia o vrstvách, ktoré svet nemá, v ňom nie sú (prázdna hodnota by
# znamenala „vrstva je, len je prázdna").
# Kľúč je téma, hodnota cesta v balíku – appka tak mená štýlov nemusí hádať.
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
    # ktorá podoba – bez toho sa z balíka nedá zistiť, či more chýba preto,
    # že je to `basic`, alebo preto, že sa build pokazil
    variant: $variant,
    layers: ($layers | split(",") | map(select(length > 0))),
    built_at: $built,
    maxzoom: $maxzoom,
    # glyfy v balíku nie sú – appka si ich nesie v sebe. Adresa tu je pre
    # toho, kto appka nie je (rozbalený balík vo webovom vieweri).
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
# kľúč regiónu a zoznam vrstiev vypadli z podoby, takže ich pozná len tento
# krok; ide to výstupom, lebo to isté potrebuje aj job s `.aar`
echo "variant=$VARIANT" >> "$GITHUB_OUTPUT"
echo "region_key=$REGION" >> "$GITHUB_OUTPUT"
echo "map_layers=$MAP_LAYERS" >> "$GITHUB_OUTPUT"
du -sh _site
printf '%s\t%s\t%s\t%s\n' "10" "Mapa sveta" "$(( $(date +%s) - T_CELKOM ))" \
  "$VARIANT, maxzoom $Z, ${MB} MB" >> steps-out/world.tsv
