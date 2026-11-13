// T82 (SR-C1, SR-C7): the golden session recorded from the real engine
// (`tests/acceptance/test_recorded_scenario.py` keeps the file equal to the engine's output),
// replayed through the Ink front end by key presses. The Python acceptance suite runs the same
// session through the engine, headless stream-json and plain mode.
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { cleanup } from "ink-testing-library";
import { KEYS, open, scenarioClient, stopAll } from "./helpers.js";

afterEach(async () => {
  cleanup();
  await stopAll();
});

describe("the golden session through the Ink front end", () => {
  it("shows the same transcript the other front ends agree on, then exits on Ctrl+C twice", async () => {
    const s = open(scenarioClient("acceptance_session"));
    await s.waitFor("session abcdef12");
    await s.waitFor("laris-base"); // status line from the engine
    await s.type("go");
    await s.type(KEYS.enter);
    await s.waitFor("Write file");
    assert.match(s.frame(), /search_corpus/); // the search ran before the write was asked
    assert.match(s.frame(), /\+hi/); // the diff of the new file
    await s.settle();
    await s.type("y");
    await s.waitFor("Perovskite cells reach 25% efficiency");
    const frame = s.frame();
    assert.match(frame, /> go/);
    assert.match(frame, /search_corpus/);
    assert.match(frame, /Write/);
    assert.match(frame, /\[nguồn #1\]/);
    assert.equal(s.client.exited, false); // the engine accepted the recorded allow
    await s.type(KEYS.ctrlC);
    await s.type(KEYS.ctrlC);
    await s.client.stop();
  });

  it("a refusal sends deny and the engine rejects it as unscripted (exit 3)", async () => {
    // the recording expects allow: answering n must not be accepted silently
    const s = open(scenarioClient("acceptance_session"));
    await s.waitFor("session abcdef12");
    await s.type("go");
    await s.type(KEYS.enter);
    await s.waitFor("Write file");
    await s.settle();
    await s.type("n");
    await new Promise((r) => setTimeout(r, 300));
    assert.equal(s.client.exited, true);
  });
});
