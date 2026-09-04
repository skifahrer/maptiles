#!/usr/bin/env bash
# JADRO ŠTAFETY – spoločné pre obe dávky nad krajinou:
#
#   Mapa · Build map state       postav každý kraj (workers/state/relay.sh)
#   Mapa · Regenerate state      pregeneruj jednu vrstvu v každom kraji
#                                (workers/state/regenerate.sh)
#
# Obe robia to isté: idú krajmi JEDEN PO DRUHOM, čakajú na beh kraja a potom
# spustia ďalší. Líšia sa len tým, ČO nad krajom spúšťajú a s akými poľami –
# a to je presne to, čo si každá z nich definuje sama (funkcie `odovzdaj`
# a `spusti_kraj` nižšie). Keby bola štafeta napísaná dvakrát, rozišla by sa
# v tom najhoršom mieste: jedna dávka by po zmene vedela pokračovať a druhá
# by ticho skončila prvým krajom, a to zelená (pravidlo 1 v CLAUDE.md).
#
# ── PREČO ŠTAFETA A NIE JEDEN DLHÝ JOB ────────────────────────────────────
# Kraj sa stavia aj tri hodiny a krajov je osem, čiže celá dávka je zhruba
# deň. Job na GitHube má strop ŠESŤ HODÍN a po ňom ho GitHub zabije –
# dispečer napísaný ako „spusti a čakaj, spusti a čakaj" by teda spoľahlivo
# umrel v polovici: tri kraje hotové, zvyšok nikdy, a v behu nič, čo by
# povedalo, že zvyšok nepríde.
#
# Beží to preto ako JEDEN KRÁTKY ÚSEK, ktorý si na konci spustí ďalší beh
# toho istého workflowu (`workflow_dispatch`). Reťaz behov strop nemá – každý
# článok je nový job s vlastnými šiestimi hodinami.
#
# `workflow_dispatch` cez `GITHUB_TOKEN` beh SPUSTÍ. Je to výslovná výnimka
# z pravidla „udalosti z GITHUB_TOKENu nespúšťajú ďalšie behy" (spolu
# s `repository_dispatch`) – práve preto je štafeta postavená na ňom a nie
# na pushi, ktorý by ticho nespravil nič a žiadal by osobný token v secrete.
#
# ── ČO NESIE ŠTAFETOVÝ KOLÍK ──────────────────────────────────────────────
# Vstup `pokracovanie`, štyri polia oddelené `|`:
#
#   <id behu>:<kraj>|<kraje, čo ešte neboli>|<hotové>|<číslo úseku>
#           │           │                      │
#           │           │                      └ `kraj:výsledok:id`, čiarkami
#           │           └ čiarkami, v poradí číselníka
#           └ na tento beh sa čaká; prázdne = prvý úsek
#
# Prázdny kolík = prvý úsek: zoznam krajov sa vezme z číselníka
# (`workers/state/queue.py`). Je to VSTUP a nie súbor v repozitári zámerne –
# stav dávky je tak vidieť priamo na behu (Actions → beh → inputs), dá sa
# z neho pokračovať ručne a nevznikajú z neho commity, ktoré by sa bili
# s `maps.json`, ktorý práve zapisuje bežiaci kraj.
#
# ── KEĎ KRAJ SPADNE, DÁVKA IDE ĎALEJ ──────────────────────────────────────
# Zmysel dávky je „sprav to nad celým Slovenskom a nechaj ma tak". Spadnutý
# kraj preto reťaz nezastaví; zapíše sa do kolíka a POSLEDNÝ úsek na ňom
# spadne, aby dávka neskončila zelená s dierou v mape. Kto chce zastaviť
# všetko, zruší posledný beh reťaze – ďalší článok už nevznikne.
#
# ── ČO MUSÍ DODAŤ VOLAJÚCI ────────────────────────────────────────────────
# Premenné: COUNTRY REPO (a voliteľne REF SELF REGION_WF SUMMARY)
#           TITUL   nadpis súhrnu
#           POPIS   odsek pod ním – čo tá dávka vlastne robí
# Funkcie:  odovzdaj <kolík>   spusti ďalší svoj beh s tým istým formulárom
#           spusti_kraj <kraj> spusti beh nad jedným krajom
# Na konci: estafeta_hlavna
set -euo pipefail

COUNTRY="${COUNTRY:?chýba krajina}"
REPO="${REPO:?chýba repozitár}"
POKRACOVANIE="${POKRACOVANIE:-}"
REF="${REF:-master}"
REGION_WF="${REGION_WF:?chýba workflow kraja}"
# Meno workflowu kraja tak, ako sa volá vo formulári GitHubu –
# do hlášky, v ktorej sa hovorí, čo si má človek pustiť ručne.
REGION_MENO="${REGION_MENO:-$REGION_WF}"
SUMMARY="${SUMMARY:-${GITHUB_STEP_SUMMARY:-/dev/null}}"
SERVER="${GITHUB_SERVER_URL:-https://github.com}"

# Koľko sa v jednom úseku čaká, kým sa štafeta odovzdá ďalej. Job má strop
# šesť hodín; päť stačí na najdlhší kraj a hodina ostáva na to, aby sa stihol
# spustiť ďalší článok. Keby sa čakalo do posledného dychu, GitHub by job
# zabil PRESNE v kroku, ktorý reťaz predlžuje – a dávka by ticho skončila.
CAKANIE_MAX_S="${CAKANIE_MAX_S:-18000}"    # 5 h
POLL_S="${POLL_S:-60}"
# Poistka proti nekonečnej reťazi: keby sa zoznam z akéhokoľvek dôvodu
# neskracoval, dávka by sa spúšťala donekonečna a míňala bežce. Na kraj
# stačia tri úseky (spustenie + dve predĺženia čakania) aj v najhoršom.
USEKOV_NA_KRAJ=3

log() { echo "$@"; }
sumar() { echo "$@" >> "$SUMMARY"; }

odkaz() { echo "$SERVER/$REPO/actions/runs/$1"; }

# ---------- súhrn ----------
# CELÝ OBRAZ V KAŽDOM ÚSEKU. Súhrn behu (`GITHUB_STEP_SUMMARY`) patrí JEDNÉMU
# behu a články štafety sú samostatné behy – keby si každý zapísal len svoj
# riadok, stav dávky by nebol nikde a musel by sa poskladať z ôsmich behov.
# Celá tabuľka sa preto skladá z kolíka a je čitateľná na ktoromkoľvek článku.
# Funkcia preto, že to isté treba napísať aj vtedy, keď sa úsek končí
# predčasne (kraj beží dlhšie než rozpočet úseku).
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
  # ---------- rozbaľ kolík ----------
  IFS='|' read -r POLE_BEZI ZOSTAVA HOTOVE USEK <<< "$POKRACOVANIE"
  POLE_BEZI="${POLE_BEZI:-}"; ZOSTAVA="${ZOSTAVA:-}"
  HOTOVE="${HOTOVE:-}";       USEK="${USEK:-0}"
  BEZI_ID="${POLE_BEZI%%:*}"
  BEZI_KRAJ="${POLE_BEZI#*:}"
  [ "$POLE_BEZI" = "$BEZI_ID" ] && BEZI_KRAJ=""

  VSETKY="$(python3 workers/state/queue.py --kraje="$COUNTRY" | paste -sd, -)"
  if [ -z "$POKRACOVANIE" ]; then
    # Prvý úsek: zoznam krajov z číselníka, nie z formulára. Keby sa písal do
    # formulára, pribudnutý kraj by v dávke ticho chýbal.
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

  # ---------- 1. počkaj na kraj, ktorý beží ----------
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
        # Kraj beží dlhšie, než sa do tohto jobu zmestí. Štafeta ide ďalej
        # s TÝM ISTÝM kolíkom – ďalší článok čaká odznova a tento skončí skôr,
        # než ho GitHub zabije.
        log "Kraj $BEZI_KRAJ beží dlhšie než $((CAKANIE_MAX_S / 3600)) h – odovzdávam štafetu ďalej."
        odovzdaj "$POLE_BEZI|$ZOSTAVA|$HOTOVE|$USEK"
        napis_sumar
        sumar "Kraj **$BEZI_KRAJ** ešte beží dlhšie než $((CAKANIE_MAX_S / 3600)) h – čaká naň ďalší článok štafety."
        exit 0
      fi
      sleep "$POLL_S"
    done
    vysledok="${stav#completed }"
    vysledok="${vysledok:-neznámy}"
    log "Kraj $BEZI_KRAJ (beh $BEZI_ID) skončil: $vysledok"
    if [ "$vysledok" != "success" ]; then
      log "::warning::Kraj $BEZI_KRAJ skončil ako $vysledok. Dávka pokračuje ďalším krajom – posledný článok na tom spadne, aby dávka neskončila zelená s dierou v mape."
    fi
    HOTOVE="${HOTOVE:+$HOTOVE,}$BEZI_KRAJ:$vysledok:$BEZI_ID"
    BEZI_ID=""; BEZI_KRAJ=""; POLE_BEZI=""
  fi

  # ---------- 2. spusti ďalší kraj ----------
  NOVY_KOLIK=""
  if [ -n "$ZOSTAVA" ]; then
    local kraj zvysok pred id
    kraj="${ZOSTAVA%%,*}"
    zvysok="${ZOSTAVA#*,}"
    [ "$zvysok" = "$ZOSTAVA" ] && zvysok=""
    log "Spúšťam kraj $kraj …"
    # Čas PRED spustením: beh sa hľadá podľa toho, že vznikol po ňom. Vrátiť
    # id priamo `workflow_dispatch` nevie (API odpovedá prázdnym 204).
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
      # Bez id sa nedá počkať, a čakať sa MUSÍ: dva kraje naraz by si liezli do
      # cache aj do katalógu. Radšej spadnúť tu, kým je vidieť, na čom.
      echo "::error::Kraj $kraj som spustil, ale jeho beh sa do dvoch minút neobjavil v zozname behov $REGION_WF. Bez jeho id sa naň nedá počkať, takže reťaz tu končí – zvyšné kraje ($kraj,$zvysok) spusti dávkou znova."
      exit 1
    fi
    log "Kraj $kraj beží ako $id ($(odkaz "$id"))"
    NOVY_KOLIK="$id:$kraj|$zvysok|$HOTOVE|$USEK"
    odovzdaj "$NOVY_KOLIK"
    BEZI_ID="$id"; BEZI_KRAJ="$kraj"; ZOSTAVA="$zvysok"
  fi

  napis_sumar

  if [ -n "$NOVY_KOLIK" ]; then
    sumar "Ďalší článok štafety je spustený; kolík: \`$NOVY_KOLIK\`"
    exit 0
  fi

  # ---------- koniec reťaze ----------
  sumar "**Dávka je hotová.**"
  if [ "$SPADLO" -gt 0 ]; then
    echo "::error::Dávka pre $COUNTRY dobehla, ale $SPADLO kraj(ov) skončilo neúspešne – v mape krajiny je diera. Zoznam je v súhrne; spadnuté kraje pusti znova jednotlivo cez „$REGION_MENO“."
    exit 1
  fi
  log "Dávka pre $COUNTRY je hotová – všetky kraje prešli."
}
