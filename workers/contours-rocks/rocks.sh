#!/usr/bin/env bash
# SKALY: najstrmšie úseky terénu → data/rock.gpkg.
#
# ČÍTA SA CEZ `.` (source) Z `workers/contours-rocks/build.sh`, nie ako vlastný
# proces – je to DRUHÁ POLOVICA toho istého výpočtu, nie druhý skript. Obe
# polovice stoja na tom istom výreze, tom istom DEM a tom istom rozpočte
# (`ONLY` hovorí, ktorá sa má počítať), takže si podávajú premenné: odtiaľto
# ide von `ROCK_SLOPE`, `ROCK_DEM_USED` a `RR` do mena assetu, do štatistiky
# aj do súhrnu behu. Spustiť to samostatne by znamenalo podať si tie hodnoty
# druhý raz – čiže mať ich napísané dvakrát (pravidlo 1 v CLAUDE.md).
#
# ODDELENÉ JE TO PRETO, ŽE `build.sh` PRERÁSTOL 800 RIADKOV a v jednom takom
# súbore sa nedá rýchlo nájsť, čo sa zmenilo alebo prečo to spadlo (pravidlo 5;
# stráži to „Kontrola · lint workflowov"). Rez vedie tam, kde sa mení otázka:
# hore „aký je terén" (výrez, model, izolínie), tu „kde je strmý".
#
# Premenné, ktoré sem chodia z `build.sh`: BBOX AREA_KEY AREA_NAME AREA_BBOX
# AREA_KM2 CUT DEM_VRT ROCK_VRT ROCK_DEM_USED OPT_ROCKS OPT_ROCK_DEM
# OPT_ROCK_SOURCE OPT_ROCK_PLNE OPT_ROCK_ZAPLN_DIERY OPT_ROCK_IMG_ASSET
# OPT_ROCKS_REBUILD ROCK_SLOPE_IN ROCK_RES_IN SLOPE_DIR a `env:` workflowu
# (ROCK_*, *_STORE). Funkcia `make_empty_gpkg` je tiež odtiaľ.
#
# `set -euo pipefail` sa tu NENASTAVUJE: platí to, čo si nastavil `build.sh`,
# a druhé nastavenie by len tvrdilo, že tento súbor beží sám.

# ---------- skaly: najstrmšie úseky terénu ----------
# Celý výpočet je vo workers/contours-rocks/rock-areas.py – po častiach, aby sa
# jemná mriežka zmestila do pamäte aj na disk. Bbox kraja má pri
# 2 m vyše 3 miliardy buniek (~13 GB na jeden raster), takže naraz
# sa to spočítať nedá.
T_ROCK=$(date +%s)
ROCK_SLOPE="$ROCK_SLOPE_IN"
case "$ROCK_SLOPE" in ''|*[!0-9]*) ROCK_SLOPE=50 ;; esac
ROCK_CLIFF=$(( ROCK_SLOPE + ROCK_CLIFF_PLUS ))
# `auto` = mriežku vyberie rock-areas.py: najjemnejšiu, ktorá sa
# zmestí do rozpočtu času a má pri danom DEM ešte zmysel. Nedá sa
# to spočítať tu, lebo to závisí od plochy výrezu aj od bunky DEM.
RR="$ROCK_RES_IN"
case "$RR" in
  auto|'') RR=auto ;;
  *[!0-9.]*) RR="$ROCK_RES" ;;
esac
# Najmenšiu skalu (= jedna bunka mriežky) dopočíta rock-areas.py,
# lebo pri `auto` sa mriežka vyberá až tam.

make_empty_rock() { make_empty_gpkg data/rock.gpkg rock POLYGON; }

if [ "$OPT_ROCKS" = 'true' ]; then
  ROCK_READY=""
  ROCK_SRC="výpočet"

  # ---------- skaly z tieňovaných dlaždíc (rock_source: tienovanie) ----------
  # Tie sa v TOMTO jobe nepočítajú – spravil to job `shading-rocks`
  # o kus vyššie v tom istom behu (stiahol tieňované dlaždice
  # z freemap.sk a hotové polygóny nahral do skladu na Drive). Tu sa
  # už len stiahne výsledok. Keď je vyplnený `rock_img_asset`, ten job
  # nebežal a berie sa presne ten súbor.
  if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
    IMG_ASSET="$OPT_ROCK_IMG_ASSET"
    echo "::group::Skaly z tieňovania – $AREA_NAME, sklad $ROCK_IMG_STORE"
    if [ -z "$IMG_ASSET" ]; then
      # Najnovší súbor pre tento výrez. Zoradiť sa musí podľa času
      # nahratia, nie podľa mena: v mene sú prahy, takže abecedne
      # by vyhral ten s najväčším číslom, nie ten posledný. Robí to
      # `--latest` v sklade, aby to poradie bolo napísané raz.
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
    # Výrez sa tu NEOREZÁVA na bbox regiónu zámerne: asset vznikol
    # presne pre tento výrez a orezanie by len prerezalo polygóny
    # na hranici. Keby výrez presahoval región, dlaždice mimo neho
    # aj tak nikto nevykreslí.
    echo "::endgroup::"
  fi

  # Hotové skaly pre tento región a tieto nastavenia sú v sklade –
  # nastavenia sú v mene súboru, takže sa nikdy nepomiešajú. Výpočet
  # je na desiatky minút, stiahnutie na sekundy. `rocks_rebuild` ten
  # súbor zahodí a počíta odznova.
  # Výrez je v mene súboru: skaly len z Tatier sa nesmú nabudúce
  # vydávať za skaly celého kraja.
  # A PREKRYV SO SUSEDNÝM KRAJOM tiež (`o…`). Pri `area: cely_region` je
  # oknom `dem_bbox`, ktorý `workers/plan/pbf.sh` nafukuje o
  # `BORDER_BUFFER_M`, a orezáva sa polygónom kraja, ktorý je nafúknutý
  # o to isté – nafúknutie teda mení, kam až skaly siahajú. Bez neho v mene
  # by sklad na už postavenom kraji vrátil skaly orezané ešte podľa tesnej
  # hranice a na hranici so susedom by končili skôr než mapa – presne to sa
  # namerane stalo tieňovaniu (rozpis vo `workers/terrain/build.sh`).
  ROCK_BORDER_M=$(python3 -c "import sys; sys.path.insert(0, 'workers/plan'); import area; print(int(area.BORDER_BUFFER_M))")
  ROCK_ASSET="rock-${REGION_KEY}-${AREA_KEY}-${ROCK_DEM_USED:-none}-s${ROCK_SLOPE}-g${RR}-${ROCK_ALGO}-o${ROCK_BORDER_M}.gpkg.zst"
  # TESTOVACÍ BEH SA SKLADU NESMIE DOTKNÚŤ. Pri `area: cely_region` totiž kľúč
  # výrezu ostáva `cely` aj v teste (prípona `_test4` by prepla podobu DMR 5.0
  # – viď workers/plan/area.py), takže by testovacie skaly zo 4 km² ležali
  # v sklade pod menom skál CELÉHO KRAJA a ďalší ostrý beh by si ich stiahol
  # ako hotové. To je ten istý druh tichého omylu ako dlaždica, ktorá sľubuje
  # celý stupeň – meno musí hovoriť, čo v súbore naozaj je. Sklad častí sklonu
  # to má rovnako (`--no-store` nižšie), lebo tam ide o to isté.
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
    # Skaly sú bonus nad vrstevnicami: keby ich výpočet zlyhal (alebo
    # v rovine nič nenašiel), nemá to zhodiť hodinový build.
    # Exit 2 = „toto sa nedá spočítať" (nezmestí sa to do pamäte,
    # alebo je zlé zadanie – priveľa častí, chýbajúca mozaika). To
    # nie je bonus, ktorý sa dá preskočiť – build sa má zastaviť
    # hneď, nie nasadiť mapu bez skál po hodine práce. Iný nenulový
    # kód je skutočné zlyhanie výpočtu a tam prázdna vrstva stačí.
    # ČAS MEDZI TÝMI DÔVODMI NIE JE: keď je vektorizácia nad
    # rozpočtom, povie to a beží ďalej (viď workers/contours-rocks/rock-areas.py).
    # ---- 1. odkiaľ sa číta výška ----
    # `dmr5` ide priamo z Drive po častiach; ostatné modely sú lokálne
    # dlaždice, ktoré už stiahol `fetch_dem`.
    SRC_ARGS=(--dem "$ROCK_VRT")
    [ "$ROCK_DEM_USED" = 'dmr5' ] && SRC_ARGS=(--drive --dem-cell-m 1)

    # Testovací beh a pregenerovanie sa skladu nesmú dotknúť: test počíta
    # pár km² s inými nastaveniami a jeho časti by v sklade vyzerali ako
    # plnohodnotné, `rocks_rebuild` zase znamená „never ničomu uloženému".
    STORE_ARGS=()
    [ "${OPT_TEST_KM2:-0}" != '0' ] && STORE_ARGS+=(--no-store)
    [ "$OPT_ROCKS_REBUILD" = 'true' ] && STORE_ARGS+=(--rebuild)

    # ---- 2. mriežka ----
    # Vyberá ju `slope-chunks.py`, lebo ju musí poznať skôr, než začne
    # počítať; `rock-areas.py` ju potom dostane hotovú. Dva výbery toho
    # istého by sa raz rozišli a vektorizovalo by sa niečo iné, než sa
    # počítalo.
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
      # Ulož ich, nech ich nabudúce netreba počítať znova. Zlyhanie
      # uloženia NESMIE zhodiť beh – skaly sú spočítané a v `rock.gpkg`.
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

  # Štatistika ide do contours-out, takže ju nesie aj cache – pri
  # cache hite sa tento krok vôbec nespustí, ale súhrn čísla má.
  ROCK_N=$(ogrinfo -so data/rock.gpkg rock 2>/dev/null \
    | awk -F': ' '/^Feature Count/ {print $2}')
  # Skaly z tieňovania nemajú ani sklon, ani mriežku – písať ich do
  # merania by bolo číslo, ktoré nikde nevzniklo.
  if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
    ROCK_HOW="tmavé plochy v tieňovaní"
  else
    ROCK_HOW="$ROCK_DEM_USED, sklon ≥ ${ROCK_SLOPE}°, mriežka ${RR} m"
  fi
  printf '%s\t%s\t%s\t%s\n' "40" "Skalné plochy" "$(( $(date +%s) - T_ROCK ))" \
    "${ROCK_N:-0} plôch, $AREA_NAME, ${ROCK_HOW} ($ROCK_SRC)" \
    >> steps-out/contours.tsv
  # Keď skaly prišli z releasu, script nebežal a štatistiku nemá kto
  # napísať – aspoň to základné, nech súhrn nie je plný otáznikov.
  if [ ! -s contours-out/rock-stats.txt ]; then
    # `min_area_m2` sa tu nedopĺňa: dopočítava ho rock-areas.py
    # z vybranej mriežky a ten práve nebežal. Súhrn si s chýbajúcou
    # hodnotou poradí (`${min_area_m2:-?}`) – dosadiť sem premennú,
    # ktorá nikde nevzniká, by pri `set -u` zhodilo celý build.
    if [ "$OPT_ROCK_SOURCE" = 'tienovanie' ]; then
      # Skaly z tieňovania sú z iného sveta – ani sklon, ani mriežka
      # pre ne neexistujú. Súhrn podľa `source` vypíše inú tabuľku.
      { echo "source=tienovanie"; echo "count=${ROCK_N:-0}"
        printf "asset='%s'\n" "$ROCK_SRC"
      } > contours-out/rock-stats.txt
    else
      { echo "source=dem"; echo "count=${ROCK_N:-0}"; echo "grid_m=$RR"
        echo "slope_deg=$ROCK_SLOPE"; echo "cliff_deg=$ROCK_CLIFF"
      } > contours-out/rock-stats.txt
    fi
  fi
  # Z ktorého modelu sú skaly – do súhrnu. Pri `tienovanie` je
  # prázdny, lebo tam žiadny výškový model nefiguruje.
  printf "rock_dem='%s'\n" "$ROCK_DEM_USED" >> contours-out/rock-stats.txt
  # Výrez do štatistiky, nech je v súhrne vidieť, že skaly nie sú
  # všade – aj keď sa tento krok nabudúce vezme z cache.
  # Hodnoty v apostrofoch: súhrn si súbor načíta cez `.` a meno
  # výrezu má medzeru („celý región").
  { printf "area_key='%s'\n" "$AREA_KEY"
    printf "area_name='%s'\n" "$AREA_NAME"
    printf "area_bbox='%s'\n" "$AREA_BBOX"; } >> contours-out/rock-stats.txt
else
  make_empty_rock
  echo "Skaly: vypnuté (prázdna vrstva)."
fi
