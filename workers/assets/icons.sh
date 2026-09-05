#!/usr/bin/env bash
# SDF sprity zo sád ikoniek → `_site/sprites/`.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 kB.
#
# Zoznam zdrojov je v `poc/web/icon-sources.js` – jedno miesto pre web aj
# pipeline. Z každého sa vyrobí SDF sprite: symboly bez koliesok, ktorým sa dá
# nastaviť farba.
#
# Sada, ktorá sa nestiahne, build nezhodí – sú to súbory z cudzích serverov;
# chyba je až to, keď nevyjde ani jedna. Ktoré vznikli, ide von v `available`.
#
# `set -uo pipefail` bez `-e` je zámer: preskakovanie chýbajúcich sád na tom stojí.

set -uo pipefail
T_SPR=$(date +%s)
mkdir -p _site/sprites /tmp/icons

# Cache: hotové sprity sa nemenia, kým sa nezmení zoznam zdrojov ani
# generátor – v kľúči je hash oboch.
# find, nie ls: `ls vzor*` bez zhody končí kódom 2 a `pipefail`
# by ním zhodil celý krok (find nad existujúcim adresárom vráti 0).
CACHED_SPRITES=$(find _site/sprites -maxdepth 1 -name '*.json' | wc -l)

# vlastné sady z developer módu sú v tom zozname tiež – je to tá istá vec
# (`<url>.json` + `<url>.png`), len ju nezapísal repozitár, ale človek
node -e "
  Promise.all([
    import('./poc/web/icon-sources.js'),
    import('./poc/web/themes.js'),
    import('node:fs')
  ]).then(([ic, th, fs]) => {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync('poc/web/style-overrides.json', 'utf8')); } catch {}
    for (const s of ic.allIconSources(th.normalizeOverrides(raw).overrides)) {
      console.log(s.id + ' ' + s.sprite);
    }
  });
" > /tmp/icons/list.txt
cat /tmp/icons/list.txt

ok=""
while read -r id url; do
  [ -n "$id" ] || continue
  if [ "$CACHED_SPRITES" -gt 0 ] && [ -s "_site/sprites/$id.json" ]; then
    echo "── $id (z cache)"
    ok="$ok $id"
    continue
  fi
  echo "── $id"
  got=1
  for ext in .json .png; do
    curl -fL --retry 4 --retry-delay 5 -o "/tmp/icons/$id$ext" "$url$ext" || got=0
  done
  # @2x je voliteľné – bez neho mapa funguje, len je na retine mäkšia.
  for ext in '@2x.json' '@2x.png'; do
    curl -fL --retry 2 --retry-delay 3 -o "/tmp/icons/$id$ext" "$url$ext" \
      || rm -f "/tmp/icons/$id$ext"
  done
  if [ "$got" != 1 ]; then
    echo "::warning::Sadu ikoniek $id sa nepodarilo stiahnuť – preskakujem."
    continue
  fi
  if node workers/assets/sprite.mjs --in="/tmp/icons/$id" --out="_site/sprites/$id"; then
    # Štítky s číslom cesty („D1") si kreslíme sami – v cudzej sade ikoniek
    # nie sú a byť nemôžu, lebo sa naťahujú podľa dĺžky čísla. Keď sa
    # nedopečú, mapa nespadne: štýl číslo nakreslí len s hrubým halom
    # (viď `hasIcon` v `poc/web/themes.js`), takže je to varovanie, nie chyba.
    node workers/assets/shields.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Štítky ciest sa do sady $id nepodarilo dopiecť – čísla ciest budú bez podkladu."
    # To isté pre TURISTICKÉ A CYKLISTICKÉ ZNAČKY (biely či žltý štvorec
    # s farebným pásom): v cudzej sade ikoniek nie sú a byť nemôžu – je to
    # obrázok konkrétnej tabuľky z terénu, nie symbol. Keď sa nedopečú, mapa
    # nespadne: pozdĺž trasy sa kreslí ikonka druhu trasy ako predtým.
    node workers/assets/marks.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Značky trás sa do sady $id nepodarilo dopiecť – trasy budú s ikonkou druhu, nie so značkou."
    # A ŠÍPKY JEDNOSMERIEK. Tie sme si predtým brali z cudzej sady a mala ich
    # jediná z troch – pri ostatných vrstva `road-oneway` do štýlu vôbec
    # nevznikla, takže sa nedalo nastaviť ani ako často sú šípky, ani akej sú
    # farby (rozpis v `poc/web/arrows.js`). Keď sa nedopečú, mapa nespadne:
    # vrstva sa vynechá presne tak ako predtým.
    node workers/assets/arrows.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Šípky jednosmeriek sa do sady $id nepodarilo dopiecť – jednosmerky budú bez šípok."
    # A nakoniec VLASTNÉ IKONY z úprav – obrázky, ktoré si niekto nahral
    # v developer móde. Sú v `style-overrides.json` ako PNG, takže sa len
    # dekódujú a vložia do atlasu.
    node workers/assets/custom-icons.mjs --sprite="_site/sprites/$id" \
      || echo "::warning::Vlastné ikony sa do sady $id nepodarilo dopiecť – vrstvy, ktoré ich používajú, ostanú bez ikony."
    ok="$ok $id"
  else
    echo "::warning::Sadu ikoniek $id sa nepodarilo prerobiť na SDF – preskakujem."
  fi
done < /tmp/icons/list.txt

if [ -z "$ok" ]; then
  echo "::error::Nepodarilo sa pripraviť ani jednu sadu ikoniek – mapa by bola bez ikon."
  exit 1
fi

# Ktorú sadu má použiť štýl, hovoria úpravy z developer módu.
WANT=$(node -e "
  Promise.all([import('./poc/web/themes.js'), import('node:fs')]).then(([m, fs]) => {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync('poc/web/style-overrides.json', 'utf8')); } catch {}
    console.log(m.selectedIconSource(m.normalizeOverrides(raw).overrides));
  });
")
if [ ! -s "_site/sprites/$WANT.json" ]; then
  WANT=$(printf '%s' "$ok" | awk '{print $1}')
  echo "::warning::Zvolená sada ikoniek nie je k dispozícii – používam $WANT."
fi
echo "name=$WANT" >> "$GITHUB_OUTPUT"
echo "available=$(printf '%s' "$ok" | xargs)" >> "$GITHUB_OUTPUT"
echo "Nasadené sady:$ok, štýl použije $WANT"
printf '%s\t%s\t%s\t%s\n' "80" "Ikonky (SDF sprity)" "$(( $(date +%s) - T_SPR ))" \
  "sady:$ok, štýl používa $WANT$([ "$CACHED_SPRITES" -gt 0 ] && echo ' (z cache)')" \
  >> steps-out/assets.tsv
