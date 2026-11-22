// Runs `laris gap score` for one run with every judgement that exists: the gold standard, the tag verdicts, the
// expert ratings and, for a run up to the cutoff year, the full run of the same topic for the time split.
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { gapDir, runDir, topicDir } from "@/lib/gap";

export async function POST(request: Request) {
  const bin = process.env.LARIS_BIN;
  if (!gapDir || !bin) return Response.json({ error: "LARIS_GAP_DIR or LARIS_BIN is not set" }, { status: 503 });
  const body = (await request.json().catch(() => null)) as { topic?: string; run?: string } | null;
  if (!body?.topic || !body.run) return Response.json({ error: "bad request" }, { status: 400 });
  let dir: string;
  try {
    dir = runDir(body.topic, body.run);
  } catch {
    return Response.json({ error: "bad name" }, { status: 400 });
  }
  const args = ["gap", "score", dir];
  const gold = path.join(gapDir, "gold", body.topic);
  if (existsSync(gold)) args.push("--gold", gold);
  const verdicts = path.join(dir, "verdicts.json");
  if (existsSync(verdicts)) args.push("--verdicts", verdicts);
  const sheet = path.join(gapDir, "rating", "sheet.json");
  const ratings = path.join(gapDir, "rating", "ratings.json");
  if (existsSync(sheet) && existsSync(ratings)) args.push("--sheet", sheet, "--ratings", ratings);
  const full = path.join(topicDir(body.topic), "runs", "all");
  if (body.run.startsWith("until-") && existsSync(path.join(full, "analysis.json"))) args.push("--full", full);
  return await new Promise<Response>((resolve) => {
    execFile(bin, args, { timeout: 120_000, maxBuffer: 64 << 20 }, (error, _stdout, stderr) => {
      resolve(error ? Response.json({ error: stderr || String(error) }, { status: 500 }) : Response.json({ ok: true }));
    });
  });
}
