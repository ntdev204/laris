// `laris` with the Ink interface: start the engine program, speak E1 to it, draw what it sends.
import { spawn } from "node:child_process";
import { render } from "ink";
import { App } from "./App.js";
import { EngineClient, spawnTransport } from "./engine-client.js";
import { plan, type Env } from "./launch.js";
import type { State } from "./state.js";

export interface Context {
  exe: string;
  env?: Env;
  tty?: boolean;
}

function run(exe: string, args: string[]): Promise<number> {
  return new Promise((resolve) => {
    const child = spawn(exe, args, { stdio: "inherit" });
    child.on("error", (error) => {
      process.stderr.write(`Could not start ${exe}: ${error.message}\n`);
      resolve(1);
    });
    child.on("close", (code) => resolve(code ?? 1));
  });
}

async function session(exe: string, engineArgs: string[], initialInput: string | null): Promise<State> {
  const client = new EngineClient(spawnTransport(exe, engineArgs));
  let final: State | null = null;
  const instance = render(
    <App client={client} initialInput={initialInput} onFinish={(state) => { final = state; }} />,
    { exitOnCtrlC: false, interactive: true }, // plan() only gets here on a real terminal, even when CI is set
  );
  await instance.waitUntilExit();
  await client.stop(500);
  return final ?? ({ fatal: "the session ended before it started", exitCode: 1, ready: null } as unknown as State);
}

export async function main(argv: string[], ctx: Context): Promise<number> {
  const env = ctx.env ?? process.env;
  const tty = ctx.tty ?? Boolean(process.stdin.isTTY && process.stdout.isTTY);
  const chosen = plan(argv, env, tty);
  if (chosen.kind === "passthrough") return run(ctx.exe, chosen.args);

  // No key, no server or an unknown certificate is asked inside the interface (the engine sends
  // `login_required` before `ready`), so there is nothing to run first.
  const final = await session(ctx.exe, chosen.engineArgs, chosen.initialInput);
  if (final.fatal) process.stderr.write(`\n${final.fatal}\n`);
  else if (final.ready && final.items.some((item) => item.kind === "user")) {
    // the way back into this conversation, like the last line of a terminal session should say
    process.stderr.write(`\nResume this session with: laris --resume ${final.ready.session.slice(0, 8)}\n`);
  }
  return final.exitCode;
}
