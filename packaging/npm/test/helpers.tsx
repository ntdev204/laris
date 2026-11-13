import path from "node:path";
import { fileURLToPath } from "node:url";
import { render } from "ink-testing-library";
import { App } from "../src/App.js";
import { EngineClient, spawnTransport, type Transport } from "../src/engine-client.js";
import type { State } from "../src/state.js";

const here = path.dirname(fileURLToPath(import.meta.url));
// tests run from build/test; the fixtures stay in the source tree
export const FIXTURES = path.resolve(here, "..", "..", "test");

export const KEYS = {
  enter: "\r", esc: "\x1b", ctrlC: "\x03", ctrlD: "\x04", ctrlR: "\x12", tab: "\t", shiftTab: "\x1b[Z",
  up: "\x1b[A", down: "\x1b[B", left: "\x1b[D", right: "\x1b[C", backspace: "\x7f", ctrlU: "\x15",
} as const;

const opened: EngineClient[] = [];
/** End every engine a test started, so a failed test cannot keep the run alive. */
export async function stopAll(): Promise<void> {
  await Promise.all(opened.splice(0).map((c) => c.stop(300)));
}

export function scenarioClient(name: string): EngineClient {
  const transport = spawnTransport(process.execPath, [path.join(FIXTURES, "fake-engine.mjs"), path.join(FIXTURES, "scenarios", `${name}.json`)]);
  const client = new EngineClient(transport);
  opened.push(client);
  return client;
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function until(check: () => boolean, what: string, timeoutMs = 4000): Promise<void> {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error(`timed out waiting for ${what}`);
    await sleep(15);
  }
}

export interface Session {
  frame: () => string;
  type: (text: string) => Promise<void>;
  settle: () => Promise<void>;
  waitFor: (text: string, timeoutMs?: number) => Promise<void>;
  gone: (text: string) => Promise<void>;
  final: () => State | null;
  stdin: { write: (data: string) => void };
  unmount: () => void;
  client: EngineClient;
}

/** The interface against a recorded engine, driven by key presses. */
export function open(client: EngineClient, props: { exitWindowMs?: number; initialInput?: string | null; columns?: number } = {}): Session {
  let final: State | null = null;
  const r = render(<App client={client} onFinish={(s) => { final = s; }} {...props} />);
  const frame = () => r.lastFrame() ?? "";
  return {
    frame,
    final: () => final,
    stdin: r.stdin,
    unmount: r.unmount,
    client,
    type: async (text) => { r.stdin.write(text); await sleep(40); },
    // a dialog is on screen one frame before its key handler is attached: let it settle
    settle: async () => { await sleep(150); },
    waitFor: (text, timeoutMs) => until(() => r.frames.some((f) => f.includes(text)) || frame().includes(text), `"${text}" on screen; last frame:\n${frame()}`, timeoutMs),
    gone: (text) => until(() => !frame().includes(text), `"${text}" to leave the screen`),
  };
}

export class FakeTransport implements Transport {
  sent: string[] = [];
  private data: Array<(c: string) => void> = [];
  private exits: Array<(code: number | null, tail: string) => void> = [];
  write(text: string): void { this.sent.push(text); }
  onData(cb: (c: string) => void): void { this.data.push(cb); }
  onExit(cb: (code: number | null, tail: string) => void): void { this.exits.push(cb); }
  close(): void { this.exit(0, ""); }
  kill(): void { this.exit(137, ""); }
  emit(event: unknown): void { for (const cb of this.data) cb(JSON.stringify(event) + "\n"); }
  exit(code: number | null, tail: string): void { for (const cb of this.exits) cb(code, tail); }
  commands(): Array<Record<string, unknown>> { return this.sent.map((s) => JSON.parse(s) as Record<string, unknown>); }
}
