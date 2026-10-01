#!/usr/bin/env python3
"""
GitHub cache cleanup: deletes EVERY entry, since none is used any more.

WHY IT EXISTS. GitHub's cache caps a repository at **10 GB** and when full it
says nothing – it quietly evicts the oldest entries (LRU). This pipeline stored
DEM tiles, the slope part store, contours and shading there, tens of GB per
cutout, so entries evicted each other and hour-long computations reran unseen.

The cache now lives on Google Drive (`workers/drive/cache.py`), so GitHub's is
just leftovers taking space. This script empties it.

WHY IT CAN'T BE DONE OTHERWISE: a cache entry isn't a file in the repository,
so no pull request can delete it; inside a run `GITHUB_TOKEN` can, given
`actions: write`. Hence a workflow.

Runs as `workers/tools/cleanup-cache.py`; the environment says what to do:
    DRY_RUN=true | false           (default: false)
    KEEP=<prefix>                  keep keys with this prefix (default: none)
Expects `gh` and GITHUB_REPOSITORY from the runner.
"""
import json
import os
import subprocess
import sys

REPO = os.environ["GITHUB_REPOSITORY"]
DRY = os.environ.get("DRY_RUN", "false").lower() == "true"
KEEP = os.environ.get("KEEP", "").strip()
SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")


def human(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def gh(path, method=None):
    """One API call. Parsed JSON, or None on error."""
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if method:
        cmd += ["-X", method]
    cmd.append(path)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        # one failed call mustn't stop the cleanup; a 404 on delete is fine
        print(f"::warning::{method or 'GET'} {path}: {p.stderr.strip()[:160]}")
        return None
    return json.loads(p.stdout) if p.stdout.strip() else {}


def pages(path, key, cap=50):
    """A list page by page – all of it before deleting, which shifts the pages."""
    out, page = [], 1
    sep = "&" if "?" in path else "?"
    while page <= cap:
        d = gh(f"{path}{sep}per_page=100&page={page}")
        if not d:
            break
        items = d[key] if isinstance(d, dict) else d
        out += items
        if len(items) < 100:
            break
        page += 1
    return out


def usage():
    """How much cache the repository holds, by GitHub's count, not ours."""
    d = gh(f"/repos/{REPO}/actions/cache/usage") or {}
    return (int(d.get("active_caches_size_in_bytes") or 0),
            int(d.get("active_caches_count") or 0))


def main():
    print(f"Repository: {REPO}   "
          f"{'DRY RUN (nothing deleted)' if DRY else 'for real'}"
          + (f"   keeping keys prefixed `{KEEP}`" if KEEP else ""))

    before_b, before_n = usage()
    print(f"\nGitHub cache before: {before_n} entries, {human(before_b)} "
          f"(the repository cap is 10 GB)")

    caches = pages(f"/repos/{REPO}/actions/caches", "actions_caches")
    rubbish = [c for c in caches if not (KEEP and c["key"].startswith(KEEP))]
    kept = len(caches) - len(rubbish)
    size = sum(int(c.get("size_in_bytes") or 0) for c in rubbish)

    print(f"\nEntries to delete: {len(rubbish)} of {len(caches)}, "
          f"{human(size)}")
    for c in sorted(rubbish, key=lambda c: -int(c.get("size_in_bytes") or 0)):
        print(f"  {human(int(c.get('size_in_bytes') or 0)):>9}  "
              f"{(c.get('last_accessed_at') or '')[:19]}  {c['key']}")
    if kept:
        print(f"  (keeping {kept} entries prefixed `{KEEP}`)")

    deleted = 0
    if not DRY:
        for c in rubbish:
            if gh(f"/repos/{REPO}/actions/caches/{c['id']}",
                  method="DELETE") is not None:
                deleted += 1
            else:
                print(f"::warning::entry `{c['key']}` couldn't be deleted")
        after_b, after_n = usage()
        print(f"\nDeleted: {deleted} of {len(rubbish)}. "
              f"GitHub cache after: {after_n} entries, {human(after_b)}")

    if SUMMARY:
        with open(SUMMARY, "a") as f:
            f.write("### GitHub cache\n\n")
            f.write("Dry run, nothing was deleted.\n\n" if DRY else "")
            f.write("| what | value |\n|---|--:|\n")
            f.write(f"| entries before | {before_n} |\n")
            f.write(f"| size before | {human(before_b)} (cap 10 GB) |\n")
            f.write(f"| {'to delete' if DRY else 'deleted'} | "
                    f"{len(rubbish) if DRY else deleted} |\n")
            f.write(f"| {'would free' if DRY else 'freed'} | "
                    f"{human(size)} |\n")
            if rubbish:
                f.write("\n<details><summary>Entries</summary>\n\n")
                for c in sorted(rubbish,
                                key=lambda c: -int(c.get("size_in_bytes") or 0)):
                    f.write(f"- `{c['key']}` – "
                            f"{human(int(c.get('size_in_bytes') or 0))}\n")
                f.write("\n</details>\n")
            f.write("\nBuilds take their cache from Google Drive "
                    "(`workers/drive/cache.py`), so nobody looks for these "
                    "entries any more.\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
