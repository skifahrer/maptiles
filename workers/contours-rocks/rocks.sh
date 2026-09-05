#!/usr/bin/env bash
# SKALY: najstrmšie úseky terénu → data/rock.gpkg.
#
# Číta sa cez `.` z `workers/contours-rocks/build.sh` – je to druhá polovica
# toho istého výpočtu, nie druhý skript: obe stoja na tom istom výreze, DEM
# aj rozpočte a podávajú si premenné (`ROCK_SLOPE`, `ROCK_DEM_USED`, `RR`).
# Oddelené preto, že `build.sh` prerástol 800 riadkov; rez vedie tam, kde sa
# mení otázka – hore „aký je terén", tu „kde je strmý".
#
# `set -euo pipefail` sa tu nenastavuje: platí to, čo si nastavil `build.sh`.

# ---------- skaly: najstrmšie úseky terénu ----------
# Výpočet je vo `rock-areas.py`, po častiach: bbox kraja má pri 2 m vyše
# 3 miliardy buniek.
T_ROCK=$(date +%s)
ROCK_SLOPE="$ROCK_SLOPE_IN"
case "$ROCK_SLOPE" in ''|*[!0-9]*) ROCK_SLOPE=50 ;; esac
ROCK_CLIFF=$(( ROCK_SLOPE + ROCK_CLIFF_PLUS ))
# `auto` = mriežku vyberie rock-areas.py; závisí od plochy výrezu aj od
# bunky DEM, takže sa to nedá spočítať tu
RR="$ROCK_RES_IN"
case "$RR" in
  auto|'') RR=auto ;;
  *[!0-9.]*) RR="$ROCK_RES" ;;
esac
# najmenšiu skalu (jedna bunka mriežky) dopočíta rock-areas.py

make_empty_rock() { make_empty_gpkg data/rock.gpkg rock POLYGON; }

if [ "$OPT_ROCKS" = 'true' ]; then
  ROCK_READY=""
  ROCK_SRC="výpočet"

  # ---------- skaly z tieňovaných dlaždíc (rock_source: tienovanie) ----------
  # V tomto jobe sa nepočítajú – spravil to job `shading-rocks` v tom istom
  # behu a tu sa už len stiahne výsledok.
  if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
    IMG_ASSET="$OPT_ROCK_IMG_ASSET"
    echo "::group::Skaly z tieňovania – $AREA_NAME, sklad $ROCK_IMG_STORE"
    if [ -z "$IMG_ASSET" ]; then
      # najnovší súbor pre tento výrez. Zoradiť sa musí podľa času nahratia,
      # nie podľa mena: v mene sú prahy, tak by abecedne vyhral iný.
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
    # výrez sa tu zámerne neorezáva na bbox regiónu: asset vznikol presne
    # pre tento výrez a orez by len prerezal polygóny na hranici
    echo "::endgroup::"
  fi

  # hotové skaly pre tento región a nastavenia sú v sklade – nastavenia sú
  # v mene súboru, takže sa nikdy nepomiešajú. `rocks_rebuild` ich zahodí.
  # V mene je aj výrez a prekryv so susedom (`o…`): nafúknutie mení, kam až
  # skaly siahajú, a bez neho by sklad vrátil skaly orezané po starom.
  ROCK_BORDER_M=$(python3 -c "import sys; sys.path.insert(0, 'workers/plan'); import area; print(int(area.BORDER_BUFFER_M))")
  ROCK_ASSET="rock-${REGION_KEY}-${AREA_KEY}-${ROCK_DEM_USED:-none}-s${ROCK_SLOPE}-g${RR}-${ROCK_ALGO}-o${ROCK_BORDER_M}.gpkg.zst"
  # testovací beh sa skladu nesmie dotknúť: pri `area: cely_region` ostáva kľúč
  # výrezu `cely` aj v teste, takže by skaly zo 4 km² ležali v sklade pod menom
  # skál celého kraja
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
    # skaly sú bonus nad vrstevnicami: zlyhanie ich výpočtu nemá zhodiť
    # hodinový build. Výnimka je exit 2 = „toto sa nedá spočítať" (nezmestí sa
    # do pamäte, zlé zadanie) – tam sa má build zastaviť hneď.
    # ---- 1. odkiaľ sa číta výška ----
    # `dmr5` ide priamo z Drive po častiach; ostatné modely sú lokálne dlaždice.
    SRC_ARGS=(--dem "$ROCK_VRT")
    [ "$ROCK_DEM_USED" = 'dmr5' ] && SRC_ARGS=(--drive --dem-cell-m 1)

    # testovací beh a pregenerovanie sa skladu nesmú dotknúť: test počíta pár
    # km² a jeho časti by vyzerali ako plnohodnotné
    STORE_ARGS=()
    [ "${OPT_TEST_KM2:-0}" != '0' ] && STORE_ARGS+=(--no-store)
    [ "$OPT_ROCKS_REBUILD" = 'true' ] && STORE_ARGS+=(--rebuild)

    # ---- 2. mriežka ----
    # Vyberá ju `slope-chunks.py` (musí ju poznať skôr, než začne počítať)
    # a `rock-areas.py` ju dostane hotovú.
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
      # ulož ich, nech ich nabudúce netreba počítať znova; zlyhanie uloženia
      # nesmie zhodiť beh – skaly sú spočítané
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

  # štatistika ide do contours-out, takže ju nesie aj cache – pri cache hite
  # sa tento krok nespustí, ale súhrn čísla má
  ROCK_N=$(ogrinfo -so data/rock.gpkg rock 2>/dev/null \
    | awk -F': ' '/^Feature Count/ {print $2}')
  # skaly z tieňovania nemajú ani sklon, ani mriežku
  if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
    ROCK_HOW="tmavé plochy v tieňovaní"
  else
    ROCK_HOW="$ROCK_DEM_USED, sklon ≥ ${ROCK_SLOPE}°, mriežka ${RR} m"
  fi
  printf '%s\t%s\t%s\t%s\n' "40" "Skalné plochy" "$(( $(date +%s) - T_ROCK ))" \
    "${ROCK_N:-0} plôch, $AREA_NAME, ${ROCK_HOW} ($ROCK_SRC)" \
    >> steps-out/contours.tsv
  # keď skaly prišli zo skladu, skript nebežal a štatistiku nemá kto napísať
  if [ ! -s contours-out/rock-stats.txt ]; then
    # `min_area_m2` sa tu nedopĺňa: dopočítava ho rock-areas.py a ten nebežal.
    # Súhrn si s chýbajúcou hodnotou poradí; premenná, ktorá nikde nevzniká,
    # by pri `set -u` zhodila build.
    if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
      # skaly z tieňovania sú z iného sveta – súhrn podľa `source` vypíše
      # inú tabuľku
      { echo "source=tienovanie"; echo "count=${ROCK_N:-0}"
        printf "asset='%s'\n" "$ROCK_SRC"
      } > contours-out/rock-stats.txt
    else
      { echo "source=dem"; echo "count=${ROCK_N:-0}"; echo "grid_m=$RR"
        echo "slope_deg=$ROCK_SLOPE"; echo "cliff_deg=$ROCK_CLIFF"
      } > contours-out/rock-stats.txt
    fi
  fi
  # z ktorého modelu sú skaly – do súhrnu; pri `tienovanie` prázdny
  printf "rock_dem='%s'\n" "$ROCK_DEM_USED" >> contours-out/rock-stats.txt
  # výrez do štatistiky, nech je v súhrne vidieť, že skaly nie sú všade.
  # Hodnoty v apostrofoch: súhrn si súbor načíta cez `.` a meno má medzeru.
  { printf "area_key='%s'\n" "$AREA_KEY"
    printf "area_name='%s'\n" "$AREA_NAME"
    printf "area_bbox='%s'\n" "$AREA_BBOX"; } >> contours-out/rock-stats.txt
else
  make_empty_rock
  echo "Skaly: vypnuté (prázdna vrstva)."
fi
