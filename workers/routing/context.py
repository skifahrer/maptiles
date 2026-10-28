#!/usr/bin/env python3
"""A road's speed context – which of its country's default limits applies on it."""
import math

# the order of `speed_context` in routing-tags.json
CONTEXTS = ("urban", "rural", "motorway", "urban_motorway", "motorroad",
            "urban_motorroad", "living_street")

# a path or a footway has no default car speed
MOTOR = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
         "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
         "residential", "living_street", "service", "track", "road"}

# industry often stands outside a village, so it isn't one
BUILT_UP = ("residential", "commercial", "retail")

# OSM writes the default a road falls under as `<country>:<zone>`
ZONE_KEYS = ("maxspeed:type", "source:maxspeed", "zone:maxspeed", "zone:traffic", "maxspeed")
ZONES = {"urban": "urban", "rural": "rural", "motorway": "motorway",
         "living_street": "living_street", "pedestrian_zone": "living_street"}

# the gap a village's gardens and a church leave between residential areas
GAP_M = 30
# the share of an edge that makes it urban
URBAN_SHARE = 0.5
METRES_PER_DEGREE = 111_320


def tagged_zone(tags):
    """The zone a mapper wrote, `SK:urban` → `urban`; `None` when none."""
    for key in ZONE_KEYS:
        value = tags.get(key, "")
        if ":" not in value:
            continue
        zone = ZONES.get(value.split(":", 1)[1].strip().lower())
        if zone:
            return zone
    return None


def road(tags):
    """`(kind, zone)` of a motor road, or `None`; zone `None` is left to the map."""
    highway = tags.get("highway")
    if highway not in MOTOR:
        return None
    zone = tagged_zone(tags)
    if highway == "living_street" or zone == "living_street":
        return "living_street", None
    if zone == "motorway":
        return "motorway", "rural"
    if highway in ("motorway", "motorway_link"):
        kind = "motorway"
    elif tags.get("motorroad") == "yes":
        kind = "motorroad"
    else:
        kind = "road"
    return kind, zone


def name(kind, urban):
    if kind == "living_street":
        return kind
    if kind == "road":
        return "urban" if urban else "rural"
    return f"urban_{kind}" if urban else kind


class BuiltUp:
    """Built-up areas in local metres, joined across the gaps between them."""

    def __init__(self, polygons):
        import numpy as np                                        # noqa: PLC0415
        import shapely                                            # noqa: PLC0415
        self.np, self.shapely = np, shapely
        polygons = [p for p in polygons if p is not None and not p.is_empty]
        self.parts = []
        self.tree = None
        if not polygons:
            return
        _w, south, _e, north = shapely.bounds(shapely.GeometryCollection(polygons))
        self.cos = math.cos(math.radians((south + north) / 2))
        joined = shapely.unary_union([shapely.buffer(self._metres(p), GAP_M)
                                      for p in polygons])
        self.parts = list(getattr(joined, "geoms", [joined]))
        self.tree = shapely.STRtree(self.parts)

    def _metres(self, geometry):
        cos = self.cos
        return self.shapely.transform(
            geometry, lambda xy: xy * [cos * METRES_PER_DEGREE, METRES_PER_DEGREE])

    def shares(self, lines):
        """Each line's share of length inside; lines are `[(lon, lat), …]`."""
        np, shapely = self.np, self.shapely
        if self.tree is None or not lines:
            return np.zeros(len(lines))
        drawn = np.empty(len(lines), dtype=object)
        drawn[:] = [self._metres(shapely.LineString(line)) for line in lines]
        hit_line, hit_part = self.tree.query(drawn, predicate="intersects")
        inside = shapely.length(shapely.intersection(drawn[hit_line],
                                                     np.array(self.parts)[hit_part]))
        total = shapely.length(drawn)
        out = np.bincount(hit_line, weights=inside, minlength=len(lines))
        return np.divide(out, total, out=np.zeros(len(lines)), where=total > 0)


def built_up_areas(pbf):
    """Built-up polygons of a PBF, as shapely geometries in degrees."""
    import osmium                                                 # noqa: PLC0415
    import shapely                                                # noqa: PLC0415

    class Areas(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.wkb = osmium.geom.WKBFactory()
            self.found = []

        def area(self, a):
            if a.tags.get("landuse") not in BUILT_UP:
                return
            try:
                self.found.append(shapely.from_wkb(self.wkb.create_multipolygon(a)))
            except RuntimeError:
                pass

    areas = Areas()
    areas.apply_file(pbf, locations=True, idx="flex_mem")
    return areas.found


def assign(network, built_up):
    """`speed_context` into each motor edge's tags; edges sharing tags get their own."""
    from collections import Counter                               # noqa: PLC0415
    unsure = [h for h in network.edges
              if h.get("road") and h["road"][1] is None and h["road"][0] != "living_street"]
    lines = [[network.nodes[h["from"]], *h["geom"], network.nodes[h["to"]]] for h in unsure]
    shares = built_up.shares([[(lon / 1e7, lat / 1e7) for lat, lon in line] for line in lines])
    urban = {id(h): share >= URBAN_SHARE for h, share in zip(unsure, shares)}
    counted = Counter()
    for h in network.edges:
        found = h.pop("road", None)
        if not found:
            continue
        kind, zone = found
        context = name(kind, urban.get(id(h), zone == "urban"))
        h["tags"] = {**h["tags"], "speed_context": context}
        counted[context] += 1
    network.contexts = counted
    return counted
