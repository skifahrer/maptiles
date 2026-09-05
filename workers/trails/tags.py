#!/usr/bin/env python3
"""Čo o trase hovoria jej tagy: farba pásika, dôležitosť siete a značka.

Oddelené od `routes.py`, ktorý odpovedá na „kade trasa vedie"; tu je otázka
„čo je to za trasu" – čítanie `osmc:symbol`, `colour` a `network`.

    python3 workers/trails/tags.py --osmc=red:white:red_bar --route=hiking
"""
import argparse
import re

# ------------------------------------------------------------------- siete
# `network` hovorí, aká je trasa dôležitá: i = medzinárodná, n = národná,
# r = regionálna, l = miestna (iwn/nwn/rwn/lwn pre pešie, icn/… pre cyklo,
# ihn/… pre jazdecké). Z toho je `tier`, ktorý riadi, od akého zoomu je
# trasa v dlaždiciach – diaľkové trasy majú byť vidieť aj z prehľadu.
TIER_BY_PREFIX = {"i": "international", "n": "national", "r": "regional", "l": "local"}
TIER_ORDER = {"international": 0, "national": 1, "regional": 2, "local": 3}

# Farby značiek, ktoré vie štýl prefarbiť cez paletu. Čokoľvek mimo tohto
# zoznamu ide do mapy ako surový hex z OSM (atribút `hex`).
NAMED_COLOURS = {
    "black": (0x00, 0x00, 0x00),
    "blue": (0x00, 0x00, 0xFF),
    "brown": (0x96, 0x4B, 0x00),
    "gray": (0x80, 0x80, 0x80),
    "green": (0x00, 0x80, 0x00),
    "orange": (0xFF, 0xA5, 0x00),
    "purple": (0x80, 0x00, 0x80),
    "red": (0xFF, 0x00, 0x00),
    "white": (0xFF, 0xFF, 0xFF),
    "yellow": (0xFF, 0xFF, 0x00),
}
COLOUR_ALIASES = {
    "grey": "gray",
    "silver": "gray",
    "lightgray": "gray",
    "lightgrey": "gray",
    "darkgray": "gray",
    "darkgrey": "gray",
    "violet": "purple",
    "magenta": "purple",
    "pink": "purple",
    "lightblue": "blue",
    "darkblue": "blue",
    "navy": "blue",
    "cyan": "blue",
    "lightgreen": "green",
    "darkgreen": "green",
    "lime": "green",
    "olive": "green",
    "gold": "yellow",
    "beige": "yellow",
    "maroon": "brown",
    "tan": "brown",
}
# Ako ďaleko smie byť hex od pomenovanej farby, aby sa na ňu ešte zaokrúhlil.
# 441 je maximum (čierna ↔ biela), 110 je „tá istá farba, iný odtieň“.
COLOUR_SNAP = 110

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex(value):
    """`#a3b` / `a3b2c1` → (r, g, b); inak None."""
    m = HEX_RE.match(value.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def resolve_colour(tags):
    """
    Farba značky ako (názov, hex).

    Poradie zdrojov je zámerné: `osmc:symbol` je *predpis značky* a jeho
    prvé pole je farba pásika na strome – to je presne to, čo je v teréne.
    `colour` býva to isté, ale niekedy chýba alebo nesie farbu podkladu.
    """
    raw = ""
    osmc = tags.get("osmc:symbol", "")
    if osmc:
        raw = osmc.split(":")[0].strip().lower()
    if not raw:
        raw = (tags.get("colour") or tags.get("color") or "").strip().lower()
    if not raw:
        return "", ""

    if raw in NAMED_COLOURS:
        return raw, ""
    if raw in COLOUR_ALIASES:
        return COLOUR_ALIASES[raw], ""

    rgb = parse_hex(raw)
    if rgb is None:
        return "", ""

    # Hex sa zaokrúhli na najbližšiu pomenovanú farbu, ale len keď je naozaj
    # blízko – #e01b24 je červená, #ff69b4 už nie. Čo sa nezaokrúhli, ide do
    # mapy tak, ako to je: štýl použije priamo tento hex.
    name, dist = min(
        ((n, sum((a - b) ** 2 for a, b in zip(rgb, ref)) ** 0.5)
         for n, ref in NAMED_COLOURS.items()),
        key=lambda x: x[1],
    )
    if dist <= COLOUR_SNAP:
        return name, ""
    return "", "#%02x%02x%02x" % rgb


# ------------------------------------------------ značka, ako je na strome
# TURISTICKÁ A CYKLISTICKÁ ZNAČKA (SK aj CZ): štvorec 10 × 10 cm, v ňom
# vodorovný pás vo farbe trasy a nad ním aj pod ním pás podkladu – biely pri
# pešej značke, žltý pri cyklistickej. Okrem pásovej sú aj tvarové (vrcholová
# trojuholníková, „L" k pamiatke, kruh k prameňu) a česká cyklistická značka
# má na žltom podklade bicykel.
#
# Je to iná otázka než farba pásika trasy (`resolve_colour`): tá hovorí,
# akou farbou trasu KRESLIŤ, kým toto je obrázok tabuľky, ktorú má človek
# v teréne hľadať. Do dlaždíc preto idú tri atribúty (`mark`, `mark_bg`,
# `mark_fg`) a štýl z nich skladá meno obrázka v sprite.
#
# `osmc:symbol` je `farba_pásika:podklad:predok[:predok2][:text:farba_textu]`,
# napríklad `red:white:red_bar` alebo `yellow:yellow:black_bicycle`.

# Predné pole `osmc:symbol` bez farebnej predpony → tvar, ktorý vie štýl
# nakresliť (`MARK_SHAPES` v `poc/web/marks.js`; stráži to
# `workers/lint/marks.mjs`). Varianty s príponou sedia na tom istom tvare:
# značenie rozlišuje `bar` a `bar_right`, ale značka je v mape 14 px veľká
# a nerozoznateľný rozdiel je horší než ten istý tvar dvakrát.
OSMC_SHAPES = {
    "bar": "bar", "stripe": "bar", "rectangle": "bar", "rectangle_line": "bar",
    "bar_right": "bar", "bar_left": "bar", "lower": "bar", "upper": "bar",
    "slash": "slash", "backslash": "slash", "diagonal": "slash",
    "triangle": "triangle", "triangle_line": "triangle",
    "triangle_turned": "triangle", "pointer": "triangle", "arrow": "triangle",
    "circle": "circle", "ring": "circle", "wheel": "circle",
    "wheel_crossed": "circle",
    "dot": "dot", "disc": "dot", "circle_full": "dot", "round": "dot",
    "l": "corner", "corner": "corner", "right": "corner", "left": "corner",
    "turned_t": "corner",
    "bowl": "bowl", "arch": "bowl", "u": "bowl", "cup": "bowl",
    "horseshoe": "bowl",
    "cross": "cross", "plus": "cross",
    "x": "x", "saltire": "x", "crossing": "x",
    "diamond": "diamond", "rhombus": "diamond", "lozenge": "diamond",
    "bicycle": "bicycle", "bike": "bicycle", "cycle": "bicycle",
}

# Farby, ktoré sú na značkách naozaj namaľované. Trasa s inou farbou značku
# NEDOSTANE (kreslí sa jej ikonka druhu trasy) – tabuľka s fialovým pásom
# v teréne nie je a vyrobiť ju by znamenalo tvrdiť o značení niečo, čo nie je
# pravda (pravidlo 2: meno je sľub o rozsahu, tu je ním obrázok).
MARK_COLOURS = {"red", "blue", "green", "yellow", "black", "white"}

# Dvojice podklad → farba, ktoré `workers/assets/marks.mjs` pečie do spritu.
# Musia sedieť s `MARK_FACES` v `poc/web/marks.js`: meno obrázka skladá štýl
# z týchto dvoch hodnôt, takže dvojica navyše znamená v mape prázdno –
# a nič pri tom nespadne. Stráži to `workers/lint/marks.mjs`.
MARK_FACES = {
    ("white", "red"), ("white", "blue"), ("white", "green"),
    ("white", "yellow"), ("white", "black"),
    ("yellow", "red"), ("yellow", "blue"), ("yellow", "green"),
    ("yellow", "black"), ("yellow", "white"),
    ("red", "white"), ("blue", "white"), ("green", "white"), ("black", "white"),
}

# Podklad podľa druhu trasy, keď ho `osmc:symbol` nepovie: pešia značka je
# biela, cyklistická žltá (SK aj CZ).
MARK_BG_BY_ROUTE = {"bicycle": "yellow", "mtb": "yellow"}
MARK_BG_DEFAULT = "white"


def colour_name(raw):
    """Meno farby zo `osmc:symbol` – to isté zaokrúhľovanie ako pri pásiku."""
    raw = (raw or "").strip().lower()
    if raw in NAMED_COLOURS:
        return raw
    return COLOUR_ALIASES.get(raw, "")


def split_symbol(token):
    """`red_bar` → („red", „bar"); `bar` → („", „bar")."""
    token = (token or "").strip().lower()
    if not token:
        return "", ""
    head, _, rest = token.partition("_")
    farba = colour_name(head)
    if farba and rest:
        tvar = OSMC_SHAPES.get(rest) or OSMC_SHAPES.get(rest.partition("_")[0], "")
        return farba, tvar
    return "", OSMC_SHAPES.get(token) or OSMC_SHAPES.get(head, "")


def resolve_mark(tags, route, colour):
    """
    Značka trasy ako `(tvar, podklad, farba)`, alebo `(None, None, None)`.

    Poradie zdrojov: `osmc:symbol` (predpis značky – je v ňom podklad aj tvar),
    potom farba pásika a druh trasy. Cyklotrasa bez farby dostane českú
    cyklistickú značku – žltý štvorec s čiernym bicyklom –, lebo presne tá je
    v teréne; pešia trasa bez farby značku nedostane, tam by sme si ju vymysleli.
    """
    fields = [f.strip().lower() for f in (tags.get("osmc:symbol") or "").split(":")]
    bg = colour_name(fields[1]) if len(fields) > 1 else ""
    fg, shape = "", ""
    # Predok býva v treťom poli, ale nie vždy – `red:white::red_bar` má prvé
    # pole predku prázdne a značku až v ďalšom.
    for token in fields[2:]:
        f, t = split_symbol(token)
        fg = fg or f
        shape = shape or t
        if fg and shape:
            break

    fg = fg or colour
    if not shape:
        # Cyklotrasa bez tvaru v `osmc:symbol` má pás vo svojej farbe; keď
        # farbu nemá, je to bicykel na žltom – tak, ako je značka v teréne.
        shape = "bicycle" if (route in MARK_BG_BY_ROUTE and not fg) else "bar"
    if shape == "bicycle" and fg in ("", "yellow"):
        # Bicykel je na značke čierny. Žltý na žltom podklade by bol prázdny
        # štvorec a „bez farby" pri cyklotrase neznamená „bez značky" –
        # v teréne je tá značka žltý štvorec s čiernym bicyklom.
        fg = "black"
    # Pešia trasa bez farby značku nedostane: vymysleli by sme tabuľku, ktorá
    # v teréne nie je. Kreslí sa jej ikonka druhu trasy, tak ako predtým.
    if fg not in MARK_COLOURS:
        return None, None, None

    if bg not in MARK_COLOURS:
        bg = MARK_BG_BY_ROUTE.get(route, MARK_BG_DEFAULT)
    # Pás vo farbe podkladu je prázdny štvorec, takže sa podklad vymení za
    # taký, ktorý sa pečie. Poradie je „čo je v teréne najbežnejšie".
    for kandidat in (bg, MARK_BG_BY_ROUTE.get(route, MARK_BG_DEFAULT),
                     MARK_BG_DEFAULT, "yellow", "black"):
        if (kandidat, fg) in MARK_FACES:
            return shape, kandidat, fg
    return None, None, None


def resolve_tier(tags):
    """Ako ďaleko je trasa vidieť: medzinárodná … miestna."""
    network = (tags.get("network") or "").strip().lower()
    base = network.split(":")[0]
    if len(base) == 3 and base[0] in TIER_BY_PREFIX and base[1:] in (
        "wn", "cn", "hn", "sn", "mn", "pn"
    ):
        return TIER_BY_PREFIX[base[0]], network

    # Bez siete rozhoduje dĺžka – diaľková trasa má byť vidieť aj z prehľadu,
    # aj keď ju nikto nezaradil do siete.
    try:
        km = float(re.sub(r"[^0-9.]", "", tags.get("distance", "")) or 0)
    except ValueError:
        km = 0
    if km >= 150:
        return "national", network
    if km >= 50:
        return "regional", network
    return "local", network


def main():
    """Ručná skúška: čo z tohto `osmc:symbol` vyjde za značku a farbu."""
    ap = argparse.ArgumentParser(description="Čo o trase hovoria jej tagy")
    ap.add_argument("--osmc", default="", help="hodnota `osmc:symbol`")
    ap.add_argument("--colour", default="", help="hodnota `colour`")
    ap.add_argument("--network", default="", help="hodnota `network`")
    ap.add_argument("--route", default="hiking", help="druh trasy (hiking, bicycle…)")
    a = ap.parse_args()
    tags = {}
    if a.osmc:
        tags["osmc:symbol"] = a.osmc
    if a.colour:
        tags["colour"] = a.colour
    if a.network:
        tags["network"] = a.network
    colour, hexcolour = resolve_colour(tags)
    tier, network = resolve_tier(tags)
    mark, bg, fg = resolve_mark(tags, a.route, colour)
    print(f"farba:  {colour or '(žiadna)'}{' ' + hexcolour if hexcolour else ''}")
    print(f"sieť:   {tier} ({network or '?'})")
    print("značka: " + (f"{bg}-{fg}-{mark}  (obrázok `mark-{bg}-{fg}-{mark}`)"
                        if mark else "(žiadna – kreslí sa ikonka druhu trasy)"))


if __name__ == "__main__":
    main()
