"use client";
// Recomputes metrics.json of a run with `laris gap score` on the server side of the web app.
import { useState } from "react";

export function ScoreButton({ topic, run }: { topic: string; run: string }) {
  const [state, setState] = useState("");
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{state}</span>
      <button
        className="rounded-md border px-3 py-1.5 hover:bg-muted"
        onClick={async () => {
          setState("Đang tính…");
          const r = await fetch("/api/gap/score", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ topic, run }) });
          const j = await r.json().catch(() => ({}));
          setState(r.ok ? "Xong" : `Lỗi: ${j.error ?? r.status}`);
          if (r.ok) window.location.reload();
        }}
      >
        Tính lại số liệu
      </button>
    </div>
  );
}
