#!/usr/bin/env python3
"""Copies the country's traffic regulations from traffic-signs into the region's tiles."""
import argparse
import json
import os
import sys


def checked(doc, country):
    """The regulations, or why the file can't ride in a package."""
    if not isinstance(doc, dict) or doc.get("country") != country:
        return None, f"not the regulations of “{country}”"
    speed = doc.get("speed")
    if not isinstance(speed, dict) or not speed:
        return None, "no `speed` limits"
    for context, limits in speed.items():
        if not isinstance(limits, dict) or not isinstance(limits.get("default"), int):
            return None, f"context `{context}` has no whole `default` limit"
    return doc, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signs", required=True, help="traffic-signs checkout")
    ap.add_argument("--country", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    src = os.path.join(args.signs, "regulations", f"{args.country}.json")
    if not os.path.exists(src):
        print(f"no regulations for “{args.country}” – the app keeps its own")
        return 0
    with open(src, encoding="utf-8") as f:
        doc, why = checked(json.load(f), args.country)
    if why:
        print(f"{src}: {why}", file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
