// The connection to `laris engine --stdio`: JSON lines both ways.
import { spawn } from "node:child_process";
import { encodeCommand, parseLine, type EngineCommand, type EngineEvent } from "./protocol.js";

export interface Transport {
  write(text: string): void;
  onData(cb: (chunk: string) => void): void;
  onExit(cb: (code: number | null, stderrTail: string) => void): void;
  /** Ask the engine to stop (closing its input); `kill` ends it at once. */
  close(): void;
  kill(): void;
}

export function spawnTransport(exe: string, args: string[], env: NodeJS.ProcessEnv = process.env): Transport {
  const child = spawn(exe, args, { stdio: ["pipe", "pipe", "pipe"], env });
  let tail = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (text: string) => {
    tail = (tail + text).slice(-4000);
  });
  child.stdout.setEncoding("utf8");
  child.stdin.on("error", () => undefined); // the engine ended first: onExit reports it
  return {
    write: (text) => {
      if (!child.stdin.destroyed) child.stdin.write(text);
    },
    onData: (cb) => child.stdout.on("data", cb),
    onExit: (cb) => {
      let done = false;
      const finish = (code: number | null) => {
        if (!done) {
          done = true;
          cb(code, tail);
        }
      };
      child.on("close", (code) => finish(code));
      child.on("error", (error) => {
        tail += `\n${error.message}`;
        finish(127);
      });
    },
    close: () => child.stdin.end(),
    kill: () => child.kill(),
  };
}

export type Listener = (event: EngineEvent) => void;

export class EngineClient {
  private buffer = "";
  private listeners: Listener[] = [];
  // events that arrive before anyone listens (the `ready` of a fast engine) are kept, not lost
  private backlog: EngineEvent[] = [];
  private exits: Array<(code: number | null, stderrTail: string) => void> = [];
  private problems: Array<(message: string) => void> = [];
  exited = false;

  constructor(private readonly transport: Transport) {
    transport.onData((chunk) => this.feed(chunk));
    transport.onExit((code, tail) => {
      this.feed("\n"); // a last line without a newline
      this.exited = true;
      for (const cb of this.exits) cb(code, tail);
    });
  }

  private feed(chunk: string): void {
    this.buffer += chunk;
    let at = this.buffer.indexOf("\n");
    while (at >= 0) {
      const line = this.buffer.slice(0, at).trim();
      this.buffer = this.buffer.slice(at + 1);
      if (line) this.handle(line);
      at = this.buffer.indexOf("\n");
    }
  }

  private handle(line: string): void {
    const parsed = parseLine(line);
    if (!parsed.ok) {
      for (const cb of this.problems) cb(parsed.error);
      return;
    }
    if (this.listeners.length === 0) this.backlog.push(parsed.event);
    for (const cb of this.listeners) cb(parsed.event);
  }

  onEvent(cb: Listener): void {
    const first = this.listeners.length === 0;
    this.listeners.push(cb);
    if (first) for (const event of this.backlog.splice(0)) cb(event);
  }
  onExit(cb: (code: number | null, stderrTail: string) => void): void { this.exits.push(cb); }
  onProblem(cb: (message: string) => void): void { this.problems.push(cb); }

  send(command: EngineCommand): void {
    if (!this.exited) this.transport.write(encodeCommand(command));
  }

  /** shutdown, then close the input; kill the engine if it has not ended after `graceMs`. */
  stop(graceMs = 3000): Promise<void> {
    if (this.exited) return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.transport.kill();
        resolve();
      }, graceMs);
      timer.unref();
      this.onExit(() => {
        clearTimeout(timer);
        resolve();
      });
      this.send({ type: "shutdown" });
      this.transport.close();
    });
  }
}
