#!/usr/bin/env python3
"""What a route's tags say: lane colour, network importance and the painted mark.

    python3 workers/trails/tags.py --osmc=red:white:red_bar --route=hiking
"""
import argparse
import re

# `network` prefix i/n/r/l → `tier`, which sets the zoom a route appears from
TIER_BY_PREFIX = {"i": "international", "n": "national", "r": "regional", "l": "local"}
TIER_ORDER = {"international": 0, "national": 1, "regional": 2, "local": 3}

# colours the style can recolour by palette; anything else goes as raw `hex`
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
# 441 is black ↔ white, 110 is "the same colour, another shade"
COLOUR_SNAP = 110

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex(value):
    """`#a3b` / `a3b2c1` → (r, g, b); else None."""
    m = HEX_RE.match(value.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def resolve_colour(tags):
    """Mark colour as (name, hex); `osmc:symbol` first, its first field is the painted stripe."""
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

    # snapped only when close: #e01b24 is red, #ff69b4 isn't
    name, dist = min(
        ((n, sum((a - b) ** 2 for a, b in zip(rgb, ref)) ** 0.5)
         for n, ref in NAMED_COLOURS.items()),
        key=lambda x: x[1],
    )
    if dist <= COLOUR_SNAP:
        return name, ""
    return "", "#%02x%02x%02x" % rgb


# the mark as painted on the tree (`mark`, `mark_bg`, `mark_fg`), not the lane colour;
# `osmc:symbol` is `stripe:background:foreground[:foreground2][:text:text_colour]`.
# Shape variants map to one shape: at 14 px they'd be indistinguishable anyway.
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

# colours really painted on marks; any other gets the route kind icon instead
MARK_COLOURS = {"red", "blue", "green", "yellow", "black", "white"}

# background → colour pairs baked into the sprite; must match `poc/web/marks.js`
MARK_FACES = {
    ("white", "red"), ("white", "blue"), ("white", "green"),
    ("white", "yellow"), ("white", "black"),
    ("yellow", "red"), ("yellow", "blue"), ("yellow", "green"),
    ("yellow", "black"), ("yellow", "white"),
    ("red", "white"), ("blue", "white"), ("green", "white"), ("black", "white"),
}

# walking marks are white, cycling yellow, when `osmc:symbol` doesn't say
MARK_BG_BY_ROUTE = {"bicycle": "yellow", "mtb": "yellow"}
MARK_BG_DEFAULT = "white"


def colour_name(raw):
    """Colour name from `osmc:symbol` – the same snapping as the lane."""
    raw = (raw or "").strip().lower()
    if raw in NAMED_COLOURS:
        return raw
    return COLOUR_ALIASES.get(raw, "")


def split_symbol(token):
    """`red_bar` → ("red", "bar"); `bar` → ("", "bar")."""
    token = (token or "").strip().lower()
    if not token:
        return "", ""
    head, _, rest = token.partition("_")
    colour = colour_name(head)
    if colour and rest:
        shape = OSMC_SHAPES.get(rest) or OSMC_SHAPES.get(rest.partition("_")[0], "")
        return colour, shape
    return "", OSMC_SHAPES.get(token) or OSMC_SHAPES.get(head, "")


def resolve_mark(tags, route, colour):
    """The route's mark as `(shape, background, colour)`, or `(None, None, None)`."""
    fields = [f.strip().lower() for f in (tags.get("osmc:symbol") or "").split(":")]
    bg = colour_name(fields[1]) if len(fields) > 1 else ""
    fg, shape = "", ""
    # the foreground may sit a field later (`red:white::red_bar`)
    for token in fields[2:]:
        f, t = split_symbol(token)
        fg = fg or f
        shape = shape or t
        if fg and shape:
            break

    fg = fg or colour
    if not shape:
        # a colourless cycle route is a bicycle on yellow, as in the field
        shape = "bicycle" if (route in MARK_BG_BY_ROUTE and not fg) else "bar"
    if shape == "bicycle" and fg in ("", "yellow"):
        # the bicycle is black; yellow on yellow would be an empty square
        fg = "black"
    # a colourless walking route gets no invented mark
    if fg not in MARK_COLOURS:
        return None, None, None

    if bg not in MARK_COLOURS:
        bg = MARK_BG_BY_ROUTE.get(route, MARK_BG_DEFAULT)
    # a baked background, most common in the field first
    for candidate in (bg, MARK_BG_BY_ROUTE.get(route, MARK_BG_DEFAULT),
                      MARK_BG_DEFAULT, "yellow", "black"):
        if (candidate, fg) in MARK_FACES:
            return shape, candidate, fg
    return None, None, None


def resolve_tier(tags):
    """How far a route shows: international … local."""
    network = (tags.get("network") or "").strip().lower()
    base = network.split(":")[0]
    if len(base) == 3 and base[0] in TIER_BY_PREFIX and base[1:] in (
        "wn", "cn", "hn", "sn", "mn", "pn"
    ):
        return TIER_BY_PREFIX[base[0]], network

    # without a network the length decides
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
    """Try by hand: which mark and colour an `osmc:symbol` gives."""
    ap = argparse.ArgumentParser(description="What a route's tags say")
    ap.add_argument("--osmc", default="", help="value of `osmc:symbol`")
    ap.add_argument("--colour", default="", help="value of `colour`")
    ap.add_argument("--network", default="", help="value of `network`")
    ap.add_argument("--route", default="hiking", help="route kind (hiking, bicycle…)")
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
    print(f"colour:  {colour or '(none)'}{' ' + hexcolour if hexcolour else ''}")
    print(f"network: {tier} ({network or '?'})")
    print("mark:    " + (f"{bg}-{fg}-{mark}  (image `mark-{bg}-{fg}-{mark}`)"
                         if mark else "(none – the route kind icon is drawn)"))


if __name__ == "__main__":
    main()
