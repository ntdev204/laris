import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import * as ed from "../src/input/editor.js";
import { applyCompletion, currentTrigger } from "../src/input/completion.js";
import { History } from "../src/input/history.js";
import { highlightLine, languageOf } from "../src/highlight.js";
import { parseInline, parseMarkdown } from "../src/markdown.js";
import { plan } from "../src/launch.js";
import { COMMAND_TYPES, E1_VERSION, EVENT_TYPES, checkVersion, parseLine } from "../src/protocol.js";
import { initialState, isFinal, reduce, type State } from "../src/state.js";
import { argsPreview, compactNumber, diffKind, statusLine, summarise } from "../src/format.js";
import { EngineClient } from "../src/engine-client.js";
import { FakeTransport, FIXTURES } from "./helpers.js";

describe("protocol", () => {
  it("accepts every event type and rejects the rest without throwing", () => {
    for (const type of EVENT_TYPES) assert.equal(parseLine(JSON.stringify({ type })).ok, true, type);
    assert.equal(parseLine("{nope").ok, false);
    assert.equal(parseLine("[1]").ok, false);
    const unknown = parseLine('{"type":"surprise"}');
    assert.equal(unknown.ok, false);
    assert.match(unknown.ok ? "" : unknown.error, /unknown event type "surprise"/);
  });

  it("says the same thing as the engine on a version mismatch", () => {
    assert.equal(checkVersion({ version: E1_VERSION }), null);
    assert.equal(
      checkVersion({ version: "2" }),
      'this front end speaks engine protocol E1 version 1 but the engine reports "2"; update the laris program and the front end together',
    );
  });

  it("matches the schema the engine ships (events, commands, version)", (t) => {
    const file = path.resolve(FIXTURES, "..", "..", "..", "src", "laris", "protocol", "e1.schema.json");
    if (!fs.existsSync(file)) return t.skip("not in a source checkout");
    const schema = JSON.parse(fs.readFileSync(file, "utf8")) as {
      version: string;
      events: { $defs: Record<string, { properties: { type?: { const?: string } } }> };
      commands: { $defs: Record<string, { properties: { type?: { const?: string } } }> };
    };
    const typesOf = (defs: typeof schema.events.$defs) =>
      Object.values(defs).map((d) => d.properties.type?.const).filter((x): x is string => Boolean(x)).sort();
    assert.equal(schema.version, E1_VERSION);
    assert.deepEqual(typesOf(schema.events.$defs), [...EVENT_TYPES].sort());
    assert.deepEqual(typesOf(schema.commands.$defs), [...COMMAND_TYPES].sort());
  });
});

describe("engine client", () => {
  it("splits chunks into lines, keeps events that arrive before a listener, reports bad lines", () => {
    const t = new FakeTransport();
    const client = new EngineClient(t);
    const seen: string[] = [];
    const problems: string[] = [];
    t.emit({ type: "text", delta: "early" }); // before anyone listens
    client.onProblem((m) => problems.push(m));
    client.onEvent((e) => seen.push(e.type === "text" ? e.delta : e.type));
    (t as unknown as { data: Array<(c: string) => void> }).data[0]?.('{"type":"te');
    (t as unknown as { data: Array<(c: string) => void> }).data[0]?.('xt","delta":"split"}\nnot json\n{"type":"done","status":"completed","answer":""}\n');
    assert.deepEqual(seen, ["early", "split", "done"]);
    assert.equal(problems.length, 1);
  });

  it("stop sends shutdown and resolves when the engine ends", async () => {
    const t = new FakeTransport();
    const client = new EngineClient(t);
    await client.stop();
    assert.ok(t.commands().some((c) => c["type"] === "shutdown"));
    assert.equal(client.exited, true);
  });
});

describe("state", () => {
  const ready = { type: "ready", version: "1", engine: "2", session: "s", cwd: "/w", mode: "default", server: "" } as const;
  const play = (...actions: Parameters<typeof reduce>[1][]): State => actions.reduce(reduce, initialState());
  const ev = (event: unknown) => ({ kind: "event", event }) as Parameters<typeof reduce>[1];

  it("text streams into one assistant item that a tool call closes", () => {
    const s = play(ev(ready), ev({ type: "text", delta: "a" }), ev({ type: "text", delta: "b" }),
      ev({ type: "tool_call", id: "c1", name: "t", arguments: {} }), ev({ type: "text", delta: "c" }));
    assert.deepEqual(s.items.map((i) => i.kind), ["assistant", "tool", "assistant"]);
    assert.equal((s.items[0] as { text: string }).text, "ab");
    assert.equal(isFinal(s.items[0]!), true);
    assert.equal(isFinal(s.items[1]!), false); // the call has no result yet
    const done = reduce(s, ev({ type: "tool_result", id: "c1", name: "t", result: 1 }));
    assert.equal(isFinal(done.items[1]!), true);
  });

  it("queues messages while busy and starts them on the engine's word", () => {
    let s = play(ev(ready), { kind: "sent", text: "one" }, { kind: "sent", text: "two" });
    assert.equal(s.busy, true);
    assert.deepEqual(s.pending, ["two"]);
    s = reduce(s, ev({ type: "done", status: "completed", answer: "" }));
    assert.equal(s.busy, true); // something is waiting
    s = reduce(s, ev({ type: "status", kind: "queued", data: { count: 0, started: "two" } }));
    assert.deepEqual(s.pending, []);
    assert.deepEqual(s.items.map((i) => i.kind === "user" && i.text), ["one", "two"]);
    s = reduce(s, ev({ type: "done", status: "completed", answer: "" }));
    assert.equal(s.busy, false);
  });

  it("an error that answers a command ends the busy state; others do not", () => {
    const base = play(ev(ready), { kind: "sent", text: "/x" });
    assert.equal(reduce(base, ev({ type: "error", code: "unknown_command", message: "m" })).busy, false);
    assert.equal(reduce(base, ev({ type: "error", code: "model_failed", message: "m" })).busy, true);
  });

  it("a permission request is held until answered; done clears it", () => {
    const req = { type: "permission_request", id: "p", tool: "w", arguments: {}, reason: "", rule: "", diff: "", scopes: ["once"] };
    let s = play(ev(ready), ev(req));
    assert.equal(s.permission?.id, "p");
    s = reduce(s, { kind: "answered" });
    assert.equal(s.permission, null);
    s = reduce(reduce(s, ev(req)), ev({ type: "done", status: "interrupted", answer: "" }));
    assert.equal(s.permission, null);
    assert.equal((s.items.at(-1) as { text: string }).text, "interrupted");
  });

  it("status events fill the status line, the mode and the sandbox", () => {
    const s = play(ev(ready),
      ev({ type: "status", kind: "line", data: { model: "m", mode: "plan", branch: "b" } }),
      ev({ type: "status", kind: "sandbox", data: { state: "building", hint: "wait" } }),
      ev({ type: "status", kind: "mode", data: { mode: "acceptEdits" } }));
    assert.equal(s.mode, "acceptEdits");
    assert.equal(s.line?.branch, "b");
    assert.equal(s.sandbox?.state, "building");
  });

  it("a version mismatch closes the session with code 2", () => {
    const s = play(ev({ ...ready, version: "7" }));
    assert.equal(s.phase, "closed");
    assert.equal(s.exitCode, 2);
    assert.match(s.fatal ?? "", /E1 version 1 but the engine reports "7"/);
  });

  it("an unexpected end is fatal with the engine's own words; a requested one is clean", () => {
    const dead = play(ev(ready), { kind: "closed", code: 2, stderrTail: "[ERROR] boom\n", clean: false });
    assert.equal(dead.exitCode, 1);
    assert.match(dead.fatal ?? "", /exit code 2\):\n\[ERROR\] boom/);
    const clean = play(ev(ready), { kind: "closed", code: 0, stderrTail: "", clean: true });
    assert.equal(clean.fatal, null);
    assert.equal(clean.exitCode, 0);
  });

  it("a plan is shown live and kept in the transcript when the turn ends", () => {
    let s = play(ev(ready), ev({ type: "plan", source: "agent", steps: [{ text: "a", status: "done" }] }));
    assert.equal(s.plan?.steps.length, 1);
    s = reduce(s, ev({ type: "done", status: "completed", answer: "" }));
    assert.equal(s.plan, null);
    assert.equal(s.items.at(-1)?.kind, "plan");
  });
});

describe("editor", () => {
  it("edits and moves across lines", () => {
    let b = ed.insert(ed.insert(ed.empty(), "abc"), "\ndef");
    assert.equal(b.text, "abc\ndef");
    b = ed.up(b);
    assert.deepEqual(ed.position(b), { row: 0, column: 3 });
    b = ed.home(b);
    assert.equal(b.cursor, 0);
    assert.equal(ed.onFirstLine(b), true);
    b = ed.down(b);
    assert.deepEqual(ed.position(b), { row: 1, column: 0 });
    assert.equal(ed.onLastLine(b), true);
    b = ed.backspace(b); // joins the lines
    assert.equal(b.text, "abcdef");
  });

  it("word moves and kills", () => {
    const b = ed.fromText("one two three");
    assert.equal(ed.deleteWordBack(b).text, "one two ");
    assert.equal(ed.wordLeft(b).cursor, 8);
    assert.equal(ed.wordRight({ text: "one two", cursor: 0 }).cursor, 3);
    assert.equal(ed.killToStart({ text: "a\nbcd", cursor: 4 }).text, "a\nd");
    assert.equal(ed.killToEnd({ text: "ab\ncd", cursor: 1 }).text, "a\ncd");
    assert.equal(ed.killToEnd({ text: "ab\ncd", cursor: 2 }).text, "abcd");
    assert.equal(ed.del({ text: "ab", cursor: 2 }).text, "ab");
  });
});

describe("history", () => {
  it("walks back and forth and brings the draft back", () => {
    const h = new History();
    h.add("one");
    h.add("two");
    h.add("two"); // no duplicate in a row
    assert.deepEqual(h.all(), ["one", "two"]);
    assert.equal(h.previous("draft"), "two");
    assert.equal(h.previous("x"), "one");
    assert.equal(h.previous("x"), null);
    assert.equal(h.next(), "two");
    assert.equal(h.next(), "draft");
    assert.equal(h.next(), null);
  });
  it("searches backwards, case-insensitively", () => {
    const h = new History(["alpha", "Beta", "alphabet"]);
    assert.equal(h.search("alp"), 2);
    assert.equal(h.search("alp", 1), 0);
    assert.equal(h.search("BETA"), 1);
    assert.equal(h.search("zzz"), -1);
  });
});

describe("completion triggers", () => {
  it("finds / at the start and @ anywhere, and not inside words", () => {
    assert.deepEqual(currentTrigger("/he", 3), { trigger: "/", text: "he", start: 0 });
    assert.equal(currentTrigger("say /he", 7), null);
    assert.deepEqual(currentTrigger("read @src/a", 11), { trigger: "@", text: "src/a", start: 5 });
    assert.equal(currentTrigger("me@example.com", 14), null);
    assert.equal(currentTrigger("/help arg", 9), null);
  });
  it("applies a choice", () => {
    const t = currentTrigger("read @sr", 8)!;
    assert.deepEqual(applyCompletion("read @sr", 8, t, "src/"), { text: "read @src/", cursor: 10 });
    assert.deepEqual(applyCompletion("read @sr", 8, t, "srv.py"), { text: "read @srv.py ", cursor: 13 });
    assert.equal(applyCompletion("/he", 3, currentTrigger("/he", 3)!, "help").text, "/help ");
  });
});

describe("markdown and highlighting", () => {
  it("parses inline styles and leaves a lone marker alone", () => {
    assert.deepEqual(parseInline("a **b** `c` *d*"), [
      { text: "a " }, { text: "b", bold: true }, { text: " " }, { text: "c", code: true }, { text: " " }, { text: "d", italic: true },
    ]);
    assert.deepEqual(parseInline("2 ** 3"), [{ text: "2 ** 3" }]);
    assert.deepEqual(parseInline("snake_case_name"), [{ text: "snake_case_name" }]);
    assert.deepEqual(parseInline("[x](http://a.b)"), [{ text: "x", link: "http://a.b" }]);
  });

  it("parses blocks, including a code fence that is still streaming", () => {
    const blocks = parseMarkdown("# T\n\ntext\nmore\n\n- a\n- b\n\n1. x\n\n> q\n\n---\n\n```py\nprint(1)");
    assert.deepEqual(blocks.map((b) => b.kind), ["heading", "paragraph", "list", "list", "quote", "rule", "code"]);
    const code = blocks.at(-1)!;
    assert.equal(code.kind === "code" && code.closed, false);
    assert.equal(code.kind === "code" && code.lines[0], "print(1)");
    const closed = parseMarkdown("```\nx\n```\nafter");
    assert.equal(closed[0]?.kind === "code" && closed[0].closed, true);
    assert.equal(closed[1]?.kind, "paragraph");
  });

  it("parses a table and skips its separator row", () => {
    const [table] = parseMarkdown("| a | b |\n|---|---|\n| 1 | 2 |");
    assert.deepEqual(table, { kind: "table", rows: [["a", "b"], ["1", "2"]] });
  });

  it("highlights keywords, strings, numbers and comments", () => {
    const kinds = highlightLine("python", 'def f(x): return "s" + 1  # hi').filter((t) => t.kind !== "plain").map((t) => `${t.kind}:${t.text.trim()}`);
    assert.deepEqual(kinds, ["keyword:def", "keyword:return", "string:\"s\"", "number:1", "comment:# hi"]);
    assert.deepEqual(highlightLine(null, "x"), [{ text: "x", kind: "plain" }]);
    assert.equal(languageOf("TS title=a"), "js");
    assert.equal(highlightLine("json", '{"a": true}').find((t) => t.text === '"a"')?.kind, "keyword");
  });
});

describe("launch plan", () => {
  const tty = true;
  it("opens Ink for a bare laris on a terminal", () => {
    assert.deepEqual(plan([], {}, tty), { kind: "ink", engineArgs: ["engine", "--stdio"], initialInput: null });
  });
  it("hands anything that is not the interactive screen to the engine program", () => {
    for (const argv of [["--plain"], ["-p", "hi"], ["agent", "tools"], ["login"], ["--version"], ["--help"], ["--permission-mode", "plan"]]) {
      assert.equal(plan(argv, {}, tty).kind, "passthrough", argv.join(" "));
    }
    assert.equal(plan([], {}, false).kind, "passthrough"); // a pipe has no screen
    assert.equal(plan([], { LARIS_UI: "plain" }, tty).kind, "passthrough");
  });
  it("passes the session options the engine understands", () => {
    assert.deepEqual(plan(["-c"], {}, tty), { kind: "ink", engineArgs: ["engine", "--stdio", "--continue"], initialInput: null });
    assert.deepEqual(plan(["--resume", "abc", "--allow-write"], {}, tty), { kind: "ink", engineArgs: ["engine", "--stdio", "--resume", "abc", "--allow-write"], initialInput: null });
    assert.deepEqual(plan(["--model-name=m"], {}, tty), { kind: "ink", engineArgs: ["engine", "--stdio", "--model-name", "m"], initialInput: null });
    assert.deepEqual(plan(["--resume"], {}, tty), { kind: "ink", engineArgs: ["engine", "--stdio"], initialInput: "/resume" });
  });
});

describe("format", () => {
  it("summarises results like the plain mode", () => {
    assert.equal(summarise({ error: { code: "x", message: "bad" } }), "error x: bad");
    assert.equal(summarise({ hits: [1, 2, 3] }), "3 passages");
    assert.equal(summarise({ text: "abc", total_chars: 99 }), "99 chars");
    assert.equal(summarise(null), "null");
    assert.equal(argsPreview({ a: "x".repeat(300) }).length, 110);
  });
  it("builds the status line from model, mode, context, tokens, branch, sandbox", () => {
    const line = { model: "m", context: { tokens: 10, window: 100, percent: 10 }, tokens_left: 12345, branch: "main", sandbox: "ready" };
    assert.equal(statusLine(line, "plan", null, 0).text, "m · plan · context 10% · 12k tokens left · ⎇ main");
    assert.equal(statusLine({ unlimited: true }, "default", { state: "building", hint: "" }, 2).text, "default · tokens unlimited · sandbox building · 2 queued");
    assert.equal(statusLine(null, "default", null, 0).text, "default");
    assert.equal(compactNumber(999), "999");
    assert.equal(compactNumber(2_500_000), "2.5M");
  });
  it("classifies diff lines", () => {
    assert.deepEqual(["+++ b", "--- a", "@@ -1 +1 @@", "+x", "-y", " z"].map(diffKind), ["meta", "meta", "hunk", "add", "del", "context"]);
  });
});
