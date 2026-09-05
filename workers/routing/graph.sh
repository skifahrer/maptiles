#!/usr/bin/env bash
# Navigačný graf Valhally z PBF – a balík, ktorý sa dá otvoriť v telefóne.
#
# Vypadnú štyri súbory a všetky štyri treba:
#   valhalla_tiles.tar   samotný graf
#   valhalla.json        konfigurácia
#   admins.sqlite        hranice štátov a strana jazdy
#   timezones.sqlite     časové pásma pre trasy so zadaným časom odjazdu
#
# Bez `admins.sqlite` Valhalla nevie, v ktorej krajine hrana leží – nefunguje
# `country_crossing_penalty`, strana jazdy sa hádá a diaľničná známka nemá na
# čom stáť. A nefunguje ticho: trasa sa spočíta, len je iná.
#
# Stavia to docker obraz Valhally, nie vlastná sekvencia binárok – vlastná
# kópia toho poradia by sa rozišla pri prvej zmene na ich strane. Obraz sa
# zadáva s tagom (nie `latest`) a použitá verzia sa zapíše do balíka: graf
# a knižnica si musia sedieť, nesúlad vyzerá ako pokazená trasa.
#
# Dva rozsahy, jeden skript: celý štát (`AREA`) aj jeden región (`REGION_KEY`),
# každý s vlastným balíkom. Pri regióne je PBF rezaný presne na hranicu kraja,
# takže hrana bez druhého konca je slepá ulica a trasa končí na hranici – je to
# zámer a `graf.json` to o sebe hovorí.
#
# Vstup:  ROUTING_PBF, AREA alebo REGION_KEY, VALHALLA_IMAGE
# Výstup: _site/routing/* a `graph_mb`, `valhalla` do GITHUB_OUTPUT

set -euo pipefail
mkdir -p custom_files _site/routing steps-out
T=$(date +%s)

AREA="${AREA:-}"
REGION_KEY="${REGION_KEY:-}"
if [ -n "$AREA" ]; then
  ROZSAH="area"                       # celý štát (alebo štáty) z číselníka
  POPIS="rozsah \`$AREA\`"
  PBF="${ROUTING_PBF:-data/routing.osm.pbf}"
  ROBI="workers/routing/pbf.sh"
elif [ -n "$REGION_KEY" ]; then
  ROZSAH="region"                     # jeden kraj, vlastný balík vedľa mapy
  POPIS="región \`$REGION_KEY\`"
  PBF="${ROUTING_PBF:-data/region.osm.pbf}"
  ROBI="workers/plan/pbf.sh (krok „PBF regiónu“)"
else
  echo "::error::Povedz, na aký rozsah sa graf stavia: buď AREA (kľúč z workers/data/routing-areas.json, celoštátny balík), alebo REGION_KEY (kraj, vlastný balík vedľa jeho mapy). Bez toho by sa nedalo napísať do graf.json, čo ten graf pokrýva – a rozsah je pri navigácii to hlavné, čo o nej treba vedieť."
  exit 1
fi
IMAGE="${VALHALLA_IMAGE:-ghcr.io/valhalla/valhalla-scripted:latest}"
# log stavby sa odkladá: Valhalla si v ňom sama napíše, koľko ciest z PBF je
# prejazdných – jediné poctivé meradlo toho, či v grafe niečo je
BUILD_LOG="valhalla-build.log"

[ -s "$PBF" ] || {
  echo "::error::Chýba $PBF – najprv musí prejsť $ROBI."
  exit 1
}
cp "$PBF" custom_files/routing.osm.pbf

PBF_MB=$(( $(stat -c%s custom_files/routing.osm.pbf) / 1048576 ))
# plán s odhadom pred drahou časťou; odhad je hrubý a namerané čísla pre tieto
# rozsahy ešte nemáme
echo "::notice::Staviam graf z ${PBF_MB} MB PBF ($POPIS, obraz $IMAGE). Kraj sú jednotky minút; Slovensko samo desiatky a so susedmi to môže byť hodiny – na job je strop 360 minút. Namerané čísla z celoštátnych behov patria do workers/data/routing-areas.json."

# verzia motora sa zisťuje pred stavbou, nech sa na ňu nečaká hodinu.
# Žiadna rúra z `docker run`: `head -1` zavrie rúru pod stále píšucim
# producentom a `pipefail` z EPIPE spraví pád.
VALHALLA_RAW=$(docker run --rm --entrypoint valhalla_build_tiles "$IMAGE" \
               --version 2>/dev/null || true)
VALHALLA_VER=$(tr -d '\r' <<<"$VALHALLA_RAW" | head -1)
if [ -z "$VALHALLA_VER" ]; then
  VALHALLA_VER=$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || true)
  echo "::warning::Verziu Valhally sa nepodarilo prečítať z obrazu; do balíka ide digest „${VALHALLA_VER:-neznámy}“. Klient si musí verziu grafu overiť sám."
fi
echo "Valhalla: ${VALHALLA_VER:-neznáma}"

echo "::group::valhalla_build_tiles (Docker)"
# `serve_tiles=False` – tento job graf stavia, neobsluhuje ho; s `True` by
# kontejner ostal bežať do stropu času. `force_rebuild=True` – bez neho by
# obraz našiel starý `tiles.tar` a vrátil graf z predošlého PBF.
docker run --rm \
  -e serve_tiles=False \
  -e force_rebuild=True \
  -e build_admins=True \
  -e build_time_zones=True \
  -e build_tar=True \
  -e build_elevation=False \
  -e tileset_name=valhalla_tiles \
  -e server_threads="$(nproc)" \
  -v "$PWD/custom_files:/custom_files" \
  "$IMAGE" 2>&1 | tee "$BUILD_LOG"
echo "::endgroup::"

# čo sa neoverí, to sa neurobilo: obraz môže dobehnúť s nulou aj keď niektorý
# krok preskočil. Spodná hranica veľkosti je len na troch súboroch – graf
# malého výrezu má legitímne kilobajty, takže `0` je zámer, nie zabudnutá
# hodnota (prázdny súbor chytí `-s`). Koľko toho v grafe je, sa číta nižšie
# z toho, čo si Valhalla narátala sama.
chyba=0
for pair in "valhalla_tiles.tar:0:graf" \
            "valhalla.json:200:konfigurácia" \
            "admins.sqlite:20000:hranice štátov a strana jazdy" \
            "timezones.sqlite:20000:časové pásma"; do
  IFS=: read -r f min popis <<<"$pair"
  src="custom_files/$f"
  if [ ! -s "$src" ]; then
    echo "::error::V grafe chýba $f ($popis). Obraz $IMAGE dobehol, ale súbor nevyrobil – skús to s \`force_rebuild=True\` a pozri log kroku vyššie."
    chyba=1
    continue
  fi
  size=$(stat -c%s "$src")
  if [ "$size" -lt "$min" ]; then
    echo "::error::$f má len ${size} B ($popis) – to je useknutý súbor. Tento súbor je pri každom behu rovnaký, takže to nie je malým územím; pozri log kroku vyššie, či stavbu nezabil limit pamäte (zníž server_threads)."
    chyba=1
    continue
  fi
  cp "$src" "_site/routing/$f"
  echo "  $f  $(du -h "$src" | cut -f1)  ($popis)"
done
[ "$chyba" = 0 ] || exit 1

# koľko je v grafe ciest – vrátane chodníkov a schodov, po ktorých sa vedie
# profil `pedestrian`. Nula teda neznamená „nie sú tu cesty pre autá", ale že
# v PBF nie je nič, po čom by sa dalo ísť; veľkosť tare hovorí o veľkosti
# územia, nie o tom, či sa v ňom dá niekam dôjsť.
# Je to varovanie, nie pád: prázdny výrez je legitímny výsledok zadania a číslo
# ide aj do `graf.json`, takže balík o sebe povie, koľko ciest v ňom je.
CESTY=$(grep -oE '[0-9]+ routable ways' "$BUILD_LOG" | tail -1 \
        | grep -oE '^[0-9]+' || true)
if [ -z "$CESTY" ]; then
  echo "::warning::V logu stavby nie je riadok „routable ways“, takže sa nedá povedať, koľko ciest graf pokrýva – do \`graf.json\` ide \`cesty: null\`. Pravdepodobne sa zmenil výpis obrazu $IMAGE."
elif [ "$CESTY" = 0 ]; then
  echo "::warning::Valhalla v PBF nenašla ANI JEDNU cestu, po ktorej sa dá ísť – ani cestu pre autá, ani chodník, pešiu cestu, schody či \`sidewalk\`. Graf ($POPIS) je prázdny: trasa sa v ňom nespočíta. Pri malom výreze alebo pri rýchlom teste je to očakávané a beh preto nepadá; inak sa pozri, či sa PBF nerezal na územie, kde nič nie je."
else
  echo "Ciest v grafe: $CESTY (aj chodníky, pešie cesty a \`sidewalk\`)"
fi

# čo je v balíku a z čoho – rozsah, verzia motora a PBF; `obsah.json` dopisuje
# `deploy/publish-map.py`
python3 - "$ROZSAH" "${AREA:-$REGION_KEY}" "$VALHALLA_VER" "$PBF_MB" "$CESTY" \
        > _site/routing/graf.json <<'PY'
import json, os, sys, time
druh, kluc, valhalla, pbf_mb = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
cesty = int(sys.argv[5]) if sys.argv[5] else None
graf = {
    # aký rozsah graf pokrýva je pri navigácii to hlavné: `area` je celý štát
    # z číselníka, `region` jeden kraj
    "rozsah": druh,
    "kluc": kluc,
    "pbf_mb": pbf_mb,
    # koľko ciest v grafe je – prázdny graf beh nezhadzuje, tak to musí balík
    # o sebe povedať; `null` znamená „z logu sa to nedalo prečítať", nie nulu
    "cesty": cesty,
    # verzia motora musí byť v balíku: graf a knižnica si musia sedieť
    "valhalla": valhalla or "neznáma",
    "profily": ["auto", "bus", "bicycle", "pedestrian"],
    # `multimodal` v tomto grafe nie je: potrebuje GTFS, ktoré v OSM nie je
    "multimodal": False,
    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "run": os.environ.get("GITHUB_RUN_NUMBER", ""),
    "run_id": os.environ.get("GITHUB_RUN_ID", ""),
}
if druh == "area":
    areas = json.load(open(os.path.join("workers", "data", "routing-areas.json"),
                           encoding="utf-8"))["areas"]
    area = areas[kluc]
    graf.update({
        "name": area["name"],
        "region_key": area["region_key"],
        "krajiny": area["countries"],
        "pbf": area["pbf"],
        # celý štátny extrakt, nič sa nerezalo – `routing/pbf.sh` nesmie rezať
        "hranica": "trasa smie ísť po okraj rozsahu",
    })
else:
    regions = json.load(open(os.path.join("workers", "data", "regions.json"),
                             encoding="utf-8"))
    graf.update({
        "name": (regions.get(kluc) or {}).get("name") or kluc,
        "region_key": kluc,
        # `krajiny` (ISO kódy pre známky) tu zámerne nie je: `country`
        # v `regions.json` je uzol katalógu (`slovensko`), nie `SK`. Známky to
        # nebrzdí – `profile.py` berie krajiny z `vignettes.json`.
        "krajina_uzol": (regions.get(kluc) or {}).get("country") or "",
        # PBF je rezaný na hranicu kraja, takže hrana bez druhého konca je
        # slepá ulica; mlčanie by sa dalo čítať ako iná príčina
        "hranica": "trasa končí na hranici regiónu; cez hranicu vedie "
                   "celoštátny graf z .github/workflows/navigation.yml",
    })
print(json.dumps(graf, ensure_ascii=False, indent=2))
PY
cat _site/routing/graf.json

MB=$(( $(du -sb _site/routing | cut -f1) / 1048576 ))
echo "graph_mb=$MB" >> "$GITHUB_OUTPUT"
echo "valhalla=${VALHALLA_VER:-neznama}" >> "$GITHUB_OUTPUT"
SEK=$(( $(date +%s) - T ))
echo "::notice::Graf hotový: ${MB} MB za $(( SEK / 60 )) min $(( SEK % 60 )) s (PBF ${PBF_MB} MB, $POPIS). Pri celoštátnom behu patrí toto číslo do workers/data/routing-areas.json; pri kraji je v katalógu pod vlastným balíkom (`maps.navigacia`)."
printf '%s\t%s\t%s\t%s\n' "20" "Navigačný graf (Valhalla)" "$SEK" \
  "${MB} MB z ${PBF_MB} MB PBF" >> steps-out/routing.tsv
