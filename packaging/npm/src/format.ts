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
    if (typeof r["total_lines"] === "number") {
      const from = Number(r["start"] ?? 1), to = Number(r["end"] ?? r["total_lines"]);
      const part = to - from + 1 < r["total_lines"] ? ` (${from}-${to} of ${r["total_lines"]})` : "";
      return `Read ${to - from + 1} lines${part}`;
    }
    if (typeof r["text"] === "string") return `${String(r["total_chars"] ?? r["text"].length)} chars`;
    if (typeof r["bytes"] === "number") return `${r["created"] ? "Created" : "Wrote"} ${String(r["path"] ?? "")} (${compactNumber(r["bytes"])} bytes)`;
    if (typeof r["replacements"] === "number") return `Updated ${String(r["path"] ?? "")} (${r["replacements"]} replacement${r["replacements"] === 1 ? "" : "s"})`;
    if (Array.isArray(r["files"])) return `${r["files"].length} files${r["truncated"] ? " (more not shown)" : ""}`;
    if (Array.isArray(r["matches"])) return `${r["matches"].length} matches${r["truncated"] ? " (more not shown)" : ""}`;
    if ("exit_code" in r || "timed_out" in r) {
      const lines = String(r["output"] ?? "").replace(/\n$/, "").split("\n");
      const first = (lines[0] ?? "").slice(0, 120);
      const more = lines.length > 1 ? ` … +${lines.length - 1} lines` : "";
      const end = r["timed_out"] ? "timed out" : r["exit_code"] === 0 ? "" : `exit ${String(r["exit_code"])}`;
      return [first + more, end].filter(Boolean).join(" · ") || "(no output)";
    }
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

const PATH_TOOLS = new Set(["Read", "Write", "Edit", "read_file", "write_file"]);

/** `Name(detail)` the way a person reads a tool call: the file, the command, the pattern. */
export function toolTitle(name: string, args: Record<string, unknown>, max = 90): { name: string; detail: string } {
  const text = (key: string): string => (typeof args[key] === "string" ? (args[key] as string) : "");
  let detail = "";
  if (PATH_TOOLS.has(name)) detail = text("file_path") || text("path");
  else if (name === "Bash") detail = text("command");
  else if (name === "Grep" || name === "Glob") detail = [text("pattern"), text("path")].filter(Boolean).join(" in ");
  else detail = text("query") || text("task") || text("name");
  if (!detail) {
    const json = JSON.stringify(args) ?? "";
    detail = json === "{}" ? "" : json;
  }
  detail = detail.replace(/\s+/g, " ");
  return { name, detail: detail.length > max ? detail.slice(0, max - 1) + "…" : detail };
}

/** A human title for a permission dialog. */
export function permissionTitle(tool: string): string {
  if (tool === "Bash") return "Bash command";
  if (tool === "Write" || tool === "write_file") return "Write file";
  if (tool === "Edit") return "Edit file";
  if (tool === "Read" || tool === "read_file") return "Read file";
  return "Tool use";
}

/** `/home/me/work/x` as `~/work/x`; long paths keep their end. */
export function shortPath(path: string, home: string, max = 44): string {
  let out = home && (path === home || path.startsWith(home + "/") || path.startsWith(home + "\\")) ? "~" + path.slice(home.length) : path;
  if (out.length > max) out = "…" + out.slice(out.length - max + 1);
  return out;
}

/** The host of a server address (`https://laris.example.com/v1` -> `laris.example.com`). */
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
