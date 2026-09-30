#!/usr/bin/env python3
"""Split the free `key=value` input `options` into single settings; an unknown key is an error.

    python3 workers/plan/options.py --options=\"rock_res=1\" \\
        --rebuild=rocks --contour-source=sonny --rock-source=dmr5 \\
        --shading-source=sonny --test=true --publish-pages=true \\
        --out=$GITHUB_OUTPUT
"""
import argparse
import json
import os
import shlex
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

sys.path.insert(0, os.path.join(_WORKERS, "lib"))
from cell import terrain_zoom_for, tile_m_per_px  # noqa: E402

# key: (default, description)
DEFAULTS = {
    "crop_bbox": ("", "crop the region to west,south,east,north"),
    "area_bbox": ("", "own cut-out W,S,E,N instead of the range picked"),
    # 4 km², not 2: on two a rock area often hit nothing
    "test_km2": ("4", "square size with the `test` switch on (km²)"),
    "test_at": ("", "centre of the test square `lon,lat` (empty = centre of the cut-out)"),
    "reuse_layers": ("true", "don't compute a height-model layer already made "
                             "with these settings"),
    "size_limit_mb": ("900", "budget of the whole site in MB"),
    "auto_shrink": ("true", "lower the tile zoom when they don't fit"),
    "ugkk_fallback": ("true", "when DMR 5.0 is missing for the cut-out, use Sonny"),
    "ugkk_urls": ("", "direct URLs to ÚGKK data (last resort)"),
    "contour_maxzoom": ("14", "max zoom of contour tiles"),
    # 16 is Planetiler's hard cap; overzoom does the rest
    "rock_maxzoom": ("16", "max zoom of rock tiles (Planetiler caps at 16)"),
    "rock_solid": ("1", "1 = one rock class (no area inside another), "
                        "0 = steep/cliff classes as before"),
    # holes are gullies and ledges – the very shape rocks are computed for
    "rock_fill_holes": ("0", "1 = fill holes in rocks (solid areas instead of "
                             "shape) – not recommended"),
    # `auto` picks the grid from the DEM cell and the time budget, and says why
    "rock_res": ("auto", "grid for the rock outline in metres, or `auto`"),
    "contour_smoothing": ("0", "DEM smoothing in arc seconds"),
    "trails_maxzoom": ("14", "max zoom of waymarked trail tiles"),
    # `auto` = the lowest zoom whose pixel is finer than the model cell
    "terrain_maxzoom": ("auto", "max zoom of height tiles (auto = by the model grid)"),
    # public AWS tiles are global and coarse, so no 3D on them
    "terrain_3d": ("auto", "3D terrain in the style (auto = when we have our own height tiles)"),
    # trails have no source choice – the same PBF as the map
    "trails": ("true", "make waymarked trails from OSM relations"),
    "features": ("true", "make landscape features OpenMapTiles lacks"),
    "routing": ("true", "build the routing network of this region – it rides "
                        "in the base map and in package `roads`"),
    "transport": ("true", "make the road network (roads, railways, ferries, "
                          "lifts) with road limits – package `roads`"),
    # 14, not 15: the schema's highest `min_zoom` is 14
    "transport_maxzoom": ("14", "max zoom of road network tiles"),
    "boundaries": ("true", "make area boundaries and their names – package "
                           "`boundaries`"),
    # 12: past it only settlement points are added (`min_zoom: 10`)
    "boundaries_maxzoom": ("12", "max zoom of boundary tiles"),
    "water": ("true", "make water (rivers, lakes, sea) – package `water`"),
    # 14: the schema's highest `min_zoom` is 13, one more is headroom
    "water_maxzoom": ("14", "max zoom of water tiles"),
    "rail": ("true", "make railways with stations and the track network "
                     "for navigation – package `railways`"),
    # 15: kilometre posts start at z15
    "rail_maxzoom": ("15", "max zoom of railway tiles"),
    "buildings": ("true", "make settlements – buildings with floor area and "
                          "name – package `settlements`"),
    # 14: the schema's highest `min_zoom`, past it tiles only grow
    "buildings_maxzoom": ("14", "max zoom of settlement tiles"),
    # from DMR 5.0, 5 m is a good default nearly everywhere
    "contour_interval": ("5", "contour interval in metres (10 = sparser)"),
    # 15, not 14: the schema has classes with `min_zoom: 15`
    "features_maxzoom": ("15", "max zoom of landscape feature tiles"),
    # clipping tiles to the region outline (`workers/lib/region-clip.sh`); off for now
    "region_clip": ("false", "clip tiles to the region outline (off for now)"),
    "publish": ("true", "upload the finished map as ZIPs to Google Drive"),
    # downloaded only when the region's articles are in neither cache nor catalog
    "wikipedia": ("true", "Wikipedia articles for the region's objects (workflow "
                          "“Build wiki” called from the build)"),
    # `.aar` is a job of its own on macOS – `aa` exists nowhere else
    "apple_archive": ("true", "upload the map as .aar too (Apple Archive, a macOS job)"),
    # empty = the newest asset for the cut-out
    "rock_img_asset": ("", "exact asset name of rocks from hillshading (empty = compute in this run)"),
    # tuning the pipeline the build calls itself (shading-rocks.yml)
    "rock_img_zoom": ("auto", "zoom of hillshading tiles (auto = the highest under the cap)"),
    "rock_img_options": ("", "switches for rocks from hillshading, e.g. \"fill=40 min_hole=5\""),
    "maxzoom": ("16", "max zoom of map tiles – Planetiler goes to 16 at most"),
    "custom_pbf_url": ("", "own region – URL of a .osm.pbf"),
    "custom_name": ("", "own region – display name"),
    "custom_bbox": ("", "own region – bbox W,S,E,N"),
}

# settings that moved between inputs – so they don't fail as "unknown"
MOVED = {
    "rock_source": "is an input of its own in the form (rock source), not an option",
    "test": "is a switch in the form (quick test on a few km²), not an option. "
            "The square size is the option `test_km2`",
    "publish_pages": "is a switch in the form (deploy to GitHub Pages), not an "
                     "option. Publishing to Drive is the option `publish`",
    "wiki_langs": "is an input of the workflow “Build wiki” (wiki.yml) – English "
                  "and the country's language are added by themselves",
    "wiki_format": "no longer exists: articles are always plain text",
    "wiki_max": "is an input of the workflow “Build wiki” (wiki.yml)",
    "dem_source": "split into three inputs in the form – `contour_source`, "
                  "`rock_source` and `shading_source`",
    "layers": "no longer exists: a layer is on when the form names its source "
              "(`none` = don't make). Trails are turned off with `trails=false`",
    "rocks": "no longer exists: rocks are turned off with `rock_source: none`",
}

# former Slovak names, still carried by the forms of older runs ("Re-run")
OPTION_ALIAS = {"navigacia": "routing", "rock_plne": "rock_solid",
                "rock_zapln_diery": "rock_fill_holes"}
SOURCE_ALIAS = {"ziadne": "none", "tienovanie": "shading"}

# the choice that turns a layer off; a word, so "nothing" is a visible choice
NONE = "none"

# rocks have one more source that reads no DEM: polygons from hillshading
ROCK_FROM_SHADING = "shading"

# one choice instead of three checkboxes – the form holds ten inputs at most
REBUILD = {
    "nothing": (),
    "contours": ("contours_rebuild",),
    "rocks": ("rocks_rebuild",),
    "terrain": ("terrain_rebuild",),
    "articles": ("wiki_rebuild",),
    "everything": ("contours_rebuild", "rocks_rebuild", "terrain_rebuild",
                   "wiki_rebuild"),
}
# former values → today's; translated aloud, "Re-run" carries the old form
REBUILD_ALIAS = {"teren": "terrain", "nic": "nothing", "vrstevnice": "contours",
                 "skaly": "rocks", "tienovanie": "terrain", "clanky": "articles",
                 "vsetko": "everything"}
# the flags `rebuild` switches – one list, so none can be forgotten
REBUILD_FLAGS = ("contours_rebuild", "rocks_rebuild", "terrain_rebuild",
                 "wiki_rebuild")

# what `rebuild` does NOT redo; said aloud, or "everything" reads as a lie
REBUILD_OUTSIDE = [
    ("the height model (DEM)",
     "read from Drive once and kept in the store; its shape is carried by the "
     "STORE NAME (today `dem-dmr5-v2`), so a changed rule changes the name and "
     "`check-dem` refills it itself"),
    ("packages on Drive (ZIP/AAR) and the catalog (`maps.json`, for a test "
     "`maps-test.json`)",
     "overwritten by EVERY run that makes them (upload, then delete the old); "
     "a package of a layer the run didn't make is deleted"),
]


def dem_sources(path=None):
    """Sources from workers/data/dem-sources.json → {key: its whole entry}."""
    path = path or os.path.join(_DATA, "dem-sources.json")
    with open(path) as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def pick_source(what, value, allowed):
    """Check one source choice; return it, or None on error."""
    value = (value or NONE).strip()
    if value in SOURCE_ALIAS:
        print(f"::notice::`{value}` for {what} is `{SOURCE_ALIAS[value]}` today – "
              f"taking it as that.")
        value = SOURCE_ALIAS[value]
    if value in allowed:
        return value
    print(f"::error::Unknown source “{value}” for {what}. Known: "
          f"{', '.join(allowed)}", file=sys.stderr)
    return None


def check_bool(values, key, label=""):
    """True when `key` is true/false; says so otherwise."""
    if values[key] in ("true", "false"):
        return True
    print(f"::error::Option “{key}”{f' ({label})' if label else ''} must be true "
          f"or false, not “{values[key]}”.", file=sys.stderr)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--options", default="")
    ap.add_argument("--rebuild", default="nothing")
    ap.add_argument("--contour-source", default=NONE,
                    help="height source for contours, or `none`")
    ap.add_argument("--rock-source", default=NONE,
                    help="rock source: a height model, `shading`, or `none`")
    ap.add_argument("--shading-source", default=NONE,
                    help="height source for hillshading and 3D terrain, or `none`")
    ap.add_argument("--test", default="false",
                    help="quick test switch: true = compute only a square of "
                         "`test_km2` km²")
    ap.add_argument("--publish-pages", default="true",
                    help="GitHub Pages switch: false = the map is built and "
                         "checked, not deployed")
    ap.add_argument("--dem-sources", default="",
                    help="path to dem-sources.json (default beside the script)")
    ap.add_argument("--out", default="")
    ap.add_argument("--summary", default="",
                    help="where to add a block to the run summary (GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()

    values = {k: v for k, (v, _) in DEFAULTS.items()}
    changed = {}

    # shlex, not split(): a value may be quoted
    for token in shlex.split(args.options or ""):
        if "=" not in token:
            print(f"::error::Option “{token}” is not key=value.", file=sys.stderr)
            return 1
        k, v = token.split("=", 1)
        k = k.strip()
        if k in OPTION_ALIAS:
            print(f"::notice::Option `{k}` is `{OPTION_ALIAS[k]}` today – taking it as that.")
            k = OPTION_ALIAS[k]
        if k in MOVED:
            print(f"::error::“{k}” {MOVED[k]}. Remove it from `options` "
                  f"and set it in the form.", file=sys.stderr)
            return 1
        if k not in DEFAULTS:
            print(f"::error::Unknown option “{k}”. Known options: "
                  f"{', '.join(sorted(DEFAULTS))}", file=sys.stderr)
            return 1
        values[k] = v
        changed[k] = v

    # switch and size make one number: 0 = a real run, else the square side in km²
    test_on = (args.test or "false").strip().lower()
    if test_on not in ("true", "false"):
        print(f"::error::Switch “test” must be true or false, "
              f"not “{args.test}”.", file=sys.stderr)
        return 1
    test_on = test_on == "true"

    size = (values["test_km2"] or "").strip()
    try:
        n = float(size)
    except ValueError:
        print(f"::error::Option “test_km2” must be a number in km², "
              f"not “{size}”.", file=sys.stderr)
        return 1
    if n <= 0:
        # the switch turns it off, not a zero – or there are two levers for one thing
        print(f"::error::Option “test_km2” must be above zero "
              f"(“{size}”). The quick test is turned off by unticking the "
              f"switch “test”.", file=sys.stderr)
        return 1
    if "test_km2" in changed and not test_on:
        print("::error::`test_km2` makes sense only with the switch “test” on – "
              "nothing would be computed differently. Tick `test`, or remove "
              "`test_km2` from options.", file=sys.stderr)
        return 1
    values["test_km2"] = f"{n:g}" if test_on else "0"

    # what may be picked where is the `for` in dem-sources.json
    srcs = dem_sources(args.dem_sources or None)
    contour_src = pick_source(
        "contours (contour_source)", args.contour_source,
        [NONE] + [k for k, v in srcs.items() if "contours" in v.get("for", [])])
    rock_src = pick_source(
        "rocks (rock_source)", args.rock_source,
        [NONE, ROCK_FROM_SHADING]
        + [k for k, v in srcs.items() if "rocks" in v.get("for", [])])
    shading_src = pick_source(
        "hillshading (shading_source)", args.shading_source,
        [NONE] + [k for k, v in srcs.items() if "shading" in v.get("for", [])])
    if contour_src is None or rock_src is None or shading_src is None:
        return 1

    values["contour_source"] = contour_src
    values["rock_source"] = rock_src
    values["shading_source"] = shading_src

    # `terrain_maxzoom: auto` is decided here only: cache key, asset name and
    # style attribution need the number
    tz = values["terrain_maxzoom"].strip().lower()
    if tz == "auto":
        cell = float(srcs.get(shading_src, {}).get("cell_m") or 20)
        values["terrain_maxzoom"] = str(terrain_zoom_for(cell))
        if shading_src != NONE:
            print(f"Height tiles: model {shading_src} has a {cell:g} m grid → maxzoom "
                  f"z{values['terrain_maxzoom']} (pixel "
                  f"{tile_m_per_px(int(values['terrain_maxzoom'])):.1f} m). "
                  f"A fixed zoom can be forced with `terrain_maxzoom=13`.")
    elif not tz.isdigit():
        print(f"::error::Option “terrain_maxzoom” must be a number or "
              f"`auto`, not “{values['terrain_maxzoom']}”.", file=sys.stderr)
        return 1
    # with `shading` and `none` it is empty and nobody may download a DEM
    values["rock_dem"] = rock_src if rock_src in srcs else ""

    values["contour_lines"] = "true" if contour_src != NONE else "false"
    values["rocks"] = "true" if rock_src != NONE else "false"
    values["terrain"] = "true" if shading_src != NONE else "false"
    # `contours` gates the whole job: both layers go into one .pmtiles
    values["contours"] = ("true" if contour_src != NONE or rock_src != NONE
                          else "false")
    # `trails=1` would silently turn trails off, found only on the map
    for key, label in (("trails", ""), ("features", ""), ("transport", ""),
                       ("boundaries", "boundaries"), ("water", "water"),
                       ("rail", "railways"), ("buildings", "settlements"),
                       ("routing", ""), ("apple_archive", ""), ("wikipedia", ""),
                       ("publish", "")):
        if not check_bool(values, key, label):
            return 1
    # a switch in the form, but the script can be run by hand
    pages_on = (args.publish_pages or "true").strip().lower()
    if pages_on not in ("true", "false"):
        print(f"::error::Switch “publish_pages” must be true or false, "
              f"not “{args.publish_pages}”.", file=sys.stderr)
        return 1
    values["publish_pages"] = pages_on

    # or `contour_interval=five` fails in `gdal_contour`, an hour in
    try:
        interval = float(values["contour_interval"])
    except ValueError:
        print(f"::error::Option “contour_interval” must be a number in metres, "
              f"not “{values['contour_interval']}”.", file=sys.stderr)
        return 1
    if interval <= 0:
        print(f"::error::Option “contour_interval” must be above zero "
              f"(“{values['contour_interval']}”). Contours are turned off by "
              f"picking `contour_source: none`.", file=sys.stderr)
        return 1
    values["contour_interval"] = f"{interval:g}"

    rebuild = (args.rebuild or "nothing").strip()
    if rebuild in REBUILD_ALIAS:
        print(f"::notice::`rebuild: {rebuild}` is `{REBUILD_ALIAS[rebuild]}` today – "
              f"taking it as that.")
        rebuild = REBUILD_ALIAS[rebuild]
    if rebuild not in REBUILD:
        print(f"::error::Unknown rebuild “{args.rebuild}”. Known: "
              f"{', '.join(REBUILD)}", file=sys.stderr)
        return 1
    for flag in REBUILD_FLAGS:
        values[flag] = "true" if flag in REBUILD[rebuild] else "false"

    # a quick test always rebuilds everything; the real run's cache is safe –
    # its keys carry `dem_bboxkey`, which for a test is the test square's bbox
    if test_on:
        for flag in ("contours_rebuild", "rocks_rebuild", "terrain_rebuild"):
            values[flag] = "true"

    if not check_bool(values, "reuse_layers"):
        return 1
    # a test takes nothing finished, for the same reason
    if test_on and values["reuse_layers"] == "true":
        if "reuse_layers" in changed:
            print("::notice::`reuse_layers=true` doesn't apply with the switch “test” "
                  "on – a quick test always computes layers anew, so you don't "
                  "tune on an old result.")
        values["reuse_layers"] = "false"

    lines = [f"opt_{k}={v}" for k, v in values.items()]
    if args.out:
        with open(args.out, "a") as f:
            f.write("\n".join(lines) + "\n")

    # what the run starts with, first on the run page, in sight after a failure too
    if args.summary:
        with open(args.summary, "a") as f:
            f.write("## What came of it – the run starts with this\n\n")
            f.write("| setting | value | |\n|---|---|---|\n")
            for k in sorted(values):
                mark = "**not the default**" if k in changed else ""
                f.write(f"| `{k}` | `{values[k] or '—'}` | {mark} |\n")
            f.write("\nUnmarked values are defaults. Marked ones you gave – in the "
                    "form or in the `options` field.\n\n")

    print("Settings:")
    for k in sorted(values):
        mark = "  ←" if k in changed else ""
        d = DEFAULTS.get(
            k, ("", "from the form inputs (sources / rebuild / test)"))[1]
        print(f"  {k:<20} {values[k] or '(empty)':<24} {d}{mark}")
    if changed:
        print(f"\nChanged from the defaults: {', '.join(sorted(changed))}")
    if test_on:
        print("Rebuild: EVERYTHING (a quick test always computes anew, so you don't "
              f"tune on an old cached result; it overrides `rebuild: {rebuild}`)")
    elif rebuild != "nothing":
        print(f"Rebuild: {rebuild}")
    if values["reuse_layers"] == "true":
        print("Finished layers: TAKEN – contours, rocks and hillshading already made "
              "with these settings aren't recomputed (`rebuild` recomputes them)")
    else:
        print("Finished layers: NOT TAKEN (`reuse_layers=false`) – contours, rocks and "
              "hillshading are recomputed as soon as the model store or the script "
              "drawing them changed")
    if test_on or rebuild != "nothing":
        # what is NOT recomputed too – or "everything" promises more than it does
        print("  recomputed: "
              + ", ".join(f.replace("_rebuild", "")
                          for f in REBUILD_FLAGS if values[f] == "true"))
        for what, how in REBUILD_OUTSIDE:
            print(f"  NOT recomputed: {what} – {how}")
    print(f"\nContours: {contour_src}   Rocks: {rock_src}   "
          f"Hillshading: {shading_src}   Trails: {values['trails']}   "
          f"Landscape features: {values['features']}   "
          f"Road network: {values['transport']}   "
          f"Boundaries: {values['boundaries']}   "
          f"Water: {values['water']}   "
          f"Railways: {values['rail']}   "
          f"Settlements: {values['buildings']}")
    print("Quick test: " + (f"ON, terrain (contours, rocks, hillshading) only on "
                            f"{values['test_km2']} km² in the middle of the cut-out; "
                            f"the map stays the whole region and opens there"
                            if test_on else "off – a real run"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
