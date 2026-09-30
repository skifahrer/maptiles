#!/usr/bin/env python3
"""Merge this run's catalog write into what the branch holds meanwhile (three-way)."""
import argparse
import json
import sys


def merge(base, mine, theirs):
    """`theirs` plus what this run changed against `base`."""
    out = dict(theirs)
    for key in set(base) | set(mine):
        from_base, own = base.get(key), mine.get(key)
        if from_base == own:
            continue
        if key not in mine:
            out.pop(key, None)
        elif isinstance(own, dict) and isinstance(out.get(key), dict):
            out[key] = merge(from_base if isinstance(from_base, dict) else {},
                             own, out[key])
        else:
            out[key] = own
    return out


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="catalog before the write")
    ap.add_argument("--mine", required=True, help="catalog after the write")
    ap.add_argument("--theirs", required=True, help="catalog in the branch")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        base, mine, theirs = (read(args.base), read(args.mine),
                              read(args.theirs))
    except (OSError, ValueError) as exc:
        print(f"::warning::The catalog couldn't be merged ({exc}) – taking my write.")
        return 1
    if not all(isinstance(d, dict) for d in (base, mine, theirs)):
        print("::warning::The catalog is not an object – taking my write.")
        return 1
    out = merge(base, mine, theirs)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, separators=(",", ":"),
                           sort_keys=True) + "\n")
    print("Catalog merged with the branch ✓" if out != mine
          else "The branch didn't change meanwhile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
