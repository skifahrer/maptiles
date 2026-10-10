# Test plan

What to add so a broken pipeline step fails in a one-minute check, not two
hours into a region build. Measured on 2026-10-10 against `master` (`1dae217`).

## Where we stand

`workers/lint/` holds 52 checks, run by `Check · workflow lint`. All of them
pass, and together they take about 20 s. There are three kinds:

- **Behaviour tests** (about 20) load worker code and run it on small,
  hand-built input: `rail-sections.py`, `routing-tiles.py`, `routing.py`,
  `catalog.py` (merge, write, stable id), `smoothing.py`,
  `drive-shortcuts.py`, `credits.py`, `packaging.py`, `regenerate.py`,
  `rebuild.py`, `world.py`, and the style and sprite checks in `*.mjs`.
- **Source scans** (about 8) search the code with a regex for a guard instead
  of running it: `terrain-nodata.py`, `dem-empty.py`, `rocks-empty.py`,
  `border-overlap.py`, `pipes.py`, and parts of `terrain.py` and
  `dem-resampling.py`. They pass while the text is there, whether or not it
  works.
- **Wiring checks** (the rest) cover workflows, inputs, env, paths, job
  outputs, and schema against filter. These are fine as they are.

What runs before a real build:

- **Python**: running every lint under a tracer shows that functions from 14
  of the 77 worker modules run. Another 7 are only imported
  (`deploy/names.py`, `deploy/pack.py`, `deploy/publish-map.py`,
  `plan/options.py`, `drive/api.py`, `drive/auth.py`, `drive/serve.py`). The
  remaining 56 modules first run on a GitHub runner, against a real region.
- **Shell**: `workers/` has 49 scripts. Nothing runs `bash -n` or shellcheck
  on them, because actionlint only sees `run:` blocks.
- **Web**: the style checks cover `themes.js`, `patterns.js`, `map-types.js`,
  shields and marks well. Nothing runs `app.js`, `devmode.js` (5.4k lines),
  `dev-icons.js`, `dev-patterns.js`, `languages.js`, `workers/styles/build.mjs`,
  `workers/assets/sprite.mjs`, `lib/sdf.mjs`, `lib/draw.mjs` or
  `rail/signs.mjs`.
- **Style validity**: nothing validates the built styles against the MapLibre
  style spec. An invalid expression only shows as a console error in the
  browser.
- **Packages**: no check builds a package from OSM data. Every package build
  is first tried on a real region.

`Check · workflow lint` is a single job, so the first red step skips every
step after it, and one failure hides the others.

### Bugs a test would have caught earlier

| Fix | What broke | Test that catches it |
|---|---|---|
| 1180 | boundaries and water ran 300 km past the region | §4: no feature outside the region outline + margin |
| 1160 | hillshading and rocks ran past the county border | §3: `lib/region-mask.py` `tile_touches`, `pixel_mask` |
| 1334 | world, wiki and routing packages landed in a `cely` folder | §2: `deploy/names.py` `drive_path` |
| 814 ×2 | edges met a node at different heights; the profile was laid out from a flat-plane distance instead of the edge length | §3: `routing/heights.py` `_to_nodes`, `fill_with_profiles` |
| 1718 | Wikipedia texts kept image captions and category lines | §3: `wiki/articles.py` `to_text` |
| 1681 | the state relay never re-ran a region whose jobs never started | §5: `state/relay-core.sh` with a stub `gh` |
| 843, search | rail PBF writing broke on pyosmium 3; `w.nd_ids()` didn't exist | §3: osmium handlers over a fixture, with the same `osmium` the build installs |

## 1. Harness

Keep it small, with no dependencies, and close to how the lints already work.

- **Folder**: `workers/tests/`, flat, since `layout.py` allows only one level
  of depth. Fixtures are data files in `workers/tests/fixtures/` (`layout.py`
  only checks `.py`/`.sh`/`.mjs` depth). Add `tests` to `KNOWN` in
  `workers/lint/layout.py` and to `workers/README.md`.
- **Python**: use the stdlib `unittest` (`python3 -m unittest discover -s
  workers/tests`). The lint job installs nothing today, and pytest isn't worth
  being the first install. One helper, `workers/tests/load.py`, loads a worker
  by path, because dashed file names need `importlib`. It also puts the job
  folder on `sys.path`, because `plan/seam.py` imports `boundary`.
- **JS**: `node --test 'workers/tests/*.test.mjs'`, built into Node 22.
- **Heavy dependencies** (numpy, osmium, shapely, pmtiles,
  mapbox-vector-tile, mwparserfromhell, Pillow): a test that needs one uses
  `skipUnless` the module is installed, so it still runs wherever that module
  is. In CI, the deps job sets `TESTS_REQUIRE_ALL=1`, which turns a skip into
  a failure. A silent skip verifies nothing.
- **Workflow**: `Check · tests` (`tests.yml`), triggered on `workers/**`,
  `poc/web/**` and `workflow_dispatch`:
  - `unit`: stdlib only, runs in seconds;
  - `unit-deps`: installs exactly what the build scripts install
    (`'osmium>=3.6,<5'`, `numpy`, `pillow`, `pmtiles`, `mapbox-vector-tile`,
    `shapely`, `mwparserfromhell`), then runs everything with
    `TESTS_REQUIRE_ALL=1`;
  - add it to the "merge only on green" list in `CLAUDE.md`.
- **Coverage**: `unit-deps` runs under `coverage` and writes the per-file
  table to the job summary. JS uses `--experimental-test-coverage`. Report the
  numbers but set no percentage gate: most lines are glue that only a real
  run reaches, and a global target pushes tests toward trivial lines. The rule
  below matters more.
- **Rule** (add to `CLAUDE.md`): every `fix:` commit adds the test that fails
  without the fix. The repo already does this informally (`rocks-empty.py`,
  the merge trial in `catalog.py`).

Cheap checks that find nothing today, so they go in green:

- `bash -n` on every `workers/**/*.sh`, `python3 -m py_compile` on every
  `workers/**/*.py`, and `node --check` on every `.mjs` and `poc/web/*.js`.
- shellcheck at `-S warning` on `workers/**/*.sh`. It isn't installed here, so
  its findings are unknown. Fix what it reports, or exclude a code with a
  reason, as the actionlint step already does.
- `if: ${{ !cancelled() }}` on every step of `Check · workflow lint`, so one
  run shows every failure.

## 2. Unit tests, stdlib only (job `unit`)

These cover pure functions, where a bug is cheap to find now and expensive in
a two-hour build. The table is ordered by value.

| Module | Cases |
|---|---|
| `deploy/names.py` | `safe`: diacritics fold, `/` and spaces become `_`, empty gives `unnamed`. `strip_test`: `presovsky_test4` becomes `presovsky`, stacked `_test4_test2` is stripped, `_tester` is untouched. `country_from_url`. `drive_path`: a custom PBF URL; a country (`admin_level` 2) gets no region folder; `cely`/`whole` adds no folder (1334); an area is appended. `file_name` stays the same across runs. |
| `deploy/region-mask.py` | `clip_ring`: a ring inside is unchanged; outside gives `[]`; crossing one and two edges; closed vs open ring; fewer than 3 points gives `[]`. `mask_geojson`: the world ring has the region as a hole, so everything outside is covered, and an enclave (`holes`) is masked too. `ring_area_km2` of a known square. |
| `plan/region-poly.py` | `parse_poly` with two rings and a `!` hole; `rings_to_poly_text` → `parse_poly` round trip; `ring_bbox`. |
| `plan/seam.py` | Two adjacent squares: `measure_seam` reports no overlap; shifted 300 m it reports an overlap; moved apart it reports a gap. `_inside` with a hole; `dist_to_boundary`. |
| `plan/area.py`, `plan/boundary.py` | `bbox_km2`, `pad_bbox`, `test_square`; `rings_from_geojson` ↔ `geojson_from_rings` round trip; `pick` by name and `admin_level`. |
| `plan/pbf-areas.py`, `wiki/collect.py` (OPL) | `unesc`, `opl_fields`, `tags`. `opl_unescape`: `%20%` becomes a space, and `%25%20` becomes a literal `%20`, so a percent-encoded URL survives. |
| `wiki/collect.py` | `wiki_value`: URL form (language from the host, `_` becomes a space, percent-decoded), `sk:Title`, key `wikipedia:de`, `#section` dropped. `links`: a bare title is tried in every wanted language; a `Q123` id is picked up; a malformed id isn't. |
| `wiki/articles.py` | `is_not_text` for `Súbor:`, `Kategória:`, `File:` and a normal link. `resolve` through `normalized`, then `redirects`. `fetch_texts` with a fake `Api` (no network): an unchanged `revid` is taken from the cache, a changed one is downloaded, and an empty cache skips the freshness question. |
| `trails/tags.py` | `parse_hex` (`#a3b`, `a3b2c1`, junk). `resolve_colour`: `osmc:symbol` wins over `colour`; aliases; `#e01b24` snaps to red; `#ff69b4` stays hex. `split_symbol`. `resolve_mark`: the foreground one field later (`red:white::red_bar`); a bicycle on yellow gets black; a walking route without a colour gets no mark; every result is in `MARK_FACES`. `resolve_tier`: `iwn`/`nwn`/`rwn`/`lwn`, and the distance fallback at 150 and 50 km. |
| `lib/contour-blocks.py` | `plan`: blocks cover the raster exactly, with no gap or overlap. `check_metric` catches degrees passed as metres. `_touches`. |
| `dem/tiles.py`, `dem/target.py`, `dem/coverage.py`, `dem/trust.py` | `tile_name` across hemispheres; `plan_tiles` covers the bounds with no gap or duplicate; `tiles_for`, `degrees_box`, `parse_bbox`; `target` against a fixture `dem-sources.json`; `degree_of`, `covers_own_degree`, `covered_pct`, `empty_stamp`; `suspects`. |
| `lib/watch.py` | `hms`, `gb`, `percent`. `run_watched` on a short `sleep` and on `false`: the exit code passes through, `max_s` stops the command, and GDAL progress lines are relayed. |
| `lib/cell.py` | `terrain_zoom_for` at and beyond `lo`/`hi`. The lints already run the other pure functions. |
| `state/queue.py`, `plan/summary-inputs.py` | `regions_of`, `countries`; `defaults`, `env_table`. |
| `world/sources.py` | `prop`, `names_by_language`, `human`, `took`; `prepare_countries` and `prepare_lakes` on a three-feature GeoJSON. |
| `tools/cleanup-cache.py`, `tools/cleanup-actions.py` | What gets deleted, from a fake `gh` listing. Cache: keys with the `KEEP` prefix survive, and `DRY_RUN=true` deletes nothing. Actions: only runs of retired workflows, jobless runs named by a file path, `claude/*` branches with no commit of their own, and (by `MODE`) releases and artifacts; a run of a live workflow survives. These scripts delete things, so they need tests most. Both read `GITHUB_REPOSITORY` at import, so set it in the test or move the read into `main()`. |
| `drive/api.py`, `drive/auth.py`, `drive/store.py`, `drive/cache.py` | Over a fake HTTP layer: `request_json` retries up to `tries` and then gives up; a 401 refreshes the token once, not once per thread; `api_hint` turns a refusal into the right advice; store name to folder; cache hit and miss. Today, a Drive hiccup only shows up as a red region build. |

JS (`node --test`):

- **Built styles against the MapLibre spec** (biggest gap on the web side):
  for every map type × theme, run `buildStyle` and check it with
  `validateStyleMin` from `@maplibre/maplibre-gl-style-spec`, with a pinned
  version installed by `npm` in the job. This catches rules like the one
  noted in `themes.js`: `["zoom"]` may only be the direct input of the
  top-level `interpolate`/`step`.
- `workers/styles/build.mjs` against a fixture sprite and manifest: it writes
  every `<region>-<type>-<theme>.json`, the default type also as
  `<region>-<theme>.json`, and every file passes the validator.
- `lib/sdf.mjs`, `lib/draw.mjs`, `assets/sprite.mjs`: the SDF of a filled
  square is negative inside and positive outside; the sprite index matches the
  packed image (no overlap, everything within bounds).
- `poc/web/languages.js`, and the helpers of `dev-icons.js` /
  `dev-patterns.js` that don't touch `document`.

## 3. Unit tests with dependencies (job `unit-deps`)

| Module | Needs | Cases |
|---|---|---|
| `routing/heights.py` | numpy | `bilinear` at corners and the centre. `fill_from_neighbours`: a chain fills; an island is counted as missing. `_to_nodes`: the profile ends equal the node heights, and the difference spreads linearly (814). `fill_with_profiles` with `sample` stubbed: every edge that meets a node starts or ends at the same height (814). |
| `terrain/height.py` | numpy | `fill_nodata`: a corner pixel with no neighbour in its row; linear fill between two sides, with no seam; all missing leaves the grid unchanged. `edge_height` takes the rim, not the interior. `flatten_outside`. |
| `terrain/tiles.py` | numpy, Pillow | `terrarium` encode → decode round trip within the chosen bits; `tile_range` against known z/x/y; `merc_x`, `merc_y`; `is_flat`; `png_rgb` reads back with Pillow. |
| `lib/region-mask.py` | numpy for `pixel_mask` | `inside` with a hole; `Mask.touches`; `pixel_mask` with `grow`; `tile_touches` is false for a tile just outside the border (1160). |
| `lib/clip-tiles.py` | shapely, mapbox-vector-tile, pmtiles | `tile_bounds`. `clip_tile`: a feature outside is dropped; one across the edge is clipped; a polygon stays a polygon (`_same_kind`). |
| `tiles/drop-layer.py` | pmtiles | Hand-built MVT bytes with three layers: `bez_vrstiev` drops one and leaves the others byte-identical. `varint`, `skip` on multi-byte values. |
| `terrain/pack.py` | pmtiles | `tile_bounds`; `collect` on a temp folder of tiles. |
| `wiki/articles.py` `to_text` | mwparserfromhell | A thumbnail with a caption (1718); a `[[Kategória:…]]` line; nested tables; `<gallery>`; three or more blank lines collapse; a normal link keeps its text. |
| `rail/lines.py` | osmium | `speed` (`80;60` gives 80, `50 mph` gives 80, `none` gives None); `gauge` (`1435;1520` gives 1520); `bearing`; `speed_changes`. `Lines` + `Rewrite` over `fixtures/rail.osm` write a readable PBF (843). |
| `routing/network.py` | osmium | Over `fixtures/roads.osm`: `_direction` for `oneway=yes`, `oneway=-1` and `junction=roundabout`; `_length_cm` against haversine; a `no_left_turn` via a node and an `only_straight_on` via a way resolve to the right edges. |
| `trails/routes.py` | osmium | `way_class`. `ease_corners` eases a sharp turn but leaves a straight line and both ends alone. `orient_ways` on a relation of ways in mixed directions. `lane_order` is stable. |
| `buildings/areas.py` | osmium | `ring_area`; a closed way and a multipolygon with a hole give the right floor area. |
| `contours-rocks/rock-plan.py`, `slope-chunks.py`, `rock-areas.py`, `rocks-shading/*` | numpy, Pillow | Planning first: the chunks cover the raster, and a failed chunk isn't marked done. Raster code later. |

The `.osm` fixtures are hand-written XML with a few dozen nodes each. osmium
reads `.osm` directly.

## 4. Integration: one mini region through every package

This covers what the lints can't see: building a package from OSM to
`.pmtiles`.

- **Fixture**: `workers/tests/fixtures/mini-region.osm`, a few km² inside a
  real region. It has a road with a `ref`, a motorway link, a hiking relation
  with `osmc:symbol`, a river, a lake multipolygon, admin boundaries at levels
  2, 4 and 8, a railway with a switch and a cable car, a settlement with
  buildings, and a peak with `wikipedia`. It also has a road and a lake
  **outside** the region outline.
- **Job** `integration` in `tests.yml`:
  - set up Java with `actions/setup-java`, the same version `planetiler.py`
    checks;
  - `osmium cat` the fixture to `data/region.osm.pbf`;
  - run each `workers/{transport,boundaries,water,rail,history,buildings,trails,features}/build.sh`,
    with `GITHUB_OUTPUT` pointed at a temp file.
- **Assertions**: one script reads every `.pmtiles` with pmtiles and
  mapbox-vector-tile and checks that:
  - the layers are the schema's layers, starting at the schema's zooms;
  - every fixture object is there with its attributes (`class`, `kind`,
    `name`, `name:*`, `ref`);
  - nothing lies outside the region outline + margin (1180);
  - geometry types match what the style draws (`fill` needs polygons).
    `style.mjs` checks this against the schema; this checks it against real
    tiles.
- **Style against data**: run `workers/styles/build.mjs` against the fixture
  packages, and check that every `source-layer` the style uses exists in some
  tile.
- **Routing**: build the routing archive from the fixture and read it back
  with `routing/format.py`. The oneway and the turn restriction must survive.
- **When it runs**: on PRs that touch a package's folder or `workers/lib/**`,
  on `workflow_dispatch`, and weekly, because the build installs Planetiler
  and osmium unpinned and they change under us. Expect a few minutes per run,
  mostly JVM start-up.

Second step, the DEM side: generate a synthetic 200×200 px hill GeoTIFF in the
test (GDAL from apt). Contours must come out at the expected levels, terrain
tiles must decode back to the heights, and a NODATA hole must not produce sea
level.

## 5. Shell logic

Run the scripts from Python `unittest` (no bats), with stub commands first on
`PATH`: a temp folder with a fake `gh`, `curl` or `osmium` that answers what
the test says.

- `state/relay-core.sh`:
  - parsing and handing over the baton
    (`<run id>:<region>|<to go>|<done>|<leg>`);
  - a failed region doesn't stop the chain, but the last leg fails;
  - a cancelled region stops the chain green;
  - a run whose jobs never started is re-run once, and only once (1681);
  - `LEGS_PER_REGION` caps the chain.
- `plan/cache-keys.sh`: the same inputs give the same key, and every input
  that matters changes it.
- `lib/pmtiles-budget.sh`, `plan/layer-done.sh`, `lib/store-area.sh`: their
  decisions over a handful of inputs.
- `deploy/smoke-test.sh` with a stub `curl`: a 206 passes, a 404 fails, and a
  retry that succeeds passes.

## 6. Web viewer in a browser

- **Browser smoke test with Playwright (Chromium)**: serve `poc/web` with a
  manifest that points at the packages from §4. For each map type × theme,
  check that:
  - the map reaches `idle`;
  - there's no `error` event and no console error;
  - there's no `styleimagemissing` for an image that `dev-patterns.js`
    doesn't draw on demand.
- **Devmode**: open it, apply an override, and read the paint property back.
- `deploy/smoke-test.sh` keeps guarding the deployed site.

## 7. Replace source scans with behaviour tests

Once §3 exists, these can run the code instead of searching it:

- `terrain-nodata.py`, through the `terrain/height.py` tests;
- `dem-empty.py`, through `dem/tiles.py` `empty_tile` and `dem/coverage.py`
  `empty_stamp`;
- `rocks-empty.py`, by running the failure path of `rocks.sh` with a stub and
  checking that nothing is saved as done.

Keep each scan until its replacement is green on `master`.

## Order

| Step | What | Rough size |
|---|---|---|
| 1 | §1 harness, syntax checks, `!cancelled()`, the `CLAUDE.md` rule | ½ day |
| 2 | style-spec validation; §2 `names`, `region-mask`, `seam`, `region-poly`, wiki, trails | 1 day |
| 3 | `unit-deps`: heights, terrain, region mask, clip tiles, osmium fixtures | 1–2 days |
| 4 | §5 relay and cache keys | ½ day |
| 5 | §4 mini region, then the DEM side | 2–3 days |
| 6 | the rest of §2 and §3, then §6 and §7 | ongoing |
