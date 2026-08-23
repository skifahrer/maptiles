#!/usr/bin/env bash
# Články z Wikipédie ku všetkému, čo v regióne odkazuje na wiki.
#
# PREČO SAMOSTATNÝ SKRIPT A NIE `run:` V WORKFLOWE: `build-map.yml` má strop
# 500 kB a nad ním ho GitHub ticho neprijme (stráži to „Kontrola · lint workflowov").
#
# ČO TU JE a čo je vo `collect.py`: tu inštalácia, voľby z formulára a výstupy
# pre ďalšie joby; tam celý výpočet (hľadanie odkazov, wikidata, sťahovanie).
#
# PREČO NIE PLANETILER: nič sa nedláždi. Odkazy sú tagy a `osmium tags-filter`
# ich z regionálneho PBF vyberie za sekundy – ten istý nástroj, ktorým si trasy
# predfiltrujú relácie.
#
# Hodnoty z prostredia (viď workflow `Build wiki`, wiki.yml):
#   REGION_KEY WIKI_COUNTRY OPT_WIKI_LANGS OPT_WIKI_FORMAT OPT_WIKI_MAX
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y -qq osmium-tool
# Prevod wikitextu na čistý text. Je to knižnica od Wikimedie a je to jediná
# cesta, ako mať plný text A ZÁROVEŇ dávky po päťdesiatich: hotový čistý text
# (`prop=extracts`) API dávkovo nevydá, viď komentár v `collect.py`.
pip install --quiet mwparserfromhell

mkdir -p wiki-out wiki-cache steps-out

# Jazyky: angličtina a jazyk krajiny sa DOPLNIA SAMY podľa `--country`
# (rozpis vo `collect.py`), toto sú tie navyše. Prázdno je preto správna
# predvolená hodnota, nie chyba – „sk,en" by tu bola len druhá pravda o tom,
# čo už vie číselník `workers/data/wiki-languages.json`.
LANGS="${OPT_WIKI_LANGS:-}"
COUNTRY="${WIKI_COUNTRY:-}"
FMT="${OPT_WIKI_FORMAT:-text}"
MAX="${OPT_WIKI_MAX:-5000}"
# PREKLEP SA NESMIE PREJSŤ NA PREDVOLENÚ HODNOTU. Náhrada „nerozumiem, beriem
# text" znamená, že si vypýtaš `wiki_format=htlm` a dostaneš zelený beh
# s balíkom, v ktorom je niečo iné, než čakáš – a nemáš to na čom vidieť.
# Radšej spadnúť tu, v druhej sekunde jobu, a povedať aj čo s tým.
case "$FMT" in
  text|wikitext|intro|html) ;;
  *) echo "::error::wiki_format=$FMT nepoznám – zvoľ \`text\` (celý článok" \
          "ako čistý text), \`wikitext\` (bez prevodu), \`intro\` (len úvod)" \
          "alebo \`html\` (z REST API, ale po jednom článku)."
     exit 1 ;;
esac
case "$MAX" in
  ''|*[!0-9]*)
     echo "::error::wiki_max=$MAX nie je celé číslo – napíš strop počtu" \
          "článkov, napr. \`wiki_max=2000\`."
     exit 1 ;;
esac

# CACHE JE PRIEČINOK, ktorý pred týmto krokom obnovila `cache-restore`
# z Drive – v ňom je `articles.ndjson` z minulého behu toho istého regiónu.
# Podáva sa VŽDY, aj keď ešte neexistuje: `collect.py` si ho vyrobí a uloží
# doň kópiu, takže `cache-save` má čo nahrať už po prvom behu.
python3 workers/wiki/collect.py \
  --pbf=data/region.osm.pbf \
  --out=wiki-out \
  --cache=wiki-cache \
  --country="$COUNTRY" \
  --langs="$LANGS" \
  --format="$FMT" \
  --max="$MAX" \
  --stats=steps-out/wiki.tsv

# KOĽKO ICH JE, ROZHODUJE O PUBLIKOVANÍ. Balík `-wikipedia.zip` skladá job
# `deploy` z tohto priečinka; keď v regióne nie je ani jeden článok, nemá čo
# baliť a starý balík sa zmaže (`publish-map.py`). Preto sa počet vypisuje na
# výstup jobu a nie len do logu.
COUNT=$(python3 - <<'PY'
import json
try:
    with open("wiki-out/index.json") as f:
        print(len(json.load(f).get("articles") or []))
except Exception:
    print(0)
PY
)
MB=$(du -sm wiki-out | cut -f1)
echo "count=$COUNT" >> "$GITHUB_OUTPUT"
echo "mb=$MB" >> "$GITHUB_OUTPUT"
echo "enabled=$([ "$COUNT" -gt 0 ] && echo true || echo false)" >> "$GITHUB_OUTPUT"
echo "Články: $COUNT, $MB MB v wiki-out/ (krajina ${COUNTRY:-?}, jazyky navyše ${LANGS:-žiadne}, formát $FMT)"
# `ls … | head -5` je pasca: `head` po piatich riadkoch skončí a zavrie rúru,
# `ls` dopisuje do zavretej rúry, dostane EPIPE – a `pipefail` hore z toho
# spraví PÁD SKRIPTU na poslednom riadku, keď je práca dávno hotová. Článkov
# sú tisíce, takže `ls` písať naozaj má čo. Preto here-string, nie rúra.
ZOZNAM=$(ls -1 wiki-out)
head -5 <<<"$ZOZNAM"
