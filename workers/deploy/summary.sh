#!/usr/bin/env bash
# Súhrn behu „Build map" do záložky Summary: čo sa robilo, ako dlho a s akým
# detailom. Riadky si každý job odložil do svojho `steps-*` artefaktu; `deploy`
# ich zlepí a zoradí podľa poradového čísla, nie podľa času – joby bežia
# súbežne, takže čas by hovoril o tom, ktorý runner bol rýchlejší.
#
# Vlastný skript, lebo build-map-region.yml je pri strope 128 KiB.
#
# Hodnoty chodia cez prostredie (viď krok „Súhrn buildu"): R_* výsledky jobov,
# SRC_*/USED_* zdroje vrstiev, SIZE_LIMIT_MB, PAGE_URL, PUBLISH_PAGES,
# PAGES_BUILD_TYPE, REGION_KEY, TEST_*, INPUTS_JSON. A `gh` a GITHUB_* od runnera.

set -uo pipefail
S="$GITHUB_STEP_SUMMARY"
hms() { printf '%d:%02d:%02d' $(( $1 / 3600 )) $(( $1 % 3600 / 60 )) $(( $1 % 60 )); }

# celkový čas je čas workflowu, nie tohto jobu – joby bežia súbežne
STARTED=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  -q .run_started_at 2>/dev/null || echo '')
if [ -n "$STARTED" ]; then
  TOTAL=$(( $(date +%s) - $(date -d "$STARTED" +%s) ))
else
  TOTAL=0
fi

{
  echo "# ${REGION_NAME}"
  echo
  echo "Celý beh: **$(hms "$TOTAL")** (joby bežali súbežne, súčet nižšie je väčší)"
  echo
  echo "| job | výsledok |"
  echo "|---|---|"
  echo "| Príprava | ${R_PLAN} |"
  echo "| Vrstevnice a skaly | ${R_CONTOURS} |"
  echo "| Skaly z tieňovania | ${R_SHADING_ROCKS} |"
  echo "| Značené trasy | ${R_TRAILS} |"
  echo "| Krajinné prvky | ${R_FEATURES:-–} |"
  echo "| Tieňovanie a 3D terén | ${R_TERRAIN} |"
  echo "| Mapové dlaždice | ${R_TILES} |"
  echo "| Ikonky a fonty | ${R_ASSETS} |"
  echo
  echo "## Čo sa robilo"
  echo
  echo "| krok | trvanie | výsledok |"
  echo "|---|--:|---|"
} >> "$S"

if [ -d steps-out ] && [ -n "$(find steps-out -name '*.tsv' 2>/dev/null)" ]; then
  # prvé pole je len na zoradenie
  cat steps-out/*.tsv | sort -n | while IFS=$'\t' read -r _ord name secs detail; do
    [ -n "$name" ] || continue
    printf '| %s | %s | %s |\n' "$name" "$(hms "${secs:-0}")" "$detail" >> "$S"
  done
else
  echo "| — | — | žiadny job sa nedostal po prvý meraný krok |" >> "$S"
fi

# detail skál: čísla píše rock-areas.py, job s vrstevnicami ich pribalil
# k meraniu krokov
if [ -s steps-out/rock-stats.txt ]; then
  # shellcheck disable=SC1091
  . steps-out/rock-stats.txt
fi

# „Dáta · tieňované skaly" majú vlastnú tabuľku: nemajú sklon, mriežku ani
# bunku DEM, takže tá dole by bola stĺpec otáznikov
if [ "${source:-dem}" = "tienovanie" ]; then
  {
    echo
    echo "## Skalné plochy – z tieňovaných dlaždíc"
    echo
    echo "| vlastnosť | hodnota |"
    echo "|---|---|"
    echo "| územie | ${area_name:-celý región}${area_bbox:+ (\`$area_bbox\`)} |"
    echo "| počet samostatných plôch | ${count:-?} |"
    echo "| zdroj | ${asset:-release dem-rocks-img} |"
    echo
    # buď si build hotové polygóny stiahol, alebo si podpipeline zavolal a tá
    # ich v tomto behu spočítala – kým to bola jedna veta, tvrdila to prvé aj
    # v druhom prípade
    if [ "${R_SHADING_ROCKS:-skipped}" = 'success' ]; then
      echo "Tieto skaly **spočítal tento beh** – job *Skaly z tieňovania*,"
      echo "ktorý si build zavolal sám. Hľadá ich ako tmavé plochy"
      echo "v hillshade JPG dlaždiciach z freemap.sk (nie zo sklonu"
      echo "výškového modelu), a hotové polygóny uložil do releasu"
      echo "\`dem-rocks-img\`. Podrobné čísla (prahy, zoom, koľko dlaždíc)"
      echo "sú v jeho časti tohto behu."
    else
      echo "Tieto skaly sa v tomto behu **nepočítali**. Našiel ich workflow"
      echo "*Dáta · tieňované skaly* ako tmavé plochy v hillshade JPG"
      echo "z freemap.sk a build si ich len stiahol z releasu \`dem-rocks-img\`."
      echo "Podrobné čísla (prahy, zoom, koľko dlaždíc) sú v súhrne toho behu."
    fi
    echo
    echo "> ⚠️ Hillshade je osvetlený z jednej strany, takže sú v ňom tmavé"
    echo "> **severozápadné** steny a svetlé juhovýchodné. Táto vrstva teda"
    echo "> časť skál systematicky nemá. Skaly zo sklonu výškového modelu"
    echo "> (\`rock_source: sonny\` / \`dmr35\` / \`dmr5\` / \`ugkk\`) touto"
    echo "> vadou netrpia."
  } >> "$S"
elif [ -s steps-out/rock-stats.txt ]; then
  {
    echo
    echo "## Skalné plochy – aký to je detail"
    echo
    echo "| vlastnosť | hodnota |"
    echo "|---|---|"
    echo "| územie | ${area_name:-celý región}${area_bbox:+ (\`$area_bbox\`)} |"
    echo "| výškový model | ${rock_dem:-?} |"
    echo "| počet samostatných plôch | ${count:-?} |"
    echo "| obrys sa počíta na mriežke | ${grid_m:-?} m |"
    echo "| buniek sklonu / čas výpočtu | ${cells_g:-?} mld. / ${took:-?} |"
    echo "| bunka zdrojového DEM (${rock_dem:-?}) | ~${dem_cell_m:-?} m → **strop skutočného detailu** |"
    echo "| najmenšia ponechaná plocha | ${min_area_m2:-?} m² |"
    echo "| skutočne najmenšia plocha | ${min_m2:-?} m² |"
    echo "| priemerná plocha | ${avg_m2:-?} m² |"
    echo "| najväčšia plocha | ${max_ha:-?} ha |"
    echo "| skalného terénu spolu | ${total_km2:-?} km² |"
    if [ "${plne:-1}" = '1' ]; then
      echo "| prah sklonu | ≥ ${slope_deg:-?}° (krok ${slope_step_deg:-?}°), jedna trieda |"
    else
      echo "| prah sklonu | ≥ ${slope_deg:-?}° (steny od ${cliff_deg:-?}°, krok ${slope_step_deg:-?}°) |"
    fi
    if [ "${zapln_diery:-0}" = '1' ]; then
      echo "| diery | **zaplnené** (\`rock_zapln_diery=1\`) – detail tvaru je preč |"
    else
      echo "| plôch s dierou (miesto pod prahom vnútri skaly) | ${with_holes:-0} |"
      echo "| vykrojené dierami | ${holes_km2:-0} km² |"
    fi
    echo "| zjednodušenie obrysu | ${simplify_m:-?} m |"
    echo "| zaoblenie rohov | priehyb ${smooth_sag:-0}/4 kroku mriežky dlaždice |"
    echo
    echo "Obrys je izolínia sklonu – plocha má tvar, aký terén naozaj má."
    if [ "${zapln_diery:-0}" = '1' ]; then
      echo "Diery sú **zaplnené** (\`options: rock_zapln_diery=1\`), takže"
      echo "z každej skaly je súvislá plocha bez vnútorného tvaru. Vypnutie"
      echo "toho prepínača vráti police a medzery tam, kam patria."
    else
      echo "Kde je vnútri steny miesto s menším sklonom (polica, terasa),"
      echo "vypadne z plochy **diera** a nezafarbí sa – aj keď je dookola"
      echo "všade sklon nad prahom. Práve tie diery robia tvar skaly"
      echo "čitateľným."
    fi
    if [ "${area_key:-cely}" != "cely" ]; then
      echo
      echo "> ⚠️ **Vrstevnice aj skaly sú len na výreze „${area_name}“.**"
      echo "> Vo zvyšku regiónu nebude v mape ani jedno – toto je beh"
      echo "> na testovanie, nie na nasadenie. Pre celý región zvoľ"
      echo "> v inpute \`area\` hodnotu \`cely_region\`."
    fi
    echo
    echo "> Mriežka ${grid_m:-?} m hovorí, ako jemne je obrys odkrokovaný;"
    echo "> ale zdrojový DEM má bunku ~${dem_cell_m:-?} m, takže nové detaily"
    echo "> terénu jemnejšia mriežka nevymyslí – len obrys vyhladí a presnejšie"
    echo "> umiestni. Preto \`rock_res=auto\` nejde pod desatinu bunky DEM:"
    echo "> ďalšie zjemňovanie by stálo štvornásobok času za nulový detail."
    echo
    echo "> Zubatosť rieši zaoblenie rohov, nie hrubšia mriežka. Samotná"
    echo "> izolínia zubatá nie je (priemerný lom 4,6°), zubatou ju robí až"
    echo "> zjednodušenie obrysu (28,5°). Roh preto nahradí limitná krivka"
    echo "> (kvadratický B-spline) vzorkovaná tak, aby sa od svojho presného"
    echo "> priebehu neodchýlila viac než o zlomok kroku mriežky dlaždice –"
    echo "> jemnejší detail sa do dlaždice aj tak nezmestí."
  } >> "$S"
fi

# detail značených trás: čísla píše trails/routes.py
if [ -s steps-out/trail-stats.txt ]; then
  # shellcheck disable=SC1091
  . steps-out/trail-stats.txt
  {
    echo
    echo "## Značené trasy – čo sa našlo v OSM"
    echo
    echo "| vlastnosť | hodnota |"
    echo "|---|---|"
    echo "| relácií trás (\`type=route\`) | ${routes:-0} |"
    echo "| z toho pomenovaných | ${named:-0} |"
    echo "| ciest, po ktorých vedie trasa | ${ways:-0} |"
    echo "| úsekov v dlaždiciach (cesta × trasa) | ${features:-0} |"
    echo "| ciest s viac než jednou trasou | ${multi:-0} (najviac naraz ${max_lanes:-0}) |"
    echo "| turistické / cyklo / MTB | ${type_hiking:-0} / ${type_bicycle:-0} / ${type_mtb:-0} |"
    echo "| lyžiarske / jazdecké | ${type_ski:-0} / ${type_horse:-0} |"
    echo "| diaľkové (medzinárodné + národné) | $(( ${tier_international:-0} + ${tier_national:-0} )) |"
    echo "| farby značiek | ${colours:-–} |"
    # zlom nad 120° spoj `miter` nezošije, takže sa v dátach delí
    echo "| rozdelených zlomov nad 120° | ${eased:-0} |"
    echo
    echo "Trasa sa kreslí ako farebný pásik **vedľa** cesty, každá vo"
    echo "svojom pruhu – po jednej ceste ich vedie aj ${max_lanes:-1} naraz"
    echo "a cesta pod nimi zostane vidieť aj s tým, aká je."
  } >> "$S"
fi

{
  echo
  echo "## Rozpočet stránky"
  echo
  echo "| časť | veľkosť |"
  echo "|---|--:|"
  for d in tiles terrain sprites fonts; do
    [ -d "_site/$d" ] && echo "| $d | $(du -sm "_site/$d" | cut -f1) MB |"
  done
  echo "| **spolu** | **$(du -sm _site 2>/dev/null | cut -f1) MB** z ${SIZE_LIMIT_MB} MB |"
  echo
  echo "## Odkiaľ je terén"
  echo
  echo "| vrstva | vybraný zdroj | naozaj použitý |"
  echo "|---|---|---|"
  echo "| vrstevnice | \`${SRC_CONTOURS}\` | ${USED_CONTOURS} |"
  echo "| skaly | \`${SRC_ROCKS}\` | ${USED_ROCKS} |"
  echo "| tieňovanie a 3D | \`${SRC_SHADING}\` | ${USED_SHADING} |"
  echo
  echo "Vybraný a použitý sa líšia len vtedy, keď model nebol"
  echo "k dispozícii a zapol sa náhradný (napr. 1 m ÚGKK → Sonny)."
  if [ "$SRC_ROCKS" = 'tienovanie' ]; then
    echo
    echo "Tieňované dlaždice, z ktorých sú skaly, stiahol v tomto behu"
    echo "job *Skaly z tieňovania* – sú v artefakte"
    echo "\`dlazdice-tienovania-…\` a náhľad mozaiky v \`nahlad-…\`."
  fi
  echo
} >> "$S"

# s čím bol beh spustený tu už nie je zámerne: ten blok píše job `plan` na
# začiatku behu. Keď beh o hodinu spadne, do tohto súhrnu sa nedostane, kým
# súhrn prípravy je na stránke od prvej minúty.

{
  echo "**Ako pregenerovať:** spusti workflow znova a vo výbere"
  echo "\`rebuild\` zvoľ \`vrstevnice\`, \`skaly\` (vrátane uloženej"
  echo "verzie v sklade \`dem-rocks\` a rozrobených obrysov podpipeline"
  echo "\`Dáta · tieňované skaly\`), \`tienovanie\` alebo \`vsetko\`."
  echo "Najprv sa zmaže príslušná cache – inak by sa stará verzia"
  echo "len vrátila späť."
  # tabuľka vyššie ukazuje `rebuild` tak, ako bol vo formulári – pri zapnutom
  # teste by tvrdila `nic`, hoci sa počítalo všetko nanovo
  if [ "${TEST_KM2:-0}" != '0' ]; then
    echo
    echo "V tomto behu to však nebolo treba: **rýchly test pregenerúva vždy"
    echo "všetko**, aj pri \`rebuild: nic\` – inak by si ladil na výsledku,"
    echo "ktorý sa vrátil z cache. Cache ostrého behu to nemaže, testovací"
    echo "štvorec má vlastný kľúč."
  fi
  echo
  echo "**Rýchly testovací beh:** \`area\` (napr. \`vysoke_tatry\`) počíta"
  echo "vrstevnice aj skaly len na výreze – z ~40 minút sa stane ~2."
  echo "Ešte rýchlejší je switch \`test\` (predvolene odškrtnutý): vrstevnice,"
  echo "skaly aj tieňovanie sa spočítajú len na štvorci so 4 km² zo stredu"
  echo "výrezu a mapa sa otvorí rovno tam. **Samotná mapa ostáva celá podľa"
  echo "nastavení regiónu** – kraj, cesty, trasy aj prvky. Iná veľkosť je"
  echo "\`options: test_km2=5\`. Testovací beh sa zapisuje do"
  echo "\`maps-test.json\`, nie do \`maps.json\` – mapa s terénom na pár"
  echo "km² nemá čo robiť v zozname hotových máp."
} >> "$S"

if [ "$PAGE_URL" != '' ]; then
  echo -e "\n[Otvoriť mapu](${PAGE_URL})" >> "$S"
elif [ "${PUBLISH_PAGES:-true}" = 'false' ]; then
  # nie chyba, len rozhodnutie z formulára
  echo -e "\n**Na GitHub Pages sa mapa nenasadila** (\`publish_pages=false\`) –" \
       "hotová je len na Google Drive." >> "$S"
fi

# Pages berie zdroj z vetvy: mapa je nasadená, ale najbližší push do master ju
# prepíše. Beh s tým nemôže spraviť nič – je to nastavenie repozitára.
if [ -n "${PAGES_BUILD_TYPE:-}" ] && [ "$PAGES_BUILD_TYPE" != 'workflow' ]; then
  {
    echo
    echo "> ### ⚠️ Mapu na Pages prepíše najbližší merge"
    echo ">"
    echo "> Zdroj GitHub Pages je nastavený na **vetvu**, nie na Actions"
    echo "> (\`build_type=$PAGES_BUILD_TYPE\`). Popri tomto workflowe preto beží"
    echo "> zabudovaný Jekyll builder (*pages build and deployment*), ktorý pri"
    echo "> každom pushi do \`master\` nasadí koreň repozitára – teda README –"
    echo "> a mapu z tohto behu prepíše."
    echo ">"
    echo "> Mapa je **teraz nasadená a funguje**; zmizne až pri ďalšom mergi."
    echo ">"
    echo "> **Oprava je jednorazová a musíš ju spraviť ty** (token na zmenu"
    echo "> nastavení repozitára práva nemá):"
    echo "> **Settings → Pages → Build and deployment → Source: \`GitHub Actions\`**"
  } >> "$S"
fi

# kde je testovací výrez: obrázok sa nasadil so stránkou, takže má verejnú
# adresu; odkaz mieri na stred testovaného štvorca
if [ "${TEST_KM2:-0}" != '0' ] && [ -n "${TEST_BBOX:-}" ]; then
  python3 workers/plan/test-map.py \
    --bbox="$TEST_BBOX" --full-bbox="${TEST_FULL_BBOX:-}" \
    --name="$REGION_NAME" \
    --layers="vrstevnice: ${SRC_CONTOURS}, skaly: ${SRC_ROCKS}, tieňovanie: ${SRC_SHADING}" \
    --png= --md=/tmp/kde-to-je.md \
    --img-url="${PAGE_URL}kde-to-je.png" \
    --pages-url="$PAGE_URL" --region="${REGION_KEY:-}" || true
  if [ -s /tmp/kde-to-je.md ]; then
    { echo; cat /tmp/kde-to-je.md; } >> "$S"
  else
    { echo; echo "### Testovací výrez"; echo;
      echo "bbox \`${TEST_BBOX}\` (${TEST_KM2} km²) – obrázok sa nepodarilo vyrobiť.";
    } >> "$S"
  fi
fi

# čo spadlo: tabuľka jobov hore povie „failure" a tým to končí. Tu je krok,
# trvanie a posledné `::error::` z logu. Trvanie rozlíši `cancelled` timeoutom
# jobu od zrušenia zvonku. `|| true` všade – chýbajúce právo alebo nedostupný
# log nemá zhodiť súhrn.
SPADLO=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/jobs?per_page=100" \
  --jq '.jobs[]
        | select(.conclusion == "failure" or .conclusion == "cancelled")
        | [.id, .name, .conclusion, .started_at, .completed_at,
           ([.steps[]? | select(.conclusion == "failure" or .conclusion == "cancelled")
             | .name] | first // "—"),
           .html_url] | @tsv' 2>/dev/null || true)

if [ -n "$SPADLO" ]; then
  { echo; echo "## Čo spadlo"; echo; } >> "$S"
  while IFS=$'\t' read -r jid jname jconcl jstart jend jstep jurl; do
    [ -n "${jname:-}" ] || continue
    if [ -n "${jstart:-}" ] && [ -n "${jend:-}" ]; then
      TRVALO=$(( $(date -d "$jend" +%s) - $(date -d "$jstart" +%s) ))
    else
      TRVALO=0
    fi
    {
      echo "### [$jname]($jurl) – $jconcl po $(hms "$TRVALO")"
      echo
      echo "Zastavilo sa na kroku **$jstep**."
      if [ "$jconcl" = "cancelled" ] && [ "$TRVALO" -gt 3000 ]; then
        echo
        echo "> Zrušené po $(hms "$TRVALO") – to nie je pád, to je strop."
        echo "> Buď timeout jobu, alebo rozpočet výpočtu. Skús menší výrez,"
        echo "> nižší zoom alebo hrubšiu mriežku."
      fi
    } >> "$S"
    # čas na začiatku riadku ide preč – zalomil by tabuľku
    CHYBY=$(gh api "repos/$GITHUB_REPOSITORY/actions/jobs/$jid/logs" 2>/dev/null \
      | grep -a "##\[error\]" | tail -3 | sed 's/^[0-9TZ:.-]* //' || true)
    if [ -n "$CHYBY" ]; then
      { echo; echo '```'; echo "$CHYBY"; echo '```'; echo; } >> "$S"
    fi
  done <<< "$SPADLO"
fi
