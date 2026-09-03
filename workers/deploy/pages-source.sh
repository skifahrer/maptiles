#!/usr/bin/env bash
# Zapni GitHub Pages a prepni zdroj na Actions – a keď sa nedá, povedz to.
#
# PREČO SKRIPT A NIE `run:` BLOK: `build-map-region.yml` je pri strope 128 KiB, nad
# ktorým GitHub workflow TICHO NEPRIJME (rozpis v hlavičke `roads.yml`), a
# veľký `run:` blok patrí do `workers/` (pravidlo 3 v CLAUDE.md). Obsah je ten
# istý, čo v ňom bol – nič sa v ňom nemení.
#
# PREČO TO VÔBEC EXISTUJE: pri zdroji Pages „z vetvy" nasadenie funguje, len
# mapu prepíše najbližší push do master. Kým sa to skúšalo prepnúť natvrdo,
# beh na tom PADAL – `GITHUB_TOKEN` na zmenu nastavenia repozitára nestačí –
# a mapa nebola ŽIADNA. Radšej mapa, ktorá vydrží do ďalšieho mergu, než nič:
# skúsiť, nahlas povedať, čo API odpovedalo, a ísť ďalej. Odpoveď sa NEZAHADZUJE
# do /dev/null – bez nej sa z logu nedalo zistiť, či je to chýbajúce právo,
# alebo niečo iné.
#
# Vstup:  GH_TOKEN (`github.token`), GITHUB_REPOSITORY
# Výstup: `build_type` do GITHUB_OUTPUT – `workflow`, keď berie z Actions.
#         Ide von, aby to súhrn vedel povedať nahlas a smoke test vedel, či je
#         prázdny koreň stránky chyba, alebo známa príčina.

set -uo pipefail
RUCNE="Nastav to ručne raz: Settings → Pages → Build and deployment → Source: 'GitHub Actions'."
# Ohlásená vopred, nie až v `if ODPOVED=$(…)`: pod `set -u` je premenná, ktorá
# vznikne len vo vetve, tá istá trieda tichého omylu ako chýbajúce `env:`.
ODPOVED=""

PAGES=$(gh api "repos/$GITHUB_REPOSITORY/pages" 2>/dev/null || true)

if [ -z "$PAGES" ]; then
  echo "GitHub Pages nie je zapnuté – zapínam so zdrojom GitHub Actions…"
  if ODPOVED=$(gh api -X POST "repos/$GITHUB_REPOSITORY/pages" \
       -f 'build_type=workflow' 2>&1); then
    echo "  ✓ zapnuté"
    PAGES=$(gh api "repos/$GITHUB_REPOSITORY/pages" 2>/dev/null || true)
  else
    echo "  API odpovedalo: $ODPOVED"
    # Bez zapnutých Pages sa nasadiť NEDÁ – tu zastaviť treba.
    echo "::error::GitHub Pages nie je zapnuté a tokenu sa ho nepodarilo zapnúť (na to treba admin práva). $RUCNE"
    exit 1
  fi
fi

BT=$(printf '%s' "$PAGES" | jq -r '.build_type // "?"')
if [ "$BT" != 'workflow' ]; then
  echo "Pages berie zdroj z vetvy (build_type=$BT) – skúšam prepnúť na GitHub Actions…"
  if ODPOVED=$(gh api -X PUT "repos/$GITHUB_REPOSITORY/pages" \
       -f 'build_type=workflow' 2>&1); then
    # Overiť, a nie veriť: keby PUT prešlo a nastavenie ostalo staré,
    # build by dobehol do zelena a na stránke by aj tak bolo README.
    BT=$(gh api "repos/$GITHUB_REPOSITORY/pages" --jq '.build_type // "?"' 2>/dev/null || echo '?')
    [ "$BT" = 'workflow' ] && echo "  ✓ prepnuté (build_type=$BT)"
  else
    echo "  API odpovedalo: $ODPOVED"
  fi
fi

echo "build_type=$BT" >> "$GITHUB_OUTPUT"
if [ "$BT" != 'workflow' ]; then
  # VAROVANIE, nie chyba. Mapa sa nasadí a bude na stránke; zmizne
  # až pri najbližšom pushi do master, keď ju prepíše zabudovaný
  # Jekyll builder obsahom repozitára (uvidíš README).
  echo "::warning::GitHub Pages berie zdroj z vetvy (build_type=$BT), nie z Actions, a tokenu sa to nepodarilo prepnúť. Mapa sa nasadí, ale najbližší push do master ju prepíše obsahom repozitára (uvidíš README). $RUCNE"
else
  echo "Pages je zapnuté a berie z Actions ✓ – nasadí sa mapa z tohto behu"
fi
