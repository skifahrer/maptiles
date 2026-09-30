#!/usr/bin/env python3
"""Routing: its scope, its catalog node and what must not get lost in it.

Two different things under one name, so both are here:

  * A REGION'S ROUTING NETWORK (`<region>-routing.pmtiles`, in the base map and
    in the `roads` package) – what goes to the phone; described in `docs/routing-tiles.md`;
  * VALHALLA'S GRAPH over a whole state (`navigation.yml`) – the reference build
    the new engine is cross-checked against. It's no longer built per region.

Quiet things:
  1. two scopes in one catalog node – the second run would overwrite the first's
     item and the catalog would know only one of two packages on Drive;
  2. the national graph must not be built from a cut PBF: an edge without its
     other end is a dead end, yet the graph builds and the run goes green;
  3. without `admins.sqlite` Valhalla doesn't know which country an edge is in;
  4. a scope covering a country outside `vignettes.json` never asks for a vignette;
  5. the region network must stand on the map's PBF, ride in the map and in
     `roads` and be in the manifest; its own `routing` package is retired;
  6. node order: a region build takes it from the cache, and when it's missing
     or stale computes and saves it; the cache key must read the same on every
     side, or archives quietly and forever go without it;
  7. a GitHub form can't read a list from a file, so it's written twice.
"""
import json
import os
import re
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)
_DATA = os.path.join(_WORKERS, "data")

AREAS = os.path.join(_DATA, "routing-areas.json")
REGIONS = os.path.join(_DATA, "regions.json")
VIGNETTES = os.path.join(_DATA, "vignettes.json")
REGISTRY = os.path.join(_DATA, "packages.json")
WORKFLOW = os.path.join(".github", "workflows", "navigation.yml")
ORDER_WORKFLOW = os.path.join(".github", "workflows", "routing-order.yml")
REGION_WORKFLOW = os.path.join(".github", "workflows", "navigation-region.yml")
BUILD_MAP = os.path.join(".github", "workflows", "build-map-region.yml")
SITE_SH = os.path.join(_WORKERS, "deploy", "site.sh")
PBF_SH = os.path.join(_WORKERS, "routing", "pbf.sh")
GRAPH_SH = os.path.join(_WORKERS, "routing", "graph.sh")
BUILD_SH = os.path.join(_WORKERS, "routing", "build.sh")

# listed in graph.sh too on purpose: there the run is checked, here the script
REQUIRED = ("valhalla_tiles.tar", "valhalla.json", "admins.sqlite",
            "timezones.sqlite")

bad = []


def err(path, msg):
    bad.append((path, msg))


def national_graph(areas, regions, countries):
    """Valhalla over a whole state – the reference build that stays."""
    rel_areas = "workers/data/routing-areas.json"
    rel_regions = "workers/data/regions.json"

    for key, area in areas.items():
        rk = area.get("region_key")
        if rk not in regions:
            err(rel_areas,
                f"scope `{key}` has `region_key: {rk}`, which `regions.json` "
                f"lacks – `publish-map.py` couldn't build its Drive path from it "
                f"and the package would end up in `other/`.")
            continue
        r = regions[rk]
        if r.get("admin_level") != 2:
            err(rel_regions,
                f"`{rk}` has `admin_level: {r.get('admin_level')}`. The graph isn't "
                f"a region map – with another value `publish-map.py` would give it "
                f"a region level it doesn't have.")
        if r.get("country") != rk:
            err(rel_regions,
                f"`{rk}` has `country: {r.get('country')}`, which ISN'T its key. "
                f"At `admin_level: 2` `country` is also a node in `maps.json`, "
                f"so two scopes with the same `country` OVERWRITE each other's "
                f"item: both packages stay on Drive, the catalog knows the last "
                f"one. Set `country: {rk}` – the same as `svet_basic`.")
        for c in area.get("countries") or []:
            if c not in countries:
                err(rel_areas,
                    f"scope `{key}` covers `{c}`, but `vignettes.json` doesn't "
                    f"know that country – the `vignettes` option asks nothing "
                    f"there, and silence can't be told from “no vignette needed”.")
        if not area.get("pbf"):
            err(rel_areas, f"scope `{key}` has not a single PBF.")

    if os.path.exists(PBF_SH):
        pbf = open(PBF_SH, encoding="utf-8").read()
        # comments out – the header says “cut” precisely because nothing is cut
        code = re.sub(r"^[ \t]*#.*$", "", pbf, flags=re.M)
        for wrong in ("osmium extract", "--polygon", "--bbox"):
            if wrong in code:
                err("workers/routing/pbf.sh",
                    f"the script cuts the PBF (`{wrong}`). The graph must not be "
                    f"built from a cutout: an edge missing its other end is a "
                    f"dead end and no route passes it – yet the graph builds "
                    f"and the run goes green.")
        if "osmium merge" not in code and any(
                len(a.get("pbf") or []) > 1 for a in areas.values()):
            err("workers/routing/pbf.sh",
                "the lookup has a scope with several extracts, but the script "
                "doesn't join them with `osmium merge`. PBFs can't be concatenated "
                "(each has its own header) and duplicate border nodes would turn "
                "the graph into two unconnected networks.")
    else:
        err("workers/routing/pbf.sh", "the script doesn't exist.")

    if not os.path.exists(GRAPH_SH):
        err("workers/routing/graph.sh",
            "the script doesn't exist. Valhalla's graph is no longer built per "
            "region, but it stays as the REFERENCE build – without it the new "
            "engine has nothing to be checked against.")
        return
    graph = open(GRAPH_SH, encoding="utf-8").read()
    for f in REQUIRED:
        if f not in graph:
            err("workers/routing/graph.sh",
                f"the script doesn't check `{f}`. Valhalla's image may exit with "
                f"zero even when it didn't make that file – and an incomplete "
                f"graph shows as “no route found”, an app error, not a build "
                f"error.")
    if "valhalla" not in graph or "--version" not in graph:
        err("workers/routing/graph.sh",
            "the script doesn't read Valhalla's version. The graph and the library "
            "reading it must match; a version mismatch looks like a broken route, "
            "not a version mismatch.")
    if '"border"' not in graph:
        err("workers/routing/graph.sh",
            "`graph.json` doesn't say where a route in that graph may go – and "
            "silence reads as a broken graph, not as a scope.")


def region_network():
    """`<region>-routing.pmtiles`: the map's PBF, manifest, check, packaging."""
    if not os.path.exists(BUILD_SH):
        err("workers/routing/build.sh", "the script doesn't exist – the region "
                                        "would go without a routing network.")
    else:
        build = open(BUILD_SH, encoding="utf-8").read()
        if "data/region.osm.pbf" not in build:
            err("workers/routing/build.sh",
                "the region network isn't built from `data/region.osm.pbf`. That "
                "PBF is cut exactly at the region border, so it alone keeps "
                "routing to the same region as the map – another extract would "
                "quietly extend it past the border.")
        if "workers/routing/tiles.py" not in build:
            err("workers/routing/build.sh",
                "the archive isn't built by `workers/routing/tiles.py`. A second "
                "script would be a second truth about what the archive holds and "
                "in what format.")
        if "workers/lint/routing-tiles.py" not in build:
            err("workers/routing/build.sh",
                "the finished archive isn't checked by `workers/lint/routing-tiles.py`. "
                "A broken archive shows on the phone as “no route found”, an app "
                "error – while the run is green.")
        if "tags.py --filter" not in build:
            err("workers/routing/build.sh",
                "the PBF prefilter doesn't take its class list from the dictionary "
                "(`tags.py --filter`). A second list drifts, and drifts quietly: a "
                "class drops out of the archive and the profile keeps offering it.")

    if not os.path.exists(REGION_WORKFLOW):
        err(".github/workflows/navigation-region.yml", "the workflow doesn't exist.")
        return
    wtext = open(REGION_WORKFLOW, encoding="utf-8").read()
    # comments out – the header names `graph.sh` precisely because it's no longer called
    code = re.sub(r"^[ \t]*#.*$", "", wtext, flags=re.M)
    if "workers/routing/build.sh" not in code:
        err(".github/workflows/navigation-region.yml",
            "the region isn't built by `workers/routing/build.sh`.")
    if "workers/routing/graph.sh" in code:
        err(".github/workflows/navigation-region.yml",
            "the region builds Valhalla's graph again. It weighed 176 – 192 MB per "
            "region and ended at the region border; tag tiles replaced it "
            "(`docs/navigation.md` §10). The national `navigation.yml` stays.")
    if "name: site-routing" not in wtext:
        err(".github/workflows/navigation-region.yml",
            "the archive isn't uploaded as `site-routing`. Only through it does it "
            "reach `_site` – and so the manifest, the map and `roads`; `deploy` "
            "merges exactly `site-*`.")
    if "workers/routing/order.sh" not in code:
        err(".github/workflows/navigation-region.yml",
            "the region build doesn't compute the node order (`workers/routing/"
            "order.sh`). An order from the cache is then up to a manual workflow "
            "nobody runs – and archives go without it forever.")
    if "actions/cache-save" not in code:
        err(".github/workflows/navigation-region.yml",
            "a computed order isn't saved to the cache (`cache-save`). Every region "
            "would compute it again and each would get a different one – and such "
            "archives must not be joined on the phone.")
    if "name: pbf" not in wtext:
        err(".github/workflows/navigation-region.yml",
            "the job doesn't download the `pbf` artifact from the plan, so it has "
            "nothing to build the network from – or it fetches an extract itself, "
            "a second truth about the area routing covers.")

    if os.path.exists(BUILD_MAP):
        bm = open(BUILD_MAP, encoding="utf-8").read()
        if "navigation-region.yml" not in bm:
            err(".github/workflows/build-map-region.yml",
                "the map build doesn't call `navigation-region.yml`, so no routing "
                "network is built for the region map – and nobody says so: the "
                "map is fine, you just can't route anywhere in it.")
        if "ROUTING_ENABLED" not in bm:
            err(".github/workflows/build-map-region.yml",
                "the manifest isn't told whether the network was made "
                "(`ROUTING_ENABLED`). The map and `roads` are then assembled by "
                "file names alone, and when no network was made the map pretends "
                "to have one.")

    if os.path.exists(SITE_SH):
        site = open(SITE_SH, encoding="utf-8").read()
        if "routing:" not in site:
            err("workers/deploy/site.sh",
                "the manifest doesn't carry `routing`. The manifest is the one place "
                "that knows what the map really holds – without it the network is "
                "put into the map and `roads` by the name-suffix fallback.")


def node_order(areas, regions):
    """Node order: a region build takes it from the cache, else computes and saves it.

    `routing-order.yml` stays as a manual recompute. The cache key is the only
    link between them and it's a STRING in three places – when it drifts, a
    region build just never finds anything, archives go without an order and
    nothing fails.
    """
    rel_regions = "workers/data/regions.json"
    for key, r in regions.items():
        area = r.get("routing_area")
        if area and area not in areas:
            err(rel_regions,
                f"`{key}` has `routing_area: {area}`, which "
                f"`workers/data/routing-areas.json` lacks. The region build would "
                f"look for an order nobody computes.")

    if not os.path.exists(ORDER_WORKFLOW):
        err(".github/workflows/routing-order.yml",
            "the workflow doesn't exist. It's the manual recompute of the order over "
            "the WHOLE area – without it a new order can only be forced by letting "
            "the old one go stale.")
        return
    ord_text = open(ORDER_WORKFLOW, encoding="utf-8").read()
    if "workers/routing/order.sh" not in ord_text:
        err(".github/workflows/routing-order.yml",
            "the workflow doesn't use `workers/routing/order.sh` – the same script a "
            "region build computes the order with. A second procedure would be a "
            "second truth about which PBF and which code the order comes from.")
    order_sh = os.path.join(_WORKERS, "routing", "order.sh")
    if not os.path.exists(order_sh):
        err("workers/routing/order.sh", "the script doesn't exist.")
    else:
        text = open(order_sh, encoding="utf-8").read()
        for script, why in (
                ("workers/routing/pbf.sh",
                 "a second PBF source would be a second truth about the area the "
                 "order is computed over"),
                ("workers/routing/order.py",
                 "the order must be computed by the same code whose id goes into "
                 "the archive")):
            if script not in text:
                err("workers/routing/order.sh",
                    f"the script doesn't use `{script}` – {why}.")

    keys = {ORDER_WORKFLOW: _cache_keys(ord_text)}
    if os.path.exists(REGION_WORKFLOW):
        keys[REGION_WORKFLOW] = _cache_keys(
            open(REGION_WORKFLOW, encoding="utf-8").read())
    for f in [f for f, k in keys.items() if not k]:
        err(f, "it has no node-order cache key (`routing-order-…`). The order "
               "travels between runs only through it.")
    values = set().union(*keys.values())
    if len(values) > 1:
        err(".github/workflows/routing-order.yml",
            f"the order cache key reads differently on each side ({sorted(values)}). "
            f"A region build then finds nothing, archives go without an order – "
            f"and nothing fails.")


def _cache_keys(text):
    """Order cache key prefixes – without `run_id`, which differs on purpose."""
    return {m.rstrip("-")
            for m in re.findall(r"key: (routing-order-[a-z0-9-]*)", text)}


def package():
    """Routing rides in the map and in `roads`; its own `routing` package is retired."""
    if not os.path.exists(REGISTRY):
        err("workers/data/packages.json", "the package registry doesn't exist.")
        return
    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    packages = {p["key"]: p for p in reg.get("packages") or []}
    retired = {r["key"] for r in reg.get("retired") or []}
    if "routing" in packages:
        err("workers/data/packages.json",
            "package `routing` is alive again. Routing rides in the map and in "
            "`roads`; a third ZIP would be downloaded for nothing.")
    if "routing" not in retired:
        err("workers/data/packages.json",
            "`routing` isn't in `retired`, so the old `-navigacia.zip` stays on "
            "Drive and the catalog keeps offering it.")
    roads = packages.get("roads")
    if not roads:
        err("workers/data/packages.json",
            "package `roads` isn't in the registry – “the networks to travel on, "
            "not the rest of the map” has no answer.")
    elif "transport" not in (roads.get("manifest") or []):
        err("workers/data/packages.json",
            "package `roads` doesn't take `transport` from the manifest – an empty "
            "package with a promise in its name.")
    elif "routing" not in (roads.get("manifest") or []):
        err("workers/data/packages.json",
            "package `roads` doesn't take `routing` from the manifest. Who takes "
            "only the networks must get the one routes are computed on.")
    elif "-routing.pmtiles" not in (roads.get("suffixes") or []):
        err("workers/data/packages.json",
            "package `roads` has no suffix fallback (`-routing.pmtiles`). "
            "Regenerating one layer runs without a manifest, so it would come out "
            "without the network.")


def form(areas):
    """The scope choice in a form must match the lookup."""
    for path in (WORKFLOW, ORDER_WORKFLOW):
        rel = path.replace(os.sep, "/")
        if not os.path.exists(path):
            err(rel, "the workflow doesn't exist.")
            continue
        with open(path, encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        on = wf.get("on", wf.get(True)) or {}
        inp = ((on.get("workflow_dispatch") or {}).get("inputs") or {})
        opts = set((inp.get("area") or {}).get("options") or [])
        if opts != set(areas):
            err(rel,
                f"the form's `area` choice has {sorted(opts)}, the lookup "
                f"{sorted(areas)}. GitHub's `choice` can't read a file, so it's "
                f"written twice – and a scope missing from the choice can't be "
                f"picked.")


def main():
    with open(AREAS, encoding="utf-8") as f:
        areas = json.load(f)["areas"]
    with open(REGIONS, encoding="utf-8") as f:
        regions = json.load(f)
    with open(VIGNETTES, encoding="utf-8") as f:
        countries = json.load(f)["countries"]

    national_graph(areas, regions, countries)
    region_network()
    node_order(areas, regions)
    package()
    form(areas)

    for path, msg in bad:
        print(f"::error file={path}::{msg}")
    if bad:
        print(f"\n{len(bad)} problem(s) in routing.")
        return 1
    print("Routing: the region network stands on the map's PBF, rides in the map "
          "and in `roads` and the run checks it; a region build computes and saves "
          "the node order and every side of the cache key reads the same; Valhalla's "
          "national graph stays as the reference build, its PBF isn't cut and the "
          "forms match the lookup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
