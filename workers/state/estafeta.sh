#!/usr/bin/env bash
# Jadro štafety – spoločné pre obe dávky nad krajinou (`relay.sh` postaví
# každý kraj, `regenerate.sh` pregeneruje jednu vrstvu v každom kraji).
#
# Obe idú krajmi jeden po druhom a čakajú na beh kraja. Líšia sa len tým, čo
# nad krajom spúšťajú – to si definujú samy (`odovzdaj`, `spusti_kraj`).
#
# Prečo štafeta a nie jeden dlhý job: kraj sa stavia aj tri hodiny, krajov je
# osem a job má strop šesť hodín. Beží to preto ako jeden krátky úsek, ktorý si
# na konci cez `workflow_dispatch` spustí ďalší beh toho istého workflowu –
# reťaz behov strop nemá. `workflow_dispatch` cez `GITHUB_TOKEN` beh spustí; je
# to výslovná výnimka z pravidla, že udalosti z neho ďalšie behy nespúšťajú.
#
# Štafetový kolík je vstup `pokracovanie`, štyri polia oddelené `|`:
#
#   <id behu>:<kraj>|<kraje, čo ešte neboli>|<hotové>|<číslo úseku>
#
# Prázdny kolík = prvý úsek, zoznam krajov sa vezme z číselníka. Je to vstup
# a nie súbor v repozitári zámerne: stav dávky je vidieť priamo na behu, dá sa
# z neho pokračovať ručne a nevznikajú commity biace sa s `maps.json`.
#
# Spadnutý kraj reťaz nezastaví – zapíše sa do kolíka a posledný úsek na ňom
# spadne, aby dávka neskončila zelená s dierou v mape.
#
# Zrušenie je opak: „dosť, zastav to". V API vyzerá skoro rovnako ako pád, tak
# sa rozlišuje a platí oboje – zrušený beh kraja ukončí reťaz, zrušená dávka
# cez `trap` zruší aj beh kraja, na ktorý čakala. Zastavená dávka nie je
# spadnutá dávka: skončí zelená a do súhrnu napíše, čo ostalo a ako pokračovať.
# (Zrušiť beh môže aj GitHub sám, keď sú tri behy v jednej `concurrency`
# skupine, a od ručného zrušenia sa to nedá odlíšiť.)
#
# Volajúci musí dodať: COUNTRY REPO (voliteľne REF SELF REGION_WF SUMMARY),
# TITUL a POPIS do súhrnu, funkcie `odovzdaj` a `spusti_kraj`, a na konci
# zavolať `estafeta_hlavna`.
set -euo pipefail

COUNTRY="${COUNTRY:?chýba krajina}"
REPO="${REPO:?chýba repozitár}"
POKRACOVANIE="${POKRACOVANIE:-}"
REF="${REF:-master}"
REGION_WF="${REGION_WF:?chýba workflow kraja}"
# meno workflowu kraja tak, ako sa volá vo formulári – do hlášky o tom, čo si
# má človek pustiť ručne
REGION_MENO="${REGION_MENO:-$REGION_WF}"
SUMMARY="${SUMMARY:-${GITHUB_STEP_SUMMARY:-/dev/null}}"
SERVER="${GITHUB_SERVER_URL:-https://github.com}"

# koľko sa v jednom úseku čaká, kým sa štafeta odovzdá ďalej. Job má strop
# šesť hodín; päť stačí na najdlhší kraj a hodina ostáva na spustenie ďalšieho
# článku – inak by GitHub zabil job presne v kroku, ktorý reťaz predlžuje.
CAKANIE_MAX_S="${CAKANIE_MAX_S:-18000}"    # 5 h
POLL_S="${POLL_S:-60}"
# poistka proti nekonečnej reťazi; na kraj stačia tri úseky aj v najhoršom
USEKOV_NA_KRAJ=3

log() { echo "$@"; }
sumar() { echo "$@" >> "$SUMMARY"; }

# spánok, ktorý sa dá prerušiť: `sleep 60` je popredný príkaz a trap by sa
# vykonal až po ňom – teda po minúte, ktorú nám GitHub pri zrušení nedá
cakaj() {
  sleep "$1" &
  wait "$!" 2>/dev/null || true
}

# zrušený beh dávky zruší aj kraj, na ktorý čakal – inak by kraj bežal ešte
# hodiny. Best effort: GitHub dá kroku pár sekúnd, teda na jedno volanie API.
pri_zruseni() {
  trap - INT TERM
  if [ -n "${BEZI_ID:-}" ]; then
    log "Beh dávky bol zrušený – ruším aj beh kraja ${BEZI_KRAJ:-?} ($BEZI_ID)."
    gh run cancel "$BEZI_ID" --repo "$REPO" 2>/dev/null || \
      log "::warning::Beh kraja $BEZI_ID sa nepodarilo zrušiť – zruš ho ručne, inak dobehne do konca."
  fi
  exit 130
}
trap pri_zruseni INT TERM

odkaz() { echo "$SERVER/$REPO/actions/runs/$1"; }

# súhrn: celý obraz v každom úseku. `GITHUB_STEP_SUMMARY` patrí jednému behu
# a články štafety sú samostatné behy, takže sa celá tabuľka skladá z kolíka.
# Funkcia preto, že to isté treba napísať aj pri predčasnom konci úseku.
SPADLO=0
napis_sumar() {
  sumar "## $TITUL"
  sumar ""
  sumar "Úsek štafety **$USEK**. $POPIS"
  sumar ""
  sumar "| kraj | stav |"
  sumar "| --- | --- |"
  SPADLO=0
  local kraj h riadok zvys vysl hid
  for kraj in $(echo "$VSETKY" | tr ',' ' '); do
    riadok=""
    for h in $(echo "$HOTOVE" | tr ',' ' '); do
      [ "${h%%:*}" = "$kraj" ] || continue
      zvys="${h#*:}"; vysl="${zvys%%:*}"; hid="${zvys#*:}"
      if [ "$vysl" = "success" ]; then
        riadok="| \`$kraj\` | ✅ hotovo ([beh]($(odkaz "$hid"))) |"
      else
        riadok="| \`$kraj\` | ❌ $vysl ([beh]($(odkaz "$hid"))) |"
        SPADLO=$(( SPADLO + 1 ))
      fi
    done
    if [ -z "$riadok" ] && [ "$kraj" = "$BEZI_KRAJ" ]; then
      riadok="| \`$kraj\` | ⏳ beží ([beh]($(odkaz "$BEZI_ID"))) |"
    fi
    sumar "${riadok:-"| \`$kraj\` | · čaká |"}"
  done
  sumar ""
}

estafeta_hlavna() {
  # rozbaľ kolík
  IFS='|' read -r POLE_BEZI ZOSTAVA HOTOVE USEK <<< "$POKRACOVANIE"
  POLE_BEZI="${POLE_BEZI:-}"; ZOSTAVA="${ZOSTAVA:-}"
  HOTOVE="${HOTOVE:-}";       USEK="${USEK:-0}"
  BEZI_ID="${POLE_BEZI%%:*}"
  BEZI_KRAJ="${POLE_BEZI#*:}"
  [ "$POLE_BEZI" = "$BEZI_ID" ] && BEZI_KRAJ=""

  VSETKY="$(python3 workers/state/queue.py --kraje="$COUNTRY" | paste -sd, -)"
  if [ -z "$POKRACOVANIE" ]; then
    # prvý úsek: zoznam krajov z číselníka, nie z formulára – inak by
    # pribudnutý kraj v dávke ticho chýbal
    ZOSTAVA="$VSETKY"
    log "Dávka pre krajinu $COUNTRY: $ZOSTAVA"
  fi
  USEK=$(( USEK + 1 ))
  POCET_KRAJOV="$(echo "$VSETKY" | tr ',' '\n' | grep -c .)"
  USEKOV_MAX=$(( POCET_KRAJOV * USEKOV_NA_KRAJ + 2 ))
  if [ "$USEK" -gt "$USEKOV_MAX" ]; then
    echo "::error::Štafeta má za sebou $USEK úsekov, čo je viac než $USEKOV_MAX pre $POCET_KRAJOV krajov – reťaz sa neskracuje a ďalší článok už nespustím. Pozri kolík: pokracovanie=$POKRACOVANIE"
    exit 1
  fi
  log "Úsek $USEK z najviac $USEKOV_MAX. Beží „${BEZI_KRAJ:-(nič)}“ ($BEZI_ID), zostáva „${ZOSTAVA:-(nič)}“."

  # 1. počkaj na kraj, ktorý beží
  if [ -n "$BEZI_ID" ]; then
    local zaciatok stav vysledok
    zaciatok=$(date +%s)
    stav=""
    while :; do
      stav="$(gh run view "$BEZI_ID" --repo "$REPO" --json status,conclusion \
                --jq '.status + " " + (.conclusion // "")' 2>/dev/null || true)"
      case "$stav" in
        completed*) break ;;
        "") log "::warning::Beh $BEZI_ID sa nedá prečítať (výpadok API?) – skúšam ďalej." ;;
      esac
      if [ $(( $(date +%s) - zaciatok )) -ge "$CAKANIE_MAX_S" ]; then
        # kraj beží dlhšie, než sa do tohto jobu zmestí – štafeta ide ďalej
        # s tým istým kolíkom
        log "Kraj $BEZI_KRAJ beží dlhšie než $((CAKANIE_MAX_S / 3600)) h – odovzdávam štafetu ďalej."
        odovzdaj "$POLE_BEZI|$ZOSTAVA|$HOTOVE|$USEK"
        napis_sumar
        sumar "Kraj **$BEZI_KRAJ** ešte beží dlhšie než $((CAKANIE_MAX_S / 3600)) h – čaká naň ďalší článok štafety."
        exit 0
      fi
      cakaj "$POLL_S"
    done
    vysledok="${stav#completed }"
    vysledok="${vysledok:-neznámy}"
    log "Kraj $BEZI_KRAJ (beh $BEZI_ID) skončil: $vysledok"
    HOTOVE="${HOTOVE:+$HOTOVE,}$BEZI_KRAJ:$vysledok:$BEZI_ID"
    # zrušený kraj zastaví celú dávku: je to rozhodnutie človeka a jediné, ako
    # ho vie povedať behu, ktorý práve beží
    if [ "$vysledok" = "cancelled" ]; then
      ZOSTAVA_PRED="$ZOSTAVA"
      BEZI_ID=""; BEZI_KRAJ=""; POLE_BEZI=""; ZOSTAVA=""
      napis_sumar
      sumar "**Dávka zastavená.** Beh kraja bol zrušený, takže sa ďalší kraj"
      sumar "nespúšťa a reťaz štafety tu končí."
      if [ -n "$ZOSTAVA_PRED" ]; then
        # kolík na pokračovanie – zrušenie nemusí byť rozhodnutie človeka
        # (GitHub zruší beh aj sám). Prázdne prvé pole = „na nič sa nečaká,
        # spusti prvý zo zostávajúcich".
        sumar ""
        sumar "Nepostavené ostali: \`$ZOSTAVA_PRED\`. Pokračovať sa dá tou istou"
        sumar "dávkou s kolíkom \`|$ZOSTAVA_PRED|$HOTOVE|0\` v poli \`pokracovanie\`."
      fi
      log "Kraj bol zrušený – dávka končí. Nepostavené: ${ZOSTAVA_PRED:-(nič)}"
      return 0
    fi
    if [ "$vysledok" != "success" ]; then
      log "::warning::Kraj $BEZI_KRAJ skončil ako $vysledok. Dávka pokračuje ďalším krajom – posledný článok na tom spadne, aby dávka neskončila zelená s dierou v mape."
    fi
    BEZI_ID=""; BEZI_KRAJ=""; POLE_BEZI=""
  fi

  # 2. spusti ďalší kraj
  NOVY_KOLIK=""
  if [ -n "$ZOSTAVA" ]; then
    local kraj zvysok pred id
    kraj="${ZOSTAVA%%,*}"
    zvysok="${ZOSTAVA#*,}"
    [ "$zvysok" = "$ZOSTAVA" ] && zvysok=""
    log "Spúšťam kraj $kraj …"
    # čas pred spustením: beh sa hľadá podľa toho, že vznikol po ňom –
    # `workflow_dispatch` id nevracia (204)
    pred="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    spusti_kraj "$kraj"
    id=""
    for _ in $(seq 1 30); do
      sleep 5
      id="$(gh run list --repo "$REPO" --workflow "$REGION_WF" \
              --event workflow_dispatch --branch "$REF" --limit 20 \
              --json databaseId,createdAt \
              --jq "[.[] | select(.createdAt >= \"$pred\")] | sort_by(.createdAt) | last | .databaseId" \
            2>/dev/null || true)"
      [ -n "$id" ] && [ "$id" != "null" ] && break
      id=""
    done
    if [ -z "$id" ]; then
      # bez id sa nedá počkať, a čakať sa musí: dva kraje naraz by si liezli
      # do cache aj do katalógu
      echo "::error::Kraj $kraj som spustil, ale jeho beh sa do dvoch minút neobjavil v zozname behov $REGION_WF. Bez jeho id sa naň nedá počkať, takže reťaz tu končí – zvyšné kraje ($kraj,$zvysok) spusti dávkou znova."
      exit 1
    fi
    log "Kraj $kraj beží ako $id ($(odkaz "$id"))"
    # zapísať pred odovzdaním štafety, nech `trap` vie, ktorý kraj zrušiť
    BEZI_ID="$id"; BEZI_KRAJ="$kraj"; ZOSTAVA="$zvysok"
    NOVY_KOLIK="$id:$kraj|$zvysok|$HOTOVE|$USEK"
    odovzdaj "$NOVY_KOLIK"
  fi

  napis_sumar

  if [ -n "$NOVY_KOLIK" ]; then
    sumar "Ďalší článok štafety je spustený; kolík: \`$NOVY_KOLIK\`"
    exit 0
  fi

  # koniec reťaze
  sumar "**Dávka je hotová.**"
  if [ "$SPADLO" -gt 0 ]; then
    echo "::error::Dávka pre $COUNTRY dobehla, ale $SPADLO kraj(ov) skončilo neúspešne – v mape krajiny je diera. Zoznam je v súhrne; spadnuté kraje pusti znova jednotlivo cez „$REGION_MENO“."
    exit 1
  fi
  log "Dávka pre $COUNTRY je hotová – všetky kraje prešli."
}
