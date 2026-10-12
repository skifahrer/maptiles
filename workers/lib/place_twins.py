"""Which areas name the same place as a place point, so the name is drawn once."""


def bbox(ring):
    """West, south, east, north of `(lon, lat)` points."""
    return (min(x for x, _ in ring), min(y for _, y in ring),
            max(x for x, _ in ring), max(y for _, y in ring))


def twins(points, areas):
    """`{area key: point id}` for areas with a point of the same wikidata, or the same name inside."""
    # points: (id, name, wikidata, lon, lat); areas: (key, name, wikidata, (w, s, e, n))
    by_wikidata = {w: i for i, _, w, _, _ in points if w}
    by_name = {}
    for i, name, _, x, y in points:
        by_name.setdefault(name, []).append((i, x, y))
    out = {}
    for key, name, wikidata, (w, s, e, n) in areas:
        point = by_wikidata.get(wikidata) if wikidata else None
        if point is None and name:
            point = next((i for i, x, y in by_name.get(name, ())
                          if w <= x <= e and s <= y <= n), None)
        if point is not None:
            out[key] = point
    return out
