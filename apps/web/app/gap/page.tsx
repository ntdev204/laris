import Link from "next/link";
import { gapDir, listRuns } from "@/lib/gap";

export const dynamic = "force-dynamic";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default async function GapRuns() {
  const runs = await listRuns();
  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">LARIS — Tìm khoảng trống nghiên cứu</h1>
        <div className="flex gap-3 text-sm"><Link href="/gap/rate" className="underline">Phiếu chấm chuyên gia</Link><Link href="/" className="underline">Trò chuyện</Link></div>
      </div>
      {!gapDir && <p className="text-red-700">LARIS_GAP_DIR chưa được đặt.</p>}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50"><tr>{["Chủ đề", "Lần chạy", "Bài đọc được", "Chưa đọc", "Khoảng trống", "Trích dẫn không tồn tại (HT / a / a2 / b)", "Số liệu"].map((h) => <th key={h} className="px-2 py-1.5 text-left font-medium">{h}</th>)}</tr></thead>
          <tbody>
            {runs.map((r) => {
              const m: any = r.manifest ?? {};
              const b: any = m.baselines ?? {};
              const n = (x: any) => (x?.audit?.citations_nonexistent ?? "—");
              return (
                <tr key={`${r.topic}/${r.run}`} className="border-t">
                  <td className="px-2 py-1.5">{r.topic}</td>
                  <td className="px-2 py-1.5"><Link className="underline" href={`/gap/${r.topic}/${r.run}`}>{r.run}</Link></td>
                  <td className="px-2 py-1.5">{(m.papers ?? []).length}</td>
                  <td className="px-2 py-1.5">{(m.not_read ?? []).length}</td>
                  <td className="px-2 py-1.5">{m.report_audit ? "✓" : "—"}</td>
                  <td className="px-2 py-1.5">{m.report_audit?.citations_nonexistent ?? "—"} / {n(b.closed)} / {n(b.context)} / {n(b.rag)}</td>
                  <td className="px-2 py-1.5">{r.metrics ? "✓" : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
