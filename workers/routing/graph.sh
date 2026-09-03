#!/usr/bin/env bash
# Navigačný graf Valhally z PBF – a balík, ktorý sa dá otvoriť v telefóne.
#
# ČO Z TOHO VYPADNE. Nie „dlaždice", ale ŠTYRI súbory, a všetky štyri treba:
#
#   valhalla_tiles.tar   samotný graf (jeden archív, klient si ho mmapuje)
#   valhalla.json        konfigurácia – bez nej knižnica nevie, čo kde je
#   admins.sqlite        HRANICE ŠTÁTOV a strana jazdy
#   timezones.sqlite     časové pásma pre trasy so zadaným časom odjazdu
#
# `admins.sqlite` NIE JE OZDOBA. Bez neho Valhalla nevie, v ktorej krajine
# hrana leží – takže nefunguje `country_crossing_penalty`, strana jazdy sa
# hádá a diaľničná známka po krajinách (`docs/navigation.md`) by nemala na čom
# stáť ani po záplate. A nefunguje TICHO: trasa sa spočíta, len je iná.
#
# STAVIA TO DOCKER OBRAZ VALHALLY, nie vlastná sekvencia binárok. Je to ich
# udržovaná cesta (`valhalla_build_config` → `valhalla_build_admins` →
# `valhalla_build_timezones` → `valhalla_build_tiles` → `valhalla_build_extract`),
# riadená premennými prostredia; vlastná kópia toho poradia by bola druhá pravda
# o tom, ako sa graf stavia, a rozišla by sa pri prvej zmene na ich strane.
#
# VERZIA MOTORA IDE DO BALÍKA. Graf a knižnica, ktorá ho čítá, si musia sedieť –
# nesúlad vyzerá ako pokazená trasa, nie ako nesúlad verzií. Preto sa obraz
# zadáva s TAGOM (nie `latest`) a to, čo sa naozaj použilo, sa zapíše.
#
# DVA ROZSAHY, JEDEN SKRIPT. Graf sa stavia raz pre CELÝ ŠTÁT (workflow
# „Mapa · Build navigácia", vlastný balík na Drive, `AREA` z
# `workers/data/routing-areas.json`) a raz pre JEDEN REGIÓN, kde ide priamo
# DOVNÚTRA balíka mapy toho regiónu (job `navigacia` v `build-map-region.yml`,
# `REGION_KEY` a PBF, ktoré si beh už aj tak stiahol). Dva skripty by boli dve
# pravdy o tom, ako sa graf stavia a čo sa v ňom kontroluje (pravidlo 1).
#
# ČO SA PRI REGIÓNE MENÍ: PBF je REZANÝ na hranicu kraja, takže hrana, ktorej
# chýba druhý koniec, je slepá ulica – trasa v takom grafe KONČÍ NA HRANICI
# REGIÓNU. Je to zámer (mapa aj hľadanie sú za ten istý región a človek, ktorý
# si stiahol kraj, má v ňom aj navigáciu), nie opomenutie, a `graf.json` to
# o sebe hovorí: `rozsah: "region"` a `hranica: "trasa končí na hranici
# regiónu"`. Kto potrebuje prejsť hranicu, má na to celoštátny balík.
#
# Vstup:  ROUTING_PBF (default data/routing.osm.pbf), AREA alebo REGION_KEY,
#         VALHALLA_IMAGE
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
  ROZSAH="region"                     # jeden kraj, graf ide do jeho mapy
  POPIS="región \`$REGION_KEY\`"
  PBF="${ROUTING_PBF:-data/region.osm.pbf}"
  ROBI="workers/plan/pbf.sh (krok „PBF regiónu“)"
else
  echo "::error::Povedz, na aký rozsah sa graf stavia: buď AREA (kľúč z workers/data/routing-areas.json, celoštátny balík), alebo REGION_KEY (kraj, graf ide dovnútra jeho mapy). Bez toho by sa nedalo napísať do graf.json, čo ten graf pokrýva – a rozsah je pri navigácii to hlavné, čo o nej treba vedieť."
  exit 1
fi
IMAGE="${VALHALLA_IMAGE:-ghcr.io/valhalla/valhalla-scripted:latest}"
# Log stavby sa ODKLADÁ, nielen vypisuje: Valhalla si v ňom sama napíše, koľko
# ciest z PBF je prejazdných, a to je jediné poctivé meradlo toho, či v grafe
# niečo je (kontrola pod stavbou). Nie je v `custom_files` – ten priečinok je
# vnútro obrazu, nie miesto na naše súbory.
BUILD_LOG="valhalla-build.log"

[ -s "$PBF" ] || {
  echo "::error::Chýba $PBF – najprv musí prejsť $ROBI."
  exit 1
}
cp "$PBF" custom_files/routing.osm.pbf

PBF_MB=$(( $(stat -c%s custom_files/routing.osm.pbf) / 1048576 ))
# PLÁN S ODHADOM PRED DRAHOU ČASŤOU (pravidlo 4). Odhad je hrubý a je to tu
# NAPÍSANÉ: stavba grafu rastie s veľkosťou PBF nelineárne a namerané čísla pre
# tieto rozsahy ešte nemáme – prvý beh ich doplní do `routing-areas.json`.
echo "::notice::Staviam graf z ${PBF_MB} MB PBF ($POPIS, obraz $IMAGE). Kraj sú jednotky minút; Slovensko samo desiatky a so susedmi to môže byť hodiny – na job je strop 360 minút. Namerané čísla z celoštátnych behov patria do workers/data/routing-areas.json."

# Verzia motora – zisťuje sa PRED stavbou, nech sa na ňu nečaká hodinu. Keď sa
# nedá prečítať, nie je to ticho: do balíka pôjde aspoň digest obrazu.
# ŽIADNA RÚRA Z `docker run`. `head -1` zavrie rúru pod stále píšucim
# producentom, ten dostane EPIPE a `pipefail` z toho spraví pád, hoci sa
# hodnota prečítala. Výstup sa preto najprv uloží do premennej.
VALHALLA_RAW=$(docker run --rm --entrypoint valhalla_build_tiles "$IMAGE" \
               --version 2>/dev/null || true)
VALHALLA_VER=$(tr -d '\r' <<<"$VALHALLA_RAW" | head -1)
if [ -z "$VALHALLA_VER" ]; then
  VALHALLA_VER=$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || true)
  echo "::warning::Verziu Valhally sa nepodarilo prečítať z obrazu; do balíka ide digest „${VALHALLA_VER:-neznámy}“. Klient si musí verziu grafu overiť sám."
fi
echo "Valhalla: ${VALHALLA_VER:-neznáma}"

echo "::group::valhalla_build_tiles (Docker)"
# `serve_tiles=False` – tento job graf STAVIA, neobsluhuje ho; s `True` by
# kontejner po stavbe ostal bežať a job by dobehol do stropu času.
# `force_rebuild=True` – bez neho by obraz našiel svoj starý `tiles.tar`
# a stavbu preskočil, čo je pri čistom runneri jedno, ale pri cache nie:
# vrátilo by to graf z PREDOŠLÉHO PBF a nikto by to nepovedal (pravidlo 8).
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

# ČO SA NEOVERÍ, TO SA NEUROBILO. Obraz môže dobehnúť s nulou aj vtedy, keď
# niektorý krok preskočil – a nekompletný graf je presne ten tichý omyl, kvôli
# ktorému by trasa „len nešla" a vyzeralo by to ako chyba aplikácie. Preto sa
# kontroluje KAŽDÝ zo štyroch súborov.
#
# SPODNÁ HRANICA VEĽKOSTI JE LEN NA TROCH Z NICH. `valhalla.json` a oba
# `.sqlite` sú vždy tie isté (konfigurácia a dva hotové číselníky), takže
# useknutý súbor sa na veľkosti pozná. PRI GRAFE TO NEPLATÍ – a stálo tam
# 1 MB: graf kraja má desiatky MB, ale graf malého výrezu má legitímne
# kilobajty, takže tá hranica zhadzovala správne postavené grafy (beh
# 33412856848 padol na 20 KB tare, v ktorej bolo 29 ciest a 42 hrán). Koľko
# toho v grafe je, sa preto neháda z bajtov, ale číta pod týmto cyklom z toho,
# čo si Valhalla narátala sama. `0` je teda zámer, nie zabudnutá hodnota:
# prázdny súbor chytí `-s` o riadok vyššie.
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

# KOĽKO JE V GRAFE CIEST – A NIE SÚ TO LEN CESTY PRE AUTÁ. Valhalla si pri
# stavbe sama napíše, koľko ciest z PBF je „routable", a v tom čísle je aj
# chodník (`highway=footway`), pešia cesta (`path`), schody aj `sidewalk` –
# všetko sú to hrany profilu `pedestrian`, po ktorých sa trasa vedie. Preto
# nula neznamená „nie sú tu cesty pre autá", ale že v PBF nie je NIČ, po čom
# by sa dalo ísť. Toto je jediné poctivé meradlo prázdneho grafu: veľkosť
# tare hovorí o veľkosti územia, nie o tom, či sa v ňom dá niekam dôjsť.
#
# JE TO VAROVANIE, NIE PÁD BEHU. Prázdny výrez je legitímny výsledok zadania
# (malý `area`, štvorec rýchleho testu) a zhodiť kvôli nemu celý build mapy by
# znamenalo zahodiť aj dlaždice, vrstevnice a trasy, ktoré sú v poriadku.
# Ticho to nezmizne (pravidlo 8): číslo ide aj do `graf.json`, takže balík
# o sebe povie, koľko ciest v ňom je, a klient to nemusí hádať z toho, že sa
# trasa nenašla.
CESTY=$(grep -oE '[0-9]+ routable ways' "$BUILD_LOG" | tail -1 \
        | grep -oE '^[0-9]+' || true)
if [ -z "$CESTY" ]; then
  echo "::warning::V logu stavby nie je riadok „routable ways“, takže sa nedá povedať, koľko ciest graf pokrýva – do \`graf.json\` ide \`cesty: null\`. Pravdepodobne sa zmenil výpis obrazu $IMAGE."
elif [ "$CESTY" = 0 ]; then
  echo "::warning::Valhalla v PBF nenašla ANI JEDNU cestu, po ktorej sa dá ísť – ani cestu pre autá, ani chodník, pešiu cestu, schody či \`sidewalk\`. Graf ($POPIS) je prázdny: trasa sa v ňom nespočíta. Pri malom výreze alebo pri rýchlom teste je to očakávané a beh preto nepadá; inak sa pozri, či sa PBF nerezal na územie, kde nič nie je."
else
  echo "Ciest v grafe: $CESTY (aj chodníky, pešie cesty a \`sidewalk\`)"
fi

# Čo je v balíku a z čoho – vedľa `obsah.json`, ktorý dopisuje
# `workers/deploy/publish-map.py`. Toto je tá časť, ktorú o sebe vie len tento
# krok: rozsah, verzia motora a PBF, z ktorého graf je.
python3 - "$ROZSAH" "${AREA:-$REGION_KEY}" "$VALHALLA_VER" "$PBF_MB" "$CESTY" \
        > _site/routing/graf.json <<'PY'
import json, os, sys, time
druh, kluc, valhalla, pbf_mb = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
cesty = int(sys.argv[5]) if sys.argv[5] else None
graf = {
    # AKÝ ROZSAH TEN GRAF POKRÝVA je pri navigácii to hlavné, čo o ňom treba
    # vedieť – od toho závisí, kam sa v ňom dá doviezť. `area` je celý štát
    # (alebo štáty) z číselníka a má vlastný balík; `region` je jeden kraj
    # a graf je vnútri balíka jeho mapy.
    "rozsah": druh,
    "kluc": kluc,
    "pbf_mb": pbf_mb,
    # KOĽKO CIEST V GRAFE JE – vrátane chodníkov, pešich ciest a `sidewalk`,
    # lebo aj po tých sa trasa vedie (profil `pedestrian`). Je to tu preto,
    # že prázdny graf beh NEZHADZUJE: malý výrez legitímne nemusí obsahovať
    # nič, po čom sa dá ísť, a keby to balík o sebe nepovedal, „trasa sa
    # nenašla" by v telefóne vyzeralo ako pokazená navigácia. `null` znamená,
    # že sa to z logu stavby nedalo prečítať – nie nulu.
    "cesty": cesty,
    # Verzia motora MUSÍ byť v balíku: graf a knižnica si musia sedieť.
    "valhalla": valhalla or "neznáma",
    "profily": ["auto", "bus", "bicycle", "pedestrian"],
    # `multimodal` (autobus a vlak) v tomto grafe NIE JE a je to napísané:
    # potrebuje GTFS, ktoré v OSM nie je (docs/navigation.md).
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
        # Celý štátny extrakt, nič sa nerezalo – trasa smie ísť až na okraj
        # rozsahu (`workers/routing/pbf.sh` preto nesmie rezať).
        "hranica": "trasa smie ísť po okraj rozsahu",
    })
else:
    regions = json.load(open(os.path.join("workers", "data", "regions.json"),
                             encoding="utf-8"))
    graf.update({
        "name": (regions.get(kluc) or {}).get("name") or kluc,
        "region_key": kluc,
        # `krajiny` (ISO kódy pre známky) tu ZÁMERNE NIE JE: `regions.json`
        # ich nenesie – `country` je tam UZOL KATALÓGU (`slovensko`), nie
        # `SK`. Napísať ho pod tým istým kľúčom, pod akým celoštátny graf
        # píše `["SK"]`, by bola tá istá otázka s dvoma rôznymi odpoveďami.
        # Známky to nebrzdí: `profile.py` berie krajiny z `vignettes.json`,
        # nie z grafu (viď `workers/data/routing-areas.json`).
        "krajina_uzol": (regions.get(kluc) or {}).get("country") or "",
        # ČO TENTO GRAF NEVIE, A JE TO NAPÍSANÉ. PBF je rezaný na hranicu
        # kraja, takže hrana, ktorej chýba druhý koniec, je slepá ulica.
        # Mlčanie by sa dalo čítať ako „trasa cez hranicu nefunguje z inej
        # príčiny" – a to je presne ten tichý omyl, ktorému sa tu vyhýbame.
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
echo "::notice::Graf hotový: ${MB} MB za $(( SEK / 60 )) min $(( SEK % 60 )) s (PBF ${PBF_MB} MB, $POPIS). Pri celoštátnom behu patrí toto číslo do workers/data/routing-areas.json; pri kraji je v katalógu pod balíkom mapy (`casti.navigacia`)."
printf '%s\t%s\t%s\t%s\n' "20" "Navigačný graf (Valhalla)" "$SEK" \
  "${MB} MB z ${PBF_MB} MB PBF" >> steps-out/routing.tsv
