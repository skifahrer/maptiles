#!/usr/bin/env python3
"""Which `_site` file goes into which package – and what travels inside the base map."""
import hashlib
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    """workers/*.py can't be imported normally because of the dash in their names."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


catalog = _load("deploy_catalog", "catalog.py")
packages = _load("deploy_packages", "packages.py")


def log(msg):
    print(msg, flush=True)


def manifest_data(site):
    """`_site/tiles/manifest.json` – the one place that knows what the map holds."""
    path = os.path.join(site, "tiles", "manifest.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        log(f"::warning::{path} can't be read ({exc}) – layer packages are "
            f"assembled from file names in `_site`.")
        return {}


def package_files(site, man, p):
    """Files of ONE package, from its manifest keys or, failing that, its suffixes."""
    reg = catalog.region_entry(man)
    # a sprite is several files under one key
    rel = [f for k in p.get("manifest") or () if reg.get(k)
           for f in (reg[k] if isinstance(reg[k], list) else [reg[k]])]
    if not rel and p.get("suffixes"):
        tiles = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(tiles))
               if has_suffix(n, p["suffixes"])] \
            if os.path.isdir(tiles) else []
    return [os.path.join(site, f) for f in rel
            if os.path.exists(os.path.join(site, f))]


def has_suffix(name, suffixes):
    """A package's suffix, not a longer foreign one – `-routing` is not `-rail-routing`."""
    every = {q for x in packages.listing() for q in x.get("suffixes") or ()}
    return any(name.endswith(s) and not any(
        len(q) > len(s) and q.endswith(s) and name.endswith(q) and q not in suffixes
        for q in every) for s in suffixes)


def layer_packages(site, man):
    """`[(package, files)]` for everything with its own package in `_site`, counted once."""
    return [(p, package_files(site, man, p)) for p in packages.listing()
            if p["key"] != "base" and p.get("origin", "site") == "site"]


def trails_files(site, man):
    """Part `trails` – waymarked OSM routes (`-trails.pmtiles`)."""
    reg = catalog.region_entry(man)
    rel = [reg["trails"]] if reg.get("trails") else []
    if not rel:
        base = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(base))
               if n.endswith("-trails.pmtiles")] if os.path.isdir(base) else []
    return [os.path.join(site, f) for f in rel
            if os.path.exists(os.path.join(site, f))]


def routing_files(site, man):
    """Part `routing` – the signed routing network (`-routing.pmtiles`), also in `roads`."""
    reg = catalog.region_entry(man)
    rel = [reg["routing"]] if reg.get("routing") else []
    if not rel:
        base = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(base))
               if has_suffix(n, ("-routing.pmtiles",))] if os.path.isdir(base) else []
    return [os.path.join(site, f) for f in rel
            if os.path.exists(os.path.join(site, f))]


def signs_files(site, man):
    """Part `signs` – the country's signs (`-signs.json/.png`), for road as well as rail."""
    reg = catalog.region_entry(man)
    rel = list(reg.get("rail_signs") or [])
    if not rel:
        base = os.path.join(site, "tiles")
        rel = [os.path.join("tiles", n) for n in sorted(os.listdir(base))
               if has_suffix(n, SIGNS_SUFFIXES)] if os.path.isdir(base) else []
    return [os.path.join(site, f) for f in rel
            if os.path.exists(os.path.join(site, f))]


SIGNS_SUFFIXES = ("-signs.json", "-signs.png", "-signs@2x.json", "-signs@2x.png")


def base_parts(site, man):
    """Parts of the base map: `[(key, description, files)]`, absent ones too (as `0`)."""
    return [
        ("trails", "waymarked routes from OSM relations (.pmtiles)",
         trails_files(site, man)),
        ("routing", "signed routing network (.pmtiles)",
         routing_files(site, man)),
        ("signs", "the country's rail and road signs (sprite)",
         signs_files(site, man)),
    ]


def part_sizes(parts):
    """`[(key, description, files)]` → `{key: {"raw_size": B, "files": N, …}}`; unpacked bytes."""
    return {key: {"raw_size": sum(os.path.getsize(f) for f in files),
                  "files": len(files),
                  "description": description}
            for key, description, files in parts}


def all_files(site):
    out = []
    for root, _dirs, names in os.walk(site):
        for n in names:
            out.append(os.path.join(root, n))
    return out


# the viewer is what site.sh copies into the ROOT of `_site` from poc/web
VIEWER_SUFFIXES = (".html", ".js", ".mjs", ".css")
VIEWER_FILES = ("style-overrides.json",)   # the only viewer `.json`


def is_viewer(site, path):
    """A web viewer file in the root of `_site`?"""
    rel = os.path.relpath(path, site)
    if os.path.dirname(rel):
        return False
    return rel.endswith(VIEWER_SUFFIXES) or rel in VIEWER_FILES


def is_glyph(site, path):
    """A file in `_site/fonts/` – a glyph."""
    rel = os.path.relpath(path, site)
    return rel.split(os.sep)[0] == "fonts"


def where_glyphs_are(man):
    """One line for the log and `contents.json`: where glyphs come from instead."""
    address = str(man.get("glyphs") or "")
    if address.startswith(("http://", "https://")):
        return f"the app carries them, the web takes them from {address}"
    if address:
        return (f"the app carries them; the style asks for them relatively ({address}), "
                f"so outside the app they must be added")
    return "the app carries them (manifest unreadable, address unknown)"


def outside_packages(site, man):
    """`(files, reasons)` of `_site` files no package carries; reasons go to the log."""
    every = all_files(site)
    groups = [
        ("viewer (it is on Pages)", [f for f in every if is_viewer(site, f)]),
        (f"glyphs ({where_glyphs_are(man)})", [f for f in every if is_glyph(site, f)]),
    ]

    files, reasons = [], []
    for description, chunk in groups:
        if not chunk:
            continue
        files.extend(chunk)
        reasons.append((description, len(chunk), sum(os.path.getsize(f) for f in chunk)))
    return files, reasons


def base_files(site, exclude, keep=()):
    """Files of the base map – all of `_site` minus `exclude`; `keep` (its parts) wins."""
    inside = {os.path.abspath(f) for f in keep}
    out = {os.path.abspath(f) for f in exclude} - inside
    return [f for f in all_files(site) if os.path.abspath(f) not in out]


def contents_sha(base, files):
    """sha256 of the package contents – the files, not the archive around them."""
    h = hashlib.sha256()
    for rel, path in sorted((os.path.relpath(f, base), f) for f in files):
        h.update(rel.replace(os.sep, "/").encode() + b"\0")
        h.update(_file_sha(path).encode() + b"\n")
    return h.hexdigest()


def _file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
