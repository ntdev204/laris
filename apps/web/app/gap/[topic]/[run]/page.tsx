import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { loadRun } from "@/lib/gap";
import { TagJudge } from "@/components/gap/tag-judge";
import { ScoreButton } from "@/components/gap/score-button";

export const dynamic = "force-dynamic";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;

const TABS: [string, string][] = [
  ["overview", "Tổng quan"],
  ["papers", "Bài báo"],
  ["extract", "Trích xuất"],
  ["tags", "Gắn khái niệm"],
  ["candidates", "Ứng viên & lọc"],
  ["conflicts", "Mâu thuẫn (G2)"],
  ["ranking", "Xếp hạng"],
  ["report", "Báo cáo hệ thống"],
  ["baselines", "Baseline"],
  ["eval", "Đánh giá"],
];

const REASONS: Record<string, string> = {
  g1_one_paper: "G1: chỉ một bài nêu",
  g1_addressed: "G1: có bài khác trong R đã giải quyết",
  g1_unverified: "G1: không có trích dẫn kiểm chứng được",
  g2_explained: "G2: mâu thuẫn được giải thích",
  g3_no_common_issue: "G3: hai nhóm bài không có vấn đề chung",
};

function Num({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr>{head.map((h) => <th key={h} className="px-2 py-1.5 text-left font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t align-top">{r.map((c, j) => <td key={j} className="px-2 py-1.5">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Found({ f }: { f: string }) {
  const map: Record<string, [string, string]> = {
    verbatim: ["nguyên văn", "bg-emerald-100 text-emerald-900"],
    normalized: ["khớp sau chuẩn hóa", "bg-emerald-50 text-emerald-800"],
    missing: ["KHÔNG có trong bài", "bg-red-100 text-red-900"],
    no_quote: ["không có trích dẫn", "bg-amber-100 text-amber-900"],
  };
  const [t, c] = map[f] ?? [f, ""];
  return <span className={`rounded px-1.5 py-0.5 text-xs ${c}`}>{t}</span>;
}

function AuditRow({ name, c }: { name: string; c: Any }) {
  if (!c) return null;
  return [
    name,
    c.citations,
    <b key="n" className={c.citations_nonexistent ? "text-red-700" : ""}>{c.citations_nonexistent}</b>,
    c.citations_unchecked,
    c.quotations,
    <b key="q" className={c.quotations_fabricated ? "text-red-700" : ""}>{c.quotations_fabricated}</b>,
    c.claims,
    c.claims_uncited,
    c.absence_claims,
    <b key="a" className={c.absence_unscoped ? "text-red-700" : ""}>{c.absence_unscoped}</b>,
  ] as Any;
}

const AUDIT_HEAD = ["Nguồn", "Trích dẫn", "Không tồn tại", "Chưa kiểm", "Đoạn trích", "Trích bịa", "Khẳng định", "Không trích dẫn", "Kết luận \"chưa ai làm\"", "…không giới hạn phạm vi"];
const MODE: Record<string, string> = { closed: "(a) Hỏi thẳng Qwen", context: "(a2) Qwen + trích đoạn các bài", rag: "(b) RAG (BM25 + RRF)" };

export default async function RunPage({ params, searchParams }: { params: Promise<{ topic: string; run: string }>; searchParams: Promise<{ tab?: string }> }) {
  const { topic, run } = await params;
  const tab = (await searchParams).tab ?? "overview";
  const d = await loadRun(topic, run);
  const a: Any = d.analysis ?? {};
  const m: Any = d.manifest ?? {};
  const met: Any = d.metrics ?? {};
  const counts: Any = a.counts ?? {};
  const cand: Any[] = a.candidates ?? [];
  const byId = new Map(cand.map((c: Any) => [c.id, c]));

  return (
    <main className="mx-auto max-w-7xl space-y-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <Link href="/gap" className="text-sm text-muted-foreground">← Các lần chạy</Link>
          <h1 className="text-xl font-semibold">{topic} / {run}</h1>
          <p className="text-sm text-muted-foreground">
            Chính sách {String(m.policy_version ?? "?")} · {(m.papers ?? []).length} bài đọc được · {(m.not_read ?? []).length} bài không đọc được · trích xuất {String(m.extract_seconds ?? "?")} s · phân tích {String(m.analyze_milliseconds ?? "?")} ms
          </p>
        </div>
        <ScoreButton topic={topic} run={run} />
      </div>
      <nav className="flex flex-wrap gap-1 border-b pb-2">
        {TABS.map(([k, label]) => (
          <Link key={k} href={`?tab=${k}`} className={`rounded px-2.5 py-1 text-sm ${tab === k ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>{label}</Link>
        ))}
      </nav>
      <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">
        Mô hình Qwen3.5-4B trong hệ thống CHƯA ĐƯỢC KIỂM ĐỊNH (NOT QUALIFIED). Mọi số dưới đây là đầu ra tự động của lần chạy này; phần do người chấm được ghi rõ ở tab Đánh giá.
      </p>

      {tab === "overview" && (
        <section className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Num label="Bài / bản ghi đọc được" value={`${counts.papers_parsed ?? "?"}/${counts.papers ?? "?"}`} />
            <Num label="Mục hạn chế + hướng phát triển" value={counts.items ?? "?"} />
            <Num label="Đoạn trích có thật trong bài" value={`${(counts.quotes_verbatim ?? 0) + (counts.quotes_normalized ?? 0)}/${counts.quotes ?? 0}`} hint={`${counts.quotes_missing ?? 0} không tìm thấy`} />
            <Num label="Nhãn khái niệm (trên mục)" value={`${counts.tags ?? "?"} (${counts.item_tags ?? "?"})`} />
            <Num label="Cạnh tri thức" value={counts.edges ?? "?"} hint={`${counts.concepts ?? "?"} khái niệm`} />
          </div>
          <h2 className="font-semibold">Ứng viên theo luật: sinh ra → bị loại (lý do) → giữ lại</h2>
          <Table
            head={["Luật", "Sinh ra", "Bị loại", "Lý do loại", "Giữ lại"]}
            rows={Object.entries(counts.rules ?? {}).map(([r, c]: Any) => [
              r, c.generated, Object.values(c.filtered ?? {}).reduce((x: number, y: Any) => x + y, 0),
              Object.entries(c.filtered ?? {}).map(([k, v]) => `${REASONS[k] ?? k}: ${v}`).join("; ") || "—", c.kept,
            ])}
          />
          <h2 className="font-semibold">Kiểm toán trích dẫn: hệ thống so với baseline (cùng bài, cùng mô hình)</h2>
          <Table head={AUDIT_HEAD} rows={[AuditRow({ name: "Hệ thống LARIS", c: d.audit?.counts }), ...Object.entries(d.baselines).map(([k, b]: Any) => AuditRow({ name: MODE[k] ?? k, c: b.audit?.counts }))].filter(Boolean) as Any} />
        </section>
      )}

      {tab === "papers" && (
        <Table
          head={["Mã", "Tiêu đề", "Năm", "Đọc bằng", "Ký tự", "Các phần tìm thấy", "Lỗi"]}
          rows={(a.papers ?? []).map((p: Any) => [p.id, p.title, p.year ?? "?", p.read_by, p.chars, p.sections.join(", "), p.error || "—"])}
        />
      )}

      {tab === "extract" && (
        <section className="space-y-3">
          {(a.papers ?? []).map((p: Any) => {
            const ex: Any = d.extracts[p.id] ?? {};
            const items = (a.items ?? []).filter((i: Any) => i.paper === p.id);
            return (
              <details key={p.id} className="rounded-lg border p-3">
                <summary className="cursor-pointer font-medium">{p.id} — {p.title} · {items.length} mục · {ex.seconds ?? "?"} s</summary>
                <div className="mt-2 space-y-2 text-sm">
                  <div className="grid gap-1 md:grid-cols-2">
                    <div><b>Bài toán:</b> {p.record?.problem}</div>
                    <div><b>Phương pháp:</b> {p.record?.method}</div>
                    <div><b>Bối cảnh:</b> {p.record?.setting}</div>
                    <div><b>Kết quả:</b> {p.record?.result}</div>
                  </div>
                  <Table head={["Mục", "Loại", "Diễn giải", "Trích dẫn", "Kiểm chứng", "Phần"]} rows={items.map((i: Any) => [i.id, i.kind === "limitation" ? "hạn chế" : "hướng phát triển", i.text, <q key="q">{i.quote}</q>, <Found key="f" f={i.found} />, i.section])} />
                  <div className="text-xs text-muted-foreground">Khối đưa cho mô hình: {(ex.blocks ?? []).map((b: Any) => `${b[0]} (${b[1]} ký tự)`).join(", ")} · prompt {ex.prompt_chars} ký tự</div>
                  <details><summary className="cursor-pointer text-xs">Đầu ra thô của mô hình</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">{ex.raw}</pre></details>
                </div>
              </details>
            );
          })}
        </section>
      )}

      {tab === "tags" && <TagJudge topic={topic} run={run} tags={a.tags ?? []} items={a.items ?? []} papers={a.papers ?? []} initial={d.verdicts} />}

      {tab === "candidates" && (
        <Table
          head={["Ứng viên", "Luật", "Phát biểu", "Bài", "Trạng thái", "Lý do loại"]}
          rows={cand.map((c: Any) => [c.id, c.rule, plain(c.statement), c.papers.join(", "),
            <span key="s" className={c.status === "kept" ? "font-medium text-emerald-700" : "text-muted-foreground"}>{c.status === "kept" ? "giữ" : "loại"}</span>,
            c.reason ? `${REASONS[c.reason] ?? c.reason} — ${c.detail}` : "—"])}
        />
      )}

      {tab === "conflicts" && (
        <section className="space-y-3 text-sm">
          <div className="rounded-lg border p-3">
            <p><b>Cách phát hiện r ⊥ r′.</b> r = (p, c, −): một câu của bài p có từ khóa phủ định và nêu phương pháp c — lấy từ trường bài toán / kết quả hoặc mục hạn chế do mô hình trích (diễn giải), hoặc nguyên văn từ phần tóm tắt / giới thiệu của bài (trích dẫn, đặt trong ngoặc kép). r′ = (q, c, +): bài q ≠ p dùng phương pháp c và kết quả của q có từ khóa khẳng định. Hai câu như vậy mâu thuẫn.</p>
            <p className="mt-1"><b>Điều kiện "được giải thích" (khi đó không thành khoảng trống):</b> (a) p và q không có chung khái niệm bối cảnh (khác phần cứng/dữ liệu); (b) chính p cũng báo cáo c chạy được; (c) không biết bối cảnh của p. Ngược lại là mâu thuẫn chưa giải thích.</p>
          </div>
          <Table head={["Phương pháp", "r (p, −)", "r′ (q, +)", "Bối cảnh p", "Bối cảnh q", "Kết luận"]}
            rows={(a.conflicts ?? []).map((k: Any) => [k.method,
              <span key="n"><b>{k.negative.paper}</b> [{k.negative.via}] {verbatim(k.negative.via) ? `“${k.negative.sentence}”` : `${k.negative.sentence} (diễn giải)`} <i className="text-xs">({k.negative.cue})</i></span>,
              <span key="p"><b>{k.positive.paper}</b> [{k.positive.via}] {k.positive.sentence} (diễn giải) <i className="text-xs">({k.positive.cue})</i></span>,
              k.settings_negative.join(", ") || "?", k.settings_positive.join(", ") || "?",
              <span key="e" className={k.explained ? "text-muted-foreground" : "font-medium text-red-700"}>{k.explanation}</span>])} />
        </section>
      )}

      {tab === "ranking" && (
        <section className="space-y-3 text-sm">
          <p className="rounded-lg border p-3">s(g) = w₁·số bài + w₂·[G1 hoặc G2] + w₃·số trích dẫn kiểm chứng − w₄·[chỉ một bài], với w₁ = {a.weights?.w1}, w₂ = {a.weights?.w2}, w₃ = {a.weights?.w3}, w₄ = {a.weights?.w4} (đặt tay trước lần chạy đầu, chỉ để sắp thứ tự trình bày).</p>
          <Table head={["Hạng", "KT", "Luật", "Số bài", "w₁·bài", "w₂·[G1∨G2]", "Trích kiểm chứng", "w₃·trích", "−w₄·[1 bài]", "s(g)", "Phát biểu"]}
            rows={(a.ranking ?? []).map((r: Any) => [r.rank, r.gap, r.rule, r.papers, r.parts[0], r.parts[1], r.verified, r.parts[2], r.parts[3], <b key="s">{r.score}</b>, plain(byId.get(r.candidate)?.statement ?? "")])} />
        </section>
      )}

      {tab === "report" && <article className="prose prose-sm max-w-none rounded-lg border p-4"><ReactMarkdown remarkPlugins={[remarkGfm]}>{d.report}</ReactMarkdown></article>}

      {tab === "baselines" && (
        <section className="grid gap-4 lg:grid-cols-3">
          {Object.entries(d.baselines).map(([k, b]: Any) => (
            <div key={k} className="space-y-2 rounded-lg border p-3 text-sm">
              <h3 className="font-semibold">{MODE[k] ?? k}</h3>
              <div className="text-xs text-muted-foreground">{b.seconds} s · prompt {b.prompt_chars} ký tự{b.retrieved?.length ? ` · ${b.retrieved.length} đoạn truy hồi` : ""}</div>
              <div className="prose prose-sm max-h-[32rem] max-w-none overflow-auto"><ReactMarkdown remarkPlugins={[remarkGfm]}>{b.answer}</ReactMarkdown></div>
              <details><summary className="cursor-pointer text-xs">Câu bị đánh dấu</summary>
                <ul className="list-disc pl-4 text-xs">
                  {(b.audit?.citations ?? []).filter((c: Any) => c.resolved == null).map((c: Any, i: number) => <li key={`c${i}`}>Trích dẫn ngoài danh sách: {c.text} → {c.exists_externally == null ? "chưa kiểm" : c.exists_externally ? `có trên OpenAlex: ${c.external_match}` : "KHÔNG TÌM THẤY"}</li>)}
                  {(b.audit?.quotations ?? []).filter((q: Any) => !q.found_in).map((q: Any, i: number) => <li key={`q${i}`}>Trích bịa: “{q.text}”</li>)}
                  {(b.audit?.claims ?? []).filter((c: Any) => c.absence && !c.scoped).map((c: Any, i: number) => <li key={`a${i}`}>"Chưa ai làm": {c.sentence}</li>)}
                </ul>
              </details>
            </div>
          ))}
        </section>
      )}

      {tab === "eval" && (
        <section className="space-y-4 text-sm">
          {!d.metrics && <p>Chưa có metrics.json. Bấm "Tính lại số liệu".</p>}
          {met.extraction && (
            <>
              <h2 className="font-semibold">Trích xuất từng mục so với đáp án ({met.gold_items} mục trong đáp án, {met.gold_papers} bài; ngưỡng khớp {met.extraction.threshold})</h2>
              <p className="text-xs text-muted-foreground">Đáp án do Claude (một mô hình khác Qwen) lập bằng cách đọc toàn văn từng bài, trước khi hệ thống chạy trên các bài này; xem gold/GUIDELINE.md.</p>
              <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
                <Num label="Mục hệ thống" value={met.extraction.total.system} />
                <Num label="Mục đáp án" value={met.extraction.total.gold} />
                <Num label="Khớp" value={met.extraction.total.matched} />
                <Num label="Precision" value={met.extraction.total.precision} />
                <Num label="Recall" value={met.extraction.total.recall} />
                <Num label="F1" value={met.extraction.total.f1} />
              </div>
              <Table head={["Bài", "Hệ thống", "Đáp án", "Khớp", "P", "R"]} rows={Object.entries(met.extraction.papers).map(([k, v]: Any) => [k, v.system, v.gold, v.matched, v.precision, v.recall])} />
            </>
          )}
          {met.tag_precision && (
            <p>Precision gắn khái niệm (người chấm): <b>{met.tag_precision.correct}/{met.tag_precision.judged}</b> = {met.tag_precision.precision} ({met.tag_precision.wrong} sai; {met.tag_precision.tags} nhãn trong lần chạy).</p>
          )}
          {met.time_split && (
            <>
              <h2 className="font-semibold">Đánh giá theo mốc thời gian: {met.time_split.addressed_later}/{met.time_split.gaps} khoảng trống được bài công bố sau giải quyết</h2>
              <Table head={["KT", "Luật", "Phát biểu", "Bài sau giải quyết"]} rows={met.time_split.checks.map((c: Any) => [c.gap, c.rule, plain(c.statement), c.addressed_by.join(", ") || "—"])} />
            </>
          )}
        </section>
      )}
    </main>
  );
}

// A claim read verbatim from the paper's abstract or introduction, not from the model's record.
function verbatim(via: string): boolean {
  return /:(abstract|introduction)$/.test(via);
}

// A statement of the analysis without its Markdown emphasis.
function plain(text: string): string {
  return text.replaceAll("**", "");
}
