# Extract cache – each OSM extract downloaded once a day

Ticket 354. Every job that needs a country extract downloads it from osm.fr itself: a
region cuts itself from its parent (`workers/plan/pbf.sh`, 0.4–1 GB), a mountain range from
its countries (`workers/mountain/pbf.sh`), routing from its areas (`workers/routing/pbf.sh`).
A state build downloads the same parent once per region, 14 times for Czechia. Each
download is another chance for osm.fr to fail. Two extracts of different dates also meet in
one range, as in mountain run 40479492407.

The goal: one download of each extract a day. Every other job that day takes that copy.
While one job downloads, the others wait for it rather than download too.

## 1. Where the copy lives: a GitHub artifact

| | GitHub artifact | Google Drive (`workers/drive/cache.py`) |
|---|---|---|
| Cost | free: the repository is public | free, but counts against the owner's Drive quota |
| Lifetime | `retention-days: 1` removes it itself | stays until `--prune` removes it |
| Speed | inside GitHub's network | 40 MB/s up, as measured; down similar |
| Other runs | API by name, any run in the repository | listing a folder |
| Lock | none built in | none built in |
| New code | a composite action and a lookup script | a lookup and a lock in `cache.py` |

The artifact wins on lifetime and speed. Drive stays for what must outlive a day, such as
finished layers and the cut range PBF.

## 2. Names

- Extract: `extract-<dir>-<slug>-<day>`, e.g. `extract-europe-slovakia-latest-2026-10-27`.
  `/` becomes `-`. `day` is UTC, like every other key here.
- Marker: the same name with `-fetching` appended. It holds the run id and the time the
  download started.

Both are uploaded with `retention-days: 1` and `compression-level: 0`, since a PBF is
already compressed.

## 3. A job that needs an extract

The composite action `.github/actions/extracts` takes the job's extracts, one a line:

1. **Look up** `extract-…-<day>` through
   `GET /repos/{repo}/actions/artifacts?name=…`, newest first, not expired. If it is found,
   download it with `actions/download-artifact` (`run-id`, `github-token`). Done.
2. **Someone else is downloading** if a `-fetching` marker younger than `stale` (30 min)
   exists. Poll every 30 s until the extract appears, then take it as in 1. If the marker
   goes stale first, carry on as below: the job that left it is gone.
3. **Claim it**: upload this run's `-fetching` marker, then list the markers again. The
   oldest marker (created first, then the lowest artifact id) owns the download. If it
   isn't ours, go to 2. Two jobs that start in the same second still agree on one owner.
4. **Download** from osm.fr, with the Geofabrik mirror after it (as `mountain/pbf.sh`
   does now). Check that it starts with a PBF header. Upload it as `extract-…-<day>`.
5. If the download fails, the action warns and the job's script downloads the extract as
   it did before. A cache never fails a build. The marker goes stale for the next job.

All of it is one module, `workers/lib/extracts.mjs`, run through `actions/github-script`
with `@actions/artifact`: the upload token is given only to actions, not to a shell, and
the official upload action takes one artifact a step while a range needs several. A file is
uploaded unzipped (`skipArchive`), so the artifact is named after the file.
`workers/lib/extract-urls.py` lists what a job needs. `workers/lib/extract.sh` hands a
script the file the action left.

## 4. Who uses it

| Script | Today | After |
|---|---|---|
| `workers/plan/pbf.sh` (region, parent cut) | curl from osm.fr | the action fills `data/parent.osm.pbf` before it |
| `workers/plan/pbf.sh` (a whole country) | curl | the action fills `data/region.osm.pbf` |
| `workers/mountain/pbf.sh` | curl per country | the action, once per extract the range names |
| `workers/routing/pbf.sh` | curl per area | the action, once per extract |

A custom URL (`OPT_CUSTOM_PBF_URL`) stays a plain download: it is one user's file, not a
shared extract.

The per-day Drive cache of the *cut* PBF (`pbf-v6-…`, `pbf-mountain-v3-…`) stays. It saves
the cut, not the download.

## 5. Permissions

Downloading another run's artifact needs `actions: read`. Every job that uses the action
gets it, and so does the job calling `wiki.yml`. `workers/lint/extracts.py`, part of
`Check · workflow lint`, requires it.

## 6. Tests

- `workers/tests/extracts.test.mjs`: picking the newest unexpired artifact, the
  oldest marker as owner, ties broken by id, a stale marker taken over, and two jobs in a
  row where the second takes the first one's upload. Against an artifact store in memory,
  so no network is needed.
- `workers/tests/test_extract_urls.py`: what a region, a country and a routing area need.
- `test_the_extract_of_the_day_is_taken_not_downloaded`: `mountain/pbf.sh` takes the
  file the action left.
- The first build after the merge runs the action for real. `Check · mini region` builds
  from its own small PBF, so it never reaches osm.fr.

## 7. Decided

- `stale` is 30 minutes, to outlast the slowest download of the largest extract.

## 8. Open questions

- Should a range or routing area also store its *merged* extract as an artifact? For now it
  doesn't: the merge takes seconds, so the day's Drive cache of the cut PBF is enough.
