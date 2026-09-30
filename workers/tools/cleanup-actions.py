#!/usr/bin/env python3
"""
GitHub cleanup: runs that record nothing – and every release and artifact,
since nothing is published to GitHub any more.

WHY IT CAN'T BE DONE OTHERWISE: runs and branches aren't files in the repository,
so no pull request or local token can delete them (`Resource not accessible by
integration`, HTTP 403). Inside a run `GITHUB_TOKEN` can, given `actions: write`
(runs) and `contents: write` (branches). Hence a manually started workflow.

WHAT COUNTS AS RUBBISH:

1. **Runs of retired workflows.** When a workflow file is deleted its runs stay,
   and so does its entry in the Actions sidebar – for good. It vanishes only at
   zero runs.

2. **Runs of rejected files.** When a workflow file is invalid (e.g. over the
   128 KiB cap) GitHub doesn't report an error – a push makes a run WITHOUT JOBS,
   named by the file path. They're recognised by exactly that name:
   `.github/workflows/something.yml` instead of the `name:` inside.

3. (optional) **`claude/*` branches wholly contained in the main branch** – merged,
   with not one commit of their own.

4. **EVERY RELEASE, ITS TAG AND EVERY ARTIFACT.** Elevation models, rocks and
   shading used to go to releases and intermediate results to artifacts; both
   moved to Google Drive (`workers/drive/store.py`). The old ones are gigabytes
   nobody reads, easily mistaken for software releases. Nothing is lost.

Runs as `workers/tools/cleanup-actions.py`; the environment says what to do:
    MODE=runs | runs_and_branches | releases_and_artifacts | everything   (default: runs)
    DRY_RUN=true | false                                                  (default: false)
Expects `gh` and GITHUB_REPOSITORY / GITHUB_RUN_ID from the runner.
"""
import json
import os
import subprocess
import sys

# former mode names, so an old dispatch still means the same
MODE_ALIAS = {"behy": "runs", "behy_a_vetvy": "runs_and_branches",
              "releasy_a_artefakty": "releases_and_artifacts", "vsetko": "everything"}

REPO = os.environ["GITHUB_REPOSITORY"]
MODE = os.environ.get("MODE", "runs")
MODE = MODE_ALIAS.get(MODE, MODE)
DRY = os.environ.get("DRY_RUN", "false").lower() == "true"
SELF_RUN = os.environ.get("GITHUB_RUN_ID", "")
SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")


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


def pages(path, key, cap=20):
    """A list page by page; `cap` guards against looping forever."""
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


def clean_releases():
    """Every release with its assets and tag. Returns (count, bytes).

    Deleting a release takes its assets, but leaves its tag – and a lone
    `dem-sonny` tag on a public repository looks just like a release.
    """
    rels = pages(f"/repos/{REPO}/releases", None)
    size = sum(a.get("size", 0) for r in rels for a in (r.get("assets") or []))
    print(f"\nReleases: {len(rels)}, holding {human(size)} of assets")
    for r in rels:
        n = len(r.get("assets") or [])
        vol = human(sum(a.get("size", 0) for a in (r.get("assets") or [])))
        print(f"  {r['tag_name']:<16} {n:>4} assets  {vol:>10}  {r['name']}")
    if DRY:
        return len(rels), size
    deleted = 0
    for r in rels:
        if gh(f"/repos/{REPO}/releases/{r['id']}", method="DELETE") is None:
            print(f"::warning::release {r['tag_name']} couldn't be deleted")
            continue
        deleted += 1
        # a draft release has no tag, so a 404 is fine
        gh(f"/repos/{REPO}/git/refs/tags/{r['tag_name']}", method="DELETE")
        print(f"  deleted: release and tag {r['tag_name']}")
    print(f"Releases deleted: {deleted} of {len(rels)}")
    return deleted, size


def clean_artifacts():
    """Every artifact of every run, retention or not. Returns (count, bytes)."""
    arts = pages(f"/repos/{REPO}/actions/artifacts", "artifacts")
    # this run's own `site-*` are being passed between jobs right now
    mine = [a for a in arts
            if str((a.get("workflow_run") or {}).get("id", "")) == SELF_RUN]
    arts = [a for a in arts if a not in mine]
    size = sum(a.get("size_in_bytes", 0) for a in arts)
    print(f"\nArtifacts: {len(arts)}, {human(size)}"
          + (f" (+{len(mine)} of this run kept)" if mine else ""))
    by_name = {}
    for a in arts:
        m = by_name.setdefault(a["name"], [0, 0])
        m[0] += 1
        m[1] += a.get("size_in_bytes", 0)
    for name, (n, vol) in sorted(by_name.items()):
        print(f"  {name:<52} {n:>4}×  {human(vol):>10}")
    if DRY:
        return len(arts), size
    deleted = 0
    for a in arts:
        if gh(f"/repos/{REPO}/actions/artifacts/{a['id']}",
              method="DELETE") is not None:
            deleted += 1
    print(f"Artifacts deleted: {deleted} of {len(arts)}")
    return deleted, size


def human(n):
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# spelled out, so a typo in `MODE` isn't a green run that cleaned nothing
DO = {
    "runs": ("runs",),
    "runs_and_branches": ("runs", "branches"),
    "releases_and_artifacts": ("releases", "artifacts"),
    "everything": ("runs", "branches", "releases", "artifacts"),
}


def main():
    if MODE not in DO:
        print(f"::error::Unknown mode “{MODE}”. Known: {', '.join(DO)}.")
        return 1
    doing = DO[MODE]
    print(f"Repository: {REPO}   mode: {MODE} ({', '.join(doing)})   "
          f"{'DRY RUN (nothing deleted)' if DRY else 'for real'}")

    retired, rubbish, deleted, branches = {}, [], 0, []
    rel_n = rel_b = art_n = art_b = 0

    if "releases" in doing:
        rel_n, rel_b = clean_releases()
    if "artifacts" in doing:
        art_n, art_b = clean_artifacts()
    if "runs" not in doing:
        return _summary(retired, rubbish, deleted, branches, rel_n, rel_b, art_n, art_b)

    workflows = pages(f"/repos/{REPO}/actions/workflows", "workflows")
    alive, retired = {}, {}
    for w in workflows:
        # `dynamic/pages/...` is GitHub's own Pages workflow, with no file here
        if not w["path"].startswith(".github/workflows/"):
            continue
        (alive if os.path.exists(w["path"]) else retired)[w["id"]] = w["path"]
    print(f"\nWorkflows: {len(alive)} with a file, {len(retired)} retired")
    for path in sorted(retired.values()):
        print(f"  retired: {path}")

    rubbish = []   # (id, reason, label)
    for wid, path in retired.items():
        for r in pages(f"/repos/{REPO}/actions/workflows/{wid}/runs", "workflow_runs"):
            rubbish.append((r["id"], "retired workflow", f"{path} #{r['run_number']}"))

    for wid, path in alive.items():
        for r in pages(f"/repos/{REPO}/actions/workflows/{wid}/runs", "workflow_runs"):
            # named by its path → GitHub couldn't read the file: a run without jobs
            if r["name"].startswith(".github/workflows/"):
                rubbish.append((r["id"], "rejected file", f"{path} #{r['run_number']}"))

    # a running run can't be deleted, and this one would cut itself off
    rubbish = [s for s in rubbish if str(s[0]) != SELF_RUN]

    print(f"\nRuns to delete: {len(rubbish)}")
    for _, reason, label in sorted(rubbish, key=lambda s: s[2]):
        print(f"  [{reason}] {label}")

    deleted = 0
    if not DRY:
        for rid, _, label in rubbish:
            if gh(f"/repos/{REPO}/actions/runs/{rid}", method="DELETE") is not None:
                deleted += 1
            else:
                print(f"::warning::run {label} couldn't be deleted")
        print(f"\nRuns deleted: {deleted} of {len(rubbish)}")

    if "branches" in doing:
        base = (gh(f"/repos/{REPO}") or {}).get("default_branch", "master")
        for b in pages(f"/repos/{REPO}/branches", None):
            name = b["name"]
            if name == base or not name.startswith("claude/"):
                continue
            cmp_ = gh(f"/repos/{REPO}/compare/{base}...{name}")
            if not cmp_:
                continue
            # `behind`/`identical` = merged or empty; `ahead`/`diverged` stay
            if cmp_.get("status") in ("behind", "identical"):
                branches.append((name, cmp_["status"]))
            else:
                print(f"  keeping branch {name} ({cmp_.get('status')}, "
                      f"own commits: {cmp_.get('ahead_by')})")

        print(f"\nBranches to delete: {len(branches)}")
        for name, st in branches:
            print(f"  {name} ({st})")
        if not DRY:
            for name, _ in branches:
                gh(f"/repos/{REPO}/git/refs/heads/{name}", method="DELETE")

    return _summary(retired, rubbish, deleted, branches, rel_n, rel_b, art_n, art_b)


def _summary(retired, rubbish, deleted, branches, rel_n, rel_b, art_n, art_b):
    """The `GITHUB_STEP_SUMMARY` table; releases_and_artifacts returns early, so it's apart."""
    if not SUMMARY:
        return 0
    doing = DO[MODE]
    with open(SUMMARY, "a") as f:
        f.write("## GitHub cleanup\n\n")
        f.write("Dry run, nothing was deleted.\n\n" if DRY else "")
        f.write("| what | count |\n|---|--:|\n")
        if "runs" in doing:
            f.write(f"| retired workflows (with runs left) | {len(retired)} |\n")
            f.write(f"| runs to delete | {len(rubbish)} |\n")
            if not DRY:
                f.write(f"| **runs actually deleted** | **{deleted}** |\n")
        if "branches" in doing:
            f.write(f"| merged `claude/*` branches | {len(branches)} |\n")
        if "releases" in doing:
            f.write(f"| {'releases to delete' if DRY else 'releases deleted'} "
                    f"(with tags) | {rel_n} |\n")
            f.write(f"| their assets | {human(rel_b)} |\n")
        if "artifacts" in doing:
            f.write(f"| {'artifacts to delete' if DRY else 'artifacts deleted'} "
                    f"| {art_n} |\n")
            f.write(f"| their size | {human(art_b)} |\n")
        if rubbish:
            f.write("\n<details><summary>Runs</summary>\n\n")
            for _, reason, label in sorted(rubbish, key=lambda s: s[2]):
                f.write(f"- `{label}` – {reason}\n")
            f.write("\n</details>\n")
        if "runs" in doing:
            f.write("\nA workflow leaves the Actions sidebar only with no runs "
                    "at all – so all of them are deleted.\n")
        if "releases" in doing:
            f.write("\nNothing is published to releases or artifacts any more – "
                    "everything goes to the Google Drive store "
                    "(`workers/drive/store.py`). Nothing was lost.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
