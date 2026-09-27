#!/usr/bin/env bash
# Vyhoď z PBF, čo leží celé mimo regiónu – aby to nemalo ako vojsť do dlaždice.
#
# Planetiler reže po DLAŽDICIACH, nie po prvkoch. Na z6 je jedna dlaždica široká
# 5 600 km, takže do nej padne aj Tisa – 270 km za Bratislavským krajom, v PBF ako
# člen relácie štátnej hranice. Na z7 už dlaždica tak ďaleko nevznikne, takže tú
# rieku vidno v mape presne na jednom zoome a inde nie.
#
# Reže sa OBDĹŽNIKOM, aj keď dlaždice orezáva polygón: prvok mimo obdĺžnika nemôže
# pretínať polygón, kým prvok na samotnej hranici má uzly priamo na jej čiare
# a rez polygónom by ho mohol zahodiť aj s hranicou kraja.
#
# `-s smart` necháva cesty celé a dopĺňa členov multipolygónov (veľké jazerá
# a priehrady). Relácie hraníc sa dopĺňať NESMÚ (`-S types=…boundary`): jeden člen
# štátnej hranice v kraji stačí na to, aby sa vrátila celá.
#
#   workers/lib/region-cut.sh data/water.osm.pbf "$REGION_BBOX"
set -euo pipefail

PBF="${1:?PBF, ktoré sa má orezať}"
BBOX="${2:-}"
POLY="${3:-data/region.poly}"

# ten istý región, aký dostanú dlaždice – `--bounds` je už dopočítaný o buffer,
# z polygónu sa berie jeho obdĺžnik. stderr ide preč: `::warning::` o vypnutom
# oreze patrí k dlaždiciam a job si ho vypíše pri svojom volaní.
mapfile -t CLIP < <(workers/lib/region-clip.sh "$BBOX" "$POLY" 2>/dev/null)

BOX=""
for A in "${CLIP[@]}"; do
  case "$A" in
    --bounds=*)  BOX="${A#--bounds=}" ;;
    # `+0` je nutné: `.poly` píše čísla ako text a „9.5" je ako text väčšie než
    # „16.8", takže by obdĺžnik vyšiel naopak
    --polygon=*) BOX=$(awk 'NF==2 && $1+0==$1 && $2+0==$2 {
                              lon = $1 + 0; lat = $2 + 0
                              if (k++ == 0) { w = e = lon; s = n = lat }
                              if (lon < w) w = lon; if (lon > e) e = lon
                              if (lat < s) s = lat; if (lat > n) n = lat
                            } END { if (k) printf "%.6f,%.6f,%.6f,%.6f", w, s, e, n }' \
                       "${A#--polygon=}") ;;
  esac
done

if [ -z "$BOX" ]; then
  echo "::warning::Región na rez PBF nie je (ani polygón, ani bbox), takže v ňom ostane aj to, čo je stovky kilometrov za krajom – na najnižších zoomoch to vidno v mape." >&2
  exit 0
fi

BEFORE=$(stat -c%s "$PBF")
osmium extract --overwrite -s smart -b "$BOX" -o "${PBF%.osm.pbf}-cut.osm.pbf" "$PBF"
mv "${PBF%.osm.pbf}-cut.osm.pbf" "$PBF"
echo "Rez na región ($BOX): $(( BEFORE / 1048576 )) MB → $(( $(stat -c%s "$PBF") / 1048576 )) MB" >&2
