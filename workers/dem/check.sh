#!/usr/bin/env bash
# Je v sklade na Drive výškový model pre naše územie – a keď nie, čo doplniť?
#
# Pre každú z troch vrstiev sa spýta `workers/dem/target.py`, ktorý sklad
# a ktoré súbory jej zdroj potrebuje, a pozrie sa, či tam sú.
#
# `dmr5` má dve podoby a prepína medzi nimi kľúč výrezu, ktorý vrstva podá do
# `fetch.sh`: vrstevnice a skaly podávajú výrez, tieňovanie nie (robí sa na
# celý región, kde 1 m verzia neexistuje). Tabuľka `layer_area_key` nižšie
# musí sedieť s tými troma volaniami – stráži to lint workflowov.
#
# Výrez sa podáva bboxom a nie kľúčom pohoria: `Dáta · DMR 5.0` má dostať
# presne to územie, ktoré si beh vypýtal. Kľúč by si tá pipeline vyriešila
# z `areas.json` druhýkrát a prečítala celý obdĺžnik. Meno assetu ide zvlášť.
#
# Použitie:
#   BBOX=W,S,E,N AREA_KEY=vysoke_tatry AREA_BBOX=W,S,E,N \
#   SRC_CONTOURS=dmr5 SRC_ROCKS=dmr5 SRC_TERRAIN=dmr5 \
#   GDRIVE_CREDENTIALS=… workers/dem/check.sh
#
# Do $GITHUB_OUTPUT: `demkey_<vrstva>`, `mirror_<vrstva>`, `mirror_dmr5_area`,
# `mirror_dmr5_asset`, `mirror_dmr5_tiles`.
set -euo pipefail

# cesty k susedom sa skladajú z vlastného priečinka – natvrdo napísaná cesta
# prežila presun do priečinkov a spadla až na runneri
HERE="$(dirname "$0")"
WORKERS="$(dirname "$HERE")"
BBOX="${BBOX:-}"
AREA_KEY="${AREA_KEY:-cely}"
# bbox výrezu, už pretnutý s regiónom; prázdny = výrezom je celý región
AREA_BBOX="${AREA_BBOX:-$BBOX}"
OUT="${GITHUB_OUTPUT:-/dev/null}"

# ktorá vrstva podáva kľúč výrezu – viď hlavičku
layer_area_key() {
  case "$1" in
    terrain) echo cely ;;
    *) echo "$AREA_KEY" ;;
  esac
}

MIRROR=""       # už zaradené na doplnenie (podľa PODOBY, nie podľa zdroja)
MIRROR_LIST=""  # na výpis
DMR5_AREA=""    # bbox, ktorý sa má prečítať ako výrez v plnom rozlíšení
DMR5_ASSET=""   # a meno, pod ktorým ho build hľadá
DMR5_TILES=""   # ktoré stupne doplniť ako 1° dlaždice

# pozrie sa na jeden zdroj: či pre naše územie v jeho sklade niečo je a aký je
# otlačok obsahu
check_source() { # $1 = vrstva (na výpis), $2 = zdroj
  local what="$1" src="$2" akey rel assets names need=false
  local form target want mirror degrees
  akey=$(layer_area_key "$what")
  target=$(python3 "$HERE/target.py" --source="$src" \
    --area-key="$akey" --bbox="$BBOX")
  tget() { printf '%s\n' "$target" | sed -n "s/^$1=//p" | head -1; }
  form=$(tget form); rel=$(tget store); want=$(tget assets)
  mirror=$(tget mirror); degrees=$(tget degrees)

  # meno aj veľkosť naraz: z mien sa hľadá, z celého riadku počíta otlačok.
  # `|| true`: keď sa sklad ešte nezaložil, `pipefail` by zhodil celý krok.
  assets=$({ python3 "$WORKERS/drive/store.py" --index --store="$rel" \
    2>/dev/null || true; } | sort)
  names=$(printf '%s\n' "$assets" | cut -d: -f1)

  if [ "$form" = 'area' ]; then
    # plné rozlíšenie sa zrkadlí po výrezoch (1° dlaždica má pri 1 m ~48 GB)
    if printf '%s\n' "$names" | grep -qx "$want"; then
      echo "$what ($src): $want je v sklade $rel ✓"
    else
      echo "$what ($src): $want v sklade $rel nie je → doplní sa"
      need=true
    fi
  elif [ -z "$want" ]; then
    # vlastný región bez bboxu – zoznam dlaždíc sa nedá zistiť
    [ -z "$assets" ] && need=true || true
    echo "$what ($src): bbox nie je známy; sklad $rel má $(printf '%s' "$assets" | grep -c . || true) súborov → doplniť: $need"
  else
    local have=0 total=0 t chybaju=""
    for t in $want; do
      total=$(( total + 1 ))
      if printf '%s\n' "$names" | grep -qx "$t"; then
        have=$(( have + 1 ))
      else
        chybaju="$chybaju $t"
      fi
    done
    # koľko z nich musí byť v sklade, závisí od toho, či sa dá doplniť práve
    # tá chýbajúca.
    #
    # `dmr5`: áno – doplnenie číta presne tie stupne, ktoré mu podáme, a uloží
    # každý prečítaný (prázdna dlaždica je záznam, že sa tam pozeralo), takže
    # chýbajúce meno znamená „toto sme nikdy nečítali".
    # `sonny`/`dmr35`: nie – sťahuje sa celý produkt naraz a prázdne dlaždice
    # sa zahadzujú, takže chýbajúce meno môže znamenať aj „tam ten model nemá
    # dáta". Pokrytie tam meria `coverage.py` až pri sťahovaní.
    #
    # Meno v sklade ešte nie je model: `trust.py` otvára podozrivo malé súbory
    # (veľkosť je vo výpise skladu), inak by prázdna dlaždica prešla ako hotová.
    if [ "$src" = 'dmr5' ] && [ "$have" -gt 0 ]; then
      local male nedoveryhodne
      male=$(printf '%s\n' "$assets" | python3 "$HERE/trust.py" \
        --store="$rel" --names="$want" --only-suspect)
      if [ -n "$male" ]; then
        # `gdalinfo` až keď je čo otvárať: inštalácia GDALu je pol minúty
        # na jobe, ktorý inak trvá osem sekúnd
        if ! command -v gdalinfo >/dev/null 2>&1; then
          echo "  (dopĺňam gdal-bin – v sklade je podozrivo malá dlaždica)"
          sudo apt-get update -qq
          sudo apt-get install -y -qq gdal-bin
        fi
        nedoveryhodne=$(printf '%s\n' "$assets" | python3 "$HERE/trust.py" \
          --store="$rel" --names="$want")
        for t in $nedoveryhodne; do
          case " $chybaju " in
            *" $t "*) ;;
            *) chybaju="$chybaju $t"; have=$(( have - 1 )) ;;
          esac
        done
      fi
    fi
    if [ "$src" = 'dmr5' ]; then
      [ -n "$chybaju" ] && need=true || true
    else
      [ "$have" -eq 0 ] && need=true || true
    fi
    echo "$what ($src): dlaždíc pre bbox $total, v sklade $rel $have → doplniť: $need"
    [ -n "$chybaju" ] && echo "  chýbajú:$chybaju" || true
    # doplniť treba len chýbajúce stupne, nie celý bbox – jeden stupeň je pol
    # hodiny čítania z Drive. Meno dlaždice hovorí svoj juhozápadný roh, takže
    # obálka sa spočíta z mien.
    if [ "$need" = true ] && [ "$src" = 'dmr5' ] && [ -n "$chybaju" ]; then
      degrees=$(python3 - $chybaju <<'PY'
import sys
lons, lats = [], []
for t in sys.argv[1:]:
    t = t.split(".")[0]
    lat, lon = int(t[1:3]), int(t[4:7])
    lats.append(-lat if t[0] == "S" else lat)
    lons.append(-lon if t[3] == "W" else lon)
print(f"{min(lons)},{min(lats)},{max(lons) + 1},{max(lats) + 1}")
PY
)
    fi
  fi

  if [ "$need" = true ]; then
    # deduplikuje sa podľa podoby, nie podľa zdroja: pri jedinom `dmr5` môžu
    # chýbať oba tvary naraz
    case " $MIRROR " in
      *" $mirror "*) echo "  ($mirror už dopĺňa iná vrstva)" ;;
      *)
        MIRROR="$MIRROR $mirror"
        MIRROR_LIST="$MIRROR_LIST $mirror"
        if [ "$src" = 'dmr5' ]; then
          # DMR 5.0 nedopĺňa update-dem.yml – ten ho stiahnuť nevie (145 GB
          # proti ~60 GB voľným). Robí to `Dáta · DMR 5.0` cez HTTP Range.
          if [ "$form" = 'area' ]; then
            # bbox, nie kľúč: čítať sa má presne to, čo si beh vypýtal.
            # Meno assetu je to isté `$want`, ktoré sa vyššie hľadalo v sklade.
            DMR5_AREA="$AREA_BBOX"
            DMR5_ASSET="$want"
          else
            DMR5_TILES="$degrees"
          fi
        else
          NEED_SRC="$src"
        fi
        ;;
    esac
  fi
  DEMKEY=$(printf '%s' "$assets" | sha256sum | cut -c1-12)
}

for pair in \
  "contours:${SRC_CONTOURS:-}" \
  "rocks:${SRC_ROCKS:-}" \
  "terrain:${SRC_TERRAIN:-}"; do
  layer="${pair%%:*}"
  src="${pair#*:}"
  DEMKEY=""
  NEED_SRC=""
  # skaly z DMR 5.0 si DEM nepýtajú: sklon si ho `slope-chunks.py` číta z Drive
  # po častiach a každú si odloží do vlastného skladu
  if [ "$layer" = 'rocks' ] && [ "$src" = 'dmr5' ]; then
    echo "rocks ($src): DEM sa nedopĺňa – sklon sa číta z Drive po častiach"
  # prázdny zdroj = vrstva je vypnutá (alebo skaly idú z tieňovania)
  elif [ -n "$src" ] && [ "$src" != 'ziadne' ]; then
    check_source "$layer" "$src"
  fi
  echo "demkey_$layer=$DEMKEY" >> "$OUT"
  echo "mirror_$layer=$NEED_SRC" >> "$OUT"
done

# dlaždice DMR 5.0 sa dopĺňajú po celých stupňoch a to je drahé – nech je to
# vidieť z logu, a nie až z trvania jobu
if [ -n "$DMR5_TILES" ]; then
  IFS=, read -r DW DS DE DN <<< "$DMR5_TILES"
  DEG=$(( (DE - DW) * (DN - DS) ))
  echo "DMR 5.0 dlaždice: doplní sa $DEG stupňov ($DMR5_TILES)"
  # odhad, nie meranie: jeden stupeň v 5 m sa číta z pyramídy 4 m, čo je
  # rádovo dve gigabajty a pol hodiny na stupeň
  if [ "$DEG" -gt 2 ]; then
    echo "::warning::Doplnenie $DEG stupňov DMR 5.0 je rádovo $(( DEG / 2 ))–$DEG hodín. Kratšie to ide s menším územím (input \`area\`) alebo so switchom \`test\`; hrubší model (sonny, dmr35) je hotový hneď."
  fi
  # a naopak: keď je územie oveľa menšie než stupeň, ktorý sa preň číta.
  # Dlaždica sa vždy musí prečítať celá – jej meno je sľub o celom stupni.
  # Raz doplnená v sklade ostane, takže ďalší test na tom stupni je zadarmo.
  python3 - "$BBOX" "$DEG" <<'PY' || true
import math, sys
try:
    w, s, e, n = (float(v) for v in sys.argv[1].split(","))
except ValueError:
    raise SystemExit(0)
deg = int(sys.argv[2])
km2 = ((e - w) * 111.32 * math.cos(math.radians((s + n) / 2))) * ((n - s) * 110.54)
tile_km2 = deg * 111.32 * 110.54 * math.cos(math.radians((s + n) / 2))
if km2 > 0 and tile_km2 / km2 > 50:
    print(f"::warning::Tieňovanie z DMR 5.0 potrebuje {deg}° dlaždice, čo je "
          f"~{tile_km2:.0f} km² čítania na územie s {km2:.0f} km² "
          f"({tile_km2 / km2:.0f}× viac). Dlaždica sa musí prečítať celá – jej "
          f"meno je sľub o celom stupni. Je to rádovo pol hodiny na stupeň; "
          f"na rýchly test je lacnejšie `shading_source: sonny`. Raz doplnená "
          f"dlaždica v sklade ostane, takže ďalší beh ju už neplatí.")
PY
fi
if [ -n "$DMR5_AREA" ]; then
  echo "DMR 5.0 výrez: prečíta sa $DMR5_AREA → $DMR5_ASSET"
fi
{
  echo "mirror_dmr5_area=$DMR5_AREA"
  echo "mirror_dmr5_asset=$DMR5_ASSET"
  echo "mirror_dmr5_tiles=$DMR5_TILES"
} >> "$OUT"

echo "Doplniť treba:${MIRROR_LIST:- nič}"
