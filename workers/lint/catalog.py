#!/usr/bin/env python3
"""Check: the `maps.json` catalog keeps its shape and nobody goes around it."""
import json
import os
import re
import sys

import yaml

# package kinds come from the registry publish-map.py packs by; retired ones may linger
with open("workers/data/packages.json", encoding="utf-8") as _f:
    _REGISTRY = json.load(_f)
KINDS = {p["key"] for p in _REGISTRY.get("packages") or []}
RETIRED = {r["key"] for r in _REGISTRY.get("retired") or []}
LEGACY = {old for p in (_REGISTRY.get("packages") or []) + (_REGISTRY.get("retired") or [])
          for old in p.get("legacy") or ()}
# a package file name; matches `stem()` and `file_name()` in deploy/names.py
NAME = re.compile(r"^[a-z0-9_]+(-[a-z0-9_]+)*(-test[0-9.]+km2)?\.(zip|aar)$")
CATALOG = "maps.json"
# a quick test has its own file, yet must be written
CATALOG_TEST = "maps-test.json"
CATALOGS = (CATALOG, CATALOG_TEST)
WORKFLOW = ".github/workflows/build-map-region.yml"
# separate pipelines writing the same catalog with the same script
WIKI_WORKFLOW = ".github/workflows/wiki.yml"
WORLD_WORKFLOW = ".github/workflows/world-map.yml"
PIPELINE = (WIKI_WORKFLOW, WORLD_WORKFLOW)
PUBLISH_MAP = "workers/deploy/publish-map.py"
NAMES = "workers/deploy/names.py"
CATALOG_PY = "workers/deploy/catalog.py"
# commits onto the fresh branch, not the SHA the run started from
CATALOG_SH = "workers/deploy/catalog.sh"
# and merges its change with the branch before the commit
CATALOG_MERGE = "workers/deploy/catalog-merge.py"
# the catalog relies on a package id surviving the next build
FOLDER_PY = "workers/drive/folder.py"

bad = []

# a subpackage belongs to a package that is no subpackage itself
_PARTS = {p["key"]: p.get("part_of") for p in _REGISTRY.get("packages") or []}
for _k, _c in _PARTS.items():
    if _c and (_c not in _PARTS or _PARTS[_c]):
        bad.append(f"workers/data/packages.json: `{_k}` is part of `{_c}`, but "
                   f"`{_c}` is no package that could have subpackages.")

try:
    pmap_text = open(PUBLISH_MAP, encoding="utf-8").read()
except OSError:
    pmap_text = ""
# publish-map.py takes RETIRED from the registry, not from a list of its own
pmap_retired = RETIRED if "registry.retired()" in pmap_text else set()


def entries(node, where):
    """Walk the catalog, returning (path, entry with maps)."""
    out = []
    if not isinstance(node, dict):
        return out
    if isinstance(node.get("maps"), dict):
        out.append((where, node))
    for key in ("regions", "subregions"):
        for k, v in (node.get(key) or {}).items():
            out += entries(v, f"{where}/{k}" if where else k)
    return out


def countries(data):
    """Countries are root keys; metadata starts with an underscore."""
    return {k: v for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict)}


def is_test(key):
    """A quick test node – `vysoke_tatry_test4km2`. The opposite of `split_test`."""
    cut = key.rfind("_test")
    if cut < 0 or not key.endswith("km2"):
        return False
    return key[cut + 5:-3].replace(".", "").isdigit()


for path in CATALOGS:
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        bad.append(f"{path} isn't in the repository – the build writes into it, but "
                   f"at least an empty one (`{{}}`) must exist.")
        continue
    except ValueError as exc:
        bad.append(f"{path} is no valid JSON ({exc}) – the build reads and writes "
                   f"it, so a broken file stops the catalog.")
        continue

    if not isinstance(data, dict):
        bad.append(f"{path} is no object – the top key is the COUNTRY, "
                   f"under it `regions` and `subregions`.")
        continue
    if [k for k in data if not k.startswith("_") and not isinstance(data[k], dict)]:
        bad.append(f"{path}: a root key is neither a country (object) nor "
                   f"metadata (`_…`).")
    for where, p in entries({"regions": countries(data)}, ""):
        last = where.rsplit("/", 1)[-1]
        if is_test(last) and path != CATALOG_TEST:
            bad.append(f"{path}: {where} is a quick test node and belongs in "
                       f"{CATALOG_TEST}; among finished maps it looks like one more "
                       f"area, though its terrain covers a few km².")
        if not is_test(last) and path == CATALOG_TEST:
            bad.append(f"{path}: {where} is no quick test (the key doesn't end in "
                       f"`_test<N>km2`), so it belongs in {CATALOG}.")
        # both: `updated_at` for the eye, `updated_ts` for arithmetic
        for field in ("updated_at", "updated_ts"):
            if p.get(field) in (None, ""):
                bad.append(f"{path}: {where} has no `{field}` – the catalog can't "
                           f"tell when that map was made.")
        for kind, m in p["maps"].items():
            if kind in LEGACY:
                bad.append(f"{path}: {where} still has the former key `{kind}` – "
                           f"`catalog.py --migrate {path}` renames it.")
            elif kind not in KINDS | RETIRED:
                bad.append(f"{path}: {where} has package `{kind}`, which publishing "
                           f"doesn't make (it knows {sorted(KINDS)}).")
            if kind in RETIRED and pmap_text and kind not in pmap_retired:
                bad.append(f"{path}: {where} has retired package `{kind}`, but "
                           f"`{PUBLISH_MAP}` doesn't take `retired` from the registry, "
                           f"so nobody deletes it from Drive or the entry.")
            if not isinstance(m, dict) or not m.get("file") or not m.get("link"):
                bad.append(f"{path}: {where}/{kind} has no `file` and `link` – "
                           f"a list without a link is useless.")
                continue
            for field in ("popis", "casti"):
                if field in m:
                    bad.append(f"{path}: {where}/{kind} still has `{field}` – "
                               f"today it is `description` / `parts`.")
            if not NAME.match(m["file"]):
                bad.append(f"{path}: {where}/{kind} has the name `{m['file']}`, "
                           f"which doesn't match what "
                           f"`workers/deploy/publish-map.py` makes.")

try:
    wf = yaml.safe_load(open(WORKFLOW))
    text = open(WORKFLOW).read()
except (OSError, ValueError) as exc:
    print(f"::error::{WORKFLOW} can't be read: {exc}")
    sys.exit(1)

deploy = (wf.get("jobs") or {}).get("deploy") or {}
if (deploy.get("permissions") or {}).get("contents") != "write":
    bad.append(f"{WORKFLOW}: job `deploy` lacks `contents: write`, so the catalog "
               f"{CATALOG} can't be committed – and would stop growing without "
               f"a word.")

steps = deploy.get("steps") or []
writing = [s for s in steps if str(s.get("run", "")).find("deploy/catalog.sh") >= 0]
if not writing:
    bad.append(f"{WORKFLOW}: job `deploy` has no step running "
               f"`workers/deploy/catalog.sh` – the catalog would be written on the "
               f"runner and lost with it.")
else:
    for s in writing:
        # after a failed publish the catalog would point at files not on Drive
        if "steps.publish.outcome == 'success'" not in str(s.get("if", "")):
            bad.append(f"{WORKFLOW}: step “{s.get('name')}” lacks the condition "
                       f"`steps.publish.outcome == 'success'` – the catalog would "
                       f"point at packages that never uploaded.")
if "--maps=" not in text:
    bad.append(f"{WORKFLOW}: `publish-map.py` is called without `--maps=`, so "
               f"nobody writes the catalog.")

# the one who wrote the catalog says which file to commit
for wf_path in (WORKFLOW,) + PIPELINE:
    try:
        wtext = open(wf_path, encoding="utf-8").read()
    except OSError:
        continue                      # a missing file is reported below
    if "MAPS_JSON: maps.json" in wtext:
        bad.append(f"{wf_path}: `MAPS_JSON` is hard-coded `maps.json`. Only the "
                   f"step that wrote the catalog knows which one it is – pass it "
                   f"`steps.publish.outputs.maps_file`, or a quick test writes "
                   f"{CATALOG_TEST} and commits {CATALOG}.")
    if "MAPS_JSON:" in wtext and "steps.publish.outputs.maps_file" not in wtext:
        bad.append(f"{wf_path}: the step with `catalog.sh` doesn't get "
                   f"`steps.publish.outputs.maps_file` – it would commit another "
                   f"file than `publish-map.py` just wrote.")

# separate pipelines write the same catalog
for wf_path in PIPELINE:
    try:
        wwf = yaml.safe_load(open(wf_path))
        wtext = open(wf_path, encoding="utf-8").read()
    except (OSError, ValueError) as exc:
        bad.append(f"{wf_path} can't be read: {exc}")
        continue
    for job, jd in ((wwf.get("jobs") or {})).items():
        # a job that doesn't publish (e.g. a cache check) doesn't write the catalog
        if not any(s.get("id") == "publish" for s in (jd.get("steps") or [])):
            continue
        if (jd.get("permissions") or {}).get("contents") != "write":
            bad.append(f"{wf_path}: job `{job}` lacks `contents: write`, "
                       f"so {CATALOG} can't be committed – the package would "
                       f"reach Drive and leave nothing in the catalog.")
        cat_steps = [s for s in (jd.get("steps") or [])
                     if "deploy/catalog.sh" in str(s.get("run", ""))]
        if not cat_steps:
            bad.append(f"{wf_path}: job `{job}` doesn't run "
                       f"`workers/deploy/catalog.sh` – the catalog would be written "
                       f"on the runner and lost with it.")
        for s in cat_steps:
            if "steps.publish.outcome == 'success'" not in str(s.get("if", "")):
                bad.append(f"{wf_path}: step “{s.get('name')}” lacks the "
                           f"condition `steps.publish.outcome == 'success'` – "
                           f"the catalog would point at a package that never "
                           f"uploaded.")
    if wf_path == WIKI_WORKFLOW and "--only=wikipedia" not in wtext:
        bad.append(f"{WIKI_WORKFLOW}: `publish-map.py` is called without "
                   f"`--only=wikipedia`. Publishing would then want the whole "
                   f"site (`_site`) this pipeline doesn't make, and overwrite the "
                   f"catalog entry with one without maps.")
    # the world map must say what it holds, or it gets a region map's layers
    if wf_path == WORLD_WORKFLOW and "MAP_LAYERS" not in wtext:
        bad.append(f"{WORLD_WORKFLOW}: never sets `MAP_LAYERS`, so the catalog "
                   f"would call the world map a region map without contours, "
                   f"rocks and terrain.")

try:
    NAMES_PY = open(NAMES, encoding="utf-8").read()
except OSError:
    NAMES_PY = ""

pmap = pmap_text
try:
    kmap = open(CATALOG_PY, encoding="utf-8").read()
except OSError as exc:
    bad.append(f"{CATALOG_PY} can't be read: {exc}")
    kmap = ""
if not pmap:
    bad.append(f"{PUBLISH_MAP} can't be read.")
# what a reader must not derive: tile paths from the node key, or a layer's zoom cap
for key, why in (
        ("tiles_paths", "paths to `.pmtiles` aren't written into the entry, so a "
                        "reader must derive them from the key – which is no file name"),
        ("trails_maxzoom", "the zoom cap of waymarked trails (z14) is missing"),
        ("features_maxzoom", "the zoom cap of landscape features (z15) is missing"),
        ("rock_source", "which model the ROCKS come from is missing "
                        "(`dem_source` is the contours' source)"),
        ("terrain_source", "which model the HILLSHADING comes from is missing – "
                           "on a fallback model the attribution would claim DMR 5.0"),
        ("parts", "how much of the `base` package is SEARCH is missing; the index "
                  "has no package of its own, so the catalog is the only place its "
                  "size can be read without downloading hundreds of MB")):
    if kmap and key not in kmap:
        bad.append(f"{CATALOG_PY}: {why}. Add it from `manifest.json` – it knows, "
                   f"the viewer reads tiles by it.")

if kmap and "def catalog_file(" not in kmap:
    bad.append(f"{CATALOG_PY}: `catalog_file()` is missing – there is no one place "
               f"saying whether a run writes {CATALOG} or {CATALOG_TEST}. Three ask "
               f"(publish-map.py, apple-archive.sh and through it catalog.sh).")
if kmap and "def write_catalog(path, parts, regions, uploaded, man, only=" not in kmap:
    bad.append(f"{CATALOG_PY}: `write_catalog` lacks the “add one package” mode "
               f"(parameter `only`). A separate pipeline would overwrite the region "
               f"entry and the map's links would vanish.")

# a quick test is written into a node of its own, checked on both sides
if pmap:
    if "def catalog_path(" not in NAMES_PY:
        bad.append(f"{NAMES}: `catalog_path()` is missing – a quick test would be "
                   f"written over the real map of the same region.")
    if "catalog_path(" not in pmap:
        bad.append(f"{PUBLISH_MAP}: `catalog_path()` isn't called, so the test node "
                   f"and the real map's node are one.")
    if "cat=cat" not in pmap:
        bad.append(f"{PUBLISH_MAP}: `write_catalog` is called without `cat=`, so "
                   f"the test node and the real map's node are one.")
    if "catalog.catalog_file(" not in pmap:
        bad.append(f"{PUBLISH_MAP}: `--maps` doesn't go through "
                   f"`catalog.catalog_file()`, so a quick test writes {CATALOG} "
                   f"instead of {CATALOG_TEST}.")
    if "maps_file=" not in pmap:
        bad.append(f"{PUBLISH_MAP}: doesn't write the step output `maps_file`, so "
                   f"`catalog.sh` can't know which file to commit.")
    if "not writing the catalog" in pmap:
        bad.append(f"{PUBLISH_MAP}: some run skips the catalog. A quick test has a "
                   f"node of its own (`catalog_path`), so there's no need – and a "
                   f"package not in the list is found by nobody.")

# the `.aar` job must fill the same file `deploy` wrote; bash asks `catalog.py --file`
AAR_SH = "workers/deploy/apple-archive.sh"
try:
    aar = open(AAR_SH, encoding="utf-8").read()
except OSError as exc:
    bad.append(f"{AAR_SH} can't be read: {exc}")
    aar = ""
if aar and "catalog.py --file" not in aar:
    bad.append(f"{AAR_SH}: doesn't ask `catalog.py --file` which catalog is the "
               f"right one. A quick test would fetch {CATALOG} from the branch, add "
               f"`.aar` to a map not in it, and {CATALOG_TEST} would never know.")

try:
    csh = open(CATALOG_SH, encoding="utf-8").read()
except OSError as exc:
    bad.append(f"{CATALOG_SH} can't be read: {exc}")
    csh = ""
if csh and "reset --mixed" not in csh:
    bad.append(f"{CATALOG_SH}: the commit isn't made on the fresh branch "
               f"(`git fetch` + `git reset --mixed FETCH_HEAD`). The second writing "
               f"job of a run – `.aar` after `deploy` – would carry another's write "
               f"and the catalog would be dropped silently every time.")
if csh and "catalog-merge.py" not in csh:
    bad.append(f"{CATALOG_SH}: the catalog isn't merged before the commit "
               f"(`{CATALOG_MERGE}`). `reset --mixed` alone isn't enough – the "
               f"working tree holds the WHOLE file as the run read it, so the commit "
               f"silently reverts what another job of the same run wrote.")


def _merge_trial():
    """Errors of the three-way catalog merge, tried for real."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_lint_merge", CATALOG_MERGE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lint_merge"] = mod
    spec.loader.exec_module(mod)

    errors = []
    # run 255: while `.aar` was packed, another job wrote `wikipedia` into the branch
    base = {"maps": {"base": {"formats": {"zip": 1}}}}
    mine = {"maps": {"base": {"formats": {"zip": 1, "aar": 2}}}}
    theirs = {"maps": {"base": {"formats": {"zip": 1}}},
              "wikipedia": {"formats": {"zip": 9}}}
    theirs = {"maps": {**theirs["maps"], "wikipedia": theirs["wikipedia"]}}
    out = mod.merge(base, mine, theirs)
    if "wikipedia" not in out["maps"]:
        errors.append(f"{CATALOG_MERGE}: the merge dropped a package another job "
                      f"wrote into the branch.")
    if "aar" not in (out["maps"].get("base") or {}).get("formats", {}):
        errors.append(f"{CATALOG_MERGE}: the merge didn't carry what this run "
                      f"wrote – the package would sit on Drive, unknown to the catalog.")
    # and back: what this run deleted the branch must not bring back
    out = mod.merge({"maps": {"wikipedia": {}}}, {"maps": {}},
                    {"maps": {"wikipedia": {}}})
    if "wikipedia" in out["maps"]:
        errors.append(f"{CATALOG_MERGE}: the merge brought back a package the run "
                      f"deleted.")
    return errors


def _catalog_trial():
    """Errors of the catalog, tried for real: a map, another's package, the map again."""
    import contextlib
    import importlib.util
    import io
    import tempfile

    spec = importlib.util.spec_from_file_location("_lint_catalog", CATALOG_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lint_catalog"] = mod
    spec.loader.exec_module(mod)

    regions = {"bratislavsky": {"name": "Bratislavský kraj",
                                "country": "slovensko"}}
    man = {"default_region": "bratislavsky",
           "regions": {"bratislavsky": {"bbox": [16.8, 48.0, 17.5, 48.6],
                                        "maxzoom": 16}}}
    parts = ["slovensko", "bratislavsky"]
    map_kinds = ["base", "contours-rocks", "terrain"]
    map_packages = [("", "bratislavsky.zip", 1, "id1", "zip", "sha1"),
                    ("contours-rocks", "bratislavsky-contours-rocks.zip",
                     1, "id2", "zip", "sha2"),
                    ("terrain", "bratislavsky-terrain.zip", 1, "id3",
                     "zip", "sha3")]

    def maps_in(path):
        with open(path) as f:
            return json.load(f)["slovensko"]["regions"]["bratislavsky"]["maps"]

    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.write_catalog(path, parts, regions, map_packages, man,
                              owns=map_kinds)
            # `wiki.yml`: `--only=wikipedia`, adding one package
            mod.write_catalog(path, parts, regions,
                              [("wikipedia", "bratislavsky-wikipedia.zip",
                                1, "id4", "zip", "sha4")], {},
                              only="wikipedia")
            after_wiki = maps_in(path)
            # another map build – it doesn't decide `wikipedia`
            mod.write_catalog(path, parts, regions, map_packages, man,
                              owns=map_kinds)
            after_map = maps_in(path)
            # a run that DECIDES `wikipedia` and lacks it must delete it
            mod.write_catalog(path, parts, regions, map_packages, man,
                              owns=map_kinds + ["wikipedia"])
            after_off = maps_in(path)
            # and back, this time `.aar` only: no ZIP of that package yet
            mod.write_catalog(path, parts, regions,
                              [("wikipedia", "bratislavsky-wikipedia.aar",
                                1, "id5", "aar", "sha5")], {},
                              only="wikipedia")
            aar_only = maps_in(path)
    if "wikipedia" not in after_wiki:
        errors.append(f"{CATALOG_PY}: `--only=wikipedia` doesn't add the package "
                      f"to the entry – the articles' ZIP would reach Drive and "
                      f"leave nothing in the catalog.")
    elif "wikipedia" not in after_map:
        errors.append(f"{CATALOG_PY}: a map build deleted package `wikipedia` it "
                      f"doesn't decide (it's not in `owns`).")
    if "wikipedia" in after_off:
        errors.append(f"{CATALOG_PY}: a package the run DECIDES and didn't make "
                      f"stayed in the catalog – pointing at a file the same run "
                      f"deleted on Drive.")
    only_aar = aar_only.get("wikipedia") or {}
    if not (only_aar.get("file") and only_aar.get("link")):
        errors.append(f"{CATALOG_PY}: a package with `.aar` only left the entry "
                      f"without a top – the app can't decode it and loses the "
                      f"whole country with it.")

    # former keys: a catalog written by older code is renamed on the next write
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with open(path, "w") as f:
            json.dump({"slovensko": {"regions": {"bratislavsky": {"maps": {
                "mapa": {"file": "bratislavsky.zip", "link": "x",
                         "casti": {"trasy": {"files": 1, "popis": "x"}}},
                "tienovanie": {"file": "bratislavsky-tienovanie.zip", "link": "y",
                               "popis": "x"}}}}}}, f)
        with contextlib.redirect_stdout(io.StringIO()):
            mod.write_catalog(path, parts, regions,
                              [("wikipedia", "bratislavsky-wikipedia.zip",
                                1, "id4", "zip", "sha4")], {},
                              only="wikipedia")
        migrated = maps_in(path)
    if {"mapa", "tienovanie"} & set(migrated) or not {"base", "terrain"} <= set(migrated):
        errors.append(f"{CATALOG_PY}: a write doesn't rename former package keys "
                      f"(`mapa` → `base`, `tienovanie` → `terrain`): {sorted(migrated)}.")
    elif "trails" not in (migrated["base"].get("parts") or {}) \
            or "description" not in migrated["terrain"]:
        errors.append(f"{CATALOG_PY}: a write doesn't rename `casti`/`popis` and "
                      f"former part keys (`trasy` → `trails`).")

    # when the map was made: tried for real, `updated_ts` may exist and never land
    import calendar
    import time as _time
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.write_catalog(path, parts, regions, map_packages, man,
                              owns=map_kinds)
        with open(path) as f:
            node = json.load(f)["slovensko"]["regions"]["bratislavsky"]
        if not os.path.exists(mod.write_base(path)):
            errors.append(f"{CATALOG_PY}: the write didn't keep the catalog as it "
                          f"found it – `{CATALOG_SH}` has nothing to merge and the "
                          f"commit reverts another's write of the same run.")
    for field in ("updated_at", "updated_ts"):
        if node.get(field) in (None, ""):
            errors.append(f"{CATALOG_PY}: the written entry has no `{field}`.")
    if node.get("updated_at") and node.get("updated_ts") is not None:
        try:
            from_text = calendar.timegm(
                _time.strptime(node["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            from_text = None
            errors.append(f"{CATALOG_PY}: `updated_at` is no ISO 8601 UTC "
                          f"(`{node['updated_at']}`) – text sorting needs one shape.")
        if from_text is not None and from_text != node["updated_ts"]:
            errors.append(f"{CATALOG_PY}: `updated_at` and `updated_ts` speak of "
                          f"different instants ({node['updated_at']} vs "
                          f"{node['updated_ts']}).")
    if not any(m.get("updated_ts") is not None
               for m in (node.get("maps") or {}).values()):
        errors.append(f"{CATALOG_PY}: no package of the entry has `updated_ts`.")

    # without `sha256` the app compares dates and downloads the same bytes twice
    no_sha = sorted(k for k, m in (node.get("maps") or {}).items()
                    if not m.get("sha256")
                    or not (m.get("formats") or {}).get("zip", {}).get("sha256"))
    if no_sha:
        errors.append(f"{CATALOG_PY}: package {', '.join(no_sha)} has no contents "
                      f"`sha256`, so the same build made again downloads twice.")

    # a link to a file no longer on Drive; tried for real
    def _link(fid):
        return {"file": f"{fid}.zip", "size": 1,
                "link": f"https://drive.google.com/file/d/{fid}/view",
                "download": f"https://drive.google.com/uc?export=download&id={fid}",
                "formats": {"zip": {
                    "file": f"{fid}.zip", "size": 1,
                    "link": f"https://drive.google.com/file/d/{fid}/view",
                    "download": f"https://drive.google.com/uc?export=download&id={fid}"}}}

    def _entry_with(maps, path):
        with open(path, "w") as f:
            json.dump({"slovensko": {"name": "Slovensko", "regions": {
                "bratislavsky": {"name": "Bratislavský kraj",
                                 "maps": maps}}}}, f)

    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/maps.json"
        with contextlib.redirect_stdout(io.StringIO()):
            # the `.aar` job adds (`merge`), doesn't overwrite
            _entry_with({"base": _link("alive"),
                         "search": _link("gone")}, path)
            mod.write_catalog(path, parts, regions,
                              [("", "bratislavsky.aar", 1, "aar1", "aar",
                                "sha1")],
                              man, merge=True, owns=["base"],
                              retired=tuple(RETIRED), live={"alive": "x"})
            after_aar = maps_in(path)

            # another's package without a file on Drive drops, one with a file stays
            _entry_with({"base": _link("alive"),
                         "wikipedia": _link("gone")}, path)
            mod.write_catalog(path, parts, regions, [], man,
                              merge=True, owns=["base"],
                              retired=tuple(RETIRED), live={"alive": "x"})
            after_check = maps_in(path)

            # "don't know" and "isn't there" are two answers
            _entry_with({"base": _link("alive"),
                         "wikipedia": _link("unknown")}, path)
            mod.write_catalog(path, parts, regions, [], man,
                              merge=True, owns=["base"],
                              retired=tuple(RETIRED), live=None)
            unchecked = maps_in(path)

            # a dead link to a package in the folder under another id is fixed
            _entry_with({"base": _link("old"),
                         "wikipedia": _link("gone")}, path)
            mod.write_catalog(path, parts, regions, [], man,
                              merge=True, owns=["base"],
                              retired=tuple(RETIRED),
                              live={"new": "old.zip"})
            after_revive = maps_in(path)
    if "search" in after_aar:
        errors.append(f"{CATALOG_PY}: the `.aar` job brought retired package "
                      f"`search` back into the entry.")
    if "zip" not in (after_aar.get("base", {}).get("formats") or {}):
        errors.append(f"{CATALOG_PY}: adding `.aar` dropped the base map's ZIP.")
    if "wikipedia" in after_check:
        errors.append(f"{CATALOG_PY}: the entry kept a link to a file not in the map "
                      f"folder on Drive – the app would download Drive's error page.")
    if "base" not in after_check:
        errors.append(f"{CATALOG_PY}: checking links dropped a package whose file "
                      f"IS on Drive.")
    if "wikipedia" not in unchecked:
        errors.append(f"{CATALOG_PY}: a run that never asked Drive (`live=None`) "
                      f"dropped a package – “don't know” must not mean “isn't there”.")
    revived = after_revive.get("base") or {}
    if "new" not in (revived.get("download") or ""):
        errors.append(f"{CATALOG_PY}: the link pointed nowhere, but `old.zip` IS in "
                      f"the folder (under a new id) – the catalog should relink it, "
                      f"not drop the package. Left: "
                      f"{revived.get('download') or '(package dropped)'}")
    if "new" not in ((revived.get("formats") or {}).get("zip", {})
                     .get("download") or ""):
        errors.append(f"{CATALOG_PY}: only the entry top was revived, not "
                      f"`formats.zip` (or the other way) – they are one thing.")
    if "wikipedia" in after_revive:
        errors.append(f"{CATALOG_PY}: reviving kept a package whose file is in "
                      f"the folder under no id.")

    # which file: maps.json vs maps-test.json
    before = os.environ.get("TEST_KM2")
    try:
        os.environ["TEST_KM2"] = "0"
        real = mod.catalog_file(CATALOG)
        os.environ["TEST_KM2"] = "4"
        test = mod.catalog_file(CATALOG)
        # the name passes the pipeline twice (apple-archive.sh, then publish-map.py)
        twice = mod.catalog_file(test)
    finally:
        if before is None:
            os.environ.pop("TEST_KM2", None)
        else:
            os.environ["TEST_KM2"] = before
    if real != CATALOG:
        errors.append(f"{CATALOG_PY}: a real run would write `{real}`, not `{CATALOG}`.")
    if test != CATALOG_TEST:
        errors.append(f"{CATALOG_PY}: a quick test would write `{test}`, not "
                      f"`{CATALOG_TEST}`.")
    if twice != CATALOG_TEST:
        errors.append(f"{CATALOG_PY}: `catalog_file()` isn't idempotent – it turns "
                      f"`{CATALOG_TEST}` into `{twice}`. The name travels on "
                      f"(`--file` → `--maps`), so `.aar` would write a file nobody "
                      f"commits.")
    return errors


def _stable_id_trial():  # noqa: C901
    """Does `upload_clobber` overwrite a file or make it a new id? Drive is stubbed."""
    import contextlib
    import importlib.util
    import io
    import tempfile
    errors = []
    spec = importlib.util.spec_from_file_location("_lint_folder", FOLDER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as tmp:
        package = f"{tmp}/base.zip"
        with open(package, "wb") as f:
            f.write(b"x")

        def trial(in_folder):
            trace = {"upload": 0, "update": [], "delete": []}
            mod.files_named = lambda *_a, **_k: [dict(x) for x in in_folder]
            mod.update = lambda _c, _p, fid, *_a, **_k: (
                trace["update"].append(fid) or fid)
            mod.upload = lambda *_a, **_k: (
                trace.__setitem__("upload", trace["upload"] + 1) or "new_id")
            mod.auth.api_delete = lambda _c, fid: trace["delete"].append(fid)
            with contextlib.redirect_stdout(io.StringIO()):
                fid, _ = mod.upload_clobber(None, package, "base.zip",
                                            "folder")
            return fid, trace

        # 1. a package of that name is there – contents overwritten, id kept
        fid, trace = trial([{"id": "stable_id", "createdTime": "2026-01-01T00:00:00Z"}])
        if fid != "stable_id":
            errors.append(f"{FOLDER_PY}: `upload_clobber` returned id `{fid}` "
                          f"instead of `stable_id` – the link in `maps.json` would "
                          f"break on every build.")
        if trace["upload"]:
            errors.append(f"{FOLDER_PY}: `upload_clobber` made a NEW file though "
                          f"the same one is in the folder.")
        if trace["delete"]:
            errors.append(f"{FOLDER_PY}: `upload_clobber` deleted "
                          f"{trace['delete']} – the only file of that name is the "
                          f"one the catalog points at.")

        # 2. two files of one name: the oldest is overwritten, the duplicate goes
        fid, trace = trial([
            {"id": "newer", "createdTime": "2026-02-02T00:00:00Z"},
            {"id": "older", "createdTime": "2026-01-01T00:00:00Z"}])
        if fid != "older":
            errors.append(f"{FOLDER_PY}: with two files of that name `{fid}` was "
                          f"overwritten, not the oldest `older`.")
        if trace["delete"] != ["newer"]:
            errors.append(f"{FOLDER_PY}: the duplicate wasn't deleted "
                          f"({trace['delete']}).")

        # 3. the map's first build – the file is made
        fid, trace = trial([])
        if trace["upload"] != 1 or fid != "new_id":
            errors.append(f"{FOLDER_PY}: the first package didn't upload "
                          f"(upload={trace['upload']}, id={fid}).")
    return errors


try:
    bad += _stable_id_trial()
except Exception as exc:                      # noqa: BLE001 – anything is an error
    bad.append(f"{FOLDER_PY} can't be run on trial ({exc!r}).")

try:
    bad += _merge_trial()
except Exception as exc:                      # noqa: BLE001 – anything is an error
    bad.append(f"{CATALOG_MERGE} can't be run on trial ({exc!r}).")

try:
    bad += _catalog_trial()
except SystemExit as exc:
    bad.append(f"{CATALOG_PY}: writing the catalog failed ({exc}) – the trial is "
               f"the call `publish-map.py` makes.")
except Exception as exc:                      # noqa: BLE001 – anything is an error
    bad.append(f"{CATALOG_PY} can't be run on trial ({exc!r}).")

for b in bad:
    print(f"::error::{b}")
print(f"map catalog: {len(bad)} errors")
sys.exit(1 if bad else 0)
