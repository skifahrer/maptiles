#!/usr/bin/env bash
# Overí, že nasadená stránka je celá: štýl neodkazuje na nič, čo v `_site`
# nie je, a súčet sa zmestí do rozpočtu.
#
# Chýbajúci sprite či dlaždica sa v mape neprejaví pádom – mapa sa načíta
# a len nenakreslí polovicu vecí. To je tichý omyl, ktorý sa nájde až na
# hotovej stránke, tak sa hľadá tu a beh na ňom padá.
#
# Použitie (hodnoty chodia z prostredia, aby sa dal skript spustiť aj ručne):
#   SPRITE=osm-liberty REGION_KEY=presovsky_kraj LIMIT_MB=900 \
#   workers/deploy/check.sh
set -euo pipefail

SPRITE="${SPRITE:?meno spritu (assets.outputs.name)}"
REGION_KEY="${REGION_KEY:?kľúč regiónu (plan.outputs.key)}"
LIMIT_MB="${LIMIT_MB:-900}"
SITE="${SITE:-_site}"

fail=0
shopt -s nullglob
styles=("$SITE"/styles/*.json)
if [ ${#styles[@]} -eq 0 ]; then
  echo "::error::v $SITE/styles nie sú žiadne štýly"
  exit 1
fi
STYLE="${styles[0]}"
echo "Kontrolujem $STYLE"

# sprite (ten, na ktorý štýl naozaj odkazuje)
for ext in .json .png; do
  [ -s "$SITE/sprites/$SPRITE$ext" ] || { echo "::error::chýba sprites/$SPRITE$ext"; fail=1; }
done

# RETINA VARIANT (@2x). Mapa si ho pýta podľa hustoty displeja, takže telefón
# siahne na `<sprite>@2x.json` a nie na `<sprite>.json` – a keď ho nedostane,
# NEVYKRESLÍ ŽIADNE IKONY, nie „len mäkšie". Na počítači sa to nemusí prejaviť
# vôbec. Doteraz sa `@2x` nekontroloval nikde: sťahuje sa „ak je", pečie sa doň
# „ak je", a či je, nikto nepovedal.
#
# A MUSÍ MAŤ TIE ISTÉ MENÁ. Štítky ciest, značky trás, šípky aj vlastné ikony
# sa pečú do oboch variantov zvlášť; keby sa jedno pečenie nepodarilo, sprite
# by ostal platný a v mape by na retine chýbala presne tá skupina obrázkov.
for ext in @2x.json @2x.png; do
  [ -s "$SITE/sprites/$SPRITE$ext" ] \
    || { echo "::error::chýba sprites/$SPRITE$ext – na displeji s vyššou hustotou (telefón) si mapa pýta práve tento variant a bez neho nenakreslí ANI JEDNU ikonu"; fail=1; }
done
if [ -s "$SITE/sprites/$SPRITE@2x.json" ]; then
  CHYBAJU=$(jq -r --slurpfile dva "$SITE/sprites/$SPRITE@2x.json" \
    '[keys[] | select(. as $k | ($dva[0] | has($k)) | not)] | join(", ")' \
    "$SITE/sprites/$SPRITE.json")
  if [ -n "$CHYBAJU" ]; then
    echo "::error::sprites/$SPRITE@2x.json nemá obrázky, ktoré sú v 1×: $CHYBAJU"
    fail=1
  fi
fi

# glyfy – iba ak si ich hostíme sami.
# Názvy fontstackov obsahujú medzery ("Noto Sans Regular"), preto read -r.
if jq -e '.glyphs | contains("openmaptiles.org") | not' "$STYLE" >/dev/null; then
  while IFS= read -r stack; do
    if [ ! -s "$SITE/fonts/$stack/0-255.pbf" ]; then
      echo "::error::štýl používa fontstack '$stack', ale $SITE/fonts/$stack/0-255.pbf neexistuje"
      fail=1
    fi
  done < <(jq -r '[.layers[].layout["text-font"] // empty] | flatten | unique | .[]' "$STYLE")
fi

# ikonky – pevne zadané mená ikon musia byť v sprite (mená skladané
# výrazom sa generujú priamo zo sprite indexu, tie kontrolovať netreba)
while IFS= read -r icon; do
  [ -n "$icon" ] || continue
  jq -e --arg i "$icon" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
    || { echo "::error::štýl odkazuje na ikonu '$icon', ktorá v sprite nie je"; fail=1; }
done < <(jq -r '[.layers[].layout["icon-image"]? | strings] | unique | .[]' "$STYLE")

# ZNAČKY TRÁS sa mená z výrazu netýkajú kontroly vyššie (`strings` ich
# odfiltruje), ale práve ony sú tá tichá vec: meno obrázka skladá štýl z DÁT
# (`mark-<podklad>-<farba>-<tvar>`), takže chýbajúci obrázok MapLibre ticho
# preskočí a po trase nie je nič. Keď je v štýle vrstva so značkami, musia
# byť v sprite všetky – zoznam povie `poc/web/marks.js`, jediné miesto, kde
# je napísaný.
if jq -e '[.layers[] | select(.id | endswith("-mark"))] | length > 0' "$STYLE" >/dev/null; then
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    jq -e --arg i "$img" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
      || { echo "::error::štýl kreslí značky trás, ale '$img' v sprite nie je"; fail=1; }
  done < <(node -e "
    import('./poc/web/marks.js').then((m) => {
      for (const z of m.markImages()) console.log(z.name);
    });
  ")
fi

# ŠÍPKY JEDNOSMERIEK. Tú istú úvahu ako pri značkách trás: kreslíme si ich
# sami a pečieme do každej sady, takže vrstva `road-oneway` má byť v štýle
# vždy. Keby chýbal obrázok, vrstva sa ticho vynechá – a to je presne stav,
# ktorý sme týmto odstraňovali.
if jq -e '[.layers[] | select(.id == "road-oneway")] | length > 0' "$STYLE" >/dev/null; then
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    jq -e --arg i "$img" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
      || { echo "::error::štýl kreslí jednosmerky, ale šípka '$img' v sprite nie je"; fail=1; }
  done < <(node -e "
    import('./poc/web/arrows.js').then((m) => {
      for (const z of m.arrowImages()) console.log(z);
    });
  ")
fi

# vzory plôch a čiar musia byť v sprite (inak sa plocha nevykreslí)
while IFS= read -r img; do
  [ -n "$img" ] || continue
  jq -e --arg i "$img" 'has($i)' "$SITE/sprites/$SPRITE.json" >/dev/null \
    || { echo "::error::štýl používa vzor '$img', ktorý v sprite nie je"; fail=1; }
done < <(jq -r '[.layers[].paint["fill-pattern"]?, .layers[].paint["line-pattern"]? | strings] | unique | .[]' "$STYLE")

# dlaždice
PM="$SITE/tiles/$REGION_KEY.pmtiles"
[ -s "$PM" ] || { echo "::error::chýba $PM"; fail=1; }

# Vrstvy, ktoré si štýl pýta, musia v `_site` byť. Zdroj v štýle a súbor
# vedľa neho sú dve strany tej istej vety – keď sa rozídu, mapa sa načíta
# a vrstva ticho chýba.
for pair in "contours:vrstevnice" "rocks:skaly" "trails:značené trasy" \
            "features:krajinné prvky" "points:body v krajine" \
            "roads:obmedzenia na ceste" \
            "transport:dopravná sieť"; do
  src="${pair%%:*}"; popis="${pair#*:}"
  jq -e ".sources.$src" "$STYLE" >/dev/null || continue
  f="$SITE/tiles/$REGION_KEY-$src.pmtiles"
  [ -s "$f" ] || { echo "::error::štýl používa $popis, ale chýba $f"; fail=1; }
done

# Hranica stiahnutého regiónu. Statické štýly ju majú v sebe (aby ju offline
# aplikácia nemusela dohľadávať), viewer na webe si ju načíta za behu z tohto
# súboru – takže keď ju štýl pozná, musí tu byť aj on. Bez nej mapa siaha za
# región a nikto to nepovie.
if jq -e '.sources.region' "$STYLE" >/dev/null; then
  [ -s "$SITE/region.geojson" ] \
    || { echo "::error::štýl má hranicu regiónu, ale chýba $SITE/region.geojson (vyrába ho workers/deploy/region-mask.py)"; fail=1; }
fi

# Poistka na koniec: rozpočet drží krok pri dlaždiciach, tu sa už len
# overí, že súčet naozaj sedí (Pages zvládne ~1 GB na celú stránku).
case "$LIMIT_MB" in ''|*[!0-9]*) LIMIT_MB=900 ;; esac
TOTAL_MB=$(du -sm "$SITE" | cut -f1)
echo "Veľkosť $SITE: ${TOTAL_MB} MB (rozpočet ${LIMIT_MB} MB)"
du -sm "$SITE"/tiles "$SITE"/fonts "$SITE"/sprites 2>/dev/null || true
if [ "$TOTAL_MB" -gt "$LIMIT_MB" ]; then
  echo "::error::$SITE má ${TOTAL_MB} MB, rozpočet je ${LIMIT_MB} MB (GitHub Pages zvládne ~1 GB). Zníž maxzoom, vypni contours, zväčš contour_interval alebo použi menší región / crop_bbox."
  fail=1
fi
exit $fail
