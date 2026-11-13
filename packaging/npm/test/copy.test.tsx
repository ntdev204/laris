import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import { afterEach, describe, it } from "node:test";
import { render as inkRender } from "ink";
import { cleanup } from "ink-testing-library";
import { App } from "../src/App.js";
import { copyText, nativeTools, osc52 } from "../src/clipboard.js";
import { copyTarget } from "../src/copy.js";
import type { Item } from "../src/state.js";
import { KEYS, open, scenarioClient, sleep, stopAll } from "./helpers.js";

afterEach(async () => {
  cleanup();
  await stopAll();
});

const answer = (text: string, id = 1): Item => ({ kind: "assistant", id, text, streaming: false });
const TEXT = "Intro line.\n\n```python\nfor i in range(3):\n    print(i)\n\n    done = True\n```\n\n- one\n- two\n";

describe("what /copy puts on the clipboard", () => {
  it("is the original Markdown of the last answer, trimmed at the end only", () => {
    const items: Item[] = [answer("old"), { kind: "user", id: 2, text: "q" }, answer(TEXT, 3)];
    assert.deepEqual(copyTarget(items, ""), { text: TEXT.trim(), what: "the last answer" });
  });
  it("joins the parts of one answer that tool calls separated", () => {
    const items: Item[] = [{ kind: "user", id: 1, text: "q" }, answer("Before.", 2), { kind: "note", id: 3, level: "dim", text: "tool" }, answer("After.", 4)];
    assert.deepEqual(copyTarget(items, ""), { text: "Before.\n\nAfter.", what: "the last answer" });
  });
  it("can be the last code block alone, with its indentation and blank line", () => {
    const got = copyTarget([answer(TEXT)], "code");
    assert.deepEqual(got, { text: "for i in range(3):\n    print(i)\n\n    done = True", what: "the last code block" });
  });
  it("says so when there is nothing to copy, and rejects unknown words", () => {
    assert.match((copyTarget([], "") as { error: string }).error, /no answer/);
    assert.match((copyTarget([answer("no code here")], "code") as { error: string }).error, /no code block/);
    assert.match((copyTarget([answer("x")], "everything") as { error: string }).error, /\/copy \[code\]/);
  });
});

describe("the clipboard", () => {
  it("encodes OSC 52 and wraps it for tmux", () => {
    assert.equal(osc52("héllo\n  x", {}), `\x1b]52;c;${Buffer.from("héllo\n  x").toString("base64")}\x07`);
    assert.match(osc52("a", { TMUX: "/tmp/t" }), /^\x1bPtmux;\x1b\x1b\]52;c;YQ==\x07\x1b\\$/);
  });
  it("tries the native tool of the platform first and falls back to OSC 52", async () => {
    const calls: string[] = [];
    const sink: string[] = [];
    const fail = async (cmd: string) => { calls.push(cmd); return false; };
    const env = { WAYLAND_DISPLAY: "w", DISPLAY: ":0" };
    assert.equal(await copyText("x", { env, platform: "linux", runner: fail, out: { write: (d) => sink.push(d as string) } }), "osc52");
    assert.deepEqual(calls, ["wl-copy", "xclip", "xsel", "clip.exe"]);
    assert.equal(sink.length, 1);
    const ok = async () => true;
    assert.equal(await copyText("x", { env, platform: "darwin", runner: ok }), "native");
  });
  it("uses OSC 52 only over SSH, and reports nothing possible without a terminal", async () => {
    const calls: string[] = [];
    const sink: string[] = [];
    const run = async (cmd: string) => { calls.push(cmd); return true; };
    assert.equal(await copyText("x", { env: { SSH_TTY: "/dev/pts/1" }, platform: "linux", runner: run, out: { write: (d) => sink.push(d as string) } }), "osc52");
    assert.deepEqual(calls, []);
    assert.equal(await copyText("x", { env: {}, platform: "linux", runner: async () => false, out: undefined }), process.stdout.isTTY ? "osc52" : null);
    assert.deepEqual(nativeTools("win32", {}), [["clip.exe", []]]);
  });
});

describe("selecting and copying in the interface", () => {
  it("draws code and lists with no frame, gutter or padding that a selection would copy", async () => {
    const s = open(scenarioClient("basic_chat"));
    await s.waitFor("develop");
    await s.type("hello");
    await s.type(KEYS.enter);
    await s.waitFor("for i in range(3):");
    const lines = s.frame().split("\n");
    assert.ok(lines.includes("for i in range(3):"), "code starts at column 0");
    assert.ok(lines.includes("    print(i)  # count"), "indentation is the code's own");
    assert.ok(lines.every((l) => l === l.trimEnd()), "no trailing blanks on any line");
    const answerLines = lines.filter((l) => /Hi, this is|passages|for i in|print\(i\)/.test(l) && !/search_papers|⎿/.test(l));
    assert.ok(answerLines.every((l) => !/[│╭╮╰╯]/.test(l)), "no frame characters around code");
    await s.client.stop();
  });

  it("never asks the terminal for mouse reporting or the alternate screen, so native selection works", async () => {
    const out = Object.assign(new PassThrough(), { columns: 80, rows: 24, isTTY: true });
    let raw = "";
    out.on("data", (d) => { raw += d; });
    const client = scenarioClient("basic_chat");
    const inst = inkRender(<App client={client} onFinish={() => undefined} />, { stdout: out as unknown as NodeJS.WriteStream, stdin: Object.assign(new PassThrough(), { isTTY: true, setRawMode() {}, ref() {}, unref() {} }) as unknown as NodeJS.ReadStream, exitOnCtrlC: false });
    await sleep(400);
    inst.unmount();
    assert.ok(raw.length > 0);
    assert.doesNotMatch(raw, /\x1b\[\?(1000|1002|1003|1006|1015|1049|47)[hl]/);
  });

  it("/copy sends the plain answer to the clipboard and does not reach the engine", async () => {
    const copied: string[] = [];
    const client = scenarioClient("basic_chat");
    const s = open(client, { copy: async (t) => { copied.push(t); return "native"; } });
    await s.waitFor("develop");
    await s.type("hello");
    await s.type(KEYS.enter);
    await s.waitFor("for i in range(3):");
    await s.type("/copy code");
    await s.type(KEYS.enter);
    await s.waitFor("Copied the last code block");
    assert.deepEqual(copied, ["for i in range(3):\n    print(i)  # count"]);
    await s.type("/copy");
    await s.type(KEYS.enter);
    await s.waitFor("Copied the last answer");
    assert.match(copied[1] as string, /^Hi, this is \*\*bold\*\* and `code`\.\n\nFound 2 passages\./);
    await s.client.stop();
  });

  it("/copy with nothing to copy says so", async () => {
    const s = open(scenarioClient("basic_chat"), { copy: async () => "native" });
    await s.waitFor("develop");
    await s.type("/copy");
    await s.type(KEYS.enter);
    await s.waitFor("There is no answer to copy yet.");
    await s.client.stop();
  });
});
