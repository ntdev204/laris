"use client";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

type Item = { item: string; topic: string; text: string };
type Rating = { rater: string; item: string; grounded: number; valuable: number; comment?: string };

export function RatingSheet({ items }: { items: Item[] }) {
  const [rater, setRater] = useState("");
  const [ratings, setRatings] = useState<Rating[]>([]);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    setRater(localStorage.getItem("gap-rater") ?? "");
    fetch("/api/gap/ratings").then((r) => r.json()).then(setRatings).catch(() => {});
  }, []);
  const mine = (id: string) => ratings.find((r) => r.rater === rater && r.item === id);
  async function save(r: Rating) {
    const res = await fetch("/api/gap/ratings", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(r) });
    if (res.ok) setRatings([...ratings.filter((x) => !(x.rater === r.rater && x.item === r.item)), r]);
    setMsg(res.ok ? `Đã lưu ${r.item}` : "Lưu thất bại");
  }
  const done = items.filter((i) => mine(i.item)).length;
  return (
    <div className="space-y-3">
      <div className="sticky top-0 z-10 flex items-center gap-3 rounded-lg border bg-background p-3 text-sm">
        <label>Người chấm <input className="ml-1 rounded border px-2 py-1" value={rater} onChange={(e) => { setRater(e.target.value); localStorage.setItem("gap-rater", e.target.value); }} placeholder="Tên hoặc mã" /></label>
        <span>Đã chấm {done}/{items.length}</span>
        <span className="text-muted-foreground">{msg}</span>
      </div>
      {items.map((it) => {
        const r = mine(it.item);
        const set = (k: "grounded" | "valuable", v: number) => {
          if (!rater.trim()) { setMsg("Nhập tên người chấm trước"); return; }
          const next: Rating = { rater, item: it.item, grounded: r?.grounded ?? 0, valuable: r?.valuable ?? 0, comment: r?.comment ?? "", [k]: v };
          if (next.grounded && next.valuable) save(next); else setRatings([...ratings.filter((x) => !(x.rater === rater && x.item === it.item)), next]);
        };
        return (
          <div key={it.item} className={`rounded-lg border p-3 text-sm ${r?.grounded && r?.valuable ? "border-emerald-400" : ""}`}>
            <div className="mb-1 text-xs text-muted-foreground">{it.item} · chủ đề {it.topic}</div>
            <div className="prose prose-sm max-w-none whitespace-pre-wrap"><ReactMarkdown>{it.text}</ReactMarkdown></div>
            {(["grounded", "valuable"] as const).map((k) => (
              <div key={k} className="mt-2 flex items-center gap-1">
                <span className="w-32">{k === "grounded" ? "Có căn cứ" : "Có giá trị"}</span>
                {[1, 2, 3, 4, 5].map((v) => (
                  <button key={v} onClick={() => set(k, v)} className={`h-7 w-7 rounded border ${r?.[k] === v ? "bg-primary text-primary-foreground" : ""}`}>{v}</button>
                ))}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
