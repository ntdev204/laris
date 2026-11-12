import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { cleanup } from "ink-testing-library";
import { EngineClient } from "../src/engine-client.js";
import { FakeTransport, KEYS, open, scenarioClient, sleep, stopAll, until } from "./helpers.js";

afterEach(async () => {
  cleanup();
  await stopAll();
});

describe("scenarios through a recorded engine", () => {
  it("draws a streamed answer with Markdown, highlighting, a tool call and the status line", async () => {
    const s = open(scenarioClient("basic_chat"));
    await s.waitFor("develop"); // the status line from `ready`
    assert.match(s.frame(), /laris-base · default · context 15% · 750 tokens left · ⎇ develop/);
    await s.type("hello");
    await s.type(KEYS.enter);
    await s.waitFor("Found 2 passages.");
    const frame = s.frame();
    assert.match(frame, /> hello/);
    assert.match(frame, /Hi, this is bold and code\./);
    assert.match(frame, /search_papers/);
    assert.match(frame, /2 passages/);
    assert.match(frame, /for i in range\(3\):/);
    await s.waitFor("context 19%"); // the line is refreshed after the turn
    await s.client.stop();
  });

  it("asks before a write, shows the diff and sends the chosen scope", async () => {
    const s = open(scenarioClient("approval"));
    await s.waitFor("session abcdef12");
    await s.type("write a note");
    await s.type(KEYS.enter);
    await s.waitFor("Permission: write_file");
    assert.match(s.frame(), /\+hello/);
    assert.match(s.frame(), /Yes, and don't ask again in this project/);
    await s.settle();
    await s.type("p");
    await s.waitFor("Done.");
    assert.equal(s.client.exited, false); // the scripted engine accepted the project-scoped answer
    await s.client.stop();
  });

  it("a refusal is sent as deny, and Esc at the dialog refuses too", async () => {
    const s = open(scenarioClient("refusal"));
    await s.waitFor("session abcdef12");
    await s.type("write a note");
    await s.type(KEYS.enter);
    await s.waitFor("Permission: write_file");
    await s.settle();
    await s.type("n");
    await s.waitFor("I did not write it.");
    await s.client.stop();
  });

  it("Esc interrupts the turn and the next message still works", async () => {
    const s = open(scenarioClient("interrupt"));
    await s.waitFor("session abcdef12");
    await s.type("think hard");
    await s.type(KEYS.enter);
    await s.waitFor("Let me think");
    await s.waitFor("esc to interrupt"); // the spinner
    await s.settle();
    await s.type(KEYS.esc);
    await s.waitFor("interrupted");
    await s.gone("esc to interrupt");
    await s.type("again");
    await s.type(KEYS.enter);
    await s.waitFor("Second answer.");
    await s.client.stop();
  });

  it("sends slash commands, reports an unknown one and goes on", async () => {
    const s = open(scenarioClient("slash"));
    await s.waitFor("session abcdef12");
    await s.type("/help");
    await s.type(KEYS.enter);
    await s.waitFor("Commands: /help /exit");
    await s.type("/nope x y");
    await s.type(KEYS.enter);
    await s.waitFor("unknown command /nope");
    await s.type("still alive");
    await s.type(KEYS.enter);
    await s.waitFor("yes");
    await s.client.stop();
  });

  it("a message typed while the agent works is queued and answered next", async () => {
    const s = open(scenarioClient("queued"));
    await s.waitFor("session abcdef12");
    await s.type("first");
    await s.type(KEYS.enter);
    await s.waitFor("working on first");
    await s.type("second");
    await s.type(KEYS.enter);
    await s.waitFor("queued: second");
    await s.waitFor("answer to second");
    assert.match(s.frame(), /> second/);
    await s.client.stop();
  });

  it("completes / and @ with what the engine answers", async () => {
    const s = open(scenarioClient("completion"));
    await s.waitFor("session abcdef12");
    await s.type("/he");
    await s.waitFor("list commands");
    await s.type(KEYS.tab);
    await s.waitFor("/help");
    await s.type("@sr");
    await s.waitFor("srv.py");
    assert.match(s.frame(), /src\//);
    await s.type(KEYS.tab);
    await s.waitFor("@src/");
    await s.client.stop();
  });

  it("reports a version mismatch and ends with code 2", async () => {
    const s = open(scenarioClient("mismatch"));
    await until(() => s.final() !== null, "the session to end");
    const final = s.final();
    assert.equal(final?.exitCode, 2);
    assert.match(final?.fatal ?? "", /E1 version 1 but the engine reports "9"/);
  });
});

describe("keys", () => {
  const fake = () => {
    const t = new FakeTransport();
    const client = new EngineClient(t);
    t.emit({ type: "ready", version: "1", engine: "2", session: "s1234567", cwd: "/w", mode: "default", server: "" });
    return { t, client };
  };

  it("Ctrl+C twice exits; once only warns", async () => {
    const { t, client } = fake();
    const s = open(client, { exitWindowMs: 300 });
    await s.waitFor("session s1234567");
    await s.type(KEYS.ctrlC);
    await s.waitFor("Press Ctrl+C again to exit");
    await s.gone("Press Ctrl+C again to exit"); // the window closes by itself
    assert.equal(client.exited, false);
    await s.type(KEYS.ctrlC);
    await s.type(KEYS.ctrlC);
    await until(() => s.final() !== null, "exit");
    assert.ok(t.commands().some((c) => c["type"] === "shutdown"));
    assert.equal(s.final()?.exitCode, 0);
  });

  it("Ctrl+C clears a typed line before it counts toward exit; Ctrl+D leaves from an empty prompt", async () => {
    const { t, client } = fake();
    const s = open(client);
    await s.waitFor("session s1234567");
    await s.type("some text");
    await s.waitFor("some text");
    await s.type(KEYS.ctrlC);
    await s.gone("some text");
    await s.type(KEYS.ctrlD);
    await until(() => s.final() !== null, "exit");
    assert.ok(t.commands().some((c) => c["type"] === "shutdown"));
  });

  it("Shift+Tab asks the engine for the next permission mode", async () => {
    const { t, client } = fake();
    const s = open(client);
    await s.waitFor("session s1234567");
    await s.type(KEYS.shiftTab);
    await until(() => t.commands().some((c) => c["type"] === "set_mode" && c["mode"] === "next"), "set_mode");
    t.emit({ type: "status", kind: "mode", data: { mode: "acceptEdits" } });
    await s.waitFor("acceptEdits");
    await s.client.stop();
  });

  it("multi-line input: backslash+Enter adds a line, Enter sends all of it", async () => {
    const { t, client } = fake();
    const s = open(client);
    await s.waitFor("session s1234567");
    await s.type("first line\\");
    await s.type(KEYS.enter);
    await s.type("second line");
    await s.type(KEYS.enter);
    await until(() => t.commands().some((c) => c["type"] === "user_message"), "user_message");
    const sent = t.commands().find((c) => c["type"] === "user_message");
    assert.equal(sent?.["text"], "first line\nsecond line");
    await s.client.stop();
  });

  it("Up recalls the previous message; Ctrl+R searches the history", async () => {
    const { t, client } = fake();
    const s = open(client);
    await s.waitFor("session s1234567");
    for (const text of ["alpha one", "beta two"]) {
      await s.type(text);
      await s.type(KEYS.enter);
      t.emit({ type: "done", status: "completed", answer: "" });
      await sleep(60);
    }
    await s.type(KEYS.up);
    await s.waitFor("beta two");
    await s.type(KEYS.up);
    await s.waitFor("alpha one");
    await s.type(KEYS.down);
    await s.type(KEYS.down);
    await s.type(KEYS.ctrlR);
    await s.waitFor("(history search)");
    await s.type("alp");
    await s.waitFor("alpha one");
    await s.type(KEYS.enter);
    await s.waitFor("> alpha one");
    await s.client.stop();
  });

  it("a long paste becomes a placeholder and is sent in full", async () => {
    const { t, client } = fake();
    const s = open(client);
    await s.waitFor("session s1234567");
    const long = Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n");
    s.stdin.write(`\x1b[200~${long}\x1b[201~`);
    await s.waitFor("[Pasted text #1 +12 lines]");
    await s.type(KEYS.enter);
    await until(() => t.commands().some((c) => c["type"] === "user_message"), "user_message");
    assert.equal(t.commands().find((c) => c["type"] === "user_message")?.["text"], long);
    await s.client.stop();
  });

  it("the engine dying is shown with its error text and ends with code 1", async () => {
    const t = new FakeTransport();
    const client = new EngineClient(t);
    const s = open(client);
    t.exit(2, "[ERROR] no API key: set LARIS_API_KEY or run `laris login`");
    await until(() => s.final() !== null, "end");
    assert.equal(s.final()?.exitCode, 1);
    assert.match(s.final()?.fatal ?? "", /no API key/);
  });
});
