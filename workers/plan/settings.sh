#!/usr/bin/env bash
# Job `settings` – PRVÝ job behu. Vypíše, s čím beh ide, skôr než sa začne
# čokoľvek počítať: formulár, `env:` workflowu a to, čo z volieb vyšlo.
#
# PREČO VLASTNÝ JOB A NIE PRVÝ KROK PRÍPRAVY. Bolo to krokom jobu `plan`,
# teda schované za dvoma rozkliknutiami a pod jobom, ktorý popri tom sťahuje
# 380 MB PBF. Keď sa beh vypýtal na nesprávnom výreze alebo s prahom
# z minulého ladenia, prišlo sa na to až vtedy, keď bola mapa hotová – hodinu
# po tom, čo sa to dalo prečítať. Ako samostatný job je to na stránke behu
# prvá položka a dobehne za pár sekúnd.
#
# NEBLOKUJE. Nikto naň nemá `needs:`, takže príprava beží súbežne – pár
# sekúnd navyše na kritickej ceste štyridsaťminútového buildu by za lepšie
# poradie v zozname nestálo.
#
# ZATO SPADNE, KEĎ JE FORMULÁR ZLÝ. `options.py` neznámy kľúč neprepáči
# (pravidlo 8) a tu to povie po pár sekundách – nie o desať jobov neskôr.
set -euo pipefail

OUT="$RUNNER_TEMP/nastavenia.md"
: > "$OUT"

# 1) čo si vypýtal vo formulári + `env:` workflowu (prahy, sklady, rozpočty)
python3 workers/plan/summary-inputs.py \
  --inputs="$INPUTS_JSON" \
  --workflow=.github/workflows/build-map.yml \
  --with-env >> "$OUT"

# 2) čo z toho vyšlo. Ten istý skript, aký si o kus ďalej rozoberá voľby pre
#    zvyšok behu (`plan`) – nie druhý výpočet toho istého (pravidlo 1).
#    Bez `--out`: tento job nič nevydáva, len ukazuje.
python3 workers/plan/options.py \
  --options="$OPT_OPTIONS" \
  --rebuild="$OPT_REBUILD" \
  --contour-source="$OPT_CONTOUR_SOURCE" \
  --rock-source="$OPT_ROCK_SOURCE" \
  --shading-source="$OPT_SHADING_SOURCE" \
  --test="$OPT_TEST" \
  --navigation="$OPT_NAVIGATION" \
  --publish-pages="$OPT_PUBLISH_PAGES" \
  --summary="$OUT"

# Do súhrnu behu aj do logu: súhrn sa číta z mobilu, log sa dá grepovať.
cat "$OUT" >> "$GITHUB_STEP_SUMMARY"
cat "$OUT"
