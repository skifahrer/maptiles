# Lint and tests: setup plan

Measured on 2026-10-10 against `master` at `f57d59a`.

## Where it stands

| what | today |
|---|---|
| `Check · workflow lint` | actionlint 1.7.7, `bash -n` on every `run:` block, 54 checks in `workers/lint/` (42 `.py`, 12 `.mjs`) and 11 more written inline in the yml. All pass locally, about 16 s in total |
| `Check · catalog schema` | `maps.json` and `maps-test.json` against the schema in skifahrer/schemas |
| Python linter | none. 119 files in `workers/` |
| shellcheck | only on `run:` blocks, through actionlint. The 49 `workers/*/*.sh` files are never checked |
| JS linter | none. 46 files (`poc/web/*.js`, `workers/*/*.mjs`) |
| unit tests | none. `workers/lint/` checks the repo's shape, not what a function returns |
| local run | no entry point. CLAUDE.md lists the globs to run by hand |

What breaks because of it:

- **The first failure hides the rest.** No step in the lint job has
  `if: always()`, so one red check skips every check after it. One push can
  fix one failure and turn the next one red.
- **The 11 inline checks only run in CI.** They are Python heredocs inside
  the yml, so the glob list in CLAUDE.md misses them.
- **Bugs that a plain linter catches get through.** For example,
  `poc/web/devmode.js:4856` uses `DEFAULT_ICON_SOURCE` without importing it.
  Deleting the selected custom icon set throws a `ReferenceError`.
- **A 5 MB `actionlint` binary is checked in at the repo root.** CI ignores
  it and downloads its own pinned 1.7.7.
- **`master`'s last result can be days old.** Bot pushes to `maps.json`
  start no workflow, as CLAUDE.md already says.

## How many findings each linter starts with

| tool | rules | findings | |
|---|---|---|---|
| ruff 0.15 | default (`E4 E7 E9 F`) | 29 in 15 files, 8 fixable automatically | adopt |
| ruff | `+B` (bugbear) | 17 × B023 (12 in `deploy/region-mask.py`), 24 × B905, 8 × B904 | review each one first, then adopt |
| ruff | `E501` line length | 366 | skip |
| ruff format | – | 119 of 119 files | skip |
| shellcheck 0.11 | actionlint's exclude list | 4 | adopt |
| shellcheck | no excludes | 41, of which 21 are SC1111 (typographic quotes in strings) | skip |
| eslint 10 | `recommended` + browser/node globals | 1 real `no-undef` (above), 6 unused variables | adopt |

The policy: fix every finding when a linter is introduced. No baseline file,
so "green" means zero findings. Skip formatters: rewriting every file would
conflict with every open branch.

## Plan

One PR per step. Each step leaves CI green.

### 1. One runner, every check reported

- Add `workers/lint/run.sh [checks|code|tests|all]`. It runs every check,
  even after one fails, wraps each in `::group::`, and exits non-zero if
  any check failed. CI and local runs call the same script.
- Move the 11 inline heredocs into `workers/lint/*.py`. This also shortens
  the 634-line workflow.
- The lint job becomes: actionlint, then `run.sh checks`.
- Delete the checked-in `actionlint`. `run.sh` uses the one on `PATH`, or
  downloads the pinned version the way CI does.
- Point CLAUDE.md at `run.sh` instead of the globs.

### 2. Python: ruff

- Add a root `ruff.toml` with the default rules and no line length. Keep
  the existing `# noqa: E402` comments after `sys.path.insert`.
- Fix the 29 findings.
- Follow-up: turn on `B` once every B023 has been read. Those in
  `region-mask.py` look like closures called inside the loop, which would
  make them false alarms.

### 3. Shell: shellcheck on `workers/`

- `run.sh code` runs `shellcheck workers/*/*.sh`. `SHELLCHECK_OPTS` is set
  once in `run.sh`, and actionlint's shellcheck reads the same variable, so
  the two can't drift apart.
- Fix the 4 findings:
  - `lib/languages.sh` has no shebang
  - `lib/name-languages.sh` needs `# shellcheck source=`
  - unquoted variable at `dem/check.sh:116`
  - `deploy/publish-results.sh:38` (SC2016): check whether the single quotes
    are meant
- shellcheck is already installed on `ubuntu-latest`. Locally, use
  `pip install shellcheck-py` or brew.

### 4. JS: eslint

- Add a root `package.json` (devDependencies only: `eslint`, `@eslint/js`,
  `globals`) and its lockfile. This is the repo's first npm manifest; the
  workers still use only `node:` built-ins.
- Add `eslint.config.mjs`: browser globals for `poc/web/`, node globals for
  `workers/`.
- Fix the findings, including the `DEFAULT_ICON_SOURCE` import.

### 5. Unit tests

- Python: pytest, with tests in `tests/<job>/test_*.py`, mirroring
  `workers/<job>/`. A `conftest.py` helper loads files with a hyphen in
  their name through `importlib`, the way 10 lint scripts already do.
- JS: `node --test` with `tests/web/*.test.mjs`. No new dependency: the
  viewer modules already import into node (`style.mjs` does it).
- The split: a check in `workers/lint/` guards the repo's shape (files,
  workflows, references). A test pins a function's output for a chosen
  input.
- First targets (pure logic, wrong output ships silently):

| module | what to pin |
|---|---|
| `deploy/catalog-merge.py` `merge()` | three-way merge of `maps.json` when two runs write at once |
| `lib/cell.py` | metres per pixel, `terrain_zoom_for`, `frac_bits`, `resampling` |
| `routing/format.py`, `routing/tags.py` | `RTIL` write → read round trip, tag dictionary; the app reads this format |
| `poc/web/layer-style.js` | `valueAtZoom`, `snapshotStyle` → `pasteStyle` |
| `poc/web/themes.js` | `normalizeOverrides` on old and broken override files |

- Later, the two lint scripts that already run code against a fake
  (`drive-shortcuts.py`, `overrides.mjs`) can move to `tests/`.

### 6. CI

- `lint-workflows.yml` keeps its name, because CLAUDE.md names it as the
  merge gate. Its jobs:
  - `actionlint` (exists)
  - `code`: ruff, shellcheck, eslint
  - `tests`: pytest, `node --test`

  The three run in parallel.
- Add `tests/**`, `ruff.toml`, `eslint.config.mjs` and `package.json` to
  `paths`.
- Add a nightly `schedule:`, so `master`'s last result is never older than
  a day.
- Pin every tool version: ruff, eslint, pytest and shellcheck, alongside
  actionlint 1.7.7.

### 7. Cloud sessions

- Add a SessionStart hook in `.claude/settings.json` that installs ruff,
  shellcheck, pytest and the npm devDependencies. Then `run.sh all` works
  in a web session the same way it does on a laptop.

## Out of scope

- Formatters (`ruff format`, prettier).
- Line length.
- Running workflows end to end. They need Drive tokens and hours of runner
  time, and the checks in `workers/lint/` already guard their shape.
- The 800-line limit for `poc/web/` (`devmode.js` and `themes.js` are over
  5 000 lines each). That is a separate decision.
