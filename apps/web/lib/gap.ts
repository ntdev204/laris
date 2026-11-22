// Research-gap runs on disk (T272): `laris gap run` writes one folder per run under
// LARIS_GAP_DIR/topics/<topic>/runs/<label>; the pages read them and the routes write people's judgements beside them.
import { promises as fs } from "node:fs";
import path from "node:path";

export const gapDir = process.env.LARIS_GAP_DIR ?? "";

const SAFE = /^[A-Za-z0-9._-]{1,80}$/;

export function safe(name: string): string {
  if (!SAFE.test(name) || name.startsWith(".")) throw new Error(`bad name ${name}`);
  return name;
}

export function topicDir(topic: string): string {
  return path.join(gapDir, "topics", safe(topic));
}

export function runDir(topic: string, run: string): string {
  return path.join(topicDir(topic), "runs", safe(run));
}

export async function readJson<T = unknown>(file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(file, "utf8")) as T;
  } catch {
    return null;
  }
}

export async function readText(file: string): Promise<string | null> {
  try {
    return await fs.readFile(file, "utf8");
  } catch {
    return null;
  }
}

export async function writeJson(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(value, null, 1));
  await fs.rename(tmp, file);
}

export type RunSummary = { topic: string; run: string; manifest: Record<string, unknown> | null; metrics: boolean };

export async function listRuns(): Promise<RunSummary[]> {
  if (!gapDir) return [];
  const out: RunSummary[] = [];
  let topics: string[] = [];
  try {
    topics = await fs.readdir(path.join(gapDir, "topics"));
  } catch {
    return [];
  }
  for (const topic of topics.filter((t) => SAFE.test(t)).sort()) {
    let runs: string[] = [];
    try {
      runs = await fs.readdir(path.join(gapDir, "topics", topic, "runs"));
    } catch {
      continue;
    }
    for (const run of runs.filter((r) => SAFE.test(r)).sort()) {
      const manifest = await readJson<Record<string, unknown>>(path.join(gapDir, "topics", topic, "runs", run, "run.json"));
      const metrics = (await readJson(path.join(gapDir, "topics", topic, "runs", run, "metrics.json"))) !== null;
      out.push({ topic, run, manifest, metrics });
    }
  }
  return out;
}

export async function loadRun(topic: string, run: string) {
  const dir = runDir(topic, run);
  const extracts: Record<string, Record<string, unknown>> = {};
  try {
    for (const f of (await fs.readdir(path.join(dir, "extract"))).sort()) {
      if (f.endsWith(".json")) extracts[f.slice(0, -5)] = (await readJson(path.join(dir, "extract", f))) ?? {};
    }
  } catch {}
  const baselines: Record<string, Record<string, unknown>> = {};
  for (const mode of ["closed", "context", "rag"]) {
    const b = await readJson<Record<string, unknown>>(path.join(dir, "baselines", `${mode}.json`));
    if (b) baselines[mode] = b;
  }
  return {
    manifest: await readJson<Record<string, unknown>>(path.join(dir, "run.json")),
    policy: await readJson<Record<string, unknown>>(path.join(dir, "policy.json")),
    analysis: await readJson<Record<string, unknown>>(path.join(dir, "analysis.json")),
    audit: await readJson<Record<string, unknown>>(path.join(dir, "audit.json")),
    metrics: await readJson<Record<string, unknown>>(path.join(dir, "metrics.json")),
    verdicts: (await readJson<Verdict[]>(path.join(dir, "verdicts.json"))) ?? [],
    report: (await readText(path.join(dir, "report.md"))) ?? "",
    extracts,
    baselines,
  };
}

export type Verdict = { subject: string; concept: string; correct: boolean };
export type Rating = { rater: string; item: string; grounded: number; valuable: number; comment?: string };
