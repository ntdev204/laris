"use client";
// The person's check of concept tagging: every tag on a limitation or future-work item, with the term that put it
// there, marked right or wrong. The verdicts are saved beside the run and give the tagging precision.
import { useMemo, useState } from "react";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
type Verdict = { subject: string; concept: string; correct: boolean };

export function TagJudge({ topic, run, tags, items, papers, initial }: { topic: string; run: string; tags: Any[]; items: Any[]; papers: Any[]; initial: Verdict[] }) {
  const [verdicts, setVerdicts] = useState<Verdict[]>(initial);
  const [scope, setScope] = useState<"items" | "all">("items");
  const [status, setStatus] = useState("");
  const item = useMemo(() => new Map(items.map((i: Any) => [i.id, i])), [items]);
  const record = useMemo(() => new Map(papers.map((p: Any) => [p.id, p.record ?? {}])), [papers]);
  const shown = tags.filter((t: Any) => scope === "all" || t.subject.includes("-"));
  const get = (t: Any) => verdicts.find((v) => v.subject === t.subject && v.concept === t.concept);
  const judged = shown.filter(get).length;
  const correct = shown.filter((t: Any) => get(t)?.correct).length;

  async function mark(t: Any, correct: boolean) {
    const next = [...verdicts.filter((v) => !(v.subject === t.subject && v.concept === t.concept)), { subject: t.subject, concept: t.concept, correct }];
    setVerdicts(next);
    setStatus("Đang lưu…");
    const r = await fetch("/api/gap/verdicts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ topic, run, verdicts: next }) });
    setStatus(r.ok ? `Đã lưu ${next.length} phán quyết` : "Lưu thất bại");
  }

  return (
    <section className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <span>Đã chấm <b>{judged}/{shown.length}</b> nhãn · đúng {correct} · sai {judged - correct}{judged ? ` · precision ${(correct / judged).toFixed(3)}` : ""}</span>
        <select className="rounded border px-2 py-1" value={scope} onChange={(e) => setScope(e.target.value as "items" | "all")}>
          <option value="items">Nhãn trên mục hạn chế / hướng phát triển</option>
          <option value="all">Mọi nhãn (cả trường phương pháp, bối cảnh…)</option>
        </select>
        <span className="text-muted-foreground">{status}</span>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50"><tr>{["Chủ thể", "Văn bản", "Nhóm", "Khái niệm", "Từ khớp", "Đúng?"].map((h) => <th key={h} className="px-2 py-1.5 text-left font-medium">{h}</th>)}</tr></thead>
          <tbody>
            {shown.map((t: Any, i: number) => {
              const v = get(t);
              const it: Any = item.get(t.subject);
              const text = it ? `${it.text} — “${it.quote}”` : (record.get(t.paper) as Any)?.[t.field] ?? "";
              return (
                <tr key={i} className={`border-t align-top ${v ? (v.correct ? "bg-emerald-50" : "bg-red-50") : ""}`}>
                  <td className="px-2 py-1.5 font-mono text-xs">{t.subject}</td>
                  <td className="px-2 py-1.5">{text}</td>
                  <td className="px-2 py-1.5">{t.facet}</td>
                  <td className="px-2 py-1.5">{t.concept}</td>
                  <td className="px-2 py-1.5"><code>{t.term}</code></td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    <button className={`mr-1 rounded border px-2 ${v?.correct === true ? "bg-emerald-600 text-white" : ""}`} onClick={() => mark(t, true)}>✓</button>
                    <button className={`rounded border px-2 ${v?.correct === false ? "bg-red-600 text-white" : ""}`} onClick={() => mark(t, false)}>✗</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
