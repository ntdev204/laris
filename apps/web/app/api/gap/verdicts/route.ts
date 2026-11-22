import path from "node:path";
import { gapDir, runDir, writeJson, type Verdict } from "@/lib/gap";

export async function POST(request: Request) {
  if (!gapDir) return Response.json({ error: "LARIS_GAP_DIR is not set" }, { status: 503 });
  const body = (await request.json().catch(() => null)) as { topic?: string; run?: string; verdicts?: Verdict[] } | null;
  if (!body?.topic || !body.run || !Array.isArray(body.verdicts)) return Response.json({ error: "bad request" }, { status: 400 });
  const verdicts = body.verdicts
    .filter((v) => typeof v.subject === "string" && typeof v.concept === "string" && typeof v.correct === "boolean")
    .map((v) => ({ subject: v.subject, concept: v.concept, correct: v.correct }));
  try {
    await writeJson(path.join(runDir(body.topic, body.run), "verdicts.json"), verdicts);
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 400 });
  }
  return Response.json({ saved: verdicts.length });
}
