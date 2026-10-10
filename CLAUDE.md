# CLAUDE.md

Vector map pipeline for Slovakia (OSM ─► PMTiles). `workers/` = pipeline steps
(folder = job, file = step), `.github/workflows/` = CI, `poc/web/` = web viewer,
`docs/` = proposals and analyses.

Details: `workers/README.md`.

## Pull requests: merge only on green

**Don't merge a PR until its checks are green and the pipeline really ran.**

- `Check · workflow lint`, `Check · catalog schema` and `Check · tests` are
  green on the PR's HEAD, not on an older commit of the branch.
- No conflict with `master`.
- The check really ran: a run with no job verified nothing, and green from
  another commit says nothing about this one.

The checks run only on changes to their paths, and a bot's push to `maps.json`
starts no workflow, so the last result on `master` can be days old. When it
matters, run the workflow by hand (`workflow_dispatch`) or locally:
`workers/lint/*.py`, `workers/lint/*.mjs`, `workers/deploy/catalog-schema.py`,
`python3 -m unittest discover -s workers/tests`, `node --test workers/tests/*.test.mjs`.

Fix a red check, or say on the PR why it isn't this PR's. Never switch a test
or lint off to get green.

## Tests: every fix brings its test

A `fix:` commit adds the test in `workers/tests/` that fails without the fix.

## Comments: as few words as possible

**This is a hard rule. A comment is a few words, not a paragraph.**

- One line. If that isn't enough, you usually need a better name, not a comment.
- Write **why**, never **what** – the code shows that.
- No essays, decision history, measured figures, run examples, lists of
  alternatives or "WHY NOT …" sections. Those belong in `docs/` or the commit
  message, not above a function.
- Docstring: one sentence. No `Usage:`, `Args:`, `Note:` sections.
- Don't comment the obvious; delete commented-out code.
- English, lower case, no decorative separators (`# ---`, `# ===`).
- Identifiers, JSON keys, log messages and workflow names are English too.

Good:

```python
# GDAL rounds down, hence +1
zoom = floor(z) + 1
```

Bad:

```python
# ROUNDING. GDAL rounds down when converting resolution, which means
# that at the 1.4 m/px boundary we get one level less than expected.
# We also tried solving it through ...
```

Exception: directives (`# noqa`, `# shellcheck disable=…`), shebangs, licence
headers and `yaml`/`workflow` keys where the comment carries a value.
