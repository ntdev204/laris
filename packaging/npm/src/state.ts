// The whole screen as a function of the events the engine sent: a pure reducer, so every
// scenario can be replayed in a test without a terminal.
import {
  checkVersion, ENDS_COMMAND,
  type CompletionItem, type EngineEvent, type LoginRequired, type PermissionRequest, type PlanStep, type Ready,
} from "./protocol.js";

export type Level = "info" | "warn" | "error" | "dim";

export type Item =
  | { kind: "user"; id: number; text: string }
  | { kind: "assistant"; id: number; text: string; streaming: boolean }
  | { kind: "tool"; id: number; callId: string; name: string; arguments: Record<string, unknown>; result?: unknown; done: boolean }
  | { kind: "plan"; id: number; source: string; steps: PlanStep[] }
  | { kind: "note"; id: number; level: Level; text: string };

export interface LineData {
  model?: string; mode?: string; branch?: string | null; sandbox?: string; queued?: number;
  context?: { tokens: number; window: number; percent: number | null } | null;
  tokens_left?: number | null; tokens_used?: number | null; token_limit?: number | null; unlimited?: boolean;
}

export interface State {
  phase: "starting" | "login" | "running" | "closed";
  ready: Ready | null;
  /** what the engine needs before the session can start, and whether an answer is being checked */
  login: LoginRequired | null;
  loginBusy: boolean;
  /** why the session ended abnormally (version mismatch, engine died); null on a clean end */
  fatal: string | null;
  exitCode: number;
  items: Item[];
  nextId: number;
  busy: boolean;
  pending: string[];
  permission: PermissionRequest | null;
  plan: { source: string; steps: PlanStep[] } | null;
  line: LineData | null;
  mode: string;
  sandbox: { state: string; hint: string } | null;
  usage: { tokens: number; window: number } | null;
  completion: { id: string; items: CompletionItem[] } | null;
}

export type Action =
  | { kind: "event"; event: EngineEvent }
  | { kind: "sent"; text: string }
  | { kind: "answered" }
  | { kind: "login_sent" }
  | { kind: "note"; level: Level; text: string }
  | { kind: "closed"; code: number | null; stderrTail: string; clean: boolean };

export function initialState(): State {
  return {
    phase: "starting", ready: null, login: null, loginBusy: false, fatal: null, exitCode: 0, items: [], nextId: 1, busy: false,
    pending: [], permission: null, plan: null, line: null, mode: "default", sandbox: null,
    usage: null, completion: null,
  };
}

export function isFinal(item: Item): boolean {
  if (item.kind === "assistant") return !item.streaming;
  if (item.kind === "tool") return item.done;
  return true;
}

function push(state: State, make: (id: number) => Item): State {
  return { ...state, items: [...state.items, make(state.nextId)], nextId: state.nextId + 1 };
}

function note(state: State, level: Level, text: string): State {
  return push(state, (id) => ({ kind: "note", id, level, text }));
}

function closeStream(state: State): State {
  const last = state.items[state.items.length - 1];
  if (last?.kind === "assistant" && last.streaming) {
    return { ...state, items: [...state.items.slice(0, -1), { ...last, streaming: false }] };
  }
  return state;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function status(state: State, kind: string, data: Record<string, unknown>): State {
  switch (kind) {
    case "line":
      return { ...state, line: data as LineData, mode: str(data["mode"]) || state.mode };
    case "mode":
      return { ...state, mode: str(data["mode"]) || state.mode };
    case "sandbox":
      return { ...state, sandbox: { state: str(data["state"]), hint: str(data["hint"]) } };
    case "notice":
      return note(state, "info", str(data["text"]));
    case "queued": {
      if (typeof data["started"] === "string") {
        const text = state.pending[0] ?? str(data["started"]);
        const next = { ...state, pending: state.pending.slice(1), busy: true };
        return push(next, (id) => ({ kind: "user", id, text }));
      }
      return state;
    }
    case "hook": {
      const text = "blocked" in data ? `hook ${str(data["event"])} blocked: ${str(data["blocked"])}` : `hook ${str(data["event"])}: ${str(data["warning"])}`;
      return note(state, "warn", text);
    }
    case "brain":
      return note(state, "dim", "brain: " + (Array.isArray(data["trace"]) ? data["trace"].join(" → ") : ""));
    case "reflect":
      return note(state, "dim", "reflecting: " + (Array.isArray(data["issues"]) ? data["issues"].join("; ") : ""));
    case "verify":
      return note(state, "dim", "checking citations, rewriting");
    default:
      return state; // learning, session and kinds a later engine adds
  }
}

function onEvent(state: State, event: EngineEvent): State {
  switch (event.type) {
    case "login_required":
      return { ...state, phase: "login", login: event, loginBusy: false };
    case "ready": {
      const problem = checkVersion(event);
      if (problem) return { ...state, phase: "closed", fatal: problem, exitCode: 2 };
      return { ...state, phase: "running", ready: event, mode: event.mode, login: null, loginBusy: false };
    }
    case "text": {
      const last = state.items[state.items.length - 1];
      if (last?.kind === "assistant" && last.streaming) {
        return { ...state, items: [...state.items.slice(0, -1), { ...last, text: last.text + event.delta }] };
      }
      return push(state, (id) => ({ kind: "assistant", id, text: event.delta, streaming: true }));
    }
    case "tool_call":
      return push(closeStream(state), (id) => ({
        kind: "tool", id, callId: event.id, name: event.name, arguments: event.arguments, done: false,
      }));
    case "tool_result": {
      const at = state.items.findIndex((i) => i.kind === "tool" && i.callId === event.id);
      const found = state.items[at];
      if (found?.kind !== "tool") {
        return push(state, (id) => ({
          kind: "tool", id, callId: event.id, name: event.name, arguments: {}, result: event.result, done: true,
        }));
      }
      const items = state.items.slice();
      items[at] = { ...found, result: event.result, done: true };
      return { ...state, items };
    }
    case "plan":
      return { ...state, plan: { source: event.source, steps: event.steps } };
    case "permission_request":
      return { ...closeStream(state), permission: event };
    case "status":
      return status(state, event.kind, event.data);
    case "usage":
      return { ...state, usage: { tokens: event.tokens, window: event.window } };
    case "compact":
      return note(state, "dim", `context compacted (${event.method}): ${event.before} → ${event.after} tokens`);
    case "goal":
      return event.retry ? note(state, "warn", "goal not finished: " + event.open.map(String).join("; ")) : state;
    case "completion":
      return { ...state, completion: { id: event.id, items: event.items } };
    case "error": {
      const next = note(state, "error", event.message);
      return ENDS_COMMAND.has(event.code) ? { ...next, busy: next.pending.length > 0 } : next;
    }
    case "done": {
      let next = closeStream(state);
      if (next.plan && next.plan.steps.length > 0) {
        const { source, steps } = next.plan;
        next = push(next, (id) => ({ kind: "plan", id, source, steps }));
      }
      next = { ...next, plan: null, permission: null, busy: next.pending.length > 0 };
      if (event.status === "interrupted") next = note(next, "warn", "interrupted");
      else if (event.status !== "completed") next = note(next, "warn", `${event.status}: ${event.answer}`);
      return next;
    }
  }
}

export function reduce(state: State, action: Action): State {
  switch (action.kind) {
    case "event":
      return onEvent(state, action.event);
    case "sent":
      if (state.busy) return { ...state, pending: [...state.pending, action.text] };
      return { ...push(state, (id) => ({ kind: "user", id, text: action.text })), busy: true };
    case "answered":
      return { ...state, permission: null };
    case "login_sent":
      return { ...state, loginBusy: true };
    case "note":
      return note(state, action.level, action.text);
    case "closed": {
      if (state.phase === "closed") return state; // a version mismatch already explained itself
      const fatal = action.clean
        ? null
        : `the engine ended unexpectedly (exit code ${action.code})` + (action.stderrTail.trim() ? `:\n${action.stderrTail.trim()}` : "");
      return { ...closeStream(state), phase: "closed", busy: false, permission: null, fatal, exitCode: action.clean ? 0 : 1 };
    }
  }
}
