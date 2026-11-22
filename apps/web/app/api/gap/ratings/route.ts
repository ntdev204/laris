// Expert ratings of the blind sheet: one entry per rater and item, the latest wins.
import path from "node:path";
import { gapDir, readJson, writeJson, type Rating } from "@/lib/gap";

const file = () => path.join(gapDir, "rating", "ratings.json");

export async function GET() {
  if (!gapDir) return Response.json([], { status: 503 });
  return Response.json((await readJson<Rating[]>(file())) ?? []);
}

export async function POST(request: Request) {
  if (!gapDir) return Response.json({ error: "LARIS_GAP_DIR is not set" }, { status: 503 });
  const r = (await request.json().catch(() => null)) as Rating | null;
  const ok = (n: unknown) => Number.isInteger(n) && (n as number) >= 1 && (n as number) <= 5;
  if (!r || typeof r.rater !== "string" || !r.rater.trim() || typeof r.item !== "string" || !ok(r.grounded) || !ok(r.valuable)) {
    return Response.json({ error: "bad rating" }, { status: 400 });
  }
  const all = ((await readJson<Rating[]>(file())) ?? []).filter((x) => !(x.rater === r.rater && x.item === r.item));
  all.push({ rater: r.rater.trim().slice(0, 60), item: r.item, grounded: r.grounded, valuable: r.valuable, comment: String(r.comment ?? "").slice(0, 2000) });
  await writeJson(file(), all);
  return Response.json({ saved: all.length });
}
