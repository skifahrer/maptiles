#!/usr/bin/env bash
# Čím sa Planetileru povie „drž sa regiónu": `--polygon`, ALEBO `--bounds`.
#
# Spoločný súbor, lebo dlaždice z regionálneho PBF robia tri joby (`tiles`,
# `trails`, `features`) a orez musí byť vo všetkých rovnaký.
#
# Planetiler si rozsah berie z obdĺžnika bboxu a do dlaždíc kreslí aj
# celosvetové vodstvo, pobrežia a Natural Earth – bbox Prešovského kraja je
# takmer dvojnásobok jeho plochy, takže mapa pokračovala do Poľska.
#
# `--bounds` a `--polygon` naraz nedávaj: `tileExtents` sa počíta už
# v konštruktore, takže polygón je v logu vidieť a neoreže nič. Namerané na
# Monaku (maxzoom 15): bez orezu 27 dlaždíc, `--polygon` 17, oba naraz 27.
# `--bounds` sa preto dáva len vtedy, keď polygón nie je – ako poistka pre PBF
# s nepresnou hlavičkou.
#
# Je to hrubý orez, po celé dlaždice (na z14 ~1,5 km); presnú hranicu dokreslí
# maska v štýle. Vypínač `region_clip=false` orez preskočí a dá `--bounds` –
# mapa vyzerá rovnako, ale v stiahnutých dlaždiciach sa vezie územie za
# hranicou (Bratislavský kraj: +26 % dlaždíc, +0,7 % bajtov). Kým je vypnutý,
# hovorí to `::warning::` v každom behu.
#
#   mapfile -t CLIP < <(workers/lib/region-clip.sh "$REGION_BBOX")
#   java -jar planetiler.jar … "${CLIP[@]}"
set -euo pipefail

BBOX="${1:-}"
POLY="${2:-data/region.poly}"
# predvolene zapnutý: vypnúť orez sa má dať len tak, že to niekto napíše
CLIP_ON="${OPT_REGION_CLIP:-true}"

# to isté okno, aké dostanú vrstvy z DEM (`plan/area.py::pad_bbox`,
# `BORDER_BUFFER_M` dnes 0). Platí len v tejto vetve – keď sa `--polygon`
# používa, Planetiler si okno spočíta z neho a `--bounds` sa nedáva vôbec.
pad_bbox() {
  python3 - "$1" <<'PY'
import sys
sys.path.insert(0, "workers/plan")
from area import pad_bbox, BORDER_BUFFER_M
w, s, e, n = pad_bbox([float(v) for v in sys.argv[1].split(",")], BORDER_BUFFER_M)
print(f"{w},{s},{e},{n}")
PY
}

# argumenty na stdout (volajúci si ich načíta), vysvetlenie do logu
if [ -s "$POLY" ] && [ "$CLIP_ON" != 'true' ]; then
  if [ -n "$BBOX" ]; then echo "--bounds=$(pad_bbox "$BBOX")"; fi
  echo "::warning::Orez na región je vypnutý (\`region_clip=false\`), takže sa dlaždice vyrobia na celom obdĺžniku bboxu – na Bratislavskom kraji je to o 26 % dlaždíc viac a je v nich územie za hranicou kraja (aj cudzie sídla). V mape to nevidno, lebo hranicu dokresľuje maska v štýle. Späť to zapneš \`region_clip=true\` v inpute \`options\`." >&2
elif [ -s "$POLY" ]; then
  echo "--polygon=$POLY"
  echo "Orez na región: $POLY – dlaždice mimo regiónu sa nevyrobia. (\`--bounds\` sa zámerne NEPRIDÁVA, tichý vypínač polygónu – viď hlavičku skriptu.)" >&2
else
  # (`set -e`: `[ … ] && echo` by pri prázdnom bboxe zhodilo skript)
  if [ -n "$BBOX" ]; then echo "--bounds=$BBOX"; fi
  echo "::warning::Polygón regiónu ($POLY) nie je, takže sa dlaždice vyrobia na CELOM obdĺžniku bboxu – mapa bude siahať aj za región (vodstvo a Natural Earth kreslí Planetiler všade). Zvyčajne to znamená, že sa v jobe \`plan\` nestiahol \`.poly\`; skús beh zopakovať." >&2
fi
