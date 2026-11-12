// Engine protocol E1 as the front end sees it (SR-C7). The engine owns the contract: the JSON
// Schema in `laris.protocol` is the source of truth and test/protocol.test.ts checks this file
// against the copy shipped with the engine. The front end holds no tool, permission or storage
// logic; it draws events and sends commands.

export const E1_VERSION = "1";

export type Scope = "once" | "session" | "project" | "everywhere";
export type Mode = "default" | "acceptEdits" | "plan" | "bypass";

export interface Ready { type: "ready"; version: string; engine: string; session: string; cwd: string; mode: string; server: string }
export interface TextEvent { type: "text"; delta: string }
export interface ToolCall { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
export interface ToolResult { type: "tool_result"; id: string; name: string; result: unknown }
export interface PlanStep { text?: string; status?: string; [key: string]: unknown }
export interface PlanEvent { type: "plan"; source: string; steps: PlanStep[] }
export interface PermissionRequest {
  type: "permission_request"; id: string; tool: string; arguments: Record<string, unknown>;
  reason: string; rule: string; diff: string; scopes: Scope[];
}
export interface StatusEvent { type: "status"; kind: string; data: Record<string, unknown> }
export interface Usage { type: "usage"; tokens: number; window: number }
export interface Compact { type: "compact"; before: number; after: number; summarized: number; method: string }
export interface Goal { type: "goal"; complete: boolean; open: unknown[]; failed: unknown[]; retry: boolean }
export interface CompletionItem { value: string; description: string }
export interface Completion { type: "completion"; id: string; items: CompletionItem[] }
export interface ErrorEvent { type: "error"; code: string; message: string }
export interface Done { type: "done"; status: string; answer: string }

export type EngineEvent =
  | Ready | TextEvent | ToolCall | ToolResult | PlanEvent | PermissionRequest | StatusEvent
  | Usage | Compact | Goal | Completion | ErrorEvent | Done;

export const EVENT_TYPES = [
  "ready", "text", "tool_call", "tool_result", "plan", "permission_request", "status", "usage",
  "compact", "goal", "completion", "error", "done",
] as const;

export interface Attachment { kind: "image" | "text"; name: string; data_base64: string }
export type EngineCommand =
  | { type: "user_message"; text: string; attachments?: Attachment[] }
  | { type: "permission_response"; id: string; decision: "allow" | "deny"; scope: Scope }
  | { type: "interrupt" }
  | { type: "command"; name: string; args: string }
  | { type: "set_mode"; mode: Mode | "next" }
  | { type: "complete"; id: string; trigger: "/" | "@"; text: string }
  | { type: "shutdown" };

export const COMMAND_TYPES = [
  "user_message", "permission_response", "interrupt", "command", "set_mode", "complete", "shutdown",
] as const;

// Errors that answer a command and are not followed by a `done` event.
export const ENDS_COMMAND = new Set(["unknown_command", "command_failed", "bad_command", "bad_mode", "busy"]);

/** null when the engine speaks this version, else the message to show (same text as the engine's). */
export function checkVersion(ready: { version?: unknown }, supported: string = E1_VERSION): string | null {
  if (ready.version === supported) return null;
  return (
    `this front end speaks engine protocol E1 version ${supported} but the engine reports ` +
    `${JSON.stringify(ready.version ?? null)}; update the laris program and the front end together`
  );
}

export type Parsed = { ok: true; event: EngineEvent } | { ok: false; error: string };

/** One line of engine output. Unknown event types are an error, not a crash. */
export function parseLine(line: string): Parsed {
  let data: unknown;
  try {
    data = JSON.parse(line);
  } catch {
    return { ok: false, error: `not JSON: ${line.slice(0, 120)}` };
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return { ok: false, error: "event must be a JSON object" };
  }
  const type = (data as { type?: unknown }).type;
  if (typeof type !== "string" || !(EVENT_TYPES as readonly string[]).includes(type)) {
    return { ok: false, error: `unknown event type ${JSON.stringify(type ?? null)}` };
  }
  return { ok: true, event: data as EngineEvent };
}

export function encodeCommand(command: EngineCommand): string {
  return JSON.stringify(command) + "\n";
}
