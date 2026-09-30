#!/usr/bin/env python3
"""How many areas Planetiler drops WHOLE from this PBF (a member way is missing) – and which.

Usage:
    python3 workers/plan/pbf-areas.py data/region.osm.pbf
    python3 workers/plan/pbf-areas.py data/region.osm.pbf --summary=$GITHUB_STEP_SUMMARY
"""
import argparse
import re
import subprocess
import sys
import tempfile

# only areas the style draws; hundreds of `type=boundary` relations never show
AREA_KEYS = ("landuse", "natural", "leisure", "boundary", "waterway", "place")
VISIBLE = {
    "forest", "wood", "scrub", "heath", "grass", "grassland", "meadow",
    "farmland", "orchard", "vineyard", "water", "wetland", "bay", "reservoir",
    "park", "garden", "nature_reserve", "protected_area", "national_park",
    "military", "quarry", "residential", "industrial", "golf_course", "pitch",
}

_ESC = re.compile(r"%([0-9a-fA-F]+)%")


def unesc(text):
    """OPL escapes space, comma etc. as `%20%` – back to the character."""
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), text)


def opl_fields(line):
    """OPL line → `{letter: rest}`; spaces in values are escaped."""
    out = {}
    for field in line.split(" "):
        if field:
            out[field[0]] = field[1:]
    return out


def tags(field):
    out = {}
    if not field:
        return out
    for part in field.split(","):
        k, _, v = part.partition("=")
        out[unesc(k)] = unesc(v)
    return out


def way_ids(pbf):
    """Ids of the ways really in the file."""
    ids = set()
    p = subprocess.Popen(["osmium", "cat", "-t", "way", "-f", "opl", pbf],
                         stdout=subprocess.PIPE, text=True)
    for line in p.stdout:
        space = line.find(" ")
        ids.add(int(line[1:space if space > 0 else None]))
    if p.wait() != 0:
        raise SystemExit(f"::error::`osmium cat` on {pbf} failed.")
    return ids


def broken(pbf):
    """`[(missing, members, id, kind, name)]` for areas Planetiler drops."""
    with tempfile.NamedTemporaryFile(suffix=".osm.pbf") as tmp:
        subprocess.run(
            ["osmium", "tags-filter", "-R", "--overwrite", "-o", tmp.name, pbf,
             "r/type=multipolygon", "r/type=boundary"],
            check=True, stdout=subprocess.DEVNULL)
        opl = subprocess.run(["osmium", "cat", "-f", "opl", tmp.name],
                             check=True, capture_output=True, text=True).stdout

    present = way_ids(pbf)
    out = []
    for line in opl.splitlines():
        if not line.startswith("r"):
            continue
        f = opl_fields(line)
        t = tags(f.get("T", ""))
        if t.get("type") not in ("multipolygon", "boundary"):
            continue
        kind = next((t[k] for k in AREA_KEYS if k in t), "")
        if kind not in VISIBLE:
            continue
        ways = [int(m[1:].split("@")[0]) for m in f.get("M", "").split(",")
                if m.startswith("w")]
        if not ways:
            continue
        missing = [i for i in ways if i not in present]
        if missing:
            out.append((len(missing), len(ways), line.split(" ")[0],
                        kind, t.get("name", "")))
    out.sort(reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("--summary", default="", help="where to append a line to the run summary")
    ap.add_argument("--top", type=int, default=10, help="how many victims to list")
    args = ap.parse_args()

    # not a hard error: areas across the state border can't be completed here
    dropped = broken(args.pbf)
    named = [v for v in dropped if v[4]]

    if not dropped:
        print("Areas Planetiler would drop whole: NONE ✓")
    else:
        print(f"Areas Planetiler drops WHOLE (a member is missing): {len(dropped)}")
        for missing, members, rid, kind, name in dropped[:args.top]:
            print(f"  {rid:<12} {kind:16} missing {missing:4}/{members:<5} "
                  f"{name or '(no name)'}")
        if len(dropped) > args.top:
            print(f"  … and {len(dropped) - args.top} more")

    if named:
        names = ", ".join(m for *_, m in named[:5] if m)
        print(f"::warning::These areas will be missing from the map, WHOLE – "
              f"they lack members in the PBF, so Planetiler drops them with "
              f"the part that lies in the map ({len(named)} named): "
              f"{names}. Expected are those whose members aren't even in the "
              f"parent extract, i.e. reaching beyond the STATE border (only a "
              f"Europe extract would complete them). Anything else means the "
              f"cut in `workers/plan/pbf.sh` doesn't complete members – check "
              f"`-s smart -S types=multipolygon,boundary`.")

    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(f"\n**Areas dropped for missing members:** {len(dropped)}"
                    f" ({len(named)} named)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
