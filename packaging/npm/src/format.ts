// Text helpers: one-line summaries, the status line and diff lines.
import type { LineData } from "./state.js";

/** One line for a tool result (the same wording as the plain-text mode). */
export function summarise(result: unknown): string {
  if (result && typeof result === "object" && !Array.isArray(result)) {
    const r = result as Record<string, unknown>;
    const error = r["error"];
    if (error && typeof error === "object") {
      const e = error as Record<string, unknown>;
      return `error ${String(e["code"] ?? "?")}: ${String(e["message"] ?? "").slice(0, 160)}`;
    }
    if (Array.isArray(r["hits"])) return `${r["hits"].length} passages`;
    if (typeof r["text"] === "string") return `${String(r["total_chars"] ?? r["text"].length)} chars`;
  }
  const text = JSON.stringify(result) ?? "";
  return text.slice(0, 160);
}

export function argsPreview(args: Record<string, unknown>, max = 110): string {
  const text = JSON.stringify(args) ?? "";
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

export function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}

export interface StatusParts { text: string; parts: string[] }

/** The status line (SR-C1): model, permission mode, context use, tokens left, git branch, sandbox. */
export function statusLine(line: LineData | null, mode: string, sandbox: { state: string; hint: string } | null, queued: number): StatusParts {
  const parts: string[] = [];
  if (line?.model) parts.push(line.model);
  parts.push(mode);
  if (line?.context && line.context.window) {
    const percent = line.context.percent ?? Math.round((100 * line.context.tokens) / line.context.window);
    parts.push(`context ${percent}%`);
  }
  if (line) {
    if (line.unlimited) parts.push("tokens unlimited");
    else if (typeof line.tokens_left === "number") parts.push(`${compactNumber(line.tokens_left)} tokens left`);
  }
  if (line?.branch) parts.push(`⎇ ${line.branch}`);
  const sandboxState = sandbox?.state ?? line?.sandbox;
  if (sandboxState && sandboxState !== "ready") parts.push(`sandbox ${sandboxState}`);
  if (queued > 0) parts.push(`${queued} queued`);
  return { text: parts.join(" · "), parts };
}

export type DiffKind = "add" | "del" | "hunk" | "meta" | "context";
export function diffKind(line: string): DiffKind {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "context";
}
