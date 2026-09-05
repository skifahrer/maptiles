#!/usr/bin/env python3
"""Značené trasy z OSM: turistické chodníky, cyklotrasy, bežky, jazdecké trasy.

Trasa nie je cesta – je to `type=route` relácia, ktorá zbiera cudzie cesty
a nesie značenie. Schéma OpenMapTiles relácie trás nemá, takže z dlaždíc sa
nedá zistiť, či po ceste vedie červená turistická, dve cyklotrasy, alebo nič.

Do dlaždíc ide aj značka (`osmc:symbol` rozobratý v `tags.py` na `mark`,
`mark_bg`, `mark_fg`), nie len farba pásika: pásik hovorí, čím trasu kresliť,
značka je obrázok tabuľky, ktorú má človek v teréne hľadať.

Jedna línia na dvojicu (cesta, trasa): po jednej ceste vedie bežne viac trás,
takže sa cesta zapíše toľkokrát a každá kópia dostane svoj pruh (`side` +
`off`). Pešie trasy idú na jednu stranu, kolesové na druhú, inak by sa tlačili
od cesty ďalej a ďalej:

    ━━ cyklotrasa (side −1, off 0) ━━
    ── chodník ──────────────────────
    ━━ červená    (side +1, off 0) ━━
    ━━ modrá      (side +1, off 1) ━━

Ako ďaleko rad začne a aký je krok, rozhoduje štýl – preto sa posiela aj `way`
(`road` alebo `path`). Poradie pruhov závisí len od vlastností trasy, nikdy od
poradia členov v relácii, takže si trasy na susedných úsekoch pruhy
neprehadzujú.

Smer čiary sa neurčuje z nej samej, ale z toho, na čo nadväzuje: `line-offset`
posúva podľa smeru geometrie a kým sa normalizoval „od západnejšieho konca",
preskakoval pásik na severojužnom chodníku na každom druhom úseku. Cesty sa
preto poreťazia podľa spoločných uzlov (`orient_ways`).

Nad PBF sa ide trikrát: relácie → koncové uzly ciest (bez súradníc, teda bez
indexu) → geometria. Tretí priechod je jediný drahý.

Zlom nad 120° sa rozdelí (`ease_corners`): ostrejší zlom `miter` nezošije
a pásik v zákrute vyzerá zúžený.

Vstup je PBF predfiltrovaný na `type=route` aj s členmi.

    python3 workers/trails/routes.py --pbf=data/trails.osm.pbf \\
        --out=data/trails.geojson --stats=trail-stats.txt
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict, deque

import osmium

# čo o trase hovoria jej tagy (farba, sieť, značka), je v `tags.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tags import (  # noqa: E402  (až za `sys.path`, inak sa modul nenájde)
    TIER_ORDER,
    resolve_colour,
    resolve_mark,
    resolve_tier,
)

# druhy trás: kľúč je hodnota `route` v relácii, hodnota náš druh
ROUTE_TYPES = {
    "hiking": "hiking",
    "foot": "hiking",
    "walking": "hiking",
    "bicycle": "bicycle",
    "mtb": "mtb",
    "ski": "ski",
    "nordic": "ski",
    "skitour": "ski",
    "horse": "horse",
    # ferrata je vlastný druh: vedie po skale, nie po chodníku
    "via_ferrata": "ferrata",
}

# poradie druhov v pruhoch – pešie značky najbližšie k ceste
ROUTE_ORDER = {"hiking": 0, "ferrata": 1, "bicycle": 2, "mtb": 3, "ski": 4,
               "horse": 5}

# na ktorú stranu ide pásik. Kolesové na opačnú než pešie: v jednom rade by sa
# druhá z nich odsunula tak ďaleko, že by nebolo vidieť, ku ktorej ceste patrí.
# +1 je vpravo v smere čiary (a ten je normalizovaný), −1 vľavo.
SIDE_BY_ROUTE = {"hiking": 1, "ferrata": 1, "ski": 1, "horse": 1,
                 "bicycle": -1, "mtb": -1}

# po čom trasa vedie. Asfaltka je v mape niekoľkonásobne širšia než chodník,
# takže odstup, pri ktorom sa pásik lepí na chodník, leží uprostred cesty.
# Do dlaždíc ide `path` (chodníky a lesné cesty) alebo `road`; odstup pre
# každý z tých dvoch prípadov si drží štýl.
PATH_HIGHWAYS = {
    "path", "footway", "bridleway", "steps", "track", "cycleway", "corridor",
}


def way_class(tags):
    """Po čom trasa vedie: `path` (chodník, lesná cesta) alebo `road`."""
    return "path" if (tags.get("highway") or "").strip().lower() \
        in PATH_HIGHWAYS else "road"

# zlom, ktorý sa nedá zošiť. Pásik sa kreslí `line-offset`, teda posunutím
# každého vrchola, a spoj `miter` posunie vrchol o `odstup / cos(zlom/2)`.
# MapLibre ten posun pakuje do bajtu, takže sa nad dvojnásobok odstupu
# nedostane – teda nad zlom 120°; ostrejší zreže na `bevel` a v zákrute ostane
# diera. Preto sa taký zlom rozdelí na zlomy po 60°, krátkym oblúkom:
#
#   * reže sa len 2 m (0,6 px pri z16), takže pásik ide tade, kade chodník.
#     Menej sa nedá – dlaždice trás majú pri z14 rozlíšenie 0,39 m;
#   * zlomov nad 120° je málo: namerané 1,6 % vrcholov. Pri hranici 30° by
#     geometria narástla o 108 %;
#   * vlásenka nad ~150° ostane vlásenkou a krajné body sa nehýbu.
EASE_ABOVE_DEG = 120.0
MAX_TURN_DEG = 60.0
CUT_M = 2.0
# body bližšie než toto sú po zaoblení to isté miesto – dva vrcholy na sebe
# nemajú definovaný smer
MIN_STEP_M = 0.2


def ease_corners(coords, above_deg=EASE_ABOVE_DEG, max_turn_deg=MAX_TURN_DEG,
                 cut_m=CUT_M):
    """Zaoblí zlomy ostrejšie než `above_deg`; vracia `(body, počet)`.

    Počíta sa v metroch (rovinná aproximácia okolo stredu čiary), krajné body
    sa nehýbu: cesty na seba musia nadväzovať tými istými uzlami ako v OSM.
    """
    if len(coords) < 3:
        return coords, 0
    lat_mid = sum(c[1] for c in coords) / len(coords)
    mx = 111320.0 * math.cos(math.radians(lat_mid))
    my = 110540.0
    pts = [((lon - coords[0][0]) * mx, (lat - coords[0][1]) * my)
           for lon, lat in coords]
    max_turn = math.radians(max_turn_deg)
    above = math.radians(above_deg)

    out = [pts[0]]
    eased = 0
    for i in range(1, len(pts) - 1):
        (px, py), (x, y), (nx, ny) = pts[i - 1], pts[i], pts[i + 1]
        ax, ay, bx, by = x - px, y - py, nx - x, ny - y
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        if la == 0 or lb == 0:
            continue
        dot = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        turn = math.acos(dot)
        if turn <= above:
            out.append((x, y))
            continue
        eased += 1
        cut = min(cut_m, la * 0.45, lb * 0.45)
        a = (x - ax / la * cut, y - ay / la * cut)
        b = (x + bx / lb * cut, y + by / lb * cut)
        # kvadratická Bezierova krivka s pôvodným vrcholom ako riadiacim
        # bodom – nadväzuje na ramená bez zlomu. Kúsok navyše preto, že Bezier
        # nerozdeľuje uhol rovnomerne.
        n = max(2, math.ceil(turn / max_turn) + 1)
        out.append(a)
        for k in range(1, n):
            t = k / n
            s = 1 - t
            out.append((s * s * a[0] + 2 * s * t * x + t * t * b[0],
                        s * s * a[1] + 2 * s * t * y + t * t * b[1]))
        out.append(b)
    out.append(pts[-1])

    # krajné body sa neprepočítavajú: cesty nadväzujú spoločným uzlom a ten
    # sa nesmie pohnúť, inak Planetiler susedné úseky nezlepí
    lon0, lat0 = coords[0]
    res = []
    for j, (x, y) in enumerate(out):
        last = j == len(out) - 1
        if res and not last and \
                math.hypot(x - res[-1][1], y - res[-1][2]) < MIN_STEP_M:
            continue
        if j == 0:
            res.append((list(coords[0]), x, y))
        elif last:
            res.append((list(coords[-1]), x, y))
        else:
            res.append(([round(lon0 + x / mx, 7),
                         round(lat0 + y / my, 7)], x, y))
    return [ll for ll, _, _ in res], eased


# role členov, ktoré nie sú samotnou trasou
SKIP_ROLES = {
    "guidepost", "marker", "sign", "signpost", "stop", "platform",
    "site", "label", "map", "fixme", "shelter", "info",
}

# trasy, ktoré ešte neexistujú, do mapy nepatria
SKIP_STATES = {"proposed", "planned", "abandoned", "removed", "disused"}


# smer čiar (reťazenie)

def orient_ways(ends):
    """Ktoré cesty otočiť, aby na seba pásiky nadväzovali.

    `ends` je `{id cesty: (prvý uzol, posledný uzol)}` – len susedstvo, žiadne
    súradnice. Vracia `(množina ciest na otočenie, spory, reťaze)`.

    Cesty sú hrany grafu, uzly OSM jeho vrcholy: od každej neprebranej sa ide
    do šírky a susedovi sa pridelí smer tak, aby v spoločnom uzle jedna
    končila a druhá začínala.

    Na križovatke troch a viac chodníkov „nadväzovať" definované nie je –
    niektorá vetva stranu prehodí. Koľko takých miest je, hovorí `spory`.

    Smer prvej cesty v reťazi je ľubovoľný, ale stály (najmenšie id).
    """
    at = defaultdict(list)
    for wid, (first, last) in ends.items():
        at[first].append(wid)
        # uzavretý okruh sa dotýka svojho uzla dvakrát; do susedstva patrí raz
        if last != first:
            at[last].append(wid)

    flip = {}
    chains = 0
    for seed in sorted(ends):
        if seed in flip:
            continue
        chains += 1
        first, last = ends[seed]
        flip[seed] = first > last
        queue = deque([seed])
        while queue:
            wid = queue.popleft()
            first, last = ends[wid]
            tail, head = (last, first) if flip[wid] else (first, last)
            # dopredu od hlavy aj dozadu od päty
            for node, starts_there in ((head, True), (tail, False)):
                for nxt in at.get(node, ()):
                    if nxt in flip:
                        continue
                    nfirst, nlast = ends[nxt]
                    flip[nxt] = nfirst != node if starts_there else nlast != node
                    queue.append(nxt)

    # spory sa počítajú len tam, kde je „nadväzovať" definované – v uzle,
    # kde sa stretávajú práve dve cesty
    conflicts = 0
    for node, wids in at.items():
        if len(wids) != 2:
            continue
        heads = 0
        for wid in wids:
            first, last = ends[wid]
            head = first if flip[wid] else last
            heads += head == node
        if heads != 1:
            conflicts += 1

    return {wid for wid, rev in flip.items() if rev}, conflicts, chains


class Ends(osmium.SimpleHandler):
    """2. priechod: koncové uzly ciest, po ktorých nejaká trasa vedie.

    Bez súradníc, teda bez indexu uzlov.
    """

    def __init__(self, by_way):
        super().__init__()
        self.by_way = by_way
        self.ends = {}

    def way(self, w):
        if w.id not in self.by_way or len(w.nodes) < 2:
            return
        self.ends[w.id] = (w.nodes[0].ref, w.nodes[-1].ref)


class Routes(osmium.SimpleHandler):
    """1. priechod: z relácií vyrobí zoznam trás na každej ceste."""

    def __init__(self):
        super().__init__()
        self.by_way = defaultdict(list)
        self.routes = 0
        self.skipped = Counter()

    def relation(self, r):
        tags = {t.k: t.v for t in r.tags}
        if tags.get("type") != "route":
            return
        route = ROUTE_TYPES.get((tags.get("route") or "").strip().lower())
        if not route:
            self.skipped[(tags.get("route") or "?")] += 1
            return
        if (tags.get("state") or "").strip().lower() in SKIP_STATES:
            self.skipped["state"] += 1
            return

        colour, hexcolour = resolve_colour(tags)
        tier, network = resolve_tier(tags)
        # značka, ako je na strome – iná otázka než farba pásika
        mark, mark_bg, mark_fg = resolve_mark(tags, route, colour)
        info = {
            "route": route,
            "colour": colour,
            "hex": hexcolour,
            "mark": mark or "",
            "mark_bg": mark_bg or "",
            "mark_fg": mark_fg or "",
            "network": network,
            "tier": tier,
            "name": (tags.get("name:sk") or tags.get("name") or "").strip(),
            "ref": (tags.get("ref") or "").strip(),
            "rel": r.id,
        }
        self.routes += 1
        for m in r.members:
            if m.type != "w" or (m.role or "").strip().lower() in SKIP_ROLES:
                continue
            self.by_way[m.ref].append(info)


class Ways(osmium.SimpleHandler):
    """3. priechod: cesty s trasou dostanú geometriu, a rovno toľko kópií,
    koľko trás po nich ide (každá vo svojom pruhu).
    """

    def __init__(self, by_way, out, flipped=frozenset()):
        super().__init__()
        self.by_way = by_way
        self.out = out
        # ktoré cesty kresliť opačne, nech pásik drží stranu
        self.flipped = flipped
        self.features = 0
        self.ways = 0
        self.no_geometry = 0
        self.by_type = Counter()
        self.by_colour = Counter()
        self.by_mark = Counter()
        self.by_tier = Counter()
        self.by_way_class = Counter()
        self.lanes = Counter()
        self.named = set()
        # koľko zlomov sa rozdelilo a o koľko bodov geometria narástla
        self.eased = 0
        self.points_in = 0
        self.points_out = 0

    def way(self, w):
        routes = self.by_way.get(w.id)
        if not routes:
            return

        coords = []
        for n in w.nodes:
            if n.location.valid():
                coords.append([round(n.lon, 7), round(n.lat, 7)])
        if len(coords) < 2:
            self.no_geometry += 1
            return

        # smer čiary určuje, na ktorú stranu ju `line-offset` posunie –
        # rozhodlo sa o ňom v `orient_ways` podľa toho, na čo cesta nadväzuje
        if w.id in self.flipped:
            coords.reverse()

        # zlom nad 120° `miter` nezošije. Raz na cestu, nie raz na pruh –
        # všetky pruhy tej istej cesty kreslia tú istú čiaru.
        self.points_in += len(coords)
        coords, eased = ease_corners(coords)
        self.points_out += len(coords)
        self.eased += eased

        lanes = self.lane_order(routes)
        way = way_class({t.k: t.v for t in w.tags})
        self.ways += 1
        self.lanes[len(lanes)] += 1
        self.by_way_class[way] += 1
        # rady sa číslujú zvlášť pre každú stranu
        taken = Counter()
        for info in lanes:
            side = SIDE_BY_ROUTE.get(info["route"], 1)
            idx = taken[side]
            taken[side] += 1
            self.by_type[info["route"]] += 1
            self.by_colour[info["colour"] or "bez farby"] += 1
            self.by_mark[
                f'{info["mark_bg"]}-{info["mark_fg"]}-{info["mark"]}'
                if info["mark"] else "bez značky"
            ] += 1
            self.by_tier[info["tier"]] += 1
            if info["name"]:
                self.named.add(info["rel"])
            props = {
                "route": info["route"],
                "tier": info["tier"],
                # pruhy sa číslujú od cesty von; vycentrované by koniec jednej
                # trasy posunul všetky ostatné
                "side": side,
                "off": idx,
                "way": way,
                "cnt": len(lanes),
                "rel": info["rel"],
            }
            for key in ("colour", "hex", "network", "name", "ref",
                        "mark", "mark_bg", "mark_fg"):
                if info[key]:
                    props[key] = info[key]
            self.write(coords, props)
            self.features += 1

    @staticmethod
    def lane_order(routes):
        """Poradie pruhov na ceste – kľúč len z vlastností trasy, nie z poradia
        členov v relácii.

        Zároveň sa zahodia duplikáty: nadradená trasa a jej časť sú v OSM dve
        relácie na tých istých cestách.
        """
        seen = {}
        for info in routes:
            key = (info["route"], info["colour"], info["hex"],
                   info["ref"] or info["name"])
            # z rovnakých trás si necháme tú s názvom
            old = seen.get(key)
            if old is None or (not old["name"] and info["name"]):
                seen[key] = info
        return sorted(
            seen.values(),
            key=lambda i: (
                TIER_ORDER.get(i["tier"], 9),
                ROUTE_ORDER.get(i["route"], 9),
                i["colour"],
                i["ref"],
                i["name"],
                i["rel"],
            ),
        )

    def write(self, coords, props):
        """Features sa píšu priebežne – v pamäti by ich bol celý kraj naraz."""
        self.out.write("," if self.features else "")
        json.dump(
            {"type": "Feature", "properties": props,
             "geometry": {"type": "LineString", "coordinates": coords}},
            self.out, ensure_ascii=False, separators=(",", ":"),
        )
        self.out.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True, help="PBF predfiltrovaný na relácie trás")
    ap.add_argument("--out", required=True, help="výstupný .geojson pre Planetiler")
    ap.add_argument("--stats", default="", help="kam zapísať čísla pre súhrn buildu")
    args = ap.parse_args()

    if not os.path.exists(args.pbf):
        print(f"::error::Vstup {args.pbf} neexistuje.", file=sys.stderr)
        return 1

    print(f"1/3 – hľadám relácie trás v {args.pbf} …", flush=True)
    routes = Routes()
    routes.apply_file(args.pbf)
    print(f"    trás: {routes.routes}, ciest s trasou: {len(routes.by_way)}")
    if routes.skipped:
        top = ", ".join(f"{k}={v}" for k, v in routes.skipped.most_common(6))
        print(f"    preskočené relácie (iný druh alebo stav): {top}")

    if not routes.routes:
        print("::warning::V tomto území nie je ani jedna značená trasa – "
              "mapa pôjde bez nich.")

    # smer sa nesmie brať z tvaru jednej čiary (rozpis v hlavičke); tento
    # priechod je lacný – číta len koncové uzly
    print("2/3 – kto s kým susedí (smer pásikov) …", flush=True)
    ends = Ends(routes.by_way)
    ends.apply_file(args.pbf)
    flipped, conflicts, chains = orient_ways(ends.ends)
    print(f"    ciest {len(ends.ends)} v {chains} reťaziach, "
          f"otočených {len(flipped)}")
    # spor = uzol, kde sa stretávajú dve cesty a pásik prehodí stranu. Nula sa
    # čakať nedá, ale keď číslo skočí, smerovanie sa pokazilo.
    pct = 100.0 * conflicts / max(1, len(ends.ends))
    print(f"    miest, kde pásik napriek tomu prehodí stranu: {conflicts} "
          f"({pct:.1f} % ciest)")
    if pct > 5:
        print("::warning::Pásiky trás prehadzujú stranu na "
              f"{pct:.0f} % ciest – to je veľa. Pozri `orient_ways` vo "
              "workers/trails/routes.py; malo by to byť pod 5 %.")

    print("3/3 – skladám geometriu ciest …", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write('{"type":"FeatureCollection","features":[\n')
        ways = Ways(routes.by_way, fh, flipped)
        # `locations=True` doplní súradnice uzlov – predfiltrovaný PBF ich má
        ways.apply_file(args.pbf, locations=True, idx="flex_mem")
        fh.write("]}\n")

    size_mb = os.path.getsize(args.out) / 1048576
    print(f"✓ {args.out}: {ways.features} úsekov na {ways.ways} cestách "
          f"({size_mb:.1f} MB)")
    if ways.no_geometry:
        print(f"::warning::{ways.no_geometry} ciest nemá v PBF súradnice "
              "(člen mimo územia) – tie úseky v mape nebudú.")
    order = sorted(ways.by_type.items(), key=lambda kv: -kv[1])
    print("  druhy:  " + ", ".join(f"{k} {v}" for k, v in order))
    print("  farby:  " + ", ".join(f"{k} {v}" for k, v in ways.by_colour.most_common()))
    print("  značky: " + ", ".join(
        f"{k} {v}" for k, v in ways.by_mark.most_common(8))
        + "  (podklad-farba-tvar; „bez značky\" kreslí ikonku druhu trasy)")
    print("  siete:  " + ", ".join(f"{k} {v}" for k, v in ways.by_tier.most_common()))
    print("  vedú po: " + ", ".join(
        f"{k} {v}" for k, v in ways.by_way_class.most_common())
        + "  (`path` = chodník a lesná cesta, `road` = ostatné; štýl podľa "
          "toho volí odstup pásika)")
    multi = sum(n for lanes, n in ways.lanes.items() if lanes > 1)
    print(f"  ciest s viac než jednou trasou: {multi} "
          f"(najviac naraz: {max(ways.lanes, default=0)})")
    grew = 100.0 * (ways.points_out - ways.points_in) / max(1, ways.points_in)
    print(f"  rozdelených zlomov nad {EASE_ABOVE_DEG:.0f}°: {ways.eased} "
          f"(bodov {ways.points_in} → {ways.points_out}, {grew:+.1f} %) – nad "
          "nimi spoj `miter` pásik nezošije a v zákrute sa zúži")

    if args.stats:
        with open(args.stats, "w", encoding="utf-8") as fh:
            fh.write(f"routes={routes.routes}\n")
            fh.write(f"named={len(ways.named)}\n")
            fh.write(f"ways={ways.ways}\n")
            fh.write(f"features={ways.features}\n")
            fh.write(f"multi={multi}\n")
            fh.write(f"chains={chains}\n")
            fh.write(f"side_flips={conflicts}\n")
            fh.write(f"eased={ways.eased}\n")
            fh.write(f"max_lanes={max(ways.lanes, default=0)}\n")
            for key, count in ways.by_type.items():
                fh.write(f"type_{key}={count}\n")
            for key, count in ways.by_tier.items():
                fh.write(f"tier_{key}={count}\n")
            # súhrn si súbor načíta cez `.`, takže bez úvodzoviek by to shell
            # pri medzerách a zátvorkách nezobral
            fh.write('colours="' + ", ".join(
                f"{k} {v}" for k, v in ways.by_colour.most_common()) + '"\n')
            # koľko úsekov dostalo naozajstnú značku – vidieť z toho, či sa
            # `osmc:symbol` v tomto kraji vôbec používa
            fh.write(f"marked={sum(v for k, v in ways.by_mark.items() if k != 'bez značky')}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
