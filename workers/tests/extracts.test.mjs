import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  artifactName, decide, groups, live, looksLikePbf, mirrorOf, one, owner, STALE_MS
} from "../lib/extracts.mjs";

const DAY = Date.parse("2026-10-27T09:00:00Z");
const SK = "https://download.openstreetmap.fr/extracts/europe/slovakia-latest.osm.pbf";
const NAME = "extract-europe-slovakia-latest-2026-10-27";

const art = (id, name, run, minutesAgo, now = DAY) => ({
  id, name, expired: false, workflow_run: { id: run },
  created_at: new Date(now - minutesAgo * 60000).toISOString() });

/** Artifacts of the whole repository, kept in memory, as the API and the client see them. */
function world(now) {
  const all = [];
  let next = 100;
  const github = { rest: { actions: { listArtifactsForRepo: async ({ name }) =>
    ({ data: { artifacts: all.filter((a) => a.name === name) } }) } } };
  const client = (runId) => ({
    uploaded: [],
    async uploadArtifact(name, files) {
      if (all.some((a) => a.name === name && a.workflow_run.id === runId)) throw new Error("409");
      all.push({ ...art(next++, name, runId, 0, now()), body: fs.readFileSync(files[0]) });
      this.uploaded.push(name);
    },
    async downloadArtifact(id, { path: dir, findBy }) {
      const a = all.find((x) => x.id === id);
      assert.equal(findBy.workflowRunId, a.workflow_run.id);
      fs.writeFileSync(path.join(dir, a.name), a.body);
    } });
  return { all, github, client };
}

const quiet = { info() {} };
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "extracts-"));
const pbf = Buffer.concat([Buffer.from([0, 0, 0, 13]), Buffer.from("\n\tOSMHeader")]);

test("an extract's name holds its path on osm.fr and the day", () => {
  assert.equal(artifactName(SK, "2026-10-27"), NAME);
  assert.equal(artifactName("https://download.openstreetmap.fr/extracts/europe/poland/malopolskie-latest.osm.pbf",
    "2026-10-27"), "extract-europe-poland-malopolskie-latest-2026-10-27");
  assert.equal(mirrorOf(SK), "https://download.geofabrik.de/europe/slovakia-latest.osm.pbf");
});

test("words on one line name one extract; lines are extracts", () => {
  assert.deepEqual(groups(" a b\n\nc \n"), [["a", "b"], ["c"]]);
});

test("a marker older than 30 minutes is a download that died", () => {
  const markers = [art(1, "m", 7, 31), art(2, "m", 8, 29)];
  assert.deepEqual(live(markers, DAY).map((m) => m.id), [2]);
  assert.equal(STALE_MS, 30 * 60 * 1000);
});

test("the oldest marker owns the download, the lowest id breaks a tie", () => {
  assert.equal(owner([art(5, "m", 1, 2), art(4, "m", 2, 2), art(9, "m", 3, 1)]).id, 4);
});

test("an artifact of the day is taken, whoever is downloading", () => {
  const step = decide({ extracts: [art(1, "x", 7, 5)], markers: [art(2, "m", 8, 1)],
    now: DAY, runId: 9, claimed: false });
  assert.equal(step.action, "take");
});

test("another run's live marker means wait; ours, once claimed, means download", () => {
  assert.equal(decide({ extracts: [], markers: [art(2, "m", 8, 1)], now: DAY, runId: 9 }).action, "wait");
  assert.equal(decide({ extracts: [], markers: [art(2, "m", 9, 1)], now: DAY, runId: 9,
    claimed: true }).action, "fetch");
  assert.equal(decide({ extracts: [], markers: [], now: DAY, runId: 9 }).action, "claim");
  assert.equal(decide({ extracts: [], markers: [art(2, "m", 8, 31)], now: DAY, runId: 9 }).action, "claim");
});

test("a PBF is told by its first blob header", () => {
  assert.ok(looksLikePbf(pbf));
  assert.ok(!looksLikePbf(Buffer.from("<html>Not Found</html>")));
});

test("the first job of the day downloads, uploads, and the next takes it", async () => {
  let clock = DAY;
  const { github, client } = world(() => clock);
  const fetched = [];
  const fetchTo = async (urls, dest) => { fetched.push(urls[0]); fs.writeFileSync(dest, pbf); };
  const first = client(1);
  const dir1 = tmp();
  const done = await one({ github, context: { runId: 1, repo: { owner: "o", repo: "r" } }, core: quiet,
    client: first, token: "t", urls: [SK], dir: dir1, now: () => clock, sleep: async () => {}, fetchTo });
  assert.equal(done, "downloaded");
  assert.deepEqual(first.uploaded, [`${NAME}.fetching`, `${NAME}.osm.pbf`]);
  assert.ok(fs.existsSync(path.join(dir1, "slovakia-latest.osm.pbf")));

  clock += 60000;
  const dir2 = tmp();
  const second = await one({ github, context: { runId: 2, repo: { owner: "o", repo: "r" } }, core: quiet,
    client: client(2), token: "t", urls: [SK], dir: dir2, now: () => clock, sleep: async () => {}, fetchTo });
  assert.equal(second, "taken");
  assert.equal(fetched.length, 1);
  assert.deepEqual(fs.readFileSync(path.join(dir2, "slovakia-latest.osm.pbf")), pbf);
});

test("a job waits while another downloads, then takes its upload", async () => {
  let clock = DAY;
  const { all, github, client } = world(() => clock);
  all.push(art(1, `${NAME}.fetching`, 1, 2));
  let waits = 0;
  const sleep = async (ms) => {
    clock += ms;
    if (++waits === 3) all.push({ ...art(2, `${NAME}.osm.pbf`, 1, 0, clock), body: pbf });
  };
  const done = await one({ github, context: { runId: 2, repo: { owner: "o", repo: "r" } }, core: quiet,
    client: client(2), token: "t", urls: [SK], dir: tmp(), now: () => clock, sleep,
    fetchTo: async () => assert.fail("a second download") });
  assert.equal(done, "taken");
  assert.equal(waits, 3);
});

test("a download that died is taken over once its marker is 30 minutes old", async () => {
  let clock = DAY;
  const { all, github, client } = world(() => clock);
  all.push(art(1, `${NAME}.fetching`, 1, 25));
  const sleep = async (ms) => { clock += ms; };
  const done = await one({ github, context: { runId: 2, repo: { owner: "o", repo: "r" } }, core: quiet,
    client: client(2), token: "t", urls: [SK], dir: tmp(), now: () => clock, sleep,
    fetchTo: async (urls, dest) => fs.writeFileSync(dest, pbf) });
  assert.equal(done, "downloaded");
  assert.ok(clock - DAY >= 5 * 60000);
});
