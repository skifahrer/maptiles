#!/usr/bin/env bash
# Zapni GitHub Pages a prepni zdroj na Actions – a keď sa nedá, povedz to.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 KiB.
#
# Pri zdroji „z vetvy" nasadenie funguje, len mapu prepíše najbližší push do
# master. Kým sa to prepínalo natvrdo, beh na tom padal (`GITHUB_TOKEN` na
# zmenu nastavenia repozitára nestačí) a mapa nebola žiadna. Preto: skúsiť,
# nahlas povedať, čo API odpovedalo, a ísť ďalej.
#
# Vstup:  GH_TOKEN, GITHUB_REPOSITORY
# Výstup: `build_type` do GITHUB_OUTPUT – `workflow`, keď berie z Actions.

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
