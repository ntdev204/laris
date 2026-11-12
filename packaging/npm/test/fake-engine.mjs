// A recorded engine: replays a scenario file over stdio, the way `laris engine --stdio` would.
// A step is {"emit": [events...]} (sent at once), or {"expect": {partial command}, "emit": [...]}
// (wait for a command that contains those fields, then send). `{"wait": ms}` pauses.
// A command that does not match the next expectation ends the process with exit code 3.
import fs from "node:fs";
import readline from "node:readline";

const scenario = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const steps = [...scenario.steps];
const send = (event) => process.stdout.write(JSON.stringify(event) + "\n");

function matches(want, got) {
  if (want === null || typeof want !== "object") return want === got;
  if (got === null || typeof got !== "object") return false;
  return Object.entries(want).every(([k, v]) => matches(v, got[k]));
}

async function drain() {
  while (steps.length && !steps[0].expect) {
    const step = steps.shift();
    if (step.wait) await new Promise((r) => setTimeout(r, step.wait));
    for (const event of step.emit ?? []) send(event);
  }
}

const lines = readline.createInterface({ input: process.stdin });
let work = Promise.resolve();
lines.on("line", (line) => {
  work = work.then(async () => {
    const command = JSON.parse(line);
    if (command.type === "shutdown") process.exit(0);
    const step = steps[0];
    if (!step || !step.expect) return; // unscripted commands are ignored (e.g. completion probes)
    if (!matches(step.expect, command)) {
      if (command.type === "complete") return;
      process.stderr.write(`unexpected command ${line}; wanted ${JSON.stringify(step.expect)}\n`);
      process.exit(3);
    }
    steps.shift();
    if (step.wait) await new Promise((r) => setTimeout(r, step.wait));
    for (const event of step.emit ?? []) send(event);
    await drain();
  });
});
lines.on("close", () => process.exit(0));
await drain();
