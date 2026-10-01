#!/usr/bin/env python3
"""The map catalog `maps.json` – what is written into it and where."""
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")
_DRIVE = os.path.join(_WORKERS, "drive")


def _load(name, path):
    """workers/*.py can't be imported normally because of the dash in their names."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


folder = _load("drive_folder", os.path.join(_DRIVE, "folder.py"))
packages = _load("deploy_packages", os.path.join(_HERE, "packages.py"))


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def log(msg):
    print(msg, flush=True)


def split_test(key):
    """`vysoke_tatry_test4km2` → (`vysoke_tatry`, `4`), else `(key, "")`."""
    cut = key.rfind("_test")
    if cut < 0 or not key.endswith("km2"):
        return key, ""
    middle = key[cut + 5:-3]
    return (key[:cut], middle) if middle.replace(".", "").isdigit() else (key, "")


CATALOG = "maps.json"
CATALOG_TEST = "maps-test.json"

# former part keys of the base map
LEGACY_PARTS = {"trasy": "trails", "navigacia": "routing", "znacky": "signs"}


def catalog_file(base=CATALOG):
    """`maps.json`, or `maps-test.json` for a test. Empty = don't write."""
    if not base:
        return ""
    test_km2 = env("TEST_KM2", "0")
    if test_km2 in ("", "0"):
        return base
    head, _, ext = base.rpartition(".")
    stem = head or base
    # the answer travels on, so `-test` must not be added twice
    if stem.endswith("-test"):
        return base
    return f"{stem}-test" + (f".{ext}" if head else "")


def write_base(path):
    """Where a run keeps the catalog as it found it – `catalog.sh` merges from it."""
    return f"{path}.base"


def region_entry(man):
    """The region's entry in `manifest.json` – zooms, bbox, height sources."""
    key = man.get("default_region")
    return ((man.get("regions") or {}).get(key) or {}) if key else {}


TILE_LAYERS = ("pmtiles", "contours", "rocks", "trails", "features", "points",
               "transport", "boundaries", "water", "rail", "rail_routing",
               "buildings")


def tiles_paths(man, reg):
    """Paths to `.pmtiles` in the package, from the manifest – a key can't tell them."""
    out = {k: reg[k] for k in TILE_LAYERS if reg.get(k)}
    dem = (man.get("dem") or "").rstrip("/")
    if dem.endswith(".pmtiles"):
        out["terrain"] = "tiles/" + dem.rsplit("/", 1)[-1]
    return out


def catalog_name(regions, key, kind):
    """Human name of a region/area/country – from the registries, never made up."""
    key, test = split_test(key)
    tail = f" – quick test {test} km²" if test else ""
    if kind == "area":
        try:
            with open(os.path.join(_DATA, "areas.json")) as f:
                name = (json.load(f).get(key) or {}).get("name") or key
        except (OSError, ValueError):
            name = key
        return name + tail
    r = regions.get(key) or {}
    return (r.get("name") or key) + tail


def now():
    """(ISO 8601 UTC, epoch seconds) – one instant, read by eye and by subtraction."""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), int(t)


def region_models(man, reg):
    """Which height model each layer of the region comes from."""
    return {"contours": reg.get("dem_source"), "rocks": reg.get("rock_source"),
            "shading": man.get("dem_source")}


def migrate_node(maps):
    """Rename former package and part keys of one `maps` entry to today's, in place."""
    for old, new in packages.legacy().items():
        if old in maps:
            entry = maps.pop(old)
            maps.setdefault(new, entry)
    for entry in maps.values():
        if not isinstance(entry, dict):
            continue
        if "popis" in entry:
            entry.setdefault("description", entry.pop("popis"))
        parts = entry.pop("casti", None)
        if isinstance(parts, dict):
            entry.setdefault("parts", parts)
        for key in list((entry.get("parts") or {})):
            part = entry["parts"][key]
            if isinstance(part, dict) and "popis" in part:
                part.setdefault("description", part.pop("popis"))
            if key in LEGACY_PARTS:
                entry["parts"].setdefault(LEGACY_PARTS[key], entry["parts"].pop(key))


def migrate(data):
    """Every node of the catalog on today's keys; a run on older code may still write old ones."""
    pending = [v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)]
    while pending:
        node = pending.pop()
        if isinstance(node.get("maps"), dict):
            migrate_node(node["maps"])
        for sub in ("regions", "subregions"):
            pending += [v for v in (node.get(sub) or {}).values() if isinstance(v, dict)]
    return data


def write_package(maps, kind, name, size, fid, fmt, at="", at_ts=None,
                  sha="", models=None):
    """One package in one format into a `maps` entry; the top mirrors the ZIP for older readers."""
    record = {
        "file": name,
        "size": size,
        "link": folder.file_link(fid),
        "download": folder.download_link(fid),
        # provenance per package: wiki is built by another pipeline
        "run": env("GITHUB_RUN_NUMBER"),
    }
    if at:
        record["updated_at"] = at
    if at_ts is not None:
        record["updated_ts"] = at_ts
    # contents, not date: the same build twice is no new map for the app
    if sha:
        record["sha256"] = sha
    entry = maps.setdefault(kind or "base", {})
    entry.setdefault("formats", {})[fmt] = record
    # an entry without a top is one without a link, and breaks the country in the app
    if fmt == "zip" or "zip" not in entry["formats"]:
        entry.update(record)
    try:
        meta = packages.package(kind or "base")
    except SystemExit:
        return
    entry["app"] = meta["app"]
    entry["symbol"] = meta["symbol"]
    entry["detail"] = meta["app_detail"]
    entry["description"] = meta["description"]
    if meta.get("part_of"):
        entry["part_of"] = meta["part_of"]
    credits = packages.credits(kind or "base", models)
    if credits:
        entry["credits"] = credits


def link_id(record):
    """File id from `download`/`link` of one package record, or ""."""
    if not isinstance(record, dict):
        return ""
    return (folder.id_from_link(record.get("download"))
            or folder.id_from_link(record.get("link")))


def is_dead(record, live, protected):
    """Does this record point at a file no longer on Drive?"""
    fid = link_id(record)
    return bool(fid) and fid not in live and fid not in protected


def revival(record, live):
    """New id of a file of the same name in the folder, or "" – with two matches, none."""
    name = record.get("file") if isinstance(record, dict) else None
    if not name:
        return ""
    matches = [fid for fid, title in live.items() if title == name]
    return matches[0] if len(matches) == 1 else ""


def revive(record, live):
    """Point the record at the live file of its name. True = done."""
    fid = revival(record, live)
    if not fid:
        return False
    record["link"] = folder.file_link(fid)
    record["download"] = folder.download_link(fid)
    return True


def prune_dead(maps, live, protected=()):
    """Match an entry's links with the real folder, by format. `(fixed, dropped)`."""
    fixed, dropped = [], []
    for kind in sorted(maps):
        entry = maps[kind]
        if not isinstance(entry, dict):
            continue
        fell = []
        formats = entry.get("formats")
        if isinstance(formats, dict):
            for fmt in sorted(formats):
                if not is_dead(formats[fmt], live, protected):
                    continue
                label = f"{kind}/{fmt} ({formats[fmt].get('file') or '?'})"
                if revive(formats[fmt], live):
                    fixed.append(label)
                else:
                    fell.append(label)
                    del formats[fmt]
            if not formats:
                entry.pop("formats", None)
        live_formats = entry.get("formats") or {}
        if live_formats:
            if is_dead(entry, live, protected):
                entry.update(live_formats.get("zip")
                             or live_formats[sorted(live_formats)[0]])
            dropped += fell
            continue
        # without formats the top decides alone; one message, not two
        if is_dead(entry, live, protected):
            label = f"{kind} ({entry.get('file') or '?'})"
            if revive(entry, live):
                fixed.append(label)
                dropped += fell
            else:
                dropped.append(label)
                del maps[kind]
        else:
            dropped += fell
    return fixed, dropped


def tidy(maps, retired=(), live=None, protected=()):
    """Drop what no longer belongs in an entry – and say so."""
    for kind in retired:
        if maps.pop(kind, None) is not None:
            log(f"Package `{kind}` no longer exists (its contents moved to other "
                f"packages) – dropped from the catalog entry.")
    if live is None:
        return
    fixed, dropped = prune_dead(maps, live, protected)
    for label in fixed:
        log(f"::warning::The catalog link to {label} pointed nowhere, but a file of "
            f"that name IS in the map folder – relinked it. (A run uploaded the "
            f"package but its catalog write never reached the branch.)")
    for label in dropped:
        log(f"::warning::The catalog linked {label}, but no such file is in the "
            f"map folder on Drive, not even under another id – dropped.")


def write(path, data, label):
    """Write the catalog when it really changed; minified but sorted, so diffs stay real."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True) + "\n"
    try:
        with open(path) as f:
            if f.read() == text:
                log(f"{path}: same as before – unchanged.")
                return False
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(text)
    log(f"{path}: {label}")
    return True


def write_parts(maps, parts):
    """Parts of the `base` package – no package of their own, so sized here; `0` too."""
    entry = maps.get("base")
    if entry is None:
        return                        # this run didn't upload the base map
    if not parts:
        entry.pop("parts", None)
        return
    entry["parts"] = {k: dict(v) for k, v in parts.items()}


COMMENT = ("Map catalog of finished maps on Google Drive – which there are and "
           "where. The top key is the country, under it `regions` and `subregions`; "
           "keys starting with `_` are catalog metadata, not countries. Written at the "
           "end of a build by workers/deploy/publish-map.py; never edited by hand.")
COMMENT_TEST = ("QUICK TEST runs – terrain covers only a few km² of the cut-out, so "
                "these are NOT maps to download; finished maps are in maps.json. ")


def write_catalog(path, parts, regions, uploaded, man, only="", merge=False,
                  cat=None, layers=None, owns=None, base_parts=None,
                  retired=(), live=None):
    """Add (or overwrite) an entry in `maps.json`. True when it changed.

    `uploaded` is `(kind, name, size, id, format, sha)`; `owns` the kinds this run decides.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    # so `catalog.sh` can tell this run's change from another job's
    try:
        with open(write_base(path), "w") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
    except OSError as exc:
        log(f"::warning::The catalog before the write couldn't be kept ({exc}) – "
            f"the commit carries the whole file, not just this change.")
    migrate(data)
    is_test = os.path.basename(path) == CATALOG_TEST
    data["_comment"] = (COMMENT_TEST if is_test else "") + COMMENT
    data["_updated_at"], data["_updated_ts"] = now()

    cat = cat or parts
    country = data.setdefault(cat[0], {})
    country.setdefault("name", catalog_name(regions, cat[0], "region"))
    node = country                      # a whole-country build ends here
    if len(cat) > 1:
        regs = country.setdefault("regions", {})
        node = regs.setdefault(cat[1], {})
        node.setdefault("name", catalog_name(regions, cat[1], "region"))
    if len(cat) > 2:
        subs = node.setdefault("subregions", {})
        node = subs.setdefault(cat[2], {})
        node.setdefault("name", catalog_name(regions, cat[2], "area"))

    reg = region_entry(man)
    if only:
        # an addition, not a rewrite: a separate pipeline knows only its package
        node.setdefault("name", catalog_name(regions, cat[-1], "region"))
        node.setdefault("drive", "/".join(parts))
        # `updated_at` and `run` of the region say which run built the map
        node.setdefault("updated_at", data["_updated_at"])
        node.setdefault("updated_ts", data["_updated_ts"])
        node.setdefault("run", env("GITHUB_RUN_NUMBER"))
        maps = node.setdefault("maps", {})
        for kind, name, size, fid, fmt, sha in uploaded:
            write_package(maps, kind, name, size, fid, fmt,
                          at=data["_updated_at"], at_ts=data["_updated_ts"],
                          sha=sha, models=region_models(man, reg))
        tidy(maps, retired, live, {fid for _k, _n, _v, fid, _f, _s in uploaded})
        return write(path, data, f"added package {only} to {'/'.join(cat)}")
    entry = {
        "name": node.get("name"),
        "drive": "/".join(parts),
        # the entry is written whole, so creation = rewrite
        "updated_at": data["_updated_at"],
        "updated_ts": data["_updated_ts"],
        "run": env("GITHUB_RUN_NUMBER"),
        "layers": list(layers or []),
        "maps": {},
    }
    # what a choice needs before unpacking: every zoom cap and every DEM source
    for k in ("bbox", "maxzoom", "contours_maxzoom", "contour_interval",
              "rocks_maxzoom", "rock_slope", "dem_source", "rock_source",
              "trails_maxzoom", "features_maxzoom", "points_maxzoom",
              "transport_maxzoom", "boundaries_maxzoom", "water_maxzoom",
              "rail_maxzoom", "buildings_maxzoom"):
        if reg.get(k) is not None:
            entry[k] = reg[k]
    tiles = tiles_paths(man, reg)
    if tiles:
        entry["tiles"] = tiles
    if tiles.get("terrain"):
        if man.get("dem_maxzoom") is not None:
            entry["terrain_maxzoom"] = man["dem_maxzoom"]
        if man.get("dem_source"):
            entry["terrain_source"] = man["dem_source"]
    area_bbox = env("AREA_BBOX")
    test_km2 = env("TEST_KM2", "0")
    if test_km2 not in ("", "0"):
        # the key number of a test: the map is the region, the terrain just that square
        entry["test_km2"] = test_km2
    if area_bbox and (len(parts) > 2 or test_km2 not in ("", "0")):
        try:
            entry["area_bbox"] = [float(v) for v in area_bbox.split(",")]
        except ValueError:
            pass
    old_maps = node.get("maps") or {}
    if merge:
        entry["maps"] = {k: dict(v) for k, v in old_maps.items()}
    else:
        if owns is None:
            raise SystemExit(
                "::error::`write_catalog` without `owns=`: there is no telling which "
                "packages this run decides and which belong to another pipeline. "
                "Pass the kinds of `uploaded` (publish-map.py does).")
        decided = set(owns)
        entry["maps"] = {k: dict(v) for k, v in old_maps.items()
                         if k not in decided}
    if merge:
        # what this run doesn't know it must not delete – with `merge` the catalog is the base
        kept = {k: v for k, v in node.items()
                if k not in ("maps", "regions", "subregions")}
        kept.update(entry)
        entry = kept
    for kind, name, size, fid, fmt, sha in uploaded:
        write_package(entry["maps"], kind, name, size, fid, fmt,
                      at=data["_updated_at"], at_ts=data["_updated_ts"],
                      sha=sha, models=region_models(man, reg))
    if base_parts is not None:
        write_parts(entry["maps"], base_parts)
    # only now, with this run's packages in; those are protected
    tidy(entry["maps"], retired, live,
         {fid for _k, _n, _v, fid, _f, _s in uploaded})

    # `subregions` belong to the node, not to this map
    keep = {k: node[k] for k in ("regions", "subregions") if k in node}
    node.clear()
    node.update(entry)
    node.update(keep)

    foreign = [k for k in entry["maps"]
               if k not in {(kind or "base") for kind, *_ in uploaded}]
    return write(path, data, f"wrote map {'/'.join(cat)} "
                             f"({len(entry['maps'])} packages, "
                             + (f"{len(foreign)} of them from another pipeline "
                                f"({', '.join(sorted(foreign))}), " if foreign else "")
                             + f"folder {'/'.join(parts)})")


if __name__ == "__main__":
    if sys.argv[1:] == ["--file"]:
        print(catalog_file())
    elif sys.argv[1:2] == ["--migrate"]:
        for p in sys.argv[2:]:
            with open(p) as f:
                d = json.load(f)
            write(p, migrate(d), "migrated to today's keys")
    else:
        raise SystemExit(
            "::error::workers/deploy/catalog.py alone answers only `--file` (which "
            "catalog to write – maps.json, or maps-test.json for a quick test) and "
            "`--migrate <catalog>…`. The catalog is written by workers/deploy/publish-map.py.")
