#!/usr/bin/env python3
"""The region's traffic signs for the job summary: how each is tagged, how many, what it maps to."""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from signs import MAPPING  # noqa: E402
from sprite import supported  # noqa: E402

ROWS = 100


def read_report(path):
    """`[(tagged, name, count)]` from `signs.py --report`, most first."""
    with open(path, encoding="utf-8") as f:
        rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
    return sorted(((t, n, int(c)) for t, n, c in rows), key=lambda r: -r[2])


def markdown(region, country, rows, drawn, mapping=MAPPING):
    """The summary: totals, then one row per tagging."""
    folders = supported(country, mapping) if country else {}
    total = sum(c for _, _, c in rows)
    shown = sum(c for _, n, c in rows if n in drawn)
    out = [f"## Traffic signs – {region}", ""]
    if not total:
        return "\n".join(out + ["No traffic sign in this region.", ""])
    out += [f"**{total}** sign points in {len(rows)} taggings; **{shown}** drawn "
            f"({100 * shown // total} %) with {len({folders[n] for n in drawn if n in folders})} images.", "",
            "| tagged in OSM | points | image name | mapped to | drawn |", "|---|---:|---|---|---|"]
    for t, n, c in rows[:ROWS]:
        folder = folders.get(n)
        state = ("yes" if n in drawn else "no image" if folder
                 else "no country" if not n else "not mapped")
        cell = t.replace("|", "\\|")
        out.append(f"| `{cell}` | {c} | {f'`{n}`' if n else '–'} | "
                   f"{f'`{folder}`' if folder else '–'} | {state} |")
    if len(rows) > ROWS:
        rest = rows[ROWS:]
        out.append(f"| … {len(rest)} more taggings | {sum(c for _, _, c in rest)} | | | |")
    return "\n".join(out + [""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="`signs.py --report`")
    ap.add_argument("--region", required=True)
    ap.add_argument("--country", default="")
    ap.add_argument("--sprite", help="the region's sprite index; its names are what is drawn")
    a = ap.parse_args()
    drawn = set()
    if a.sprite and os.path.isfile(a.sprite):
        with open(a.sprite, encoding="utf-8") as f:
            drawn = set(json.load(f))
    print(markdown(a.region, a.country.lower(), read_report(a.report), drawn))


if __name__ == "__main__":
    main()
