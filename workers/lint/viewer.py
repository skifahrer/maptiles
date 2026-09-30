#!/usr/bin/env python3
"""The viewer must deploy to Pages whole – every file it asks for.

On a 404 the browser drops the whole module graph, so not even `app.js` runs and
the page stays blank while the build is green.

  1. every relative import in the graph from `index.html` must exist;
  2. `site.sh` must copy the whole folder, not a list of files.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# `workers/lint/` → the repository root
_ROOT = os.path.dirname(os.path.dirname(_HERE))
WEB = os.path.join(_ROOT, "poc", "web")
SITE_SH = os.path.join(_ROOT, "workers", "deploy", "site.sh")

# `from "./x.js"`, `import "./x.js"`, `import("./x.js")` and `src="./x.js"`
IMPORT = re.compile(r'(?:from|import)\s*\(?\s*["\']\./([A-Za-z0-9._-]+\.js)["\']')
SRC = re.compile(r'src="\.?/?([A-Za-z0-9._-]+\.js)"')


def graph():
    """Files the viewer really needs – from `index.html` through imports."""
    seen, queue, errors = set(), ["index.html"], []
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join(WEB, name)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        for m in IMPORT.findall(text) + (SRC.findall(text) if name.endswith(".html") else []):
            queue.append(m)
    return seen, errors


def main():
    bad = []
    needed, _ = graph()

    # 1) does everything the viewer asks for exist?
    for name in sorted(needed):
        if not os.path.exists(os.path.join(WEB, name)):
            bad.append(
                f"::error file=poc/web::the viewer imports `{name}`, but it isn't "
                f"in `poc/web/`. On a 404 the browser drops the whole module "
                f"graph – not even `app.js` runs and the page stays blank."
            )

    # 2) does `site.sh` copy the whole folder, or keep a list again?
    try:
        sh = open(SITE_SH, encoding="utf-8").read()
    except OSError as exc:
        bad.append(f"::error file=workers/deploy/site.sh::can't be read: {exc}")
        sh = ""

    cp = [r for r in sh.splitlines() if r.strip().startswith("cp ") and "poc/web" in r]
    if not cp:
        bad.append(
            "::error file=workers/deploy/site.sh::no `cp` from `poc/web/` to "
            "`_site` found – without it Pages has no viewer at all."
        )
    line = " ".join(cp)
    # a per-file list drifts; a glob (`*.js`) can't
    if cp and "poc/web/*.js" not in line:
        bad.append(
            "::error file=workers/deploy/site.sh::the `cp` from `poc/web/` lists "
            "single `.js` files instead of `poc/web/*.js`. A file added to the "
            "folder but not the list breaks the map without a word."
        )

    # 3) and does that really ship everything the graph wants?
    if cp and "poc/web/*.js" in line:
        for name in sorted(needed):
            if name.endswith(".js"):
                continue
            if name not in line and not name.endswith(".html"):
                bad.append(
                    f"::error file=workers/deploy/site.sh::`{name}` is in the "
                    f"viewer's graph, but the `cp` doesn't get it into `_site`."
                )

    for r in bad:
        print(r)
    print(f"viewer on Pages: {len(bad)} errors "
          f"({len(needed)} files in the graph: {', '.join(sorted(needed))})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
