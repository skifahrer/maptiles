#!/usr/bin/env bash
# Job `settings` – prvý job behu. Vypíše, s čím beh ide, skôr než sa začne
# čokoľvek počítať: formulár, `env:` workflowu a to, čo z volieb vyšlo.
#
# Vlastný job, nie prvý krok prípravy: ako krok jobu `plan` to bolo schované
# za dvoma rozkliknutiami a pod sťahovaním 380 MB PBF.
# Neblokuje (nikto naň nemá `needs:`), ale spadne, keď je formulár zlý –
# `options.py` neznámy kľúč neprepáči.
set -euo pipefail

OUT="$RUNNER_TEMP/nastavenia.md"
: > "$OUT"

# 1) čo si vypýtal vo formulári + `env:` workflowu
python3 workers/plan/summary-inputs.py \
  --inputs="$INPUTS_JSON" \
  --workflow=.github/workflows/build-map-region.yml \
  --with-env >> "$OUT"

# 2) čo z toho vyšlo – ten istý skript, aký voľby rozoberá pre zvyšok behu.
#    Bez `--out`: tento job nič nevydáva, len ukazuje.
python3 workers/plan/options.py \
  --options="$OPT_OPTIONS" \
  --rebuild="$OPT_REBUILD" \
  --contour-source="$OPT_CONTOUR_SOURCE" \
  --rock-source="$OPT_ROCK_SOURCE" \
  --shading-source="$OPT_SHADING_SOURCE" \
  --test="$OPT_TEST" \
  --publish-pages="$OPT_PUBLISH_PAGES" \
  --summary="$OUT"

# do súhrnu aj do logu: súhrn sa číta z mobilu, log sa dá grepovať
cat "$OUT" >> "$GITHUB_STEP_SUMMARY"
cat "$OUT"
