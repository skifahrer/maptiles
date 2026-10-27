// Each OSM extract downloaded once a day and shared as an artifact (docs/extract-cache.md).
import fs from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

export const STALE_MS = 30 * 60 * 1000;
export const POLL_MS = 30 * 1000;
const OSMFR = "https://download.openstreetmap.fr/extracts/";
const GEOFABRIK = "https://download.geofabrik.de/";

/** `europe/slovakia-latest` → `extract-europe-slovakia-latest-2026-10-27`. */
export function artifactName(url, day) {
  const { host, pathname } = new URL(url);
  const rest = url.startsWith(OSMFR) ? url.slice(OSMFR.length) : host + pathname;
  const slug = rest.replace(/\.osm\.pbf$/, "").replace(/[^A-Za-z0-9._-]+/g, "-");
  return `extract-${slug}-${day}`;
}

export function utcDay(now) {
  return new Date(now).toISOString().slice(0, 10);
}

/** Lines of URLs; the words on a line are names for one extract, the first wins. */
export function groups(text) {
  return text.split("\n").map((l) => l.trim().split(/\s+/).filter(Boolean)).filter((g) => g.length);
}

export function mirrorOf(url) {
  return url.startsWith(OSMFR) ? GEOFABRIK + url.slice(OSMFR.length) : null;
}

/** The newest artifact not expired, or null. */
export function freshest(artifacts) {
  const live = artifacts.filter((a) => !a.expired);
  live.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id);
  return live[0] ?? null;
}

/** Markers of downloads still running: younger than `stale`. */
export function live(markers, now, stale = STALE_MS) {
  return markers.filter((m) => !m.expired && now - Date.parse(m.created_at) < stale);
}

/** The download belongs to the oldest marker; the lowest id breaks a tie. */
export function owner(markers) {
  const sorted = [...markers].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id);
  return sorted[0] ?? null;
}

/** What to do next: take the artifact, wait for another run, claim it, or download it. */
export function decide({ extracts, markers, now, runId, claimed }) {
  const found = freshest(extracts);
  if (found) return { action: "take", artifact: found };
  const first = owner(live(markers, now));
  if (!first) return { action: claimed ? "fetch" : "claim" };
  if (first.workflow_run?.id === runId) return { action: claimed ? "fetch" : "wait" };
  return { action: "wait" };
}

/** A PBF starts with the length of its first blob header, then `OSMHeader`. */
export function looksLikePbf(head) {
  return head.subarray(0, 64).includes("OSMHeader");
}

async function listNamed(github, context, name) {
  const { data } = await github.rest.actions.listArtifactsForRepo({
    owner: context.repo.owner, repo: context.repo.repo, name, per_page: 100 });
  return data.artifacts;
}

async function download(urls, dest, log, tries = 3) {
  const all = urls.flatMap((u) => [u, mirrorOf(u)].filter(Boolean));
  for (const url of all) {
    for (let attempt = 1; attempt <= tries; attempt++) {
      try {
        const res = await fetch(url);
        if (res.status === 404) break;
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await pipeline(Readable.fromWeb(res.body), fs.createWriteStream(dest));
        const fd = fs.openSync(dest, "r");
        const head = Buffer.alloc(64);
        fs.readSync(fd, head, 0, 64, 0);
        fs.closeSync(fd);
        if (!looksLikePbf(head)) throw new Error("not a PBF");
        log(`${url}: ${(fs.statSync(dest).size / 1048576).toFixed(0)} MB`);
        return url;
      } catch (err) {
        log(`${url}: ${err.message} (${attempt} of ${tries})`);
        await new Promise((r) => setTimeout(r, 5000 * attempt));
      }
    }
  }
  throw new Error(`no extract downloaded from ${all.join(", ")}`);
}

/** One extract into `dir/<basename of its first URL>`. */
export async function one({ github, context, core, client, token, urls, dir, now = Date.now,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)), fetchTo = download }) {
  const name = artifactName(urls[0], utcDay(now()));
  const file = `${name}.osm.pbf`;
  const marker = `${name}.fetching`;
  const dest = path.join(dir, path.basename(urls[0]));
  const up = path.join(dir, ".up");
  fs.mkdirSync(up, { recursive: true });
  const runId = context.runId;
  let claimed = false;
  for (;;) {
    const step = decide({ extracts: await listNamed(github, context, file),
      markers: await listNamed(github, context, marker), now: now(), runId, claimed });
    if (step.action === "take") {
      const run = step.artifact.workflow_run.id;
      core.info(`${file} from run ${run}`);
      await client.downloadArtifact(step.artifact.id, { path: up, findBy: { token,
        workflowRunId: run, repositoryOwner: context.repo.owner, repositoryName: context.repo.repo } });
      fs.renameSync(path.join(up, file), dest);
      return "taken";
    }
    if (step.action === "wait") {
      core.info(`${file} is being downloaded by another job; waiting`);
      await sleep(POLL_MS);
      continue;
    }
    if (step.action === "claim") {
      fs.writeFileSync(path.join(up, marker), JSON.stringify({ run: runId, at: now() }));
      try {
        await client.uploadArtifact(marker, [path.join(up, marker)], up,
          { retentionDays: 1, skipArchive: true });
      } catch (err) {
        // the name is taken in this very run: another job here downloads it
        core.info(`${marker} not uploaded (${err.message}); waiting`);
        await sleep(POLL_MS);
        continue;
      }
      claimed = true;
      continue;
    }
    core.info(`${file}: downloading`);
    await fetchTo(urls, path.join(up, file), (m) => core.info(`  ${m}`));
    await client.uploadArtifact(file, [path.join(up, file)], up,
      { retentionDays: 1, skipArchive: true, compressionLevel: 0 });
    fs.renameSync(path.join(up, file), dest);
    return "downloaded";
  }
}

export default async function run({ github, context, core, client, token, urls, dir }) {
  for (const group of groups(urls)) {
    try {
      await one({ github, context, core, client, token, urls: group, dir });
    } catch (err) {
      // a cache never fails a build: the script downloads what isn't here
      core.warning(`${group[0]}: ${err.message} – the job downloads it itself`);
    }
  }
  fs.rmSync(path.join(dir, ".up"), { recursive: true, force: true });
}
