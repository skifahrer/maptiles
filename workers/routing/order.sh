#!/usr/bin/env bash
# Poradie uzlov pre CCH nad celým územím – do `data/routing-order.json`.
#
# Volá ho build kraja (`navigation-region.yml`), keď z cache neprišlo poradie
# alebo prišlo staré, a ručný workflow „Navigácia · poradie uzlov" vždy. Jeden
# skript pre obe cesty: druhý postup by bol druhá pravda o tom, nad akým PBF
# a akým kódom poradie vzniká.
#
# Poradie závisí len od TVARU siete, nie od profilu, takže mierne zastarané
# je stále platné – uzol, ktorý pribudol, dostane rank na konci podľa OSM id
# (`tiles.py`). Prepočítava sa preto až po ORDER_MAX_AGE_DAYS, a keď sa
# prepočíta, dostane nové id: kraje s tým starým sa s novými v telefóne
# spojiť nesmú a treba ich prestavať. Štafeta nad krajinou to zvláda sama –
# prvý kraj poradie dopočíta, ostatné ho vezmú z cache.
#
# Vstup:  AREA (kľúč v routing-areas.json), OSMFR_BASE,
#         ORDER_MAX_AGE_DAYS (predvolene 30; 0 = počítať vždy),
#         FORCE=true = počítať aj keď je čerstvé
# Výstup: data/routing-order.json; `computed`, `id`, `uzlov` do GITHUB_OUTPUT

set -euo pipefail
mkdir -p data steps-out
: "${AREA:?povedz AREA – kľúč z workers/data/routing-areas.json}"
OUT=data/routing-order.json
MAX_AGE="${ORDER_MAX_AGE_DAYS:-30}"

if [ "${FORCE:-false}" != "true" ] && [ -s "$OUT" ]; then
  VEK=$(python3 - "$OUT" "$AREA" <<'PY'
import json, sys, time
try:
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    kedy = time.mktime(time.strptime(raw["built_at"], "%Y-%m-%dT%H:%M:%SZ"))
    if raw.get("nazov") != sys.argv[2]:
        raise ValueError(f"poradie je pre `{raw.get('nazov')}`, nie `{sys.argv[2]}`")
    print(int((time.time() - kedy) / 86400), raw["id"], raw["uzlov"])
except (OSError, ValueError, KeyError) as exc:
    print(f"::warning::{sys.argv[1]} sa nedá prečítať ({exc}) – počítam nanovo.",
          file=sys.stderr)
    print("-1 - -")
PY
)
  read -r DNI ID UZLOV <<<"$VEK"
  if [ "$DNI" -ge 0 ] && [ "$MAX_AGE" -gt 0 ] && [ "$DNI" -lt "$MAX_AGE" ]; then
    echo "Poradie uzlov $ID ($UZLOV uzlov) z cache je $DNI dní staré – pod ${MAX_AGE}, berie sa."
    { echo "computed=false"; echo "id=$ID"; echo "uzlov=$UZLOV"; } >> "${GITHUB_OUTPUT:-/dev/null}"
    exit 0
  fi
  [ "$DNI" -ge 0 ] && echo "Poradie uzlov $ID z cache je $DNI dní staré (strop $MAX_AGE) – počítam nanovo."
fi

# apt ide skôr než pbf.sh: `osmium merge` treba pri viacerých extraktoch
command -v osmium >/dev/null || { sudo apt-get update -qq; sudo apt-get install -y -qq osmium-tool; }
python3 -c 'import osmium' 2>/dev/null \
  || sudo apt-get install -y -qq python3-pyosmium \
  || python3 -m pip install --quiet --break-system-packages 'osmium>=3.6,<5'

T=$(date +%s)
# pbf.sh píše do data/routing.osm.pbf – to isté meno, aké si potom build kraja
# prepíše predfiltrom svojho PBF, takže sa po výpočte maže
workers/routing/pbf.sh
python3 workers/routing/order.py \
  --pbf=data/routing.osm.pbf \
  --out="$OUT" \
  --nazov="$AREA"
rm -f data/routing.osm.pbf

python3 - "$OUT" >> "${GITHUB_OUTPUT:-/dev/null}" <<'PY'
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
print("computed=true")
print(f"id={raw['id']}")
print(f"uzlov={raw['uzlov']}")
PY
printf '%s\t%s\t%s\t%s\n' "11" "Poradie uzlov ($AREA)" "$(( $(date +%s) - T ))" \
  "$(du -h "$OUT" | cut -f1)" >> steps-out/routing.tsv
