#!/usr/bin/env python3
"""Glyphs and viewer aren't in a package – but they must be somewhere else.

Checked: the viewer and glyphs are left out (Pages link, relative link, no
manifest); `site.sh` builds the glyph address from `$BASE`; the world style
links an address; search, trails and routing stay in the base map, sized;
routing rides in `roads` too; no package is alive and retired at once.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

PUBLISH = "workers/deploy/publish-map.py"
REGISTRY = "workers/data/packages.json"
FILES = "workers/deploy/files.py"
SITE = "workers/deploy/site.sh"
WORLD_STYLE = "workers/world/style.mjs"

bad = []


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fill(site):
    """A mock `_site`: viewer, glyphs, styles, sprite, tiles, search and own-package layers."""
    for rel in ("index.html", "app.js", "themes.js", "style-overrides.json",
                "region.geojson", "fonts/Noto Sans Regular/0-255.pbf",
                "styles/light.json", "sprites/temaki.png",
                "tiles/manifest.json", "tiles/region.pmtiles",
                "tiles/region-contours.pmtiles", "tiles/region-rocks.pmtiles",
                "tiles/region-terrain.pmtiles",
                "tiles/region-transport.pmtiles", "tiles/region-trails.pmtiles",
                "tiles/region-points.pmtiles", "tiles/region-boundaries.pmtiles",
                "tiles/region-water.pmtiles",
                "tiles/region-buildings.pmtiles",
                "tiles/region-routing.pmtiles",
                "tiles/search-index.db"):
        path = os.path.join(site, rel)
        os.makedirs(os.path.dirname(path) or site, exist_ok=True)
        with open(path, "w") as f:
            f.write("x")


def in_package(pm, man):
    """What stays in the base map when only `outside_packages` is left out."""
    with tempfile.TemporaryDirectory() as site:
        fill(site)
        out, _reasons = pm.outside_packages(site, man)
        return {os.path.relpath(p, site).replace(os.sep, "/")
                for p in pm.base_files(site, out)}


def packed():
    """`{package: {paths inside}}` – from a real `publish-map.py --zip-only` run."""
    with tempfile.TemporaryDirectory() as tmp:
        site = os.path.join(tmp, "_site")
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        fill(site)
        environment = dict(os.environ, REGION_KEY="region", AREA_KEY="whole",
                           TEST_KM2="0", TILES_MAXZOOM="16")
        run = subprocess.run(
            [sys.executable, PUBLISH, f"--site={site}", f"--out={out}",
             "--zip-only", "--maps="],
            env=environment, capture_output=True, text=True)
        if run.returncode:
            bad.append(f"{PUBLISH}: `--zip-only` over a mock `_site` failed "
                       f"({run.returncode}); what is in which package can't be told.\n"
                       f"{run.stdout}\n{run.stderr}")
            return {}
        found = {}
        for name in sorted(os.listdir(out)):
            kind = name[len("region"):-len(".zip")].lstrip("-") or "base"
            with zipfile.ZipFile(os.path.join(out, name)) as z:
                # inside is one more folder named after the package
                found[kind] = {n.split("/", 1)[1] for n in z.namelist()
                               if "/" in n}
        return found


# what stays in a package
pm = load_module("publish_map", PUBLISH)

PAGES = {"glyphs": "https://x.github.io/map/fonts/{fontstack}/{range}.pbf"}
region = in_package(pm, PAGES)
for name in ("index.html", "app.js", "style-overrides.json",
             "fonts/Noto Sans Regular/0-255.pbf"):
    if name in region:
        bad.append(
            f"{PUBLISH}: `{name}` was packed into the region map, though the manifest "
            f"links glyphs on Pages. Glyphs are tens of MB nobody opens in a package, "
            f"and the viewer is a website the app never runs.")
for name in ("tiles/region.pmtiles", "styles/light.json", "sprites/temaki.png",
             "tiles/manifest.json", "region.geojson"):
    if name not in region:
        bad.append(
            f"{PUBLISH}: `{name}` FELL OUT of the package. It's no viewer or glyph – "
            f"it's the map; without it the package can't be opened, and nothing fails.")

world = in_package(pm, {"glyphs": "fonts/{fontstack}/{range}.pbf"})
if "fonts/Noto Sans Regular/0-255.pbf" in world:
    bad.append(
        f"{PUBLISH}: glyphs stayed in the package with a RELATIVE link. The app "
        f"carries them, so even for the world map they're weight nobody unpacks.")

unknown = in_package(pm, {})
if "fonts/Noto Sans Regular/0-255.pbf" in unknown:
    bad.append(
        f"{PUBLISH}: with an unreadable manifest the glyphs stayed in the package – "
        f"tens of MB more in every package, unseen on the file.")

# search and waymarked trails must not fall out of the base map
packages = packed()
base_zip = packages.get("base", set())
roads_zip = packages.get("roads", set())

if packages and "tiles/search-index.db" not in base_zip:
    bad.append(
        f"{PUBLISH}: `tiles/search-index.db` FELL OUT of the map package. Search "
        f"has no package of its own – it travels in the base map, and without it "
        f"nothing can be found. Nothing fails; it shows on the phone.")

if packages and "tiles/region-trails.pmtiles" not in base_zip:
    bad.append(
        f"{PUBLISH}: `tiles/region-trails.pmtiles` FELL OUT of the map package. "
        f"Waymarked trails travel in the base map; without them it's a hiking map "
        f"without marks. Nothing fails.")

# and sized – the size goes to maps.json under `base`
files = load_module("deploy_files", FILES)
with tempfile.TemporaryDirectory() as site:
    fill(site)
    sized = files.part_sizes(files.base_parts(site, PAGES))
for _part, _why in (("trails", "waymarked trails"),
                    ("routing", "routing network")):
    if _part in sized and sized[_part].get("files"):
        continue
    if _part not in sized:
        bad.append(
            f"{FILES}: part `{_part}` ({_why}) isn't sized, so its size can't reach "
            f"`maps.json` – with no package of its own, only downloading the whole "
            f"map would tell.")
    else:
        bad.append(
            f"{FILES}: part `{_part}` ({_why}) found no file in `_site`, though "
            f"they're there. Did the pick by name or folder change? The part would "
            f"stay in the map, only the catalog would deny it.")

# routing is part of the map AND in `roads`; its own `routing` package is retired
if packages and "tiles/region-routing.pmtiles" not in base_zip:
    bad.append(
        f"{PUBLISH}: `tiles/region-routing.pmtiles` FELL OUT of the map package. "
        f"Routing is PART of the base map (`base_parts`) – it rides in `roads` "
        f"too, which doesn't remove it from the map (`keep` in `base_files`). "
        f"Without it the map can't route anywhere.")
if packages and "tiles/region-routing.pmtiles" not in roads_zip:
    bad.append(
        f"{PUBLISH}: `tiles/region-routing.pmtiles` isn't in `-roads.zip`. Who "
        f"takes only the networks must get the one routes are computed on – the "
        f"registry gives it to `roads` from the manifest under `routing`.")
if packages and "routing" in packages:
    bad.append(
        f"{PUBLISH}: a `-routing.zip` package was made. Routing rides in the map "
        f"and in `roads`; a third ZIP would be downloaded for nothing.")

# the same for layers with their own package: none may stay in the base map
for kind, name in (("contours", "tiles/region-contours.pmtiles"),
                   ("rocks", "tiles/region-rocks.pmtiles"),
                   ("terrain", "tiles/region-terrain.pmtiles"),
                   ("roads", "tiles/region-transport.pmtiles"),
                   ("points", "tiles/region-points.pmtiles"),
                   ("boundaries", "tiles/region-boundaries.pmtiles"),
                   ("water", "tiles/region-water.pmtiles"),
                   ("settlements", "tiles/region-buildings.pmtiles")):
    if not packages:
        break
    if name in base_zip:
        bad.append(
            f"{PUBLISH}: `{name}` is in the BASE MAP and in package `{kind}`. "
            f"“Just the map” then weighs as much as the map with everything.")
    if name not in packages.get(kind, set()):
        bad.append(
            f"{PUBLISH}: `{name}` didn't get into package `{kind}` – that package "
            f"promises a layer it doesn't carry.")

# a package that is made must not be retired: the run would upload and delete it
with open(REGISTRY, encoding="utf-8") as _f:
    _reg = json.load(_f)
_alive = {p["key"] for p in _reg.get("packages") or []}
_gone = {r["key"] for r in _reg.get("retired") or []}
for _k in sorted(_alive & _gone):
    bad.append(
        f"{REGISTRY}: package `{_k}` is alive AND in `retired`. `retired` means "
        f"“the old one is deleted” – it would vanish right after the run uploaded it.")
for _k in ("roads", "boundaries", "water", "settlements"):
    if _k not in _alive:
        bad.append(
            f"{REGISTRY}: package `{_k}` isn't in the registry, so it isn't made and "
            f"the catalog says nothing of it – the layer is built and ends nowhere.")
if "routing" in _alive or "routing" not in _gone:
    bad.append(
        f"{REGISTRY}: package `routing` must be in `retired`, not alive: routing "
        f"rides in the map and in `roads`, and an old `-navigacia.zip` would "
        f"otherwise stay on Drive with the catalog offering it.")
_roads = next((p for p in _reg.get("packages") or [] if p["key"] == "roads"), {})
if "routing" not in (_roads.get("manifest") or []) \
        or "-routing.pmtiles" not in (_roads.get("suffixes") or []):
    bad.append(
        f"{REGISTRY}: package `roads` doesn't take routing (`routing` in `manifest`, "
        f"`-routing.pmtiles` in `suffixes`). Regenerating one layer runs without a "
        f"manifest, so without both it would come out without the network.")

# Pages really has those files
with open(SITE, encoding="utf-8") as f:
    site_sh = f.read()

if not re.search(r'glyphs\s*=\s*"\$BASE/fonts/\{fontstack\}/\{range\}\.pbf"',
                 site_sh.replace("GLYPHS=", "glyphs=")):
    bad.append(
        f"{SITE}: the glyph address in the manifest isn't built from `$BASE`. "
        f"Glyphs aren't in the package, so this address is all the web has – a "
        f"relative one would point into the package, where there is nothing.")

if not re.search(r"cp\s+poc/web/\*\.js\s+poc/web/\*\.json\s+poc/web/index\.html\s+_site/",
                 site_sh):
    bad.append(
        f"{SITE}: the viewer isn't copied into `_site` any more. It's left out of "
        f"the package because it's on Pages – gone from there too, it's nowhere.")

# the world map doesn't link into the package
with open(WORLD_STYLE, encoding="utf-8") as f:
    world_style = f.read()
if 'url("fonts/{fontstack}/{range}.pbf")' in world_style:
    bad.append(
        f"{WORLD_STYLE}: the world map links glyphs INTO THE PACKAGE, where they "
        f"no longer are. An unpacked package in the viewer would have no names.")
if "fonts.openmaptiles.org" not in world_style:
    bad.append(
        f"{WORLD_STYLE}: the world style has nowhere to take glyphs from. The app "
        f"carries them, but anything else needs an address.")

for b in bad:
    print(f"::error::{b}")
print(f"Glyphs and viewer are outside packages, yet somewhere: {len(bad)} errors")
sys.exit(1 if bad else 0)
