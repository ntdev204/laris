// End to end through the real launcher: `bin/laris.js` in an empty folder with a fresh home, on a
// pseudo-terminal (util-linux `script`; skipped where it does not exist). The engine is a recorded
// scenario unless LARIS_SMOKE_ENGINE names a real engine program (CI sets it).
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { FIXTURES } from "./helpers.js";

const BIN = path.resolve(FIXTURES, "..", "bin", "laris.js");
const hasScript = process.platform !== "win32" && spawnSync("script", ["--version"]).status === 0;
const strip = (text: string) => text.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, "");

function sandbox(): { home: string; cwd: string; dir: string } {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "laris-smoke-"));
  const home = path.join(dir, "home");
  const cwd = path.join(dir, "empty");
  fs.mkdirSync(home);
  fs.mkdirSync(cwd);
  return { home, cwd, dir };
}

function engineDouble(dir: string, scenario: string): string {
  const exe = path.join(dir, "engine.sh");
  const fake = path.join(FIXTURES, "fake-engine.mjs");
  const file = path.join(FIXTURES, "scenarios", `${scenario}.json`);
  fs.writeFileSync(exe, `#!/bin/sh\nexec "${process.execPath}" "${fake}" "${file}"\n`, { mode: 0o755 });
  return exe;
}

interface Run { output: string; code: number | null }

/** Run `node bin/laris.js args` on a pty, writing `keys` (text, then a pause in ms) as it goes. */
function onPty(args: string[], env: NodeJS.ProcessEnv, cwd: string, keys: Array<[string, number]>, bin = BIN): Promise<Run> {
  return new Promise((resolve) => {
    const command = [process.execPath, bin, ...args].map((a) => `'${a}'`).join(" ");
    const child = spawn("script", ["-qefc", command, "/dev/null"], { cwd, env: { ...process.env, ...env, TERM: "xterm", COLUMNS: "100" }, stdio: ["pipe", "pipe", "pipe"] });
    let output = "";
    child.stdout.on("data", (d: Buffer) => { output += d.toString(); });
    child.stderr.on("data", (d: Buffer) => { output += d.toString(); });
    void (async () => {
      for (const [text, wait] of keys) {
        await new Promise((r) => setTimeout(r, wait));
        child.stdin.write(text);
      }
    })();
    const killer = setTimeout(() => child.kill("SIGKILL"), 25000);
    child.on("close", (code) => { clearTimeout(killer); resolve({ output: strip(output), code }); });
  });
}

describe("npm launcher smoke", { skip: !hasScript && "needs a pseudo-terminal (util-linux script)" }, () => {
  it("starts the Ink interface in an empty folder with a fresh home, chats, and exits on Ctrl+C twice", async () => {
    const { home, cwd, dir } = sandbox();
    const exe = process.env["LARIS_SMOKE_ENGINE"] ?? engineDouble(dir, "basic_chat");
    const real = Boolean(process.env["LARIS_SMOKE_ENGINE"]);
    const keys: Array<[string, number]> = real
      ? [["/help", 6000], ["\r", 300], ["\x03", 3000], ["\x03", 200]]
      : [["hello", 1500], ["\r", 200], ["\x03", 1500], ["\x03", 200]];
    const run = await onPty([], { HOME: home, USERPROFILE: home, LARIS_ENGINE_BIN: exe, LARIS_API_KEY: "smoke-key" }, cwd, keys);
    assert.match(run.output, /Try "summarise the documents/, run.output);
    assert.match(run.output, /default/); // the status line
    if (!real) assert.match(run.output, /Found 2 passages\./, run.output);
    assert.match(run.output, /Press Ctrl\+C again to exit/);
    assert.equal(run.code, 0, run.output);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("reports a protocol version mismatch and exits with code 2", async () => {
    const { home, cwd, dir } = sandbox();
    const run = await onPty([], { HOME: home, LARIS_ENGINE_BIN: engineDouble(dir, "mismatch") }, cwd, []);
    assert.match(run.output, /E1 version 1 but the engine reports "9"/, run.output);
    assert.equal(run.code, 2, run.output);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("without a terminal, arguments go straight to the engine program", () => {
    const { home, cwd, dir } = sandbox();
    const exe = path.join(dir, "echo.sh");
    fs.writeFileSync(exe, '#!/bin/sh\necho "ARGS: $@"\n', { mode: 0o755 });
    const run = spawnSync(process.execPath, [BIN, "-p", "hi"], { cwd, env: { ...process.env, HOME: home, LARIS_ENGINE_BIN: exe }, encoding: "utf8" });
    assert.equal(run.stdout.trim(), "ARGS: -p hi");
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("when the interface cannot load, the launcher says so and starts plain mode", () => {
    const { home, cwd, dir } = sandbox();
    const lonely = path.join(dir, "bin");
    fs.mkdirSync(lonely);
    fs.copyFileSync(BIN, path.join(lonely, "laris.js")); // no ../build beside it
    fs.writeFileSync(path.join(dir, "package.json"), '{"type":"module"}');
    const exe = path.join(dir, "echo.sh");
    fs.writeFileSync(exe, '#!/bin/sh\necho "ARGS: $@"\n', { mode: 0o755 });
    const run = spawnSync(process.execPath, [path.join(lonely, "laris.js"), "--resume", "x"], { cwd, env: { ...process.env, HOME: home, LARIS_ENGINE_BIN: exe }, encoding: "utf8" });
    assert.match(run.stderr, /interface could not start/);
    assert.equal(run.stdout.trim(), "ARGS: --plain --resume x");
    fs.rmSync(dir, { recursive: true, force: true });
  });
});
